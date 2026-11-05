"""Public API for other datacenters and agents: REST under /v1 and an MCP server at /mcp-public/.

Auth: header X-Precedent-Key (or Authorization: Bearer <key>) must be one of PRECEDENT_API_KEYS (comma list).
PRECEDENT_API_KEYS empty = open, for local development only.

REST
  POST /v1/telemetry  {serial, model, smart: {"5":..,"187":..,"188":..,"197":..,"198":..}, site?, tenant?, observed_on?,
                       logs?: [{ts, source: dmesg|syslog|smartctl|journalctl, line}]}  (logs are buffered per drive and
                       attached to the alert if one fires)
                      -> {model, pattern, verdict, act, precedent, alert?, network?}; act=true triggers the alert flow;
                         with tenant, network = engine.precedent_scoped (that tenant's own history vs the pool)
                         (no second alert for the same serial + pattern within 24 h)
  GET  /v1/precedent?model=&pattern=   -> engine.precedent
  GET  /v1/drives/{serial}             -> engine.drive_profile
  POST /v1/decisions  {serial, choice: swap|wait, by}  -> logs against the drive's latest alert
  POST /v1/fleet/heartbeat {date, site?, drives_reporting, ok, warnings:[{serial, model, pattern, verdict, n, died}],
                            failures:[{serial, model, warned_before}]}  -> triage per warning (see fleet_heartbeat_core)
MCP (streamable HTTP): check_warning, report_telemetry, get_drive, log_decision
  claude mcp add --transport http precedent <url>/mcp-public/ --header "X-Precedent-Key: <key>"
"""
import hmac
import json
import logging
import os
import time
import uuid
from collections import deque
from datetime import date, datetime, timedelta, timezone

import duckdb
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from precedent import decisions, engine
from precedent.config import HORIZON_DAYS

log = logging.getLogger(__name__)
KEYS = [k.strip().encode() for k in os.getenv("PRECEDENT_API_KEYS", "").split(",") if k.strip()]
_recent_logs: dict[str, deque] = {}  # serial -> its last 50 server log lines (from any reading)


def _key_ok(headers) -> bool:
    if not KEYS:
        return True
    key = headers.get("x-precedent-key") or (headers.get("authorization") or "").removeprefix("Bearer ").strip()
    return any(hmac.compare_digest(key.encode(), k) for k in KEYS)


def require_key(request: Request) -> None:
    if not _key_ok(request.headers):
        raise HTTPException(401, "missing or invalid X-Precedent-Key")


def _con():
    return engine.connect(read_only=True)


def check_warning_core(model: str, pattern: str) -> dict:
    con = _con()
    try:
        return engine.precedent(con, model, pattern)
    finally:
        con.close()


_last_reading: dict[str, dict] = {}  # serial -> {"last": newest observed_on, "seen": {observed_on, ...}}
SMART_KEYS = {"5", "187", "188", "197", "198"}


