"""Real end-to-end check of the product flow, driven through the browser with Playwright.

  .venv/bin/python scripts/e2e.py [--base http://127.0.0.1:8000] [--serial 44H0B01BV4MJ]

Uses the REAL services in .env: the collector reading goes to /v1/telemetry, Precedent texts the technician
inbox (Dial number B) from number A, the browser clicks "1 Swap" as the technician (a real B -> A text),
the listener turns it into a decision, then Darwin/Sparta/Keewano run. Run the server with ALERT_CHANNEL=sms
so nobody's phone rings. Screenshots go to rehearsal/e2e-*.png.
"""
import argparse
import os
import subprocess
import sys
import time

import httpx
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "rehearsal")
results = []


def step(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)
    return ok


def wait_for(fn, timeout=90, every=2):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(every)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--serial", default="1QHPN2VX")
    a = ap.parse_args()
    api = httpx.Client(base_url=a.base, timeout=60)
    os.makedirs(OUT, exist_ok=True)

    api.post("/api/reset")
    # 1. A server reports the drive (collector -> /v1/telemetry)
    env = {**os.environ, "PRECEDENT_URL": a.base}
    out = subprocess.run([sys.executable, "-m", "precedent.collector", "--replay", a.serial],
                         capture_output=True, text=True, cwd=ROOT, env=env).stdout
    step("collector -> /v1/telemetry says act", "-> act" in out or "'act'" in out, out.strip()[:160])
    alerts = wait_for(lambda: api.get("/api/alerts").json().get("rows") or api.get("/api/alerts").json().get("alerts"), 20)
    alert = (alerts or [{}])[-1] if isinstance(alerts, list) else {}
    alert_id = alert.get("alert_id")
    step("alert created", alert_id, f"alert {alert_id} via {alert.get('channel')}")

    # 2. A -> B text really leaves Dial (technician inbox thread)
    to_tech = wait_for(lambda: [m for m in api.get("/api/tech/thread").json().get("rows", []) if m["direction"] == "to_tech"], 60)
    step("Precedent texted the technician inbox (A -> B)", to_tech, (to_tech or [{}])[-1].get("body", "")[:90])

    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        page = b.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        page.goto(f"{a.base}/app/incidents/{alert_id}")
        page.wait_for_timeout(2500)
        step("incident page shows the evidence", "identical drives" in page.inner_text("body"))
        page.screenshot(path=f"{OUT}/e2e-1-incident.png")

        # 3. The technician replies "1" from inbox B (real B -> A text), the listener logs it
        page.click('button[data-t="1"]')
        dec = wait_for(lambda: [d for d in api.get("/api/decisions").json().get("rows", []) if d.get("alert_id") == alert_id], 90)
        d = (dec or [{}])[0]
        step("technician reply 1 -> decision SWAP (B -> A round trip)", d.get("choice") == "swap", f"via {d.get('via')} keewano_logged={d.get('keewano_logged')}")
        step("decision logged to Keewano", d.get("keewano_logged") is True)
        page.wait_for_timeout(3000)
        body = page.inner_text("body").upper()
        step("page shows the decision", any(w in body for w in ("DECISION: REPLACE", "APPROVED THE SWAP", "SWAP APPROVED")))

        # 4. Actions after swap
        acts = wait_for(lambda: [r for r in api.get("/api/actions").json().get("rows", []) if r.get("alert_id") == alert_id and r.get("sponsor") in ("darwin", "sparta")]
                        if len({r.get("sponsor") for r in api.get("/api/actions").json().get("rows", []) if r.get("alert_id") == alert_id}) >= 2 else None, 60)
        for r in acts or []:
            step(f"action {r['sponsor']}: {r.get('status')}", r.get("status") not in ("error", None), str(r.get("detail"))[:110])
        if not acts:
            step("actions (Darwin + Sparta) recorded", False)
        summary = wait_for(lambda: [m for m in api.get("/api/tech/thread").json().get("rows", []) if "SUMMARY" in m.get("body", "").upper()], 30)
        step("technician summary sent to inbox B", summary)
        page.reload(); page.wait_for_timeout(2500)
        page.screenshot(path=f"{OUT}/e2e-2-decided.png")

        # 5. Every page renders
        for name, path, must in (("landing", "/", "track record"), ("drive", f"/app/drives/{a.serial}", "sac2"), ("graph", f"/app/graph?alert_id={alert_id}", "Memory graph"),
                                 ("systems", "/app/systems", "Systems"), ("impact", "/app/impact", "4,427"),
                                 ("stage", "/stage", "Precedent"), ("today", "/app", "Watching")):
            page.goto(a.base + path); page.wait_for_timeout(3000)
            step(f"page {name}", must in page.inner_text("body"))
            page.screenshot(path=f"{OUT}/e2e-3-{name}.png")
        page.goto(f"{a.base}/app/graph?alert_id={alert_id}"); page.wait_for_timeout(2500)
        node = page.locator('g.gnode[data-id*="precedent"]').first
        if not node.count():
            node = page.locator("g.gnode").nth(3)
        before = page.inner_text("body")
        node.click(); page.wait_for_timeout(1000)
        page.screenshot(path=f"{OUT}/e2e-4-graph-click.png")
        after = page.inner_text("body")
        step("graph node click opens a summary", len(after) > len(before) and ("died" in after or "drives" in after))
        real_errors = [e for e in errors if "404" not in e]
        step("no console errors", not real_errors, "; ".join(real_errors)[:200])
        b.close()

    failed = [n for n, ok in results if not ok]
    print(f"\nE2E {'OK' if not failed else 'FAILED: ' + ', '.join(failed)}  ({len(results) - len(failed)}/{len(results)} passed)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
