"""The console pages and their read-only JSON (GET /api/*).

Reads the engine through engine.connect(read_only=True) and falls back to data/samples/*.json while the DB is
missing or locked; responses that can fall back carry "source": "db" | "samples".
"""
import json
import logging
import os
import threading
import time

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse

from precedent import actions, config, lifecycle, playbooks, public_api

log = logging.getLogger(__name__)
router = APIRouter()
HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(config.DATA, "samples")
STARTED = time.time()  # "live since" for the console footer
_cache: dict = {}  # (name, db mtime) -> result; a backtest takes ~3 s, so never rerun it per request
_lock = threading.Lock()


def _profile(serial):
    """engine.drive_profile, ending the story at today's live warning when there is one."""
    lrd = public_api.live_record_date(serial)
    return _from_db(f"drive:{serial}:{lrd}", lambda con, e: e.drive_profile(con, serial, live_record_date=lrd))


def _sample(name):
    with open(os.path.join(SAMPLES, f"{name}.json")) as f:
        return json.load(f)


def _clean(obj):
    """DataFrame/numpy/date values -> plain JSON."""
    return json.loads(json.dumps(obj, default=lambda v: v.item() if hasattr(v, "item") else str(v)))


def _from_db(name, fn, cache=True):
    """Run fn(con, engine) against the real DB (cached per DB mtime); None if the DB isn't usable."""
    if not os.path.exists(config.DB_PATH):
        return None
    key = (name, os.path.getmtime(config.DB_PATH))
    if cache and key in _cache:
        return _cache[key]
    try:
        from precedent import engine
        with _lock:  # backtest builds TEMP tables; keep the heavy calls one at a time
            con = engine.connect(read_only=True)
            try:
                out = _clean(fn(con, engine))
            finally:
                con.close()
    except Exception as e:  # locked by the ingest, table missing, ...
        log.warning("%s: falling back to samples (%s)", name, e)
        return None
    if cache:
        _cache[key] = out
    return out


def _tiers(con, engine):
    cut = engine.default_cutoff(con)
    return {"urgent": engine.backtest(con, cut, config.MIN_N, config.MIN_RATE),
            "swaplist": engine.backtest(con, cut, config.SWAPLIST_MIN_N, config.SWAPLIST_MIN_RATE)}


def _read_jsonl(path, limit):
    rows = []
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass  # half-written line
    return rows[::-1][:limit]


@router.get("/stage")
def stage():
    """The single-screen status board."""
    return FileResponse(os.path.join(HERE, "index.html"))


@router.get("/app")
@router.get("/app/{_rest:path}")
def app_page(_rest: str = ""):
    """The product console: one page, client-side routes under /app (app.js)."""
    return FileResponse(os.path.join(HERE, "app.html"), headers={"Cache-Control": "no-cache"})


@router.get("/incidents")
@router.get("/incidents/{_rest:path}")
@router.get("/drives")
@router.get("/drives/{_rest:path}")
@router.get("/graph")
@router.get("/integrations")
@router.get("/impact")
def old_paths(request: Request, _rest: str = ""):
    """Old console paths -> /app equivalents (query string kept)."""
    path = request.url.path.rstrip("/")
    q = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(f"/app{path}{q}", status_code=308)