def report_telemetry_core(serial: str, model: str, smart: dict, site: str | None = None,
                          tenant: str | None = None, observed_on: str | None = None, logs: list | None = None) -> dict:
    """Every response carries `reason`. Edge cases: empty smart -> 400; same serial + observed_on again -> duplicate;
    observed_on older than the newest -> stored, never alerts; drive already decided/resolved/open -> no re-alert;
    a paging channel down -> the incident still opens and the error is logged; unknown model -> any-model fallback."""
    from precedent import db, events
    if not (serial and model and isinstance(serial, str) and isinstance(model, str)):
        raise ValueError("serial and model are required strings")
    if not isinstance(smart, dict) or not smart or not (SMART_KEYS & {str(k) for k in smart}):
        raise ValueError('smart must include at least one of SMART 5, 187, 188, 197, 198, e.g. {"5": 0, "197": 8}')
    try:
        engine.pattern_of(smart)
    except (TypeError, ValueError):
        raise ValueError("SMART values must be whole numbers") from None
    if logs is not None and not isinstance(logs, list):
        raise ValueError("logs must be a list of {ts, source, line}")
    day = str(observed_on)[:10] if observed_on else None
    if day:
        try:
            date.fromisoformat(day)
        except ValueError:
            raise ValueError("observed_on must be an ISO date, e.g. 2026-05-29") from None
    st = _last_reading.setdefault(serial, {"last": None, "seen": set()})
    if day and day in st["seen"]:
        return {"serial": serial, "status": "duplicate", "act": False,
                "reason": f"duplicate reading for {serial} on {engine.shift_date(day)}; ignored"}
    out_of_order = bool(day and st["last"] and day < st["last"])
    prev_last = st["last"]
    if day:
        st["seen"].add(day)
        st["last"] = max(st["last"] or day, day)
    t0 = time.time()
    try:
        con = _con()
        try:
            res = engine.evaluate_reading(con, model, smart, serial)
            if tenant and res.get("pattern"):
                res["network"] = engine.precedent_scoped(con, model, res["pattern"], tenant=tenant, exclude_serial=serial)
        finally:
            con.close()
    except Exception:  # not evaluated: forget the reading, so the collector's retry isn't dropped as a duplicate
        if day:
            st["seen"].discard(day)
            st["last"] = prev_last
        raise
    buf = _recent_logs.setdefault(serial, deque(maxlen=50))
    for entry in logs or []:
        if isinstance(entry, dict) and entry.get("line"):
            buf.append({"ts": entry.get("ts") or observed_on, "source": entry.get("source") or "log",
                        "line": str(entry["line"])[:300]})
    res = {**res, "serial": serial, "site": site, **({"tenant": tenant} if tenant else {}),
           "timing_ms": {"verdict": round((time.time() - t0) * 1000, 1)}}
    p = res.get("precedent") or {}
    if not res.get("pattern"):
        res["reason"] = "healthy: no SMART warning counters are non-zero"
    elif res.get("act"):
        res["reason"] = f"act: {p.get('died')} of {p.get('n')} identical drives died within {HORIZON_DAYS} days in the fleet record"
    elif res.get("verdict") == "not enough history":
        res["reason"] = (f"not enough history for {model} {res['pattern']}; closest precedent: {p.get('died')} of "
                         f"{p.get('n')} ({p.get('scope')})")
    else:
        res["reason"] = f"{res.get('verdict')}: {p.get('died')} of {p.get('n')} identical drives died in the fleet record"
    if p.get("scope") == "any model":
        res["fallback"] = "any model"
        res["reason"] = (f"not enough history for {model} itself; using the same warning on any model "
                         f"({p.get('died')} of {p.get('n')} died) -> {res.get('verdict')}")
    if out_of_order:
        res["act"], res["status"] = False, "out_of_order"
        res["reason"] = (f"out-of-order reading ({engine.shift_date(day)} is older than {engine.shift_date(st['last'])}): "
                         f"stored, no alert. " + res["reason"])
    events.publish("telemetry_received", {"model": model, "smart": smart, "date": date.today().isoformat(),
                                          "record_date": observed_on, "pattern": res.get("pattern"),
                                          "verdict": res.get("verdict"), "act": bool(res.get("act")), "site": site,
                                          "n": (res.get("precedent") or {}).get("n"), "died": (res.get("precedent") or {}).get("died"),
                                          "tenant": tenant, "reason": res["reason"]}, None, serial)
    if not out_of_order:
        from precedent import lifecycle
        lifecycle.check_verified(serial, day, healthy=not res.get("pattern"))
    if not res.get("act"):
        return res
    inc = db.incident_for_serial(serial)
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    prior = next((a for a in reversed(decisions._read(decisions.ALERTS_PATH))
                  if a["serial"] == serial and a["pattern"] == res["pattern"]
                  and datetime.fromisoformat(a["ts"]) >= since), None)
    if inc and inc["status"] in ("decided", "resolved"):
        res["alert"] = {"alert_id": inc["alert_id"], "status": f"already {inc['status']}"}
        res["reason"] = f"{serial} is already {inc['status']} ({inc.get('choice') or 'see incident'}); no re-alert, reading logged"
        events.publish("warning_triaged", {"model": model, "pattern": res["pattern"], "verdict": "act", "site": site,
                                           "date": observed_on, "outcome": f"already {inc['status']}; no re-alert"},
                       inc["alert_id"], serial)
    elif prior or (inc and inc["status"] != "resolved"):
        aid = prior["alert_id"] if prior else inc["alert_id"]
        res["alert"] = {"alert_id": aid, "status": "already alerted"}
        res["reason"] = f"{serial} already has an open incident ({aid}); no second alert"
    else:
        from precedent.server import trigger_alert  # lazy: server mounts this module
        try:
            out = trigger_alert({"serial": serial, "model": model, "pattern": res["pattern"], "site": site,
                                 "source": "public_api", "logs": list(buf)})
            res["alert"] = {"alert_id": out["alert"]["alert_id"], "status": "sent", "channel": out["channel"]}
            res["timing_ms"]["page_started"] = (out["alert"].get("timing_ms") or {}).get("page_started")
            res["reason"] += f"; on-call paged via {out['channel']}"
        except Exception as e:  # channel down: still open the incident, log the error
            log.exception("paging for %s failed; opening the incident anyway", serial)
            aid = uuid.uuid4().hex[:8]
            err = getattr(e, "detail", None) or str(e)
            events.publish("incident_opened", {"alert": {"alert_id": aid, "model": model, "pattern": res["pattern"],
                                                         "n": p.get("n"), "died": p.get("died"), "site": site,
                                                         "status": "open (paging failed)"}, "error": str(err)[:200]},
                           aid, serial)
            res["alert"] = {"alert_id": aid, "status": "open (paging failed)", "error": str(err)[:200]}
            res["reason"] += f"; incident opened but paging failed ({str(err)[:80]})"
    return res


