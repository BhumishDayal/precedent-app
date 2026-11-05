"""Dry-run rehearsal of the whole flow through a real server, with a screenshot of each step.

  python scripts/rehearse.py [--channel call|sms|both] [--keep]   (with the project's virtualenv)

Starts its own server on port 8002 with every integration key blanked (no real texts, calls, tickets or Keewano
pushes) and state in a temp dir, then on /stage and /app: send alert -> simulated reply 1 -> decision -> actions
-> technician chat "1" -> incident page -> reset. Screenshots (1920x1080, plus one at 1280x720) go to rehearsal/.
Prints PASS/FAIL per step; exit 1 on any FAIL.
"""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8002
BASE = f"http://127.0.0.1:{PORT}"
OUT = os.path.join(ROOT, "rehearsal")
CHROME = os.getenv("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        fails.append(name)
    return cond


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
    except Exception as e:  # server down, timeout
        return 0, str(e)


def wait_for(fn, timeout, every=0.5):
    end = time.time() + timeout
    while time.time() < end:
        out = fn()
        if out:
            return out
        time.sleep(every)
    return None


def _chrome(*args):
    with tempfile.TemporaryDirectory(prefix="rehearse-chrome-") as prof:
        return subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--user-data-dir={prof}", *args],
                              capture_output=True, text=True, timeout=60).stdout


_frame = None


def frame_offset():
    """Headless Chrome's viewport is shorter than --window-size (invisible window frame); measure it once."""
    global _frame
    if _frame is None:
        out = _chrome("--window-size=1920,1080", "--dump-dom",
                      'data:text/html,<script>document.write("vh="+innerHeight)</script>')
        try:
            _frame = max(0, 1080 - int(out.split("vh=")[1].split("<")[0]))
        except (IndexError, ValueError):
            _frame = 0
    return _frame


