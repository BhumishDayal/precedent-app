"""Keewano: each drive is an entity; its warnings, failure and human decisions are its events.

Usage:
  python -m precedent.keewano register          # register the custom event map (once)
  python -m precedent.keewano backfill [limit]  # push warned drives' history (change events only)
  python -m precedent.keewano sql "<query>"     # SQL over Keewano's events table
  python -m precedent.keewano live              # the console's live query
  python -m precedent.keewano lua | at-risk     # run keewano/precedent.lua or keewano/at_risk.lua inside Keewano
  python -m precedent.keewano tools             # list MCP tools
  python -m precedent.keewano call <tool> '{"k": "v"}'
"""
import asyncio
import csv
import io
import json
import logging
import os
import sys
import time
import uuid
import zlib

import httpx

from precedent.config import KEEWANO_INGEST_KEY, KEEWANO_PAT, KEEWANO_PROJECT_ID, ROOT, STATE_DIR

log = logging.getLogger(__name__)
INGEST = "https://api.keewano.com/event/ingress/v1/json"

EVENT_TYPES = [
    {"eventTypeId": 2000, "name": "DriveModel", "dataType": "string"},
    {"eventTypeId": 2001, "name": "DriveSerial", "dataType": "string"},
    {"eventTypeId": 2002, "name": "WarningPattern", "dataType": "string"},
    {"eventTypeId": 2003, "name": "DriveFailed", "dataType": "none"},
    {"eventTypeId": 2004, "name": "Decision", "dataType": "string"},
    {"eventTypeId": 2005, "name": "Smart5", "dataType": "uint"},
    {"eventTypeId": 2006, "name": "Smart197", "dataType": "uint"},
    {"eventTypeId": 2007, "name": "Smart198", "dataType": "uint"},
    {"eventTypeId": 2008, "name": "Smart187", "dataType": "uint"},
]
ID = {e["name"]: e["eventTypeId"] for e in EVENT_TYPES}
TYPE = {e["name"]: e["dataType"] for e in EVENT_TYPES}
EVENTS_HASH = zlib.crc32(json.dumps(EVENT_TYPES, sort_keys=True).encode()) or 1


def drive_id(serial: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"precedent:{serial}"))


def ev(name: str, ts: int, data=None) -> dict:
    e = {"eventTypeId": ID[name], "dataType": TYPE[name], "timestamp": int(ts)}
    if data is not None:
        e["data"] = data
    return e


def _headers() -> dict:
    return {"k-token": KEEWANO_INGEST_KEY, "Content-Type": "application/json"}


def register() -> None:
    r = httpx.post(f"{INGEST}/custom", headers=_headers(),
                   json={"customEventsHash": EVENTS_HASH, "eventTypes": EVENT_TYPES}, timeout=30)
    print(r.status_code, r.text[:300])


async def _send(client: httpx.AsyncClient, serial: str, events: list, sem: asyncio.Semaphore) -> bool:
    body = {"dataSessionId": str(uuid.uuid4()), "batch": 1, "customEventsHash": EVENTS_HASH,
            "installId": drive_id(serial), "events": sorted(events, key=lambda e: e["timestamp"])}
    async with sem:
        for attempt in range(4):  # ingest is idempotent per (dataSessionId, batch), so retry is safe
            try:
                r = await client.post(f"{INGEST}/in", headers=_headers(), json=body, timeout=30)
                if r.status_code < 300:
                    return True
                if r.status_code not in (429, 500, 502, 503, 504):
                    print(serial, r.status_code, r.text[:200])
                    return False
            except httpx.HTTPError:
                pass
            await asyncio.sleep(2 ** attempt)
    return False


def _ts(d) -> int:
    return int(time.mktime(d.timetuple())) + 12 * 3600