@router.get("/app.js")
def app_js():
    return FileResponse(os.path.join(HERE, "app.js"), media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@router.get("/api/backtest")
def api_backtest():
    out = _from_db("backtest", _tiers)
    if out is None:
        return {"urgent": _sample("backtest"), "swaplist": _sample("backtest_swaplist"), "source": "samples"}
    return {**out, "source": "db"}


@router.get("/api/patterns")
def api_patterns():
    out = _from_db("patterns", lambda con, e: e.top_patterns(con).to_dict("records"))
    if out is None:
        return {"rows": _sample("top_patterns"), "source": "samples"}
    return {"rows": out, "source": "db"}


@router.get("/api/demo-drive")
def api_demo_drive():
    d = _sample("demo_drive")
    p = _from_db("precedent:" + d["serial"], lambda con, e: e.precedent(con, d["model"], d["pattern"], exclude_serial=d["serial"]))
    source = "db"
    if p is None:
        p, source = _sample("precedent"), "samples"
    sim = _from_db("similar:" + d["serial"], lambda con, e: e.similar_drives(
        con, d["model"], d["pattern"], limit=30, exclude_serial=d["serial"]).to_dict("records")) or []
    known = [x for x in sim if not x.get("censored")]
    return {**d, "precedent": p, "similar": known[:3], "scoped": _scoped(d["serial"], d["model"], d["pattern"]),
            "horizon_days": config.HORIZON_DAYS, "source": source}


def _scoped(serial, model, pattern):
    """engine.precedent_scoped: this customer's own history vs the pooled network (None if unavailable)."""
    out = _from_db(f"scoped:{serial}:{pattern}", lambda con, e: e.precedent_scoped(con, model, pattern, exclude_serial=serial))
    if out is None:
        try:
            smp = _sample("precedent_scoped")
            if (smp.get("own") or {}).get("pattern") == pattern and (smp.get("own") or {}).get("model") == model:
                out = smp
        except OSError:
            pass
    return out


@router.get("/api/precedent/scoped")
def api_precedent_scoped(serial: str, model: str | None = None, pattern: str | None = None):
    """Your fleet vs Precedent network for one drive (model/pattern default to the drive's latest warning)."""
    if not (model and pattern):
        prof = _profile(serial) or {}
        w = (prof.get("warnings") or [{}])[-1]
        model, pattern = model or prof.get("model"), pattern or w.get("pattern")
    if not (model and pattern):
        return {"found": False, "serial": serial}
    out = _scoped(serial, model, pattern)
    return {"found": bool(out), "serial": serial, **(out or {})}


@router.get("/api/swaplist")
def api_swaplist():
    out = _from_db("swaplist", lambda con, e: e.swap_list(
        con, 10, min_n=config.SWAPLIST_MIN_N, min_rate=config.SWAPLIST_MIN_RATE).to_dict("records"))
    return {"rows": out or [], "source": "db" if out is not None else "samples"}


@router.get("/api/decisions")
def api_decisions(limit: int = 20):
    return {"rows": _read_jsonl(config.DECISIONS_PATH, limit)}


def _actions(limit):
    """Agent action rows (actions.jsonl), newest first."""
    return _read_jsonl(actions.ACTIONS_PATH, limit)


def _iso(ts):
    if ts is None:
        return None
    ts = ts / 1000 if ts > 1e12 else ts
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts)) + "Z"


def _db_incidents(limit=200):
    """Incidents from the SQLite store (e.g. 'paged (replay)' ones from the fleet replay), shaped like alert rows."""
    try:
        from precedent import db
        rows = db.conn().execute("SELECT * FROM incidents ORDER BY created_ts DESC LIMIT ?", (limit,)).fetchall()
    except Exception as e:
        log.warning("incidents table unavailable: %s", e)
        return []
    return [{"alert_id": r["alert_id"], "serial": r["serial"], "model": r["model"], "pattern": r["pattern"], "n": r["n"], "died": r["died"],
             "ts": _iso(r["created_ts"]), "status": r["status"], "verdict": r["verdict"], "site": r["site"], "choice": r["choice"],
             "channel": "call", "assigned_to": r["assigned_to"] if "assigned_to" in r.keys() else None} for r in rows]


@router.get("/api/alerts")
def api_alerts(limit: int = 10, db: int = 0):
    """Alerts from the local log; with db=1 (the /app console) also the incidents table, e.g. replay incidents.
    The /stage board leaves db off so a reset really empties its live panel."""
    rows = _read_jsonl(os.path.join(config.STATE_DIR, "alerts.jsonl"), max(limit, 200))
    seen = {r.get("alert_id") for r in rows}
    if db:
        rows += [r for r in _db_incidents() if r["alert_id"] not in seen]
    rows.sort(key=lambda r: str(r.get("ts") or ""), reverse=True)
    return {"rows": rows[:limit], "total": len(rows)}


@router.get("/api/stage")
def api_stage():
    """Small config the page needs (technician inbox number for the chat header)."""
    return {"tech_number": os.getenv("TECH_INBOX_NUMBER", ""), "horizon_days": config.HORIZON_DAYS, "live_since": _iso(STARTED),
            "oncall_name": lifecycle.ONCALL_NAME, "tech_name": lifecycle.TECH_NAME, "states": lifecycle.STATES}


