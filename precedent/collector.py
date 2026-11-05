"""Precedent collector: runs on any server, reads disk health with smartctl, sends it to Precedent.

How a datacenter connects (no agent install beyond smartmontools + python):
  PRECEDENT_URL=https://precedent.example PRECEDENT_KEY=... python -m precedent.collector   # every disk, once
  python -m precedent.collector --every 3600                       # hourly loop (cron/systemd)
  python -m precedent.collector --replay 44H0B01BV4MJ              # send a Backblaze drive's first warning
  python -m precedent.collector --replay 44H0B01BV4MJ --live --speed 2
      # stream that drive's real history at 2 days/s and stop the moment Precedent says act

Each reading is POSTed to /v1/telemetry {serial, model, smart: {"5":..,"187":..,"188":..,"197":..,"198":..}, site}.
Precedent answers with the pattern and verdict (act / watch / quiet / healthy), and alerts the on-call if it says act.
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import time

import httpx

ATTRS = {5: "5", 187: "187", 188: "188", 197: "197", 198: "198"}
URL = os.getenv("PRECEDENT_URL", "http://127.0.0.1:8000").rstrip("/")
KEY = os.getenv("PRECEDENT_KEY", "")


def disks() -> list:
    out = subprocess.run(["smartctl", "--scan", "-j"], capture_output=True, text=True, check=False).stdout
    return [d["name"] for d in json.loads(out or "{}").get("devices", [])]


def read_disk(dev: str) -> dict | None:
    out = subprocess.run(["smartctl", "-a", "-j", dev], capture_output=True, text=True, check=False).stdout
    if not out:
        return None
    j = json.loads(out)
    table = {a["id"]: a.get("raw", {}).get("value", 0) for a in j.get("ata_smart_attributes", {}).get("table", [])}
    return {"serial": j.get("serial_number"), "model": j.get("model_name"),
            "smart": {v: int(table.get(k, 0)) for k, v in ATTRS.items()}, "site": socket.gethostname()}


def kernel_logs(dev: str | None = None) -> list:
    """Recent kernel disk-error lines (Linux journalctl/dmesg). Empty where unavailable (e.g. macOS)."""
    for cmd in (["journalctl", "-k", "--since", "-1h", "--no-pager", "-o", "short-iso"], ["dmesg", "--time-format", "iso"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False).stdout
        except (OSError, subprocess.TimeoutExpired):
            continue
        hits = [l for l in out.splitlines() if any(k in l for k in ("I/O error", "medium error", "UNC", "blk_update_request", "ata", "reset"))
                and (not dev or dev.rsplit("/", 1)[-1] in l)]
        if out:
            return [{"source": cmd[0], "line": l[:300]} for l in hits[-20:]]
    return []


def _smart_log_lines(prev: dict, cur: dict, date: str) -> list:
    """smartctl-style log lines describing what changed since the previous reading (real Backblaze values)."""
    names = {"5": "Reallocated_Sector_Ct", "187": "Reported_Uncorrect", "188": "Command_Timeout",
             "197": "Current_Pending_Sector", "198": "Offline_Uncorrectable"}
    return [{"ts": date, "source": "smartctl", "line": f"ID {a} {names[a]}: {prev.get(a, 0)} -> {cur[a]}"}
            for a in names if cur.get(a, 0) != prev.get(a, 0)]


def replay(serial: str, live: bool = False, lead_days: int = 21) -> list:
    """The drive's real Backblaze history as readings. live=False: just its first warning reading.
    live=True: every day from `lead_days` before its first warning onwards, each with its smartctl change log."""
    from precedent import engine
    con = engine.connect(read_only=True)
    p = engine.drive_profile(con, serial)
    hist = p.get("smart_history", [])
    out, prev = [], {}
    for r in hist:
        cur = {"5": r["s5"] or 0, "187": r["s187"] or 0, "188": r["s188"] or 0, "197": r["s197"] or 0, "198": r["s198"] or 0}
        out.append({"serial": serial, "model": p["model"], "site": "replay", "observed_on": r["date"], "smart": cur,
                    "logs": _smart_log_lines(prev, cur, r["date"]), "_warned": bool(r["pattern"])})
        prev = cur
    if not live:  # the moment it started failing: its first warning reading
        return [r for r in out if r["_warned"]][:1]
    first = next((i for i, r in enumerate(out) if r["_warned"]), len(out) - 1)
    return out[max(0, first - lead_days):]


def send(reading: dict) -> dict:
    r = httpx.post(f"{URL}/v1/telemetry", json=reading, timeout=30,
                   headers={"X-Precedent-Key": KEY} if KEY else {})
    return {"status": r.status_code, "body": r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:300]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--every", type=int, default=0, help="seconds between scans; 0 = once")
    ap.add_argument("--replay", help="send a Backblaze drive's latest warning instead of reading local disks")
    ap.add_argument("--dry", action="store_true", help="print readings, don't send")
    ap.add_argument("--live", action="store_true", help="with --replay: stream the history, stop at the first act")
    ap.add_argument("--speed", type=float, default=2.0, help="readings per second in --live mode")
    a = ap.parse_args()
    while True:
        readings = replay(a.replay, a.live) if a.replay else [r for r in map(read_disk, disks()) if r]
        for reading in readings:
            reading.pop("_warned", None)
            if not a.replay:
                reading["logs"] = kernel_logs()
            if a.dry:
                print(json.dumps(reading))
                continue
            try:
                res = send(reading)
            except httpx.HTTPError as e:
                if not a.every:
                    raise
                print(f"send failed ({e}); retrying at the next scan", file=sys.stderr, flush=True)  # server down or restarting
                break
            body = res.get("body") if isinstance(res.get("body"), dict) else {}
            print(f"{reading.get('observed_on', '')} {reading['serial']} {body.get('pattern') or 'healthy':>22}  -> {body.get('verdict', res['status'])}", flush=True)
            if a.live and body.get("verdict") == "act":
                print("Precedent says act: alert fired, stopping the stream.")
                break
            if a.live:
                time.sleep(1 / max(a.speed, 0.1))
        if not a.every:
            break
        time.sleep(a.every)


if __name__ == "__main__":
    main()
