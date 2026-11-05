"""Fan-out notifications: every alert, call end, decision and action result goes to each configured channel.

Env (empty = skipped): SLACK_WEBHOOK_URL (Block Kit), DISCORD_WEBHOOK_URL, TEAMS_WEBHOOK_URL (Office 365
MessageCard), OUTBOUND_WEBHOOK_URL (plain JSON for other agents). notify() never raises; every attempt is appended to
STATE_DIR/notifications.jsonl {ts, channel, event, alert_id, ok, status, error}.

Slack alert and call-ended messages carry Swap / Wait buttons. POST /slack/actions hands the click to slack_action(),
which requires SLACK_SIGNING_SECRET and a valid signature, then runs the normal decision path as "slack:<user>".

CLI:  python -m precedent.notify digest [--preview]   # morning swap list
"""
import hashlib
import hmac
import json
import logging
import os
import sys
import threading
import time
import urllib.parse

import httpx

from precedent.config import HORIZON_DAYS, STATE_DIR
from precedent.decisions import now

log = logging.getLogger(__name__)

CHANNELS = {
    "slack": os.getenv("SLACK_WEBHOOK_URL", ""),
    "discord": os.getenv("DISCORD_WEBHOOK_URL", ""),
    "teams": os.getenv("TEAMS_WEBHOOK_URL", ""),
    "webhook": os.getenv("OUTBOUND_WEBHOOK_URL", ""),
}
LOG = os.path.join(STATE_DIR, "notifications.jsonl")
_lock = threading.Lock()


def app_url() -> str:
    """Base of the "Open incident" links: APP_URL, else PUBLIC_URL or the tunnel URL, else localhost.
    A tunnel URL beats a localhost APP_URL, since links are opened from phones and Slack."""
    from precedent.dial import public_url
    explicit = os.getenv("APP_URL", "")
    if explicit and not any(h in explicit for h in ("localhost", "127.0.0.1")):
        return explicit.rstrip("/")
    return (public_url() or explicit or "http://localhost:8000").rstrip("/")


def _lines(event: str, p: dict) -> tuple[str, str, str, str]:
    """(title, evidence, decision line, link) shared by every channel."""
    if event == "digest":
        return p["title"], p["text"], "", app_url()
    drive = f"{p.get('model', '?')} {p.get('serial', '?')} ({p.get('pattern', '?')})"
    title = {
        "alert_sent": f"Drive alert: {drive}",
        "call_ended": f"Call ended: {drive}",
        "decision": f"Decision {str(p.get('choice', '?')).upper()}: {drive}",
        "action": f"{str(p.get('sponsor', 'Action')).capitalize()}: {drive}",
        "test": "Precedent test notification",
    }.get(event, f"{event}: {drive}")
    evidence = (f"{p['died']} of {p['n']} identical drives died within {HORIZON_DAYS} days"
                if p.get("n") is not None and p.get("died") is not None else "")
    if event == "action":
        decision = p.get("detail", "")
    elif p.get("choice"):
        decision = f"Decision: {p['choice']}" + (f" (via {p['via']})" if p.get("via") else "")
    elif event == "call_ended":
        decision = f"Call {p.get('termination') or 'ended'}; heard: {p.get('decision') or 'nothing clear'}"
    else:
        decision = "Waiting for the on-call: swap now or wait?" if event == "alert_sent" else ""
    link = f"{app_url()}/incident/{p['alert_id']}" if p.get("alert_id") else app_url()
    return title, evidence, decision, link


