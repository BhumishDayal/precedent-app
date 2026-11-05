"""Technician inbox: a second Dial number (TECH_INBOX_NUMBER) that gets the full summary after every call/decision,
and the two-way text thread between our Dial number (A) and it.

Target: TECH_INBOX_NUMBER, falling back to ONCALL_PHONE (a real phone needs an iMessage text sender, since US SMS
to it is 10DLC-blocked). Texts come from dial.TEXT_FROM. Neither set = dry run under the placeholder address below.
The web chat (/api/tech/send) really sends only when TECH_INBOX_NUMBER is a Dial number; otherwise it is simulated.
Files (STATE_DIR): messages.jsonl {ts, from, to, body, direction, ...}, summaries.jsonl {ts, alert_id, reason, text, parts, ...}
"""
import json
import logging
import os
import re
import threading
import time

from precedent import actions, decisions, dial
from precedent.config import HORIZON_DAYS, ONCALL_PHONE, STATE_DIR

log = logging.getLogger(__name__)
TECH_INBOX_NUMBER = os.getenv("TECH_INBOX_NUMBER", "")   # a Dial number we own (chat can send from it)
TECH_TARGET = TECH_INBOX_NUMBER or ONCALL_PHONE           # where summaries go
TECH_ADDR = TECH_TARGET or "tech-inbox (dry-run)"
A_NUMBER = os.getenv("DIAL_FROM_E164") or dial.e164(dial.TEXT_FROM)  # our texting number, E.164
MESSAGES_PATH = os.path.join(STATE_DIR, "messages.jsonl")
SUMMARIES_PATH = os.path.join(STATE_DIR, "summaries.jsonl")
MAX_PART = 1400

keewano_logged: dict[str, bool] = {}   # alert_id -> did the decision push to Keewano succeed
calls: dict[str, dict] = {}            # alert_id -> last Dial call record (for the transcript)
_lock = threading.Lock()


def is_tech(number: str | None) -> bool:
    return bool(number) and number == TECH_ADDR


_read = decisions._read  # skips a line cut short by a crash mid-write


def log_message(frm: str, to: str, body: str, kind: str = "sent", **extra) -> dict | None:
    """Append one text to the thread. A text we sent and its own inbound echo (same from/to/body, other kind,
    within 2 minutes) are logged once."""
    direction = "to_tech" if is_tech(to) else "from_tech" if is_tech(frm) else "other"
    with _lock:
        for m in reversed(_read(MESSAGES_PATH)[-20:]):
            if ((m["from"], m["to"], m["body"]) == (frm, to, body) and m.get("kind") != kind
                    and not m.get("paired") and time.time() - m.get("t", 0) < 120):
                return None
        row = {"ts": decisions.now(), "t": time.time(), "from": frm, "to": to, "body": body, "direction": direction,
               "kind": kind, **extra}
        with open(MESSAGES_PATH, "a") as f:
            f.write(json.dumps(row) + "\n")
    return row


dial.text_hooks.append(log_message)


def thread(limit: int = 100) -> list[dict]:
    return [m for m in _read(MESSAGES_PATH) if m["direction"] != "other"][-limit:]


def send_to_tech(body: str) -> list[dict]:
    """A -> technician, split into at most 2 texts of <= 1400 chars. Never retried; stops at the first failure."""
    parts = _split(body)
    sent = []
    for i, part in enumerate(parts):
        try:
            if TECH_TARGET:
                msg = dial.send_text(TECH_TARGET, part)
            else:
                with dial.forced_dry_run():
                    msg = dial.send_text(TECH_ADDR, part)
            sent.append({"part": i + 1, "id": msg.get("id"), "dry_run": bool(msg.get("dry_run"))})
        except Exception as e:
            log.warning("summary part %d failed (not retried): %s", i + 1, e)
            sent.append({"part": i + 1, "error": str(e)[:200]})
            break
    return sent


def _split(text: str) -> list[str]:
    if len(text) <= MAX_PART:
        return [text]
    first, rest = [], text.splitlines()
    while rest and len("\n".join(first + [rest[0]])) <= MAX_PART:
        first.append(rest.pop(0))
    return ["\n".join(first)[:MAX_PART], "\n".join(rest)[:MAX_PART]]