def drive_histories(con, limit: int):
    """Warned drives first (all failures included), as {serial: [events]}."""
    drives = con.execute(f"""
        SELECT d.serial, d.model, d.first_seen, d.failed_on
        FROM drives d WHERE d.serial IN (SELECT DISTINCT serial FROM warnings)
        ORDER BY d.failed_on IS NULL, d.serial LIMIT {limit}
    """).fetchall()
    serials = [d[0] for d in drives]
    con.execute("CREATE OR REPLACE TEMP TABLE kw_sel AS SELECT unnest(?) AS serial", [serials])
    warns = con.execute("""
        SELECT serial, warn_date, pattern, coalesce(s5,0), coalesce(s197,0), coalesce(s198,0), coalesce(s187,0)
        FROM warnings JOIN kw_sel USING (serial) ORDER BY serial, warn_date
    """).fetchall()
    out = {}
    for serial, model, first_seen, failed_on in drives:
        t0 = _ts(first_seen)
        out[serial] = [ev("DriveModel", t0, model), ev("DriveSerial", t0 + 1, serial)]
        if failed_on:
            out[serial].append(ev("DriveFailed", _ts(failed_on) + 3600))
    for serial, d, pattern, s5, s197, s198, s187 in warns:
        t = _ts(d)
        out[serial] += [ev("Smart5", t, s5), ev("Smart197", t, s197), ev("Smart198", t, s198),
                        ev("Smart187", t, s187), ev("WarningPattern", t + 1, pattern)]
    return out


async def backfill(limit: int = 9000) -> None:
    from precedent import engine
    con = engine.connect(read_only=True)
    hist = drive_histories(con, limit)
    print(f"pushing {len(hist)} drives, {sum(map(len, hist.values()))} events")
    sem = asyncio.Semaphore(30)
    async with httpx.AsyncClient() as client:
        ok = await asyncio.gather(*[_send(client, s, e, sem) for s, e in hist.items()])
    print(f"ok {sum(ok)}/{len(ok)}")


def push_decision(serial: str, choice: str) -> bool:
    """Log a human decision (swap/wait/show) on the drive. Sync, so it's safe inside FastAPI handlers."""
    body = {"dataSessionId": str(uuid.uuid4()), "batch": 1, "customEventsHash": EVENTS_HASH,
            "installId": drive_id(serial), "events": [ev("Decision", time.time(), choice)]}
    r = httpx.post(f"{INGEST}/in", headers=_headers(), json=body, timeout=10)
    if r.status_code >= 300:
        log.warning("Keewano ingest -> %s: %s", r.status_code, r.text[:200])
    return r.status_code < 300


def push_event(serial: str, name: str, data=None, ts=None) -> bool:
    """Record alert_sent, decision_swap, alert_escalated... on the drive. Never raises.
    Everything lands as one Decision event whose text is the name minus "decision_"; data and ts are not sent
    (the event map has a single string Decision event, stamped now)."""
    try:
        if not KEEWANO_INGEST_KEY:
            return False
        return push_decision(serial, name.removeprefix("decision_"))
    except Exception as e:  # Keewano must never break the alert loop
        log.warning("Keewano push failed: %s", e)
        return False


def sql(query: str) -> list:
    """Keewano SQL via its MCP run_sql_query (needs only KEEWANO_PAT + KEEWANO_PROJECT_ID). Returns list of dicts."""
    text = mcp_call("run_sql_query", {"projectId": KEEWANO_PROJECT_ID, "sqlQuery": query, "maxRows": 200})
    if not text.startswith("SQL result"):
        raise RuntimeError(text[:300])
    body = text.split("\n", 1)[1] if "\n" in text else ""
    return list(csv.DictReader(io.StringIO(body)))


MCP_URL = "https://api.keewano.com/mcp"


async def _mcp(fn):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client
    http = create_mcp_http_client(headers={"k-token": KEEWANO_PAT})
    async with http, streamable_http_client(MCP_URL, http_client=http) as streams:
        read, write = streams[0], streams[1]
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await fn(session)


def mcp_tools() -> list:
    """[(name, description, input schema keys)] of the Keewano MCP tools (names aren't documented)."""
    async def go(session):
        tools = (await session.list_tools()).tools
        return [(t.name, (t.description or "")[:160], list((getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {}).get("properties", {}))) for t in tools]
    return asyncio.run(_mcp(go))


def mcp_call(name: str, args: dict):
    async def go(session):
        res = await session.call_tool(name, args)
        return "\n".join(getattr(c, "text", str(c)) for c in res.content)
    return asyncio.run(_mcp(go))