PAGE_SERIALS = {s.strip() for s in os.getenv("PAGE_SERIALS", "").split(",") if s.strip()}


def _pinned() -> set:
    from precedent.config import DATA
    try:
        with open(os.path.join(DATA, "samples", "demo_drive.json")) as f:
            return {json.load(f)["serial"]} | PAGE_SERIALS
    except (OSError, ValueError, KeyError):
        return set(PAGE_SERIALS)


def fleet_heartbeat_core(hb: dict) -> dict:
    """One simulated day from a fleet: publish fleet_heartbeat, triage each warning, record failures.
    Only the pinned drive (data/samples/demo_drive.json) or PAGE_SERIALS runs the real Dial alert flow; other acts
    open a "paged (replay)" incident so phones don't ring several times a day."""
    from precedent import db, events
    day, site = hb.get("date"), hb.get("site")
    rd = hb.get("record_date") or day  # live ops are today; the Backblaze day stays in the data
    warnings, failures = hb.get("warnings") or [], hb.get("failures") or []
    if not (isinstance(warnings, list) and isinstance(failures, list)
            and all(isinstance(x, dict) for x in warnings + failures)):
        raise ValueError("warnings and failures must be lists of objects")
    events.publish("fleet_heartbeat", {"date": day, "site": site, "drives_reporting": hb.get("drives_reporting"),
                                       "ok": hb.get("ok"), "warnings": len(warnings), "failures": len(failures),
                                       "part": hb.get("part"), "parts": hb.get("parts"), "record_date": hb.get("record_date")})
    pinned, out = _pinned(), {"triaged": 0, "incidents": [], "paged": [], "failures": 0}
    con = None
    for w in warnings:
        serial, model, pattern, verdict = w.get("serial"), w.get("model"), w.get("pattern"), w.get("verdict")
        n, died = w.get("n"), w.get("died")
        base = {"model": model, "pattern": pattern, "verdict": verdict, "n": n, "died": died, "site": site, "date": day,
                "record_date": rd}
        if verdict == "act":
            prior = db.incident_for_serial(serial)
            if prior and prior["status"] != "resolved":
                outcome, aid = f"already an open incident ({prior['status']})", prior["alert_id"]
            elif serial in pinned:
                from precedent.server import trigger_alert
                try:
                    res = trigger_alert({"serial": serial, "model": model, "pattern": pattern, "site": site,
                                         "source": "fleet"})
                    aid = res["alert"]["alert_id"]
                    outcome = f"incident opened, on-call paged ({res['channel']})"
                    out["paged"].append(aid)
                except Exception as e:  # a channel down: the incident still opens, the error is logged
                    log.exception("paging for %s failed; opening the incident anyway", serial)
                    aid = uuid.uuid4().hex[:8]
                    events.publish("incident_opened", {"alert": {**base, "alert_id": aid, "status": "open"},
                                                       "error": str(e)[:200]}, aid, serial)
                    outcome = f"incident opened; paging failed ({str(e)[:80]})"
            else:
                aid = uuid.uuid4().hex[:8]
                events.publish("incident_opened", {"alert": {**base, "alert_id": aid, "status": "paged (replay)",
                                                            "assigned_to": "Ops team (simulated)"}}, aid, serial)
                outcome = f"incident opened ({died} of {n} identical drives died in the fleet record); paged (replay)"
            out["incidents"].append(aid)
        elif verdict == "quiet":
            aid, outcome = None, f"logged, history says harmless ({n} drives, {died} died in the fleet record)"
        elif verdict == "watch":
            aid, outcome = None, f"added to the morning swap list ({died} of {n} identical drives died in the fleet record)"
        else:
            aid = None
            try:
                con = con or engine.connect(read_only=True)
                p = engine.precedent(con, model, pattern)
                near = f"closest precedent: {p['died']} of {p['n']} ({p['scope']})" if p.get("n") else "no precedent yet"
            except Exception as e:
                log.warning("precedent for %s %s unavailable: %s", model, pattern, e)
                near = "closest precedent unavailable"
            outcome = f"new pattern: logged for review, {near}"
        events.publish("warning_triaged", {**base, "outcome": outcome}, aid, serial)
        out["triaged"] += 1
    if con:
        con.close()
    for f_ in failures:
        serial = f_.get("serial")
        inc = db.incident_for_serial(serial)
        text, days = "failed with no warning", None
        if f_.get("warned_before"):
            prev = [e for e in db.serial_events(serial, ("warning_triaged", "telemetry_received"), 50)
                    if (e["data"] or {}).get("date")]
            try:
                first = f_.get("first_warned") or prev[0]["data"].get("record_date") or prev[0]["data"]["date"]
                days = (datetime.fromisoformat(str(rd)[:10]) - datetime.fromisoformat(str(first)[:10])).days
                text = f"failed; it had warned {days} days earlier"
            except (IndexError, ValueError, TypeError):
                text = "failed; it had warned earlier"
        if inc:
            from precedent import lifecycle
            lifecycle.check_verified(serial, str(day), healthy=False, failed=True)
        events.publish("drive_failed", {"model": f_.get("model"), "site": site, "date": day, "record_date": rd,
                                        "days": days,
                                        "warned_before": bool(f_.get("warned_before")), "outcome": text},
                       inc["alert_id"] if inc else None, serial)
        out["failures"] += 1
    return out