def _ascii(s: str) -> str:
    return s.encode("ascii", "replace").decode()


def build_summary(alert: dict) -> str:
    aid = alert["alert_id"]
    lines = [f"Summary for drive {alert['serial']}",
             f"Drive {alert['serial']} ({alert['model']}), warning {alert['pattern']}",
             f"Evidence: {alert['died']} of {alert['n']} identical drives died within {HORIZON_DAYS} days"]
    ds = [d for d in decisions.read_decisions() if d["alert_id"] == aid and d["choice"] != "show"]
    lines.append(f"Decision: {ds[-1]['choice'].upper()} at {ds[-1]['ts']}" if ds else "Decision: none yet")
    sf = alert.get("suggested_fix")
    if sf:
        lines.append(f"Last time's fix ({sf['by']}, {sf['when']}, {sf['basis']}; held {sf['times_worked']} of "
                     f"{sf['times_used']} times applied): {sf['steps_text']}")
    logs = alert.get("logs") or []
    if logs:
        io = {}
        for entry in logs:
            if "I/O error" in entry.get("line", ""):
                m = re.search(r"\b(sd[a-z]+|nvme\d+n\d+|hd[a-z]+)\b", entry["line"])
                dev = m.group(1) if m else "disk"
                io[dev] = io.get(dev, 0) + 1
        lines += [f"Kernel: {n} I/O error{'s' if n != 1 else ''} on {dev}" for dev, n in io.items()]
        lines.append("Server logs:")
        lines += [f"  [{entry.get('source')}] {entry.get('line')}" for entry in logs[-3:]]
    call = calls.get(aid)
    if call:
        turns = call.get("transcriptTurns") or []
        if turns:
            lines.append("Call transcript (last turns):")
            lines += [f"  {t.get('speaker')}: {t.get('text', '').strip()}" for t in turns[-6:]]
        elif call.get("transcript"):
            lines.append("Call transcript: " + call["transcript"].replace("\n", " / ")[-500:])
    try:
        from precedent.context_mcp import recent_like
        similar = recent_like(alert, limit=3)
        lines.append("Most recent identical drives:")
        lines += [f"  {r['serial']}: warned {r['warned']}, {r['outcome']}" for r in similar]
    except Exception as e:
        log.warning("recent identical drives unavailable: %s", e)
        lines.append("Recent identical drives unavailable.")
    latest = {}  # the latest action row per agent for this alert, in the order they last acted
    for a in actions.read_actions(None):
        if a["alert_id"] == aid:
            latest.pop(a["sponsor"], None)
            latest[a["sponsor"]] = a
    if latest:
        lines.append("Actions:")
        lines += [f"  {a['detail']}" for a in latest.values()]
    try:
        from precedent import db
        for r in db.resolutions_for(aid):
            lines.append(f"Resolved: {r['action']}" + (f" ({r['note']})" if r["note"] else "") + f" by {r['by']}")
    except Exception as e:
        log.warning("resolutions for %s unavailable: %s", aid, e)
    if ds:
        lines.append("Logged to Keewano" if ds[-1].get("keewano_logged") else "Keewano: not logged (dry-run or no key)")
    return _ascii("\n".join(lines))


def send_summary(alert: dict, reason: str, wait_for_actions: bool = False) -> dict:
    """Build + send the summary to the tech inbox, save to summaries.jsonl. Waits up to 15 s for Darwin/Sparta rows."""
    if wait_for_actions:
        for _ in range(15):
            got = {a["sponsor"] for a in actions.read_actions(None) if a["alert_id"] == alert["alert_id"]}
            if {"darwin", "sparta"} <= got:
                break
            time.sleep(1)
    text = build_summary(alert)
    sent = send_to_tech(text)
    row = {"ts": decisions.now(), "alert_id": alert["alert_id"], "reason": reason, "to": TECH_ADDR,
           "text": text, "parts": len(_split(text)), "sent": sent}
    with _lock, open(SUMMARIES_PATH, "a") as f:
        f.write(json.dumps(row) + "\n")
    return row


def latest_summary() -> dict | None:
    rows = _read(SUMMARIES_PATH)
    return rows[-1] if rows else None