@router.get("/api/incident/{alert_id}")
def api_incident(alert_id: str):
    """Everything about one alert from local state + the engine; the page adds live call/summary/thread/Keewano."""
    alerts = [a for a in _read_jsonl(os.path.join(config.STATE_DIR, "alerts.jsonl"), 10_000) if a.get("alert_id") == alert_id]
    if not alerts:
        alerts = [r for r in _db_incidents(5000) if r["alert_id"] == alert_id]
    if not alerts:
        return {"found": False, "alert_id": alert_id}
    alert = alerts[0]
    decs = [d for d in _read_jsonl(config.DECISIONS_PATH, 10_000) if d.get("alert_id") == alert_id]
    acts = [r for r in _actions(500) if r.get("alert_id") == alert_id]
    eng = _from_db(f"incident:{alert_id}", lambda con, e: {
        "precedent": e.precedent(con, alert["model"], alert["pattern"], exclude_serial=alert["serial"]),
        "similar": e.similar_drives(con, alert["model"], alert["pattern"], limit=8,
                                    exclude_serial=alert["serial"]).to_dict("records")}) or {}
    life = {"state": lifecycle.state_of(alert_id), "stamps": lifecycle.stamps(alert_id), "states": lifecycle.STATES}
    try:
        fix = alert.get("suggested_fix") or playbooks.suggestion(alert["model"], alert["pattern"], alert["serial"])
    except Exception as e:
        log.warning("suggested fix for %s unavailable: %s", alert_id, e)
        fix = None
    return {"found": True, "alert": alert, "decisions": decs[::-1], **life, "suggested_fix": fix, "actions": sorted(acts, key=lambda r: str(r.get("ts"))),
            "precedent": eng.get("precedent"), "similar": eng.get("similar", []),
            "horizon_days": config.HORIZON_DAYS, "tech_number": os.getenv("TECH_INBOX_NUMBER", "")}


@router.get("/incident/{alert_id}")
def incident_page(alert_id: str):
    return FileResponse(os.path.join(HERE, "incident.html"))


@router.get("/api/drives/{serial}")
def api_drive(serial: str):
    """Drive page: engine.drive_profile + this drive's alerts/decisions/actions from local state (for the timeline)."""
    prof = _profile(serial)
    source = "db"
    if prof is None:
        try:
            prof, source = _sample("drive_profile"), "samples"
        except OSError:
            prof = None
        if not prof or prof.get("serial") != serial:
            return {"found": False, "serial": serial}
    if not prof or not prof.get("serial"):
        return {"found": False, "serial": serial}
    alerts = [a for a in _read_jsonl(os.path.join(config.STATE_DIR, "alerts.jsonl"), 10_000) if a.get("serial") == serial]
    ids = {a["alert_id"] for a in alerts}
    decs = [d for d in _read_jsonl(config.DECISIONS_PATH, 10_000) if d.get("alert_id") in ids]
    acts = [r for r in _actions(1000) if r.get("alert_id") in ids]
    return {"found": True, **prof, "alerts": alerts, "decisions": decs, "actions": acts,
            "horizon_days": config.HORIZON_DAYS, "source": source}


@router.get("/api/fleet/matrix")
def api_fleet_matrix(datacenter: str, serial: str | None = None):
    """One cell per drive for a datacenter: {datacenter, n, cols, statuses, vault_breaks, highlight_index?} (engine.fleet_matrix)."""
    out = _from_db(f"matrix:{datacenter}:{serial}", lambda con, e: e.fleet_matrix(con, datacenter, serial))
    return out or {"datacenter": datacenter, "n": 0, "statuses": "", "error": "matrix unavailable"}


@router.get("/api/fleet/cell")
def api_fleet_cell(datacenter: str, i: int):
    """The drive behind one matrix cell (lazy hover/click lookup)."""
    return _from_db(f"cell:{datacenter}:{i}", lambda con, e: e.fleet_cell(con, datacenter, i)) or {}


