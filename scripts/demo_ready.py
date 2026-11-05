"""Readiness check before a live session: checks and warms the server on :8000; sends NO texts, calls or tickets.

  python scripts/demo_ready.py                  # against http://127.0.0.1:8000 (PRECEDENT_URL to change it)
  python scripts/demo_ready.py --no-reset       # keep the current feed
  python scripts/demo_ready.py --seed-playbook  # + an earlier incident Sam fixed (labelled "demo setup")

1. Reset: POST /api/reset (alerts/decisions/actions) + POST /api/ops/reset (events, SQLite, threads). Archives, never deletes.
2. /api/health: every service ok, except ones intentionally off (no key configured), which are shown in yellow.
3. Warm caches: Keewano Lua table, Darwin search for the demo model, fleet matrix for the demo drive's site.
4. Dial numbers ready (calls + texts, tech inbox if set), Sparta :4242 answers.
5. Prints the checklist, the demo commands and the URLs. Exit 1 if anything is red.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import httpx  # noqa: E402

BASE = os.getenv("PRECEDENT_URL", "http://127.0.0.1:8000").rstrip("/")
G, Y, R, X = "\033[32m", "\033[33m", "\033[31m", "\033[0m"
rows: list[tuple[str, str, str]] = []  # (color, label, detail)


def mark(ok, label: str, detail: str = "") -> None:
    """ok: True (green), None (yellow: intentionally off / informational), False (red)."""
    rows.append((G if ok else (Y if ok is None else R), label, detail))


def call(method: str, path: str, timeout: float = 30, **kw):
    t = time.time()
    r = httpx.request(method, BASE + path, timeout=timeout, **kw)
    return r, round((time.time() - t) * 1000)


def main() -> int:
    reset = "--no-reset" not in sys.argv
    try:
        r, ms = call("GET", "/api/health", 10)
        health = r.json()
        mark(r.status_code == 200, "Server up", f"{BASE} ({ms} ms)")
    except Exception as e:
        mark(False, "Server up", f"{BASE} unreachable: {e}. Start it: .venv/bin/uvicorn precedent.server:app --port 8000")
        return report()

    # 1. reset
    if reset:
        for path in ("/api/reset", "/api/ops/reset"):
            try:
                r, _ = call("POST", path, 20)
                mark(r.status_code == 200, f"Reset {path}", (r.json().get("archived_to") or r.json().get("archived") or "")
                     if r.status_code == 200 else r.text[:120])
            except Exception as e:
                mark(False, f"Reset {path}", str(e)[:120])
        r, _ = call("GET", "/api/health", 10)
        health = r.json()
    if "--seed-playbook" in sys.argv:
        try:
            r, _ = call("POST", "/api/demo/seed-history", 30)
            mark(r.status_code == 200, "Seed past week (demo setup)", str(r.json().get("incidents") or r.json().get("status")))
        except Exception as e:
            mark(False, "Seed past week (demo setup)", str(e)[:120])
        try:
            r, _ = call("POST", "/api/demo/seed-playbook", 30)
            d = r.json()
            pb = d.get("playbook") or {}
            mark(r.status_code == 200, "Seed playbook (demo setup)",
                 f"{pb.get('by')}: \"{pb.get('steps_text')}\" on 1QHRVPGX" if d.get("seeded") else d.get("status", r.text[:100]))
        except Exception as e:
            mark(False, "Seed playbook (demo setup)", str(e)[:120])

    # 2. health
    for svc in ("db", "dial", "keewano", "darwin", "sparta", "slack"):
        st = (health.get(svc) or {}).get("status", "missing")
        mark(True if st == "ok" else (None if st == "off" else False), f"Health: {svc}",
             st + ("  (intentionally off: no key)" if st == "off" else ""))

    # 3. warm caches
    demo = {}
    try:
        demo = call("GET", "/api/demo-drive", 30)[0].json()
        mark(bool(demo.get("serial")), "Demo drive", f"{demo.get('serial')} {demo.get('model')} {demo.get('pattern')}")
    except Exception as e:
        mark(False, "Demo drive", str(e)[:120])
    try:
        r, ms = call("GET", "/api/keewano/lua", 60)
        d = r.json()
        n = d.get("patterns")
        ok = r.status_code == 200 and not d.get("error")
        mark(ok if (health.get("keewano") or {}).get("status") == "ok" else None, "Warm: Keewano Lua table",
             f"{ms} ms" + (f", {n} rows" if n else "") + (f", {d.get('error')}" if d.get("error") else ""))
    except Exception as e:
        mark(False, "Warm: Keewano Lua table", str(e)[:120])
    try:
        from precedent import darwin
        darwin.prewarm()
        hit = darwin._cache_get(demo.get("model", ""))
        mark(bool(hit) or None, "Warm: Darwin search (demo model)",
             f"{hit['res'].get('status')} in {hit['seconds']} s, cached" if hit else "Darwin unreachable now; stage falls back to a similar-model cache")
    except Exception as e:
        mark(None, "Warm: Darwin search (demo model)", str(e)[:120])
    site = None
    try:
        drive = call("GET", f"/api/drives/{demo.get('serial')}", 30)[0].json()
        site = (drive.get("location") or {}).get("datacenter") or drive.get("datacenter") or "sac2"
    except Exception:
        site = "sac2"
    try:
        r, ms = call("GET", f"/api/fleet/matrix?datacenter={site}&serial={demo.get('serial', '')}", 60)
        m = r.json()
        mark(r.status_code == 200 and m.get("n", 0) > 0, f"Warm: fleet matrix {site}", f"{m.get('n')} drives in {ms} ms")
    except Exception as e:
        mark(False, f"Warm: fleet matrix {site}", str(e)[:120])

    # 4. Dial numbers + Sparta
    try:
        from precedent import dial, tech
        nums = dial.list_numbers(refresh=True)
        if not dial.DIAL_API_KEY:
            mark(None, "Dial numbers", "no DIAL_API_KEY: dry-run")
        else:
            for label, ref in (("A (calls)", dial._FROM), ("A (texts)", dial.TEXT_FROM), ("B (tech inbox)", tech.TECH_INBOX_NUMBER)):
                if not ref:
                    mark(None, f"Dial {label}", "not set (falls back to ONCALL_PHONE)")
                    continue
                n = dial.number_info(ref)
                mark(bool(n) and n.get("setupStatus", "ready") == "ready", f"Dial {label}",
                     f"{n.get('number', ref)} caps={n.get('capabilities')} setup={n.get('setupStatus')}" if n else f"{ref} not on this account")
            mark(bool(nums), "Dial account", f"{len(nums)} number(s)")
    except Exception as e:
        mark(False, "Dial numbers", str(e)[:120])
    try:
        from precedent import sparta
        if not (sparta.API_KEY and sparta.ZENDESK_URL):
            mark(None, "Sparta", "not configured (dry-run)")
        else:
            r = httpx.get(f"{sparta.ADMIN_URL}/admin/health", timeout=5)
            mark(r.status_code == 200 and r.json().get("ok"), "Sparta :4242", f"{r.json().get('worlds')} world(s), auth {r.json().get('auth')}")
    except Exception as e:
        mark(False, "Sparta :4242", f"not answering ({str(e)[:80]}). Start: npx --no-install worlds serve --port 4242")
    return report()


def report() -> int:
    print("\nPrecedent: demo readiness\n")
    for c, label, detail in rows:
        sym = {G: "OK ", Y: "-- ", R: "XX "}[c]
        print(f"  {c}{sym}{X} {label:<34} {detail}")
    red = any(c == R for c, _, _ in rows)
    print(f"\n  {R + 'NOT READY: fix the red lines above' if red else G + 'READY'}{X}\n")
    print("Demo commands")
    print("  Terminal 1 (the fleet streams day by day; the demo drive warns on May 29 and the on-call phone rings):")
    print("    .venv/bin/python -m precedent.fleet_replay --start 2026-05-26 --seconds-per-day 3")
    print("  Optional, a single drive instead of the fleet:")
    print("    .venv/bin/python -m precedent.collector --replay 1QHPN2VX --live --speed 2")
    print("  Before the next take:")
    print("    .venv/bin/python scripts/demo_ready.py")
    print("\nOpen")
    for path, what in (("/", "landing"), ("/app", "console: incidents + live feed"), ("/app/drives", "drives"), ("/app/graph", "memory graph")):
        print(f"  {BASE}{path:<14} {what}")
    print()
    return 1 if red else 0


if __name__ == "__main__":
    sys.exit(main())