def _body(channel: str, event: str, p: dict) -> dict:
    title, evidence, decision, link = _lines(event, p)
    text = "\n".join(x for x in (evidence, decision) if x)
    label = "Open Precedent" if event == "digest" else "Open incident"
    if channel == "slack":
        blocks = [{"type": "header", "text": {"type": "plain_text", "text": title[:150]}}]
        if text:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})
        elements = [{"type": "button", "text": {"type": "plain_text", "text": label}, "url": link,
                     "action_id": "precedent_open"}]
        if event in ("alert_sent", "call_ended") and p.get("alert_id") and p.get("decision") in (None, "unclear"):
            if p.get("suggested_fix"):
                elements = [{"type": "button", "style": "primary", "text": {"type": "plain_text", "text": "Apply last fix"},
                             "action_id": "precedent_apply", "value": f"apply|{p['alert_id']}"}] + elements
            elements = elements[:-1] + [
                {"type": "button", "style": "danger", "text": {"type": "plain_text", "text": "Swap"},
                 "action_id": "precedent_swap", "value": f"swap|{p['alert_id']}"},
                {"type": "button", "text": {"type": "plain_text", "text": "Wait"},
                 "action_id": "precedent_wait", "value": f"wait|{p['alert_id']}"}] + elements[-1:]
        blocks.append({"type": "actions", "elements": elements})
        return {"text": f"{title}. {text}", "blocks": blocks}
    if channel == "discord":
        return {"content": title[:2000], "embeds": [{"title": label, "url": link,
                                                    "description": text[:4000], "color": 0xE5484D}]}
    if channel == "teams":
        return {"@type": "MessageCard", "@context": "http://schema.org/extensions", "summary": title,
                "themeColor": "E5484D", "title": title, "text": text.replace("\n", "<br>") or title,
                "potentialAction": [{"@type": "OpenUri", "name": label,
                                     "targets": [{"os": "default", "uri": link}]}]}
    return {"source": "precedent", "event": event, "ts": now(), "title": title, "evidence": evidence,
            "decision": decision, "link": link, "data": p}


def _send(channel: str, url: str, event: str, p: dict) -> dict:
    row = {"ts": now(), "channel": channel, "event": event, "alert_id": p.get("alert_id"), "ok": False}
    try:
        r = httpx.post(url, json=_body(channel, event, p), timeout=8)
        row.update(ok=r.status_code < 300, status=r.status_code, error=None if r.status_code < 300 else r.text[:200])
    except Exception as e:
        row.update(status=None, error=repr(e)[:200])
    if not row["ok"]:
        log.warning("%s notification '%s' failed: %s %s", channel, event, row["status"], row["error"])
    _log(row)
    from precedent import events
    events.publish("notification", {k: row.get(k) for k in ("channel", "event", "ok", "status", "error")},
                   p.get("alert_id"), p.get("serial"))
    return row


def notify(event_type: str, payload: dict, channel: str | None = None, wait: bool = False) -> list:
    """Fan out to every configured channel (or just `channel`). Background threads unless wait=True. Never raises."""
    try:
        targets = [(c, u) for c, u in CHANNELS.items() if u and (channel is None or c == channel)]
        if wait:
            return [_send(c, u, event_type, payload) for c, u in targets]
        for c, u in targets:
            threading.Thread(target=_send, args=(c, u, event_type, dict(payload)), daemon=True).start()
    except Exception:
        log.exception("notify '%s' failed", event_type)
    return []


def _log(row: dict) -> None:
    try:
        with _lock, open(LOG, "a") as f:
            f.write(json.dumps(row) + "\n")
    except OSError as e:
        log.warning("could not append to %s: %s", LOG, e)


def build_digest(limit: int = 10) -> dict:
    """Morning swap list: drives that warned in the last 7 days of data, ranked by how often drives like them died.
    Circular (SMART 187) patterns are left out unless nothing else qualifies."""
    from precedent import engine
    con = engine.connect(read_only=True)
    try:
        df = engine.swap_list(con, limit * 5)
    finally:
        con.close()
    rows = df[~df["circular"]].head(limit)
    circular_only = rows.empty and not df.empty
    if circular_only:
        rows = df.head(limit)
    title = f"Precedent morning swap list: {len(rows)} drive{'s' if len(rows) != 1 else ''}"
    lines = [f"{i}) {r.serial} {r.model} {r.pattern}, {int(r.died)} of {int(r.n)} like it died"
             + (" (circular: SMART 187)" if r.circular else "")
             for i, r in enumerate(rows.itertuples(), 1)]
    if not lines:
        lines = ["No drive warned with a pattern that history says to act on."]
    text = "\n".join(lines)
    return {"title": title, "text": text, "full": f"{title}.\n{text}\n{app_url()}", "count": len(rows),
            "circular_only": circular_only, "serials": list(rows["serial"])}