@router.get("/api/fleet/map")
def api_fleet_map(datacenter: str | None = None, vault_id: str | None = None, pod_id: str | None = None):
    """engine.fleet_map at any level: fleet (no args) / datacenter / pod (datacenter + vault_id + pod_id)."""
    out = _from_db(f"map:{datacenter}:{vault_id}:{pod_id}", lambda con, e: e.fleet_map(con, datacenter, vault_id, pod_id))
    if out is None and pod_id:
        try:
            out = _sample("fleet_pod")
            if (out.get("vault_id"), out.get("pod_id")) != (vault_id, pod_id):
                out = None
        except OSError:
            out = None
    return out or {"level": None, "error": "map unavailable"}


ATTR = {"5": "5 reallocated sectors", "187": "187 reported uncorrectable", "188": "188 command timeouts",
        "197": "197 pending sectors", "198": "198 offline uncorrectable"}
SEV = {"low": "low (under 8)", "mid": "mid (8 to 99)", "high": "high (100 or more)"}


def _lc(t):
    return t[:1].lower() + t[1:] if t[:2] != t[:2].upper() else t  # "Reseated the cable" -> "reseated the cable"; keep "RMA"


def _pct(x):
    return f"{x * 100:.0f}%" if x is not None else "n/a"


@router.get("/api/graph")
def api_graph(alert_id: str | None = None, serial: str | None = None):
    """Memory graph for one alert (or one drive): {nodes: [{id, type, label, summary, data}], edges: [{from, to}]}.
    Every summary is a template filled from real data (engine, alert/decision/action logs, Keewano, channels)."""
    alerts = _read_jsonl(os.path.join(config.STATE_DIR, "alerts.jsonl"), 10_000)
    alert = next((x for x in alerts if alert_id and x.get("alert_id") == alert_id), None) \
        or next((x for x in alerts if serial and x.get("serial") == serial), None)
    if alert is None and not serial:
        if alerts:
            alert = alerts[0]
        else:
            serial = _sample("demo_drive")["serial"]
    serial = alert["serial"] if alert else serial
    prof = _profile(serial) or {}
    if not prof.get("serial"):
        return {"found": False, "serial": serial, "nodes": [], "edges": []}
    warn = (prof.get("warnings") or [{}])[-1]
    model, pattern = prof["model"], (alert or {}).get("pattern") or warn.get("pattern")
    eng = _from_db(f"graph:{serial}:{pattern}", lambda con, e: {
        "p": e.precedent(con, model, pattern, exclude_serial=serial),
        "sim": e.similar_drives(con, model, pattern, limit=30, exclude_serial=serial).to_dict("records")}) or {}
    p, sim = eng.get("p") or {}, eng.get("sim") or []
    known = [d for d in sim if not d.get("censored")]  # show outcomes we know: two that died, two that survived
    sim = ([d for d in known if d.get("died")][:2] + [d for d in known if not d.get("died")][:2]) or sim[:4]
    bt = _from_db("backtest", _tiers) or {}
    u = bt.get("urgent") or {}
    base = u["L_failures"] / u["N_checks_today"] if u.get("N_checks_today") else None
    H = config.HORIZON_DAYS
    nodes, edges = [], []

    def node(id_, type_, label, summary, data=None, after=()):
        nodes.append({"id": id_, "type": type_, "label": label, "summary": summary, "data": data or {}})
        edges.extend({"from": f, "to": id_} for f in after)

    loc = prof.get("location") or {}
    where = (f"in {loc['datacenter']}, vault {loc['vault_id']}, pod {loc['pod_id']}, slot {loc['pod_slot_num']}"
             if loc.get("datacenter") else "(location syncing)")
    node("drive", "drive", serial, f"Drive {serial} is a {model} {where}. In service {prof.get('first_seen')} to {prof.get('last_seen')}"
         + (f"; it failed on {prof['failed_on']}." if prof.get("failed_on") else "; still running at the end of the data."),
         {"model": model, **{k: v for k, v in loc.items() if v}, "failed_on": prof.get("failed_on")})
    node("model", "model", model, f"Precedent only compares like with like: {model} drives are judged against other {model} drives, "
         "never against the fleet average for all models.", {"model": model}, ["drive"])
    attrs, _, sev = str(pattern).partition(":")
    node("pattern", "pattern", pattern, f"Warning {pattern}: non-zero " + ", ".join(ATTR.get(x, "SMART " + x) for x in attrs.split("+"))
         + (f", severity {SEV.get(sev, sev)}" if sev else "")
         + (f". This drive showed it at {alert['ts']}." if alert and alert.get("ts") and alert.get("pattern") == pattern  # live incident: its own time
            else f". First seen on this drive on {warn.get('warn_date', 'n/a')}."),
         {"pattern": pattern, "warn_date": warn.get("warn_date")}, ["model"])
    node("precedent", "precedent", f"{p.get('n', 0)} drives · {p.get('died', 0)} failed",
         f"Of {p.get('n', 0)} {model} drives that showed {pattern}, {p.get('died', 0)} failed within {H} days ({_pct(p.get('rate'))})."
         + (f" Fleet baseline for warned drives is {base * 100:.1f}%." if base is not None else "")
         + (" History says act." if p.get("act") else " Not enough for an urgent call."),
         {"n": p.get("n"), "died": p.get("died"), "rate": p.get("rate"), "baseline": base, "scope": p.get("scope")}, ["pattern"])
    sc = _scoped(serial, model, pattern) or {}
    sim_from = "precedent"
    if sc.get("own") and sc.get("network"):
        own, net, others = sc["own"], sc["network"], max(0, (sc.get("tenants_contributing") or 1) - 1)
        tenant = sc.get("tenant") or "This customer"
        node("network", "network", f"{sc.get('tenants_contributing')} customers pooled",
             f"{tenant} alone: {own.get('n')} drives" + (f", {own.get('died')} died, not enough to decide." if not own.get("enough") else
             f", {own.get('died')} died.") + f" Pooled with {others} other customer{'s' if others != 1 else ''}: {net.get('n')} drives, "
             f"{net.get('died')} died." + (" Pooling is what made this call possible." if net.get("act") and not own.get("act") else ""),
             {"tenant": tenant, "own_n": own.get("n"), "own_died": own.get("died"), "network_n": net.get("n"),
              "network_died": net.get("died"), "customers": ", ".join(sc.get("contributors") or [])}, ["precedent"])
        sim_from = "network"
    for i, d in enumerate(sim):
        died = bool(d.get("died"))
        outcome = (f"died on {str(d.get('failed_on'))[:10]}" if died else
                   "outcome not known yet" if d.get("censored") else f"was still alive {H} days later")
        node(f"sim{i}", "similar", d["serial"], f"Drive {d['serial']} showed the same {pattern} on {str(d.get('warn_date'))[:10]} and {outcome}.",
             {"died": died, "warn_date": str(d.get("warn_date"))[:10]}, [sim_from])
    try:  # learned playbook: what engineers logged for this exact warning
        from precedent import db
        res = db.resolutions(model, pattern, exclude_serial=serial, limit=20)
    except Exception as e:
        log.warning("resolutions unavailable: %s", e)
        res = []
    if res:
        r0 = res[0]
        when = _iso(r0.get("ts")) or ""
        node("playbook", "playbook", (r0.get("note") or r0.get("action") or "Logged fix")[:40],
             f"Last time this warning appeared, {r0.get('by') or 'an engineer'} {_lc((r0.get('note') or r0.get('action') or 'logged a fix').rstrip('.'))}"
             f"{' on ' + when[:10] if when else ''}. Logged {len(res)} time{'s' if len(res) != 1 else ''} for {model} · {pattern}. "
             "Precedent suggests it on the next identical warning; applying it is rehearsed in Sparta first, then carried out via Darwin.",
             {"by": r0.get("by"), "action": r0.get("action"), "times_logged": len(res)}, ["precedent"])
    last = "precedent"
    if alert:
        aid = alert["alert_id"]
        node("alert", "alert", "On-call alerted", f"Precedent alerted the on-call at {alert.get('ts')} by {alert.get('channel', 'sms')}, "
             f"citing {alert.get('died')} of {alert.get('n')} identical drives dying.", alert, ["precedent"])
        last = "alert"
        from precedent import server
        call = dict(server._call_state)
        if call.get("alert_id") != aid:
            call = {}
        if alert.get("channel") in ("call", "both"):
            tx = (call.get("transcript") or "").strip()
            node("call", "call", "Voice call", f"Dial called the on-call ({call.get('state') or 'state unknown'})."
                 + (f" Transcript: \"{tx[-240:]}\"" if tx else " No transcript yet."), {k: call.get(k) for k in ("call_id", "state", "decision")}, ["alert"])
            last = "call"
        decs = [d for d in _read_jsonl(config.DECISIONS_PATH, 10_000) if d.get("alert_id") == aid]
        if decs:
            d = decs[0]
            node("decision", "decision", {"swap": "Replace", "wait": "Wait", "show": "Asked for details"}.get(d["choice"], d["choice"].title()), f"The on-call chose {d['choice'].upper()} at {d['ts']}. "
                 + ("The decision was logged and pushed to Keewano as a drive event." if d.get("keewano_logged") is True else
                    "The decision was saved locally (not pushed to Keewano)." if d.get("keewano_logged") is False else
                    "The decision was logged."), d, [last])
            last = "decision"
        elif call.get("decision") == "unclear":
            node("decision", "decision", "No clear answer", "No clear answer on the call, so the full details went to the technician inbox.", call, [last])
            last = "decision"
        acts = {r["sponsor"]: r for r in sorted(_actions(1000), key=lambda r: str(r.get("ts"))) if r.get("alert_id") == aid}
        act_ids = []
        for sp, label in (("darwin", "Darwin"), ("sparta", "Sparta")):
            if sp in acts:
                r = acts[sp]
                node(sp, "action", label, (r.get("detail") if isinstance(r.get("detail"), str) else f"{label}: {r.get('status')}"), r, [last])
                act_ids.append(sp)
        last_ids = act_ids or [last]
        try:
            from precedent import notify
            ch = notify.status().get("channels", {})
        except Exception as e:
            log.warning("notification status unavailable: %s", e)
            ch = {}
        on = [k for k, v in ch.items() if v.get("configured")]
        node("channels", "channels", "Channels", ("Notifications go to " + ", ".join(on) + "." if on else
             "Slack, Discord, Teams and webhook notifications are available; none is configured on this server yet."), ch, last_ids)
        last_ids = ["channels"]
    else:
        last_ids = [last]
    kw = _kw.get("data") or {}
    lua = _lua_now()
    krow = next((r for r in lua.get("rows") or [] if r.get("model") == model and r.get("pattern") == pattern), None)
    lua_txt = ""
    if krow:
        kn, kd = int(krow.get("n") or 0), int(krow.get("died") or 0)
        window = max(0, kn - int(p.get("n") or 0) - 1)
        lua_txt = (f" Computed inside Keewano (Lua over {os.getenv('KEEWANO_INGESTED_DRIVES', '12,111')} drives): {kn} warnings of this pattern, "
                   f"{kd} died. Matches the engine, which shows {p.get('n')} because it leaves out this drive"
                   + (f" and the {window} warnings still inside their {H}-day window." if window else "."))
    decs_kw = ", ".join(f"{x.get('decision')} {x.get('n')}" for x in kw.get("decisions") or [] if x.get("decision"))
    node("keewano", "keewano", "Keewano", ("Keewano is live: " if kw.get("connected") or lua.get("connected") else "Keewano (not connected on this server): ")
         + "every warning, alert and decision for this drive is stored as an event, so the next warning starts with this history." + lua_txt
         + (f" Decisions recorded so far: {decs_kw}." if decs_kw else ""), {"connected": kw.get("connected") or lua.get("connected"), "lua_n": (krow or {}).get("n"), "lua_died": (krow or {}).get("died"),
          "lua_seconds": lua.get("seconds")},
         ["precedent"] + (["decision"] if any(n["id"] == "decision" for n in nodes) else []))
    return {"found": True, "alert_id": (alert or {}).get("alert_id"), "serial": serial, "nodes": nodes, "edges": edges}


