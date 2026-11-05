"""Real-time event bus: publish() at every write point -> STATE_DIR/events.jsonl, the SQLite mirror and SSE.

Event: {id (int, increasing), ts (epoch ms), type, alert_id, serial, data}
Types: telemetry_received, alert_created, message_sent, message_received, call_state, transcript_turn, decision,
       action_started, action_result, notification, keewano_logged, server_logs.
GET /api/stream (server.py) sends each one as
  id: <event id>\nevent: <type>\ndata: {"type", "ts" (ISO), "id", "alert_id"?, "serial"?, ...payload}\n\n
Last-Event-ID (or ?last_id=) replays what was missed; `: ping` comment every 15 s.
publish() is thread-safe and never raises; delivery is in-process (one uvicorn worker).
"""
import asyncio
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone

from precedent import db
from precedent.config import ONCALL_NAME, STATE_DIR, TECH_NAME

log = logging.getLogger(__name__)
PATH = os.path.join(STATE_DIR, "events.jsonl")
_lock = threading.Lock()
_subs: set = set()  # (loop, queue)


def _last_id() -> int:
    try:
        with open(PATH, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 4096))
            lines = [l for l in f.read().splitlines() if l.strip()]
        return json.loads(lines[-1])["id"] if lines else 0
    except (OSError, ValueError, KeyError, IndexError):
        return 0


_next = _last_id()
try:  # SQLite mirror: create it and import any JSONL rows it doesn't have yet
    db.backfill(PATH)
    # _last_id() only reads the file's tail, and one alert with its logs can be longer than that
    _next = max(_next, db.conn().execute("SELECT coalesce(max(id), 0) FROM events").fetchone()[0])
except Exception:
    log.exception("sqlite backfill failed")


def publish(type: str, data: dict | None = None, alert_id: str | None = None, serial: str | None = None,
            ts_ms: int | None = None) -> dict | None:
    """ts_ms: only for clearly labelled setup data (e.g. the "last week" demo-setup incident); live events use now."""
    global _next
    try:
        with _lock:
            _next += 1
            ev = {"id": _next, "ts": ts_ms or int(time.time() * 1000), "type": type, "alert_id": alert_id, "serial": serial,
                  "data": data or {}}
            with open(PATH, "a") as f:
                f.write(json.dumps(ev, default=str) + "\n")
            try:
                db.record(ev)
            except Exception:
                log.exception("sqlite write of event %s failed", ev["id"])
            subs = list(_subs)
        for loop, q in subs:
            try:
                loop.call_soon_threadsafe(q.put_nowait, ev)
            except RuntimeError:  # loop closed
                _subs.discard((loop, q))
        return ev
    except Exception:
        log.exception("publish of %s failed", type)
        return None


def read(after_id: int = 0, alert_id: str | None = None) -> list[dict]:
    try:
        return db.events_after(after_id, alert_id)
    except Exception:
        log.exception("sqlite read failed, using jsonl")
    if not os.path.exists(PATH):
        return []
    out = []
    with open(PATH) as f:
        for line in f:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev["id"] > after_id and (alert_id is None or ev.get("alert_id") == alert_id):
                out.append(ev)
    return out


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def wire(ev: dict) -> dict:
    """Flattened event as SSE and /api/feed send it: {type, ts (ISO), id, alert_id?, serial?, ...payload}."""
    out = {"type": ev["type"], "ts": iso(ev["ts"]), "id": ev["id"]}
    for k in ("alert_id", "serial"):
        if ev.get(k):
            out[k] = ev[k]
    return {**out, **(ev.get("data") or {})}


def _sse(ev: dict) -> str:
    return f"id: {ev['id']}\nevent: {ev['type']}\ndata: {json.dumps(wire(ev), default=str)}\n\n"


async def stream(last_id: int = 0, heartbeat: float = 15.0):
    """Async generator of SSE frames: replay after last_id, then live events, heartbeats when idle."""
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    sub = (loop, q)
    _subs.add(sub)  # subscribe before replay so nothing falls in the gap
    try:
        yield "retry: 1000\n\n"
        sent = last_id
        if last_id:
            for ev in read(last_id):
                sent = ev["id"]
                yield _sse(ev)
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), heartbeat)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue
            if ev["id"] > sent:
                sent = ev["id"]
                yield _sse(ev)
    finally:
        _subs.discard(sub)


def _who_number(num) -> str:
    from precedent import lifecycle  # lifecycle imports this module
    return lifecycle.who(num) if num else "someone"


def _first(s) -> str:
    s = (s or "").strip()
    return s.splitlines()[0] if s else ""


_CH_NAME = {"slack": "Slack", "discord": "Discord", "teams": "Microsoft Teams", "webhook": "the webhook"}


