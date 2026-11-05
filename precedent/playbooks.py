"""Learn from the fix: every resolution becomes a playbook; the next identical warning gets it as a suggested fix.

record(alert, action, note, by)  on resolve: the person's own words become steps_text, action classified by keywords.
lookup(model, pattern)           same model+pattern, else same pattern, else same counters (attrs); newest first.
apply(alert_id, by, via)         idempotent per incident, runs in the background:
   1. rehearse in the Sparta Zendesk world: a ticket carrying the steps, one injected failure, then checks
      (opened, failure recovered, replay = same ticket, steps present) -> sparta_verified {ok, ticket, checks}
   2. only if that passes: execute via Darwin Act (search for an agent that can do the steps, POST /api/v3/act with
      Idempotency-Key = alert_id, poll the request). No agent able to act -> logged honestly, a human does it.
   3. failed rehearsal -> "Blocked: the action agent failed its Sparta rehearsal", page a human, no action.
A verified incident (7 healthy days) whose playbook was applied increments times_worked.
"""
import contextvars
import json
import logging
import re
import threading
import time

import httpx

from precedent import db, events
from precedent.config import HORIZON_DAYS

log = logging.getLogger(__name__)

ACTIONS = [("replaced", r"\b(replac\w*|swapp?\w*|new drive)\b"), ("reseated", r"\b(reseat\w*|re-seat\w*|cable|connector|seated)\b"),
           ("firmware", r"\b(firmware|fw|updat\w*)\b"), ("rma", r"\b(rma|warranty|return\w*)\b"),
           ("cleaned", r"\b(clean\w*|dust|cool\w*|fan)\b"), ("no_fault_found", r"\b(no fault|nff|nothing wrong|false alarm)\b")]
_lock = threading.Lock()
_applying: set = set()


def _ensure() -> None:
    db.init()
    c = db.conn()
    with db._wlock:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS playbooks (id INTEGER PRIMARY KEY AUTOINCREMENT, model TEXT, pattern TEXT, attrs TEXT,
            steps_text TEXT, action TEXT, by TEXT, alert_id TEXT, created_ts INTEGER, times_used INTEGER DEFAULT 0,
            times_worked INTEGER DEFAULT 0);
        CREATE INDEX IF NOT EXISTS pb_mp ON playbooks(model, pattern, created_ts);
        CREATE INDEX IF NOT EXISTS pb_p ON playbooks(pattern, created_ts);
        CREATE INDEX IF NOT EXISTS pb_a ON playbooks(attrs, created_ts);""")
        have = {r["name"] for r in c.execute("PRAGMA table_info(incidents)")}
        for col in ("suggested_playbook_id", "applied_playbook_id"):
            if col not in have:
                c.execute(f"ALTER TABLE incidents ADD COLUMN {col} INTEGER")
        if "serial" not in {r["name"] for r in c.execute("PRAGMA table_info(playbooks)")}:
            c.execute("ALTER TABLE playbooks ADD COLUMN serial TEXT")
        c.commit()


_ensure()


def classify(note: str, action: str | None = None) -> str:
    text = (note or "").lower()
    for name, rx in ACTIONS:
        if re.search(rx, text):
            return name
    return action or "other"


def record(alert: dict, action: str, note: str, by: str, ts_ms: int | None = None) -> dict:
    """Store a playbook from a resolution (no note: the action alone)."""
    act = classify(note, action) if note else action
    steps = (note or "").strip() or {"replaced": "Replaced the drive", "reseated": "Reseated the drive",
                                     "firmware": "Updated the drive firmware", "rma": "Sent the drive back under warranty (RMA)",
                                     "cleaned": "Cleaned and re-cooled the bay", "no_fault_found": "Checked it: no fault found"}.get(act, act)
    pattern = alert.get("pattern") or ""
    with db._wlock:
        cur = db.conn().execute("""INSERT INTO playbooks (model, pattern, attrs, steps_text, action, by, alert_id, created_ts, serial)
                                   VALUES (?,?,?,?,?,?,?,?,?)""", (alert.get("model"), pattern, pattern.split(":")[0], steps,
                                                                   act, by, alert.get("alert_id"), ts_ms or int(time.time() * 1000),
                                                                   alert.get("serial")))
        db.conn().commit()
    pb = {"id": cur.lastrowid, "model": alert.get("model"), "pattern": pattern, "steps_text": steps, "action": act, "by": by}
    events.publish("playbook_learned", {**pb, "text": f"Saved {by}'s fix for next time: \"{steps}\""}, alert.get("alert_id"),
                   alert.get("serial"), ts_ms)
    return pb


def lookup(model: str, pattern: str, exclude_serial: str | None = None) -> dict | None:
    """Newest playbook by basis; a drive's own earlier fix is excluded (it is not precedent for itself)."""
    attrs = (pattern or "").split(":")[0]
    for basis, where, args in (("same model and warning", "model=? AND pattern=?", (model, pattern)),
                               ("same warning on another model", "pattern=?", (pattern,)),
                               ("same SMART counters", "attrs=?", (attrs,))):
        r = db.conn().execute(f"SELECT * FROM playbooks WHERE {where} AND coalesce(serial,'')!=? "
                              f"ORDER BY created_ts DESC LIMIT 1", (*args, exclude_serial or "")).fetchone()
        if r:
            return {**dict(r), "basis": basis}
    return None