def send_digest(limit: int = 10) -> dict:
    """Send the digest to every channel, plus one text to the tech inbox target when a text sender exists."""
    d = build_digest(limit)
    results = notify("digest", d, wait=True)
    text_row = None
    try:
        from precedent import dial, tech
        if tech.TECH_TARGET and dial.TEXT_FROM:
            text_row = {"ts": now(), "channel": "text", "event": "digest", "alert_id": None,
                        "to": tech.TECH_TARGET, "sent": tech.send_to_tech(d["full"])}
            text_row["ok"] = all("error" not in s for s in text_row["sent"])
            _log(text_row)
    except Exception:
        log.exception("digest text failed")
    return {**d, "channels": results, "text": d["text"], "sms": text_row}


SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")


def verify_slack(raw: bytes, headers) -> bool:
    """Slack request signing: v0=HMAC_SHA256(secret, "v0:{ts}:{body}"), timestamp within 5 minutes.
    No secret configured means no request is trusted: an unsigned click would otherwise log a real decision."""
    if not SLACK_SIGNING_SECRET:
        log.warning("SLACK_SIGNING_SECRET is not set; refusing Slack action")
        return False
    ts = headers.get("x-slack-request-timestamp", "")
    sig = headers.get("x-slack-signature", "")
    if not ts.isdigit() or abs(time.time() - int(ts)) > 300:
        return False
    mine = "v0=" + hmac.new(SLACK_SIGNING_SECRET.encode(), f"v0:{ts}:".encode() + raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(mine, sig)


def slack_action(raw: bytes, headers, decide) -> tuple[int, dict]:
    """Handle one Slack block_actions click. decide(alert, choice, source) is server._decide.
    Returns (http_status, body); the message update goes to response_url in the background."""
    if not verify_slack(raw, headers):
        return 401, {"error": "bad Slack signature"}
    try:
        payload = json.loads(urllib.parse.parse_qs(raw.decode()).get("payload", ["{}"])[0])
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        return 400, {"error": "no payload"}
    action = next((a for a in payload.get("actions", []) if a.get("action_id") in ("precedent_swap", "precedent_wait", "precedent_apply")), None)
    if action is None:
        return 200, {}  # e.g. the "Open incident" link button
    choice, _, alert_id = (action.get("value") or "").partition("|")
    u = payload.get("user") or {}
    user = u.get("username") or u.get("name") or u.get("id") or "someone"
    from precedent import decisions
    alert = decisions.get_alert(alert_id)
    if alert is None or choice not in ("swap", "wait", "apply"):
        note = "Precedent: unknown alert."
    elif decisions.is_resolved(alert_id):
        last = [d for d in decisions.read_decisions() if d["alert_id"] == alert_id and d["choice"] in ("swap", "wait", "apply")][-1]
        choice = last["choice"]
        note = f"Already decided: {choice} at {last['ts']}."
    else:
        decide(alert, choice, f"slack:{user}")
        note = f"{choice.capitalize()} logged by {user}."
    url = payload.get("response_url")
    if url and alert is not None:
        title, evidence, _, link = _lines("decision", {**alert, "choice": choice})
        msg = {"replace_original": True, "text": note, "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": title[:150]}},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"{evidence}\n*{note}*"}},
            {"type": "actions", "elements": [{"type": "button", "text": {"type": "plain_text", "text": "Open incident"},
                                              "url": link, "action_id": "precedent_open"}]}]}
        threading.Thread(target=lambda: _post_quiet(url, msg), daemon=True).start()
    return 200, {"text": note}


def _post_quiet(url: str, body: dict) -> None:
    try:
        r = httpx.post(url, json=body, timeout=8)
        if r.status_code >= 300:
            log.warning("Slack response_url -> %s: %s", r.status_code, r.text[:200])
    except httpx.HTTPError as e:
        log.warning("Slack response_url failed: %s", e)


def status() -> dict:
    last = {}
    if os.path.exists(LOG):
        with open(LOG) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    last[r["channel"]] = r
                except ValueError:
                    pass
    return {"app_url": app_url(),
            "channels": {c: {"configured": bool(u), "last": last.get(c)} for c, u in CHANNELS.items()}}


if __name__ == "__main__":
    if sys.argv[1:2] == ["digest"]:
        if "--preview" in sys.argv:
            print(build_digest()["full"])
        else:
            res = send_digest()
            print(res["full"])
            print("channels:", [(r["channel"], r["ok"]) for r in res["channels"]] or "none configured",
                  "| text:", res["sms"] and res["sms"]["ok"])
    else:
        print(__doc__)