def live_record_date(serial: str) -> str | None:
    """The record_date of the drive's latest live reading/triage (so its story ends at today's warning), else None."""
    from precedent import db
    for ev in reversed(db.serial_events(serial, ("telemetry_received", "warning_triaged"), 20)):
        rd = (ev.get("data") or {}).get("record_date")
        if rd:
            return str(rd)[:10]
    return None


def get_drive_core(serial: str) -> dict:
    con = _con()
    try:
        prof = engine.drive_profile(con, serial, live_record_date=live_record_date(serial))
    finally:
        con.close()
    if not prof:
        raise LookupError(f"unknown drive {serial}")
    return prof


def log_decision_core(serial: str, choice: str, by: str = "api") -> dict:
    choice = (choice or "").lower()
    if choice not in ("swap", "wait"):
        raise ValueError("choice must be swap or wait")
    alert = next((a for a in reversed(decisions._read(decisions.ALERTS_PATH)) if a["serial"] == serial), None)
    if alert is None:
        raise LookupError(f"no alert for drive {serial}")
    from precedent.server import _decide
    return _decide(alert, choice, f"api:{by or 'unknown'}")


DB_DOWN = "drive history is unavailable right now (database missing or locked by an ingest)"


def _http(fn, *args):
    """The *_core functions raise ValueError for bad input and LookupError for unknown drives."""
    try:
        return fn(*args)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except duckdb.Error as e:
        log.warning("%s: %s", fn.__name__, e)
        raise HTTPException(503, DB_DOWN)