def suggestion(model: str, pattern: str, exclude_serial: str | None = None) -> dict | None:
    """The suggested_fix shape for an alert/incident, or None."""
    pb = lookup(model, pattern, exclude_serial)
    if not pb:
        return None
    when = time.strftime("%b %d %H:%M", time.localtime(pb["created_ts"] / 1000))
    return {"playbook_id": pb["id"], "steps_text": pb["steps_text"], "action": pb["action"], "by": pb["by"],
            "when": when, "basis": pb["basis"], "times_used": pb["times_used"], "times_worked": pb["times_worked"]}


def attach(alert: dict) -> None:
    """After the incident row exists: store + publish the suggestion carried on the alert."""
    s = alert.get("suggested_fix")
    if not s:
        return
    with db._wlock:
        db.conn().execute("UPDATE incidents SET suggested_playbook_id=? WHERE alert_id=?", (s["playbook_id"], alert["alert_id"]))
        db.conn().commit()
    held = f" It held {s['times_worked']} of {s['times_used']} times." if s["times_used"] else ""
    events.publish("playbook_suggested", {**s, "text": f"Last time, {s['by']} fixed a drive like this: {s['steps_text']}.{held}"},
                   alert["alert_id"], alert["serial"])


def credit_if_applied(alert_id: str) -> None:
    """Called when an incident verifies (no new warnings for 7 days)."""
    r = db.conn().execute("SELECT applied_playbook_id, serial FROM incidents WHERE alert_id=?", (alert_id,)).fetchone()
    if r and r["applied_playbook_id"]:
        with db._wlock:
            db.conn().execute("UPDATE playbooks SET times_worked = times_worked + 1 WHERE id=?", (r["applied_playbook_id"],))
            db.conn().commit()
        events.publish("playbook_worked", {"playbook_id": r["applied_playbook_id"],
                                           "text": "The applied fix held: no new warnings for 7 days"}, alert_id, r["serial"])


def apply(alert: dict, by: str, via: str, page_human) -> dict:
    """Start applying the suggested playbook (idempotent per incident). Returns immediately; work runs in a thread."""
    aid = alert["alert_id"]
    r = db.conn().execute("SELECT suggested_playbook_id, applied_playbook_id FROM incidents WHERE alert_id=?", (aid,)).fetchone()
    pb_id = (r and (r["applied_playbook_id"] or r["suggested_playbook_id"])) or (alert.get("suggested_fix") or {}).get("playbook_id")
    if not pb_id:
        return {"ok": False, "status": "no playbook for this warning yet"}
    with _lock:
        if aid in _applying or (r and r["applied_playbook_id"]):
            return {"ok": True, "status": "already applying or applied", "playbook_id": pb_id}
        _applying.add(aid)
    pb = dict(db.conn().execute("SELECT * FROM playbooks WHERE id=?", (pb_id,)).fetchone())
    events.publish("playbook_apply", {"playbook_id": pb_id, "by": by, "via": via,
                                      "text": f"Applying the last fix: {pb['steps_text']}."}, aid, alert["serial"])
    ctx = contextvars.copy_context()
    threading.Thread(target=ctx.run, args=(_run, alert, pb, page_human), daemon=True).start()
    return {"ok": True, "status": "rehearsing in Sparta", "playbook_id": pb_id}