def _run_script(script: str, cache_name: str, max_age_s: int, shape) -> dict:
    """Run a Lua script inside Keewano (MCP run_script_query) and cache the result in STATE_DIR/<cache_name>.
    shape(result) picks the fields to keep. Never raises."""
    cache = os.path.join(STATE_DIR, cache_name)
    try:
        if os.path.exists(cache) and time.time() - os.path.getmtime(cache) < max_age_s:
            with open(cache) as f:
                return json.load(f)
        if not (KEEWANO_PAT and KEEWANO_PROJECT_ID):
            return {"connected": False, "rows": [], "error": "Keewano keys not set"}
        t = time.time()
        with open(os.path.join(ROOT, script)) as f:
            lua = f.read()
        text = mcp_call("run_script_query", {"projectId": KEEWANO_PROJECT_ID, "luaScript": lua, "filters": []})
        result = json.loads(text[text.index("{"):]).get("result", {})
        out = {"connected": True, **shape(result), "seconds": round(time.time() - t, 1),
               "computed_at": int(time.time()), "script": script}
        with open(cache, "w") as f:
            json.dump(out, f)
        return out
    except Exception as e:
        log.warning("Keewano %s failed: %s", script, e)
        return {"connected": False, "rows": [], "error": str(e)[:300]}


def lua_table(max_age_s: int = 600) -> dict:
    """The precedent table computed inside Keewano by keewano/precedent.lua. Takes ~10 s, so it's cached."""
    return _run_script("keewano/precedent.lua", "keewano_lua.json", max_age_s,
                       lambda res: {"rows": res.get("rows", [])})


def at_risk(max_age_s: int = 60, limit: int = 10) -> dict:
    """Prediction computed inside Keewano (keewano/at_risk.lua): every still-running warned drive scored by the
    failure rate of its latest warning pattern, riskiest first."""
    out = _run_script("keewano/at_risk.lua", "keewano_at_risk.json", max_age_s,
                      lambda res: {"rows": res.get("at_risk", []), "scored": res.get("running_drives_scored")})
    return {**out, "rows": out.get("rows", [])[:limit]}


def keewano_precedent(model: str, pattern: str) -> dict | None:
    """Keewano's own count for one (model, pattern), from the cached Lua table."""
    for r in lua_table().get("rows", []):
        if r.get("model") == model and r.get("pattern") == pattern:
            return r
    return None


# Keewano SQL has one `events` table; each event name is a column that carries its last value forward. So grouping
# by the latest model + pattern and counting DriveFailed events counts the drives that died after that pattern.
LIVE_SQL = """
SELECT "DriveModel" AS model, "WarningPattern" AS pattern,
       count("WarningPattern") AS warnings, count("DriveFailed") AS died
FROM events WHERE "WarningPattern" IS NOT NULL
GROUP BY 1, 2 ORDER BY died DESC LIMIT 12
"""
DECISIONS_SQL = """SELECT "Decision" AS decision, count("Decision") AS n FROM events
WHERE "Decision" IN ('swap', 'wait', 'unclear', 'show') GROUP BY 1"""


def live_table() -> dict:
    """For the stage page: a live query answered by Keewano. Never raises."""
    if not (KEEWANO_PAT and KEEWANO_PROJECT_ID):
        return {"connected": False, "rows": [], "error": "Keewano keys not set"}
    try:
        out = {"connected": True, "rows": sql(LIVE_SQL), "query": LIVE_SQL.strip()}
        try:
            out["decisions"] = sql(DECISIONS_SQL)
        except Exception as e:
            log.warning("Keewano decisions query failed: %s", e)
            out["decisions"] = []
        return out
    except Exception as e:
        log.warning("Keewano live query failed: %s", e)
        return {"connected": False, "rows": [], "error": str(e)[:300]}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "register":
        register()
    elif cmd == "backfill":
        asyncio.run(backfill(int(sys.argv[2]) if len(sys.argv) > 2 else 9000))
    elif cmd == "tools":
        for t in mcp_tools():
            print(t)
    elif cmd == "call":  # python -m precedent.keewano call <tool> '<json args>'
        print(mcp_call(sys.argv[2], json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}))
    elif cmd == "lua":
        t = lua_table(0)
        print(t.get("seconds"), "s,", len(t.get("rows", [])), "rows", t.get("error", ""))
        print(keewano_precedent("TOSHIBA MG10ACA20TE", "5+197+198:high"))
    elif cmd == "at-risk":
        print(json.dumps(at_risk(0), indent=1))
    elif cmd == "live":
        print(json.dumps(live_table(), indent=1, default=str))
    elif cmd == "sql":
        for row in sql(sys.argv[2]):
            print(row)
    else:
        print(__doc__)