def _sentence(ev: dict) -> tuple[str, str, str, str]:
    """(channel, actor, kind, one plain sentence) for the incident log and feeds."""
    d, t, serial = ev.get("data") or {}, ev["type"], ev.get("serial") or ""
    oncall, techname = ONCALL_NAME, TECH_NAME
    n, died = d.get("n"), d.get("died")
    like = f"{died} of {n} drives like it failed" if n is not None and died is not None else ""
    if t == "warning_triaged":
        v, out = d.get("verdict"), d.get("outcome") or ""
        if v == "quiet":
            text = f"Checked a warning on {serial}: harmless, {like}."
        elif v == "watch":
            text = f"Checked a warning on {serial}: added to tomorrow's swap list, {like}."
        elif v == "act" and "already" in out:
            text = f"Drive {serial} warned again. It already has an open incident."
        elif v == "act":
            text = f"Checked a warning on {serial}: needs a person, {like}."
        else:
            text = f"Checked a warning on {serial}: a new kind of warning, saved for review."
        return "server", d.get("site") or "fleet", "check", text
    if t == "telemetry_received":
        v = d.get("verdict")
        if not d.get("pattern"):
            return "server", d.get("site") or "collector", "check", f"Drive {serial} reported in: healthy."
        plain = {"act": "needs a person", "watch": "added to tomorrow's swap list", "quiet": "harmless"}.get(v, "a new kind of warning, saved for review")
        return "server", d.get("site") or "collector", "check", f"Checked a warning on {serial}: {plain}" + (f", {like}." if like else ".")
    if t == "drive_failed":
        if d.get("warned_before"):
            days = d.get("days")
            return "server", d.get("site") or "fleet", "failure", (f"Drive {serial} failed. It had warned {days} days earlier."
                                                                   if days is not None else f"Drive {serial} failed. It had warned earlier.")
        return "server", d.get("site") or "fleet", "failure", f"Drive {serial} failed. It never warned."
    if t == "fleet_heartbeat":
        r = d.get("drives_reporting")
        return "server", d.get("site") or "fleet", "heartbeat", (f"Watching {r:,} drives." if r else
                                                                 f"Checked {d.get('warnings')} more warnings.")
    if t in ("alert_created", "incident_opened"):
        a = d.get("alert") or d
        if (a.get("source") == "demo setup"):
            return "precedent", "Precedent", "incident", f"Earlier incident on drive {serial} (demo setup, last week)."
        l2 = f"{a.get('died')} of {a.get('n')} drives like it failed within a month"
        return "precedent", "Precedent", "incident", f"Drive {serial} needs a person: {l2}."
    if t == "call_state":
        st = d.get("state")
        txt = {"dry-run": f"Calling {oncall} about drive {serial} (practice mode).", "Queued": f"Calling {oncall} about drive {serial}.",
               "Ringing": f"{oncall}'s phone is ringing.", "In-Progress": f"{oncall} picked up.",
               "Terminated": "The call ended."}.get(st, f"Call: {st}.")
        return "call", "Dial", "call", txt
    if t == "transcript_turn":
        who = oncall if d.get("role") == "user" else "Precedent"
        return "call", who, "said", f"{who} said: \"{(d.get('text') or '').strip()}\""
    if t == "message_sent":
        return "text", "Precedent", "text", f"Texted {_who_number(d.get('to'))}: {_first(d.get('body'))[:120]}"
    if t == "message_received":
        return "text", _who_number(d.get("from")), "reply", f"{_who_number(d.get('from'))} replied: {_first(d.get('body'))[:120]}"
    if t == "decision":
        via = d.get("via") or ""
        by = d.get("by") or (via.split(":", 1)[1] if ":" in via else oncall)
        said = {"swap": "said replace", "wait": "said wait", "apply": "said apply the last fix",
                "show": "asked to see drives like it", "unclear": "didn't give a clear answer"}.get(d.get("choice"), f"chose {d.get('choice')}")
        return (via.split(":")[0] or "web"), by, "decision", f"{by} {said}."
    if t == "incident_state":
        return (d.get("via") or "precedent").split(":")[0], d.get("by") or "Precedent", "state", d.get("text") or ""
    if t in ("incident_escalated", "comment", "playbook_learned", "playbook_suggested", "playbook_apply", "playbook_blocked",
             "playbook_worked", "sparta_verified", "darwin_act"):
        chan = {"sparta_verified": "sparta", "darwin_act": "darwin"}.get(t, "precedent")
        return chan, d.get("by") or "Precedent", t, d.get("text") or ""
    if t == "action_started":
        sp = d.get("sponsor")
        return sp or "action", sp or "agent", "action", {"darwin": "Looking for an agent to file the warranty return.",
                                                       "sparta": "Opening a remote-hands ticket."}.get(sp, "Started an action.")
    if t == "action_result":
        sp, st, det, data = d.get("sponsor"), d.get("status"), d.get("detail") or "", d.get("data") or {}
        if sp == "sparta":
            text = (f"Opened remote-hands ticket #{data.get('ticket_id')} (checked in Sparta first)." if st == "opened"
                    else "Would open a remote-hands ticket (practice mode)." if st == "dry-run"
                    else "Couldn't open the remote-hands ticket. A person should open it.")
        elif sp == "darwin":
            text = ("Would look for an agent to file the warranty return (practice mode)." if st == "dry-run"
                    else "Looked for an agent to file the warranty return: it needs the order code." if st == "needs_input" or "order code" in det
                    else "Looked for an agent to file the warranty return: none can do it yet." if st in ("no_match", "cached", "error", "none")
                    else "Found an agent to file the warranty return.")
        elif sp == "darwin_part":
            text = det
        elif sp == "darwin_agent":
            text = ("No agent to contact for the warranty return yet." if st in ("none", "no_route")
                    else "Reached the warranty agent." if st == "contacted" else "Couldn't reach the warranty agent.")
        else:
            text = det
        return sp or "action", sp or "agent", "action", text
    if t == "notification":
        ch = _CH_NAME.get(d.get("channel"), d.get("channel"))
        return d.get("channel") or "notify", "Precedent", "notification", (f"Posted to {ch}." if d.get("ok") else f"Couldn't post to {ch}.")
    if t == "keewano_logged":
        return "keewano", "Precedent", "keewano", ("Saved to the drive's history in Keewano." if d.get("ok")
                                                  else "Keewano isn't connected, so this wasn't saved there.")
    if t == "incident_resolved":
        by = d.get("by") or techname
        chan = "replay" if d.get("simulated") else ("text" if str(by).startswith("+") else "web")
        if not d.get("note"):
            verb = {"replaced": "replaced", "reseated": "reseated", "firmware": "updated the firmware on", "rma": "sent back",
                    "cleaned": "cleaned", "no_fault_found": "checked and found no fault on"}.get(d.get("action"), "fixed")
            return chan, by, "fixed", f"{by} {verb} drive {serial}."
        return chan, by, "fixed", f"{by} fixed drive {serial}: {d.get('note')}."
    if t == "server_logs":
        return "server", d.get("source", "log"), "log", plain_log_line(d.get("line", ""), serial)
    return t, "Precedent", t, d.get("text") or ""