def shot(name, w=1920, h=1080, path_="/stage"):
    """Screenshot with a true w x h viewport (taller window, then crop the bottom off with macOS sips)."""
    path = os.path.join(OUT, f"{name}.png")
    if not os.path.exists(CHROME):
        return check(f"screenshot {name}", False, f"Chrome not found at {CHROME}; set CHROME=")
    off = frame_offset() if shutil.which("sips") else 0
    _chrome(f"--window-size={w},{h + off}", "--virtual-time-budget=5000", f"--screenshot={path}", BASE + path_)
    if off and os.path.exists(path):
        subprocess.run(["sips", "--cropToHeightWidth", str(h), str(w), "--cropOffset", "0", "0", path],
                       capture_output=True, timeout=30)
    return check(f"screenshot {name}", os.path.exists(path) and os.path.getsize(path) > 10_000, os.path.relpath(path, ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="call", choices=["call", "sms", "both", "imessage"])
    ap.add_argument("--keep", action="store_true", help="leave the server running on 8002 afterwards")
    args = ap.parse_args()

    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", PORT)) == 0:
            check(f"port {PORT} free", False, "something is already running there; stop it first")
            return 1
    shutil.rmtree(OUT, ignore_errors=True)  # only our own previous frames
    os.makedirs(OUT)
    state = tempfile.mkdtemp(prefix="precedent-rehearse-")
    env = {**os.environ, "PRECEDENT_STATE_DIR": state, "ALERT_CHANNEL": args.channel, "ESCALATE_SECONDS": "0",
           "ONCALL_PHONE": os.getenv("ONCALL_PHONE") or "+15550000001",
           # dry-run every integration (empty env vars win over .env: python-dotenv doesn't override)
           "DIAL_API_KEY": "", "KEEWANO_INGEST_KEY": "", "KEEWANO_PAT": "", "DARWIN_API_KEY": "",
           "SPARTA_API_KEY": "", "SPARTA_ZENDESK_URL": "", "SPARTA_ADMIN_TOKEN": "", "SPARTA_INJECT_FAULT": ""}
    log = open(os.path.join(OUT, "server.log"), "w")
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "precedent.server:app", "--port", str(PORT)],
                              cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    print(f"dry-run rehearsal · channel={args.channel} · state={state} · frames -> rehearsal/\n")
    try:
        if not check("server up on 8002", wait_for(lambda: call("GET", "/api/alerts")[0] == 200, 30)):
            return 1
        st, d = call("GET", "/api/demo-drive")
        p = (d or {}).get("precedent", {}) if st == 200 else {}
        check("demo drive", st == 200 and p.get("n"), f"{d.get('serial')} {d.get('model')}: {p.get('n')} like it, "
              f"{p.get('died')} died" if st == 200 else d)
        st, b = call("GET", "/api/backtest")
        check("backtest from live engine", st == 200 and b.get("source") == "db", f"source={b.get('source') if st == 200 else st}")
        shot("01-stage")

        st, a = call("POST", "/alerts/send")
        ok = check("send alert (dry-run)", st == 200 and a.get("dry_run") is True,
                   f"channel={a.get('channel')} dry_run={a.get('dry_run')}" if st == 200 else a)
        if not ok:
            return 1
        alert_id = a["alert"]["alert_id"]
        print("     text:", (a.get("text") or "")[:160])
        shot("02-alert-sent")

        st, r = call("POST", "/demo/simulate-reply", {"choice": "1"})
        check("simulate reply 1", st == 200, "" if st == 200 else r)
        dec = wait_for(lambda: next((x for x in call("GET", "/api/decisions")[1].get("rows", [])
                                     if x.get("alert_id") == alert_id), None), 10)
        check("decision logged", dec and dec.get("choice") == "swap", dec and f"{dec['choice']} {dec['serial']}")
        shot("03-reply")

        def acts(need):
            rows = [x for x in call("GET", "/api/actions")[1].get("rows", []) if x.get("alert_id") == alert_id]
            return rows if need <= {x.get("sponsor") for x in rows} else None
        rows = wait_for(lambda: acts({"sparta"}), 30)
        check("action: sparta ticket", rows, "; ".join(f"{x['sponsor']}={x.get('status')}" for x in rows or []))
        rows = wait_for(lambda: acts({"darwin"}), 5)  # in dry-run Darwin logs a "dry-run" row instead of searching
        print("INFO action: darwin", "logged" if rows else "not logged")
        time.sleep(1)

        # technician inbox (Dial-to-Dial chat): the technician answers "1" from the stage page
        st, r = call("POST", "/api/tech/send", {"body": "1"})
        check("technician sends 1 (dry-run)", st == 200, "" if st == 200 else f"{st} {str(r)[:120]}")
        if st == 200:
            def in_thread():
                st2, t = call("GET", "/api/tech/thread")
                rows = (t if isinstance(t, list) else (t or {}).get("rows", [])) if st2 == 200 else []
                return rows if any(str(m.get("body", "")).strip() == "1" for m in rows) else None
            rows = wait_for(in_thread, 10)
            check("technician message in thread", rows, f"{len(rows or [])} messages")
        st, inc = call("GET", f"/api/incident/{alert_id}")
        check("incident data", st == 200 and inc.get("found") and inc.get("precedent", {}).get("n"),
              f"{inc.get('precedent', {}).get('n')} like it, {len(inc.get('similar', []))} similar, "
              f"{len(inc.get('actions', []))} actions" if st == 200 and inc.get("found") else str(inc)[:120])
        shot("04-actions")
        shot("04-actions-1280x720", 1280, 720)
        shot("06-incident", 1920, 1080, f"/incident/{alert_id}")

        # product app at / (the stage board above lives at /stage)
        serial = d.get("serial")
        st, g = call("GET", f"/api/graph?alert_id={alert_id}")
        ids = {n["id"] for n in (g or {}).get("nodes", [])} if st == 200 else set()
        check("memory graph", st == 200 and g.get("found") and {"precedent", "alert", "decision", "keewano"} <= ids,
              f"{len(ids)} nodes" + (", network node" if "network" in ids else ""))
        st, prof = call("GET", f"/api/drives/{serial}")
        check("drive profile", st == 200 and prof.get("found") and prof.get("smart_history"),
              f"{(prof.get('location') or {}).get('datacenter')} pod {(prof.get('location') or {}).get('pod_id')}, "
              f"{len(prof.get('smart_history') or [])} SMART days" if st == 200 and prof.get("found") else str(prof)[:120])
        st, sc = call("GET", f"/api/precedent/scoped?serial={serial}")
        check("network precedent", st == 200 and sc.get("found"),
              f"own {sc.get('own', {}).get('n')}/{sc.get('own', {}).get('died')}, network {sc.get('network', {}).get('n')}/"
              f"{sc.get('network', {}).get('died')} from {sc.get('tenants_contributing')} customers" if st == 200 and sc.get("found") else str(sc)[:120])
        for name, path_ in [("10-app-home", "/app"), ("11-app-new-warning", "/app/incidents/new"), ("12-app-incident", f"/app/incidents/{alert_id}"),
                            ("13-app-drive", f"/app/drives/{serial}"), ("14-app-graph", f"/app/graph?alert_id={alert_id}"),
                            ("15-app-integrations", "/app/integrations"), ("16-app-impact", "/app/impact"), ("17-app-drives-matrix", "/app/drives")]:
            shot(name, 1440, 900, path_ + ("&" if "?" in path_ else "?") + "snapshot=1")  # no SSE: lets headless finish

        st, r = call("POST", "/api/reset")
        check("reset archives state", st == 200 and set(r.get("moved", [])) >= {"alerts.jsonl", "decisions.jsonl"},
              r.get("archived_to", "") if st == 200 else r)
        check("live panel empty after reset", call("GET", "/api/alerts")[1].get("rows") == [])
        shot("05-reset")
    finally:
        if args.keep:
            print(f"\nserver left running on {BASE} (pid {server.pid})")
        else:
            server.terminate()
            server.wait(10)
    print("\nREHEARSAL " + ("OK" if not fails else f"FAILED: {fails}"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
