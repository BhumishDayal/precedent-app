"""Check every key in .env against the real services, without sending any text or call.

  .venv/bin/python scripts/preflight.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import httpx  # noqa: E402

from precedent import config as c  # noqa: E402

ok = True


def line(name, good, detail=""):
    global ok
    ok &= bool(good)
    print(f"{'OK  ' if good else 'FAIL'} {name}  {detail}")


for k in ("DIAL_API_KEY", "DIAL_FROM_NUMBER_ID", "ONCALL_PHONE", "KEEWANO_INGEST_KEY", "KEEWANO_PAT",
          "KEEWANO_PROJECT_ID"):
    line(f"env {k}", os.getenv(k), "missing in .env" if not os.getenv(k) else "")

# Dial: list numbers (read-only). The body lists the account's phone numbers, so only its status is printed.
if c.DIAL_API_KEY:
    from precedent import dial
    try:
        r = httpx.get(f"{dial.BASE}/numbers", headers={"Authorization": f"Bearer {c.DIAL_API_KEY}"}, timeout=20)
        line("dial auth", r.status_code == 200, str(r.status_code) if r.status_code == 200 else f"{r.status_code} {r.text[:200]}")
        if c.DIAL_FROM_NUMBER_ID:
            line("dial from-number exists", c.DIAL_FROM_NUMBER_ID in r.text, c.DIAL_FROM_NUMBER_ID)
    except Exception as e:
        line("dial auth", False, str(e))

# Keewano ingest key: registering the same event map is idempotent (200 already_registered / 202)
if c.KEEWANO_INGEST_KEY:
    from precedent import keewano
    try:
        r = httpx.post(f"{keewano.INGEST}/custom", headers=keewano._headers(),
                       json={"customEventsHash": keewano.EVENTS_HASH, "eventTypes": keewano.EVENT_TYPES}, timeout=20)
        line("keewano ingest key + event map", r.status_code in (200, 202), f"{r.status_code} {r.text[:200]}")
    except Exception as e:
        line("keewano ingest key", False, str(e))

if c.KEEWANO_PAT and c.KEEWANO_PROJECT_ID:
    from precedent import keewano
    try:
        rows = keewano.sql("SELECT count(*) AS n FROM events")
        line("keewano sql", True, str(rows))
    except Exception as e:
        line("keewano sql", False, str(e)[:300])
if c.KEEWANO_PAT:
    from precedent import keewano
    try:
        tools = keewano.mcp_tools()
        line("keewano mcp", bool(tools), ", ".join(t[0] for t in tools))
    except Exception as e:
        line("keewano mcp", False, str(e)[:300])

print("\nPREFLIGHT " + ("OK" if ok else "has failures (see above)"))
