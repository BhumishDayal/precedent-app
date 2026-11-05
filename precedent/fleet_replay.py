"""Replay the whole fleet, day by day, from Backblaze's real history into Precedent's live feed.

  python -m precedent.fleet_replay --start 2026-05-24 --end 2026-06-10 --seconds-per-day 4

Each simulated day is presented as TODAY (date = today, record_date = the Backblaze day it comes from) and
POSTs /v1/fleet/heartbeat in a few chunks: how many drives reported, every warning that day with
Precedent's verdict (act / watch / quiet / not enough history), and every failure (did it warn first?). The server
turns these into the live feed; only the pinned demo drive (or PAGE_SERIALS) rings a real phone.
"""
import argparse
import datetime as dt
import os
import time

import httpx

from precedent import engine
from precedent.config import MIN_N, MIN_RATE, SWAPLIST_MIN_N, SWAPLIST_MIN_RATE

URL = os.getenv("PRECEDENT_URL", "http://127.0.0.1:8000").rstrip("/")
KEY = os.getenv("PRECEDENT_KEY", "")


def verdict(n: int, died: int) -> str:
    if n >= MIN_N and died / n >= MIN_RATE:
        return "act"
    if n >= SWAPLIST_MIN_N and died / n >= SWAPLIST_MIN_RATE:
        return "watch"
    if n >= SWAPLIST_MIN_N:
        return "quiet"
    return "not enough history"


def day_payload(con, hist: dict, day: dt.date) -> dict:
    reporting = con.execute("SELECT count(*) FROM daily WHERE date = ?", [day]).fetchone()[0]
    warns = []
    for serial, model, pattern, died, censored, circular in con.execute(
            "SELECT serial, model, pattern, died, censored, circular FROM warnings WHERE warn_date = ? ORDER BY serial", [day]).fetchall():
        n, d = hist.get((model, pattern), (0, 0))
        if not censored:  # leave the drive out of its own history
            n, d = n - 1, d - (1 if died else 0)
        warns.append({"serial": serial, "model": model, "pattern": pattern, "verdict": verdict(n, d),
                      "n": n, "died": d, "circular": bool(circular)})
    fails = [{"serial": s, "model": m, "warned_before": bool(w), "first_warned": str(fw) if fw else None}
             for s, m, w, fw in con.execute("""
                SELECT d.serial, d.model, w.first_warn IS NOT NULL, w.first_warn FROM drives d
                LEFT JOIN (SELECT serial, min(warn_date) AS first_warn FROM warnings GROUP BY serial) w
                  ON w.serial = d.serial AND w.first_warn <= d.failed_on
                WHERE d.failed_on = ?""", [day]).fetchall()]
    return {"date": str(day), "drives_reporting": reporting, "ok": reporting - len(warns) - len(fails),
            "warnings": warns, "failures": fails}


def post(body: dict, attempts: int = 30) -> int:
    """POST a heartbeat chunk; survives server restarts by retrying for up to ~30 s (idempotent per date/part)."""
    for i in range(attempts):
        try:
            r = httpx.post(f"{URL}/v1/fleet/heartbeat", json=body, timeout=30, headers={"X-Precedent-Key": KEY} if KEY else {})
            return r.status_code
        except httpx.HTTPError:
            time.sleep(1)
    return 599


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-05-24")
    ap.add_argument("--end", default="2026-06-10")
    ap.add_argument("--seconds-per-day", type=float, default=4.0)
    ap.add_argument("--chunks", type=int, default=6, help="posts per day, so the feed scrolls instead of jumping")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--loop", action="store_true", help="never stop: wrap from --end back to --start (always-on console)")
    a = ap.parse_args()
    con = engine.connect(read_only=True)
    hist = {(m, p): (n, d) for m, p, n, d in con.execute(
        "SELECT model, pattern, count(*), count(*) FILTER (died) FROM warnings WHERE NOT censored GROUP BY ALL").fetchall()}
    day, end = dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end)
    while day <= end:
        p = day_payload(con, hist, day)
        counts = {v: sum(1 for w in p["warnings"] if w["verdict"] == v) for v in ("act", "watch", "quiet", "not enough history")}
        print(f"{day}  {p['drives_reporting']:,} reporting · {len(p['warnings'])} warnings {counts} · {len(p['failures'])} failures", flush=True)
        k = max(1, a.chunks)
        for i in range(k):
            # Live operations happen today: the replayed day is presented as today's date, and the historical
            # Backblaze day travels along as record_date so the source stays traceable.
            part = {"date": dt.date.today().isoformat(), "record_date": p["date"], "part": i + 1, "parts": k,
                    "drives_reporting": p["drives_reporting"] if i == 0 else None, "ok": p["ok"] if i == 0 else None,
                    "warnings": p["warnings"][i::k], "failures": p["failures"][i::k]}
            if not a.dry:
                status = post(part)
                if status >= 400:
                    print("  heartbeat ->", status)
            time.sleep(a.seconds_per_day / k)
        day += dt.timedelta(days=1)
        if a.loop and day > end:
            day = dt.date.fromisoformat(a.start)


if __name__ == "__main__":
    main()