_ATTR = {"5": "Reallocated sectors", "187": "Reported uncorrectable errors", "188": "Command timeouts",
         "197": "Pending sectors", "198": "Offline uncorrectable sectors"}


def plain_log_line(line: str, serial: str = "") -> str:
    """Collector/kernel log lines as plain sentences (the raw line stays in data.line)."""
    m = re.match(r"\s*ID\s+(\d+)\s+\S+:\s*(\d+)\s*(?:->|→)\s*(\d+)", line or "")
    if m:
        name = _ATTR.get(m.group(1), f"SMART counter {m.group(1)}")
        a, b = int(m.group(2)), int(m.group(3))
        verb = "jumped" if b > a else "dropped" if b < a else "stayed"
        return f"{name} {verb} from {a:,} to {b:,}."
    if "I/O error" in (line or ""):
        dev = re.search(r"\b(sd[a-z]+|nvme\d+n\d+)\b", line)
        return f"The server logged a disk read/write error{f' on {dev.group(1)}' if dev else ''}."
    if re.search(r"medium error|UNC\b", line or ""):
        return "The server logged an unreadable sector."
    if re.search(r"\breset\b", line or "", re.I):
        return "The server reset the disk link."
    return (line or "").strip()


def _row(ev: dict) -> dict:
    channel, actor, kind, text = _sentence(ev)
    return {"ts": iso(ev["ts"]), "id": ev["id"], "channel": channel, "actor": actor, "kind": kind, "text": text,
            "data": ev.get("data") or {}}


def incident_log(alert_id: str, serial: str | None = None) -> list[dict]:
    """Every event for this incident, oldest first: its own events plus that drive's readings/logs just before it."""
    own = read(0, alert_id)
    pre = [ev for ev in (db.serial_events(serial, ("telemetry_received", "server_logs")) if serial else [])
           if not ev.get("alert_id")
           and (ev["type"] == "server_logs" or (ev["type"] == "telemetry_received" and (ev["data"] or {}).get("pattern")))]
    # the drive's last 10 warning readings + their log lines (a live replay sends every healthy day too)
    keep_t = {ev["id"] for ev in [e for e in pre if e["type"] == "telemetry_received"][-10:]}
    pre = [ev for ev in pre if ev["type"] == "server_logs" or ev["id"] in keep_t]
    return [r for r in map(_row, sorted(own + pre, key=lambda e: e["id"])) if r]