def _run(alert: dict, pb: dict, page_human) -> None:
    aid, serial = alert["alert_id"], alert["serial"]
    try:
        ok, ticket, checks = rehearse(alert, pb)
    except Exception as e:
        log.exception("Sparta rehearsal for %s failed", aid)
        ok, ticket, checks = False, None, {"error": str(e)[:200]}
    events.publish("sparta_verified", {"ok": ok, "ticket": ticket, "checks": checks,
                                       "text": (f"Practiced the fix in Sparta first: it passed (ticket #{ticket})." if ok
                                                else "Practiced the fix in Sparta first: it failed, so nothing was done.")}, aid, serial)
    if not ok:
        events.publish("playbook_blocked", {"text": "Stopped: the agent failed its practice run. Asked a person instead."}, aid, serial)
        try:
            page_human(alert, f"Precedent: the automated fix for {serial} failed its rehearsal and was NOT applied. "
                              f"Please do it by hand: {pb['steps_text']}")
        except Exception:
            log.exception("paging a person for %s failed", aid)
        _done(aid)
        return
    with db._wlock:
        db.conn().execute("UPDATE incidents SET applied_playbook_id=? WHERE alert_id=?", (pb["id"], aid))
        db.conn().execute("UPDATE playbooks SET times_used = times_used + 1 WHERE id=?", (pb["id"],))
        db.conn().commit()
    try:
        res = darwin_act(alert, pb)
    except Exception as e:
        log.warning("Darwin Act for %s failed: %r", aid, e)
        res = {"status": "error", "text": "Couldn't reach an agent for the fix, so a person will.", "error": str(e)[:200]}
    events.publish("darwin_act", res, aid, serial)
    _done(aid)


def _done(aid: str) -> None:
    with _lock:
        _applying.discard(aid)


def _ticket_body(alert: dict, pb: dict) -> dict:
    from precedent.sparta import _plain
    loc = alert.get("site") or "the datacenter"
    return {"ticket": {
        "subject": f"Playbook: {pb['action']} {alert['serial']} {alert['model']}",
        "comment": {"body": _plain(f"Apply the fix that worked last time ({pb['by']}): {pb['steps_text']}\n"
                                   f"Drive {alert['serial']} ({alert['model']}) at {loc}, warning {alert['pattern']}.\n"
                                   f"Evidence: {alert['died']} of {alert['n']} identical drives died within {HORIZON_DAYS} days.\n"
                                   f"Precedent alert {alert['alert_id']}.")},
        "priority": "high", "tags": ["precedent", "playbook", pb["action"]], "external_id": f"precedent-pb-{alert['alert_id']}"}}


def rehearse(alert: dict, pb: dict) -> tuple[bool, int | None, dict]:
    """Run the playbook as a ticket in the Sparta world with one injected failure; verify exactly one correct ticket.
    Without a live Sparta world (or in dry-run), the same checks run against Sparta's offline simulation."""
    from precedent import sparta
    from precedent.config import DIAL_API_KEY
    body = _ticket_body(alert, pb)
    key = f"precedent-pb-{alert['alert_id']}"
    live = bool(sparta.ZENDESK_URL and sparta.API_KEY and sparta.WORLD_ID and DIAL_API_KEY)
    if live:
        client = httpx.Client(base_url=sparta.ZENDESK_URL, headers={"Authorization": f"Bearer {sparta.API_KEY}"}, timeout=15)
        sparta._admin("POST", "/scenario", json={"scenario_doc": sparta._ONE_500})
    else:
        client = _simulated_client()
    try:
        first, second, ticket, shown, attempt = None, {}, None, {}, 0
        for attempt in range(3):
            r = client.post("/tickets.json", json=body, headers={"Idempotency-Key": key})
            if r.status_code < 300:
                first = r.json()["ticket"]
                break
            time.sleep(0.5 * (attempt + 1))
        if first:
            ticket = first.get("id")
            second = client.post("/tickets.json", json=body, headers={"Idempotency-Key": key}).json().get("ticket", {})
            shown = client.get(f"/tickets/{ticket}.json").json().get("ticket", {}) if ticket else {}
    finally:
        client.close()
        if live:
            try:
                sparta._admin("DELETE", "/scenario")
            except httpx.HTTPError as e:
                log.warning("could not clear the injected fault scenario: %s", e)
    content =json.dumps(shown if first else {}).lower()
    checks = {"ticket opened": bool(first),
              "injected failure recovered": bool(first) and attempt >= 1,
              "exactly one ticket (replay = same id)": bool(first) and second.get("id") == ticket,
              "steps in the ticket": bool(first) and sparta._plain(pb["steps_text"]).lower()[:40] in content,
              "mode": "live Sparta world" if live else "Sparta simulation (dry-run)"}
    ok = all(v is True for k, v in checks.items() if k != "mode")
    return ok, ticket, checks


