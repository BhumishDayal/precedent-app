"""Incident lifecycle: one forward-only state machine, persisted in SQLite (incidents.state + per-state timestamps).

detected -> triaged -> paged -> acknowledged -> decided -> actioned -> resolved -> verified
Every transition publishes `incident_state` {from, to, by, via, text}, so it lands in SSE and the incident log.
A page not acknowledged within ACK_SECONDS escalates once (text -> call, call -> text + Slack). The escalated
flag lives in SQLite and resume() re-arms pending timers after a restart.
"""
import json
import logging
import threading
import time
from datetime import date

from precedent import db, events
from precedent.config import ACK_SECONDS, ONCALL_NAME, ONCALL_PHONE, TECH_NAME

log = logging.getLogger(__name__)
STATES = ["detected", "triaged", "paged", "acknowledged", "decided", "actioned", "resolved", "verified"]
_lock = threading.Lock()
_escalate_fn = None  # set by server.py: fn(alert_id) -> sentence describing what it did


def _ensure_columns() -> None:
    c = db.conn()
    have = {r["name"] for r in c.execute("PRAGMA table_info(incidents)")}
    with db._wlock:
        for col, typ in (("state", "TEXT"), ("state_ts_json", "TEXT"), ("escalated_ts", "INTEGER"),
                         ("paged_ts", "INTEGER"), ("verify_from", "TEXT")):
            if col not in have:
                c.execute(f"ALTER TABLE incidents ADD COLUMN {col} {typ}")
        c.commit()


db.init()
_ensure_columns()


def state_of(alert_id: str) -> str | None:
    r = db.conn().execute("SELECT state FROM incidents WHERE alert_id=?", (alert_id,)).fetchone()
    return r["state"] if r else None


def transition(alert_id: str, to: str, by: str = "Precedent", via: str = "system", text: str = "",
               serial: str | None = None) -> bool:
    """Move forward to `to` (skipping is fine, going back is ignored). Returns True if the state changed."""
    with _lock:
        row = db.conn().execute("SELECT state, state_ts_json, serial FROM incidents WHERE alert_id=?", (alert_id,)).fetchone()
        if row is None:
            return False
        cur = row["state"]
        if cur and STATES.index(to) <= STATES.index(cur):
            return False
        ts = int(time.time() * 1000)
        stamps = json.loads(row["state_ts_json"] or "{}")
        stamps[to] = ts
        with db._wlock:
            db.conn().execute("UPDATE incidents SET state=?, state_ts_json=?" + (", paged_ts=?" if to == "paged" else "")
                              + " WHERE alert_id=?", (to, json.dumps(stamps), *([ts] if to == "paged" else []), alert_id))
            db.conn().commit()
    events.publish("incident_state", {"from": cur, "to": to, "by": by, "via": via,
                                      "text": text or f"{to.capitalize()} ({by} via {via})"}, alert_id, serial or row["serial"])
    if to == "paged" and ACK_SECONDS > 0:
        _arm(alert_id, ACK_SECONDS)
    return True


def set_verify_from(alert_id: str, day: str | None) -> None:
    with db._wlock:
        db.conn().execute("UPDATE incidents SET verify_from=? WHERE alert_id=?", (day, alert_id))
        db.conn().commit()


def check_verified(serial: str, day: str | None, healthy: bool, failed: bool = False) -> None:
    """resolved -> verified when the drive failed (outcome known) or reads healthy 7+ days after the fix."""
    r = db.conn().execute("SELECT alert_id, state, verify_from FROM incidents WHERE serial=? ORDER BY created_ts DESC LIMIT 1",
                          (serial,)).fetchone()
    if r is None or r["state"] != "resolved":
        return
    if failed:
        from precedent.engine import shift_date
        transition(r["alert_id"], "verified", "Precedent", "telemetry", f"Outcome: the drive failed on {shift_date(day)}.", serial)
        return
    if not (healthy and day):
        return
    if not r["verify_from"]:
        set_verify_from(r["alert_id"], day)
        return
    try:
        days = (date.fromisoformat(day[:10]) - date.fromisoformat(r["verify_from"][:10])).days
    except ValueError:  # a collector sent a date we can't read; wait for the next reading
        return
    if days >= 7 and transition(r["alert_id"], "verified", "Precedent", "telemetry",
                                "Outcome: no new warnings for 7 days after the fix.", serial):
        from precedent import playbooks
        playbooks.credit_if_applied(r["alert_id"])


def stamps(alert_id: str) -> dict:
    r = db.conn().execute("SELECT state_ts_json FROM incidents WHERE alert_id=?", (alert_id,)).fetchone()
    return json.loads(r["state_ts_json"] or "{}") if r else {}


def _arm(alert_id: str, delay: float) -> None:
    t = threading.Timer(max(0.0, delay), _ack_check, [alert_id])
    t.daemon = True
    t.start()


def _ack_check(alert_id: str) -> None:
    with _lock:
        r = db.conn().execute("SELECT state, escalated_ts, serial FROM incidents WHERE alert_id=?", (alert_id,)).fetchone()
        if r is None or r["escalated_ts"] or r["state"] != "paged":
            return  # acknowledged/decided already, or escalated before: never twice
        with db._wlock:
            db.conn().execute("UPDATE incidents SET escalated_ts=? WHERE alert_id=?", (int(time.time() * 1000), alert_id))
            db.conn().commit()
    did = "escalation unavailable"
    try:
        did = _escalate_fn(alert_id) if _escalate_fn else did
    except Exception as e:
        log.exception("escalation failed for %s", alert_id)
        did = f"escalation failed ({str(e)[:80]})"
    events.publish("incident_escalated", {"text": f"No answer in {ACK_SECONDS} seconds, {did}.", "after_s": ACK_SECONDS},
                   alert_id, r["serial"])


def resume() -> int:
    """After a restart: re-arm ACK timers for incidents still waiting in `paged` and never escalated."""
    n = 0
    for r in db.conn().execute("SELECT alert_id, paged_ts FROM incidents WHERE state='paged' AND escalated_ts IS NULL"):
        left = ACK_SECONDS - (time.time() * 1000 - (r["paged_ts"] or 0)) / 1000
        _arm(r["alert_id"], left)
        n += 1
    return n


def who(phone: str | None = None, via: str = "") -> str:
    """The person behind a phone number or a "slack:Name" / "api:Name" via."""
    from precedent import tech  # tech imports actions, which imports this module
    if via.startswith(("slack:", "api:")):
        return via.split(":", 1)[1] or via
    if phone and tech.TECH_INBOX_NUMBER and phone == tech.TECH_INBOX_NUMBER:
        return TECH_NAME
    if phone and tech.is_tech(phone) and phone != ONCALL_PHONE:
        return TECH_NAME
    return ONCALL_NAME