_risk = {"at": 0.0, "busy": False, "data": None}


def _refresh_risk():
    try:
        from precedent import keewano
        out = keewano.at_risk(max_age_s=60, limit=10)
        if out.get("rows"):
            _risk["data"] = {"source": "keewano", "rows": _clean(out["rows"]), "scored": out.get("scored"),
                             "seconds": out.get("seconds")}
    except Exception:
        log.exception("at-risk refresh failed")
    _risk["at"], _risk["busy"] = time.time(), False


@router.get("/api/keewano/at-risk")
def api_at_risk():
    """Top drives most likely to fail next: Keewano's own ranking (keewano.at_risk, refreshed in the background
    every 60 s). Until Keewano has answered, the engine's swap list (source=engine)."""
    if time.time() - _risk["at"] > 60 and not _risk["busy"]:
        _risk["busy"] = True
        threading.Thread(target=_refresh_risk, daemon=True).start()
    if _risk["data"]:
        return _risk["data"]
    sw = _from_db("swaplist5", lambda con, e: e.swap_list(con, 5, min_n=config.SWAPLIST_MIN_N, min_rate=config.SWAPLIST_MIN_RATE).to_dict("records")) or []
    return {"source": "engine", "rows": sw}


@router.post("/api/reset")
def api_reset():
    """Empty the live panel: move alerts/decisions/actions into STATE_DIR/archive/<ts>/. Never deletes."""
    dest = os.path.join(config.STATE_DIR, "archive", time.strftime("%Y%m%d-%H%M%S"))
    base, i = dest, 1
    while os.path.exists(dest):  # two resets in one second must not overwrite an archive
        i += 1
        dest = f"{base}-{i}"
    moved = []
    for name in ("alerts.jsonl", "decisions.jsonl", "actions.jsonl"):
        src = os.path.join(config.STATE_DIR, name)
        if os.path.exists(src):
            os.makedirs(dest, exist_ok=True)
            os.replace(src, os.path.join(dest, name))  # atomic; writers just start a fresh file
            moved.append(name)
    return {"ok": True, "archived_to": dest if moved else None, "moved": moved}