router = APIRouter(prefix="/v1", dependencies=[Depends(require_key)], tags=["public"])


@router.post("/telemetry")
def telemetry(payload: dict = Body(...)):
    return _http(report_telemetry_core, payload.get("serial"), payload.get("model"), payload.get("smart"),
                 payload.get("site"), payload.get("tenant"), payload.get("observed_on"), payload.get("logs"))


@router.post("/fleet/heartbeat")
def fleet_heartbeat(payload: dict = Body(...)):
    return _http(fleet_heartbeat_core, payload)


@router.get("/precedent")
def get_precedent(model: str, pattern: str):
    return _http(check_warning_core, model, pattern)


@router.get("/drives/{serial}")
def get_drive(serial: str):
    return _http(get_drive_core, serial)


@router.post("/decisions")
def post_decision(payload: dict = Body(...)):
    return _http(log_decision_core, payload.get("serial", ""), payload.get("choice", ""), payload.get("by", "api"))


mcp = MCPServer("Precedent public")


def _mcp(fn, *args) -> str:
    try:
        return json.dumps(fn(*args), default=str)
    except (ValueError, LookupError) as e:
        return json.dumps({"error": str(e)})
    except duckdb.Error as e:
        log.warning("%s: %s", fn.__name__, e)
        return json.dumps({"error": DB_DOWN})


@mcp.tool()
def check_warning(model: str, pattern: str) -> str:
    """What happened to every identical drive (same model + SMART warning pattern, e.g. "5+197+198:high"):
    n, died within 30 days, rate, and whether history says act."""
    return _mcp(check_warning_core, model, pattern)


@mcp.tool()
def report_telemetry(serial: str, model: str, smart: dict, site: str = "", tenant: str = "") -> str:
    """Report one drive's SMART reading, e.g. smart={"5": 120, "197": 8, "198": 8}. Returns its warning pattern and
    precedent; if history says act, Precedent alerts the on-call (once per drive + pattern per 24 h).
    With tenant, also returns `network`: that customer's own history vs the pooled network."""
    return _mcp(report_telemetry_core, serial, model, smart, site or None, tenant or None)


@mcp.tool(name="get_drive")
def get_drive_tool(serial: str) -> str:
    """One drive's identity, physical location, SMART history and past warnings with outcomes."""
    return _mcp(get_drive_core, serial)


@mcp.tool()
def log_decision(serial: str, choice: str, by: str = "agent") -> str:
    """Log a human/agent decision (swap or wait) against the drive's latest alert."""
    return _mcp(log_decision_core, serial, choice, by)


def mcp_asgi_app():
    """Streamable-HTTP MCP behind the same key check as REST."""
    inner = mcp.streamable_http_app(streamable_http_path="/", stateless_http=True, json_response=True,
                                    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))

    async def app(scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
            if not _key_ok(headers):
                body = b'{"error":"missing or invalid X-Precedent-Key"}'
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": body})
                return
        await inner(scope, receive, send)
    return app