def _simulated_client() -> httpx.Client:
    """Offline Sparta-like Zendesk: first create 500s once, honours Idempotency-Key, GET by id."""
    tickets, by_key, n = {}, {}, {"c": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET":
            tid = int(req.url.path.rstrip("/").split("/")[-1].split(".")[0])
            return httpx.Response(200, json={"ticket": tickets.get(tid, {})})
        n["c"] += 1
        if n["c"] == 1:
            return httpx.Response(500, json={"error": "InternalError", "description": "injected"})
        k = req.headers["idempotency-key"]
        if k not in by_key:
            t = json.loads(req.content)["ticket"]
            tid = len(tickets) + 1
            tickets[tid] = {"id": tid, "subject": t["subject"], "description": t["comment"]["body"]}
            by_key[k] = tid
        return httpx.Response(201, json={"ticket": tickets[by_key[k]]})
    return httpx.Client(base_url="http://sparta.sim/api/v2", transport=httpx.MockTransport(handler))


def darwin_act(alert: dict, pb: dict) -> dict:
    """Execute via Darwin Act: search for an agent that can do the steps, then POST /api/v3/act (Idempotency-Key =
    alert_id) and poll the request. Honest outcome when no agent can act."""
    from precedent import darwin
    from precedent.config import DIAL_API_KEY
    steps = pb["steps_text"]
    if not DIAL_API_KEY:
        return {"status": "dry-run", "text": "Would ask an agent to do the fix (practice mode)."}
    query = f"datacenter remote hands: {steps} on server drive {alert['model']} at {alert.get('site') or 'colocation'}"
    headers = {"Authorization": f"Bearer {darwin.DARWIN_API_KEY}"} if darwin.DARWIN_API_KEY else {}
    r = httpx.post(darwin.URL, json={"query": query, "maxResults": 3}, headers=headers, timeout=20)
    r.raise_for_status()  # a Darwin error is not "no agent found"
    res = r.json()
    agents =[a for a in ((res.get("response") or {}).get("agents") or []) if a.get("canStartThread")]
    if not agents:
        return {"status": "no_agent", "searchId": res.get("searchId"),
                "text": "No agent can do this fix yet, so a person will."}
    a = agents[0]
    msg = (f"Please perform this datacenter task: {steps}. Drive {alert['serial']} ({alert['model']}) at "
           f"{alert.get('site') or 'our datacenter'}, warning {alert['pattern']}. Evidence: {alert['died']} of {alert['n']} "
           f"identical drives died within {HORIZON_DAYS} days. Confirm requirements before acting.")
    base = darwin.URL.rsplit("/search", 1)[0]
    r = httpx.post(f"{base}/act", json={"searchId": res.get("searchId"), "agentIds": [a.get("agentId")], "message": msg},
                   headers={**headers, "Idempotency-Key": f"precedent-{alert['alert_id']}"}, timeout=20)
    if r.status_code >= 300:
        return {"status": "act_refused", "text": "The agent couldn't take the fix, so a person will.", "error": r.text[:200]}
    accepted = r.json()
    act_id = accepted.get("actRequestId") or (accepted.get("actRequest") or {}).get("id")
    state = {}
    for _ in range(6):  # the agent already has the task; a failed status poll only means we report "accepted"
        time.sleep(3)
        try:
            g = httpx.get(f"{base}/act/requests/{act_id}", params={"includeThreadState": "true"}, headers=headers, timeout=15)
            if g.status_code < 300:
                state = g.json()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("polling act request %s failed: %r", act_id, e)
            break
        if str(state.get("status", "")).lower() in ("completed", "failed", "needs_input", "cancelled"):
            break
    return {"status": state.get("status") or "accepted", "actRequestId": act_id, "agent": a.get("name"),
            "text": f"Asked {a.get('name')} to do the fix ({state.get('status') or 'accepted'})."}