_kw = {"at": 0.0, "busy": False, "data": {"connected": False, "rows": [], "error": "not queried yet"}}


def _refresh_keewano():
    try:
        from precedent import keewano
        _kw["data"] = _clean(keewano.live_table())
    except Exception as e:
        _kw["data"] = {"connected": False, "rows": [], "error": str(e)[:300]}
    _kw["at"], _kw["busy"] = time.time(), False


@router.get("/api/keewano")
def api_keewano():
    """Cached 30 s, refreshed in the background so a slow Keewano never stalls the page."""
    if time.time() - _kw["at"] > 30 and not _kw["busy"]:
        _kw["busy"] = True
        threading.Thread(target=_refresh_keewano, daemon=True).start()
    return {**_kw["data"], "age_s": round(time.time() - _kw["at"]) if _kw["at"] else None}


_lua = {"at": 0.0, "busy": False, "data": {"connected": False, "rows": [], "error": "not computed yet"}}


def _refresh_lua():
    try:
        from precedent import keewano
        _lua["data"] = _clean(keewano.lua_table())
    except Exception as e:
        _lua["data"] = {"connected": False, "rows": [], "error": str(e)[:300]}
    _lua["at"], _lua["busy"] = time.time(), False


def _lua_now():
    """Keewano's own precedent table (Lua inside Keewano, ~10 s): refreshed in the background, never waited on."""
    if time.time() - _lua["at"] > 600 and not _lua["busy"]:
        _lua["busy"] = True
        threading.Thread(target=_refresh_lua, daemon=True).start()
    return _lua["data"]


@router.get("/api/keewano/lua")
def api_keewano_lua(model: str | None = None, pattern: str | None = None):
    d = _lua_now()
    rows = d.get("rows") or []
    out = {k: v for k, v in d.items() if k != "rows"}
    out["patterns"] = len(rows)
    out["age_s"] = round(time.time() - _lua["at"]) if _lua["at"] else None
    if model and pattern:
        out["row"] = next((r for r in rows if r.get("model") == model and r.get("pattern") == pattern), None)
    else:
        out["rows"] = rows[:50]
    return out


def _warm():
    """Compute the slow backtests (and Keewano's Lua table) at startup so the first page load is instant."""
    _lua_now()
    _from_db("backtest", _tiers)


threading.Thread(target=_warm, daemon=True).start()
