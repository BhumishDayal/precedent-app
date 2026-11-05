"""Dial (getdial.ai) client: send texts, place AI voice calls, read calls/messages, long-poll events.

Docs: https://docs.getdial.ai/llms-full.txt. Auth is `Authorization: Bearer sk_live_...`.
No DIAL_API_KEY (or inside `forced_dry_run()`) -> dry run: logs instead of sending.
Sends are NOT idempotent: nothing here ever retries a POST /messages.

CLI:  python -m precedent.dial test                  # ONE text to ONCALL_PHONE, then report delivery
      python -m precedent.dial send +15551234567 "hello"
      python -m precedent.dial call +15551234567 "Tell them drive X is failing."
      python -m precedent.dial webhook            # subscribes PUBLIC_URL/webhooks/dial (only if using a tunnel)
      python -m precedent.dial webhooks           # list subscriptions
      python -m precedent.dial register-context-mcp https://xxxx.trycloudflare.com   # voice agent tool /mcp/
      python -m precedent.dial numbers            # account numbers: capabilities, setupStatus

Numbers: calls go from DIAL_FROM_NUMBER_ID; texts from DIAL_TEXT_FROM_NUMBER (falls back to DIAL_FROM_NUMBER_ID).
A sender whose capabilities include "imessage" sends with channel "imessage" (exempt from 10DLC).
"""
import contextlib
import contextvars
import logging
import os
import sys
import time
import uuid

import httpx

from precedent.config import (DIAL_API_BASE, DIAL_API_KEY, DIAL_FROM, DIAL_FROM_NUMBER_ID, ONCALL_PHONE, PUBLIC_URL,
                              STATE_DIR)

log = logging.getLogger(__name__)

# Real base is https://api.getdial.ai/api/v1; tolerate the older ".../v1" value.
BASE = DIAL_API_BASE.rstrip("/")
if BASE.endswith("getdial.ai/v1"):
    BASE = BASE[: -len("/v1")] + "/api/v1"
ALERT_CHANNEL = os.getenv("ALERT_CHANNEL", "sms")  # sms | imessage | call

_FROM = DIAL_FROM_NUMBER_ID or DIAL_FROM
FROM_FIELD = {"fromNumberId": _FROM} if _FROM.startswith("pn_") else {"fromNumber": _FROM}
TEXT_FROM = os.getenv("DIAL_TEXT_FROM_NUMBER", "") or _FROM  # sender for texts (e.g. a new iMessage number)
_numbers: list | None = None  # cached GET /numbers

_force_dry = contextvars.ContextVar("dial_force_dry", default=False)
text_hooks: list = []  # called as hook(frm, to, body, id=..., dry_run=...) after every text sent (tech.py logs the thread)


@contextlib.contextmanager
def forced_dry_run():
    """Everything sent inside this block is logged, not sent (used by /demo/simulate-reply)."""
    token = _force_dry.set(True)
    try:
        yield
    finally:
        _force_dry.reset(token)


def is_dry() -> bool:
    return not DIAL_API_KEY or _force_dry.get()


def _auth() -> dict:
    return {"Authorization": f"Bearer {DIAL_API_KEY}"}


def mask(number: str | None) -> str:
    """+15551234567 -> ...4567, for logs. Anything that isn't a phone number is returned as is."""
    return f"...{number[-4:]}" if number and number.startswith("+") else str(number)


def _json(r: httpx.Response, what: str) -> dict:
    if r.status_code >= 400:
        raise RuntimeError(f"Dial {what} -> {r.status_code}: {r.text[:300]}")
    try:
        return r.json()
    except ValueError:
        raise RuntimeError(f"Dial {what} -> {r.status_code} with a non-JSON body") from None


def _post(path: str, payload: dict, headers: dict | None = None) -> dict:
    if is_dry():
        log.info("dry run: POST %s to %s %r", path, mask(payload.get("to")), (payload.get("body") or "")[:160])
        return {"dry_run": True, "id": f"dry_{uuid.uuid4().hex[:8]}"}
    r = httpx.post(f"{BASE}{path}", json=payload, timeout=30, headers={**_auth(), **(headers or {})})
    return _json(r, f"POST {path}")


def _get(path: str, params: dict | None = None) -> dict:
    return _json(httpx.get(f"{BASE}{path}", params=params, headers=_auth(), timeout=30), f"GET {path}")


def list_numbers(refresh: bool = False) -> list:
    """Account numbers [{id, number, nickname, capabilities, setupStatus, ...}] (cached; [] in dry run or on error)."""
    global _numbers
    if _numbers is None or refresh:
        if not DIAL_API_KEY:
            return []
        try:
            res = _get("/numbers")
            _numbers = res if isinstance(res, list) else (res.get("numbers") or res.get("phoneNumbers") or res.get("data") or [])
        except Exception as e:
            log.warning("listing Dial numbers failed: %s", e)
            return []
    return _numbers


def number_info(ref: str) -> dict:
    """The account number matching an id (pn_...), E.164 or nickname; {} if unknown."""
    return next((n for n in list_numbers() if ref in (n.get("id"), n.get("number"), n.get("nickname"))), {})


def e164(ref: str) -> str:
    return ref if ref.startswith("+") else number_info(ref).get("number", ref)


def send_text(to: str, body: str, from_: str | None = None) -> dict:
    """Send a text from DIAL_TEXT_FROM_NUMBER (or from_, e.g. the tech inbox number). iMessage when ALERT_CHANNEL is
    imessage or the sender has the imessage capability (exempt from 10DLC). Keep body plain ASCII."""
    frm = from_ or TEXT_FROM
    payload = {"to": to, **({"fromNumberId": frm} if frm.startswith("pn_") else {"fromNumber": frm}), "body": body}
    if ALERT_CHANNEL == "imessage" or "imessage" in (number_info(frm).get("capabilities") or []):
        payload["channel"] = "imessage"
    msg = _post("/messages", payload)
    msg = msg.get("message", msg)
    for hook in text_hooks:
        try:
            hook(frm, to, body, id=msg.get("id"), dry_run=bool(msg.get("dry_run")))
        except Exception:
            log.exception("text hook %s failed", getattr(hook, "__name__", hook))
    return msg


def place_call(to: str, script: str) -> dict:
    """Place an AI voice call; `script` is the agent's system prompt (outboundInstruction)."""
    call = _post("/calls", {"to": to, **FROM_FIELD, "outboundInstruction": script, "language": "en-US",
                            "maxCallDurationSeconds": 180},
                 headers={"Idempotency-Key": uuid.uuid4().hex})
    return call.get("call", call)


def get_call(call_id: str) -> dict:
    """{status: {state, terminationType}, transcript, transcriptTurns: [{speaker, text}], ...}"""
    return _get(f"/calls/{call_id}").get("call", {})


def find_message(message_id: str, contact: str) -> dict | None:
    """There is no GET /messages/{id}; search this contact's outbound messages instead."""
    msgs = _get("/messages", {"contact": contact, "direction": "outbound"}).get("messages", [])
    return next((m for m in msgs if m.get("id") == message_id), None)


def wait_event(event_type: str = "message.received", timeout: int = 55) -> dict | None:
    """Long-poll POST /events/wait. Returns the event, or None on 408 (nothing arrived)."""
    r = httpx.post(f"{BASE}/events/wait", json={"eventType": event_type, "timeout": timeout},
                   headers=_auth(), timeout=timeout + 15)
    if r.status_code == 408:
        return None
    return _json(r, "POST /events/wait").get("event")


def public_url() -> str:
    """PUBLIC_URL from env, else the URL scripts/tunnel.sh wrote to STATE_DIR/public_url.txt, else ""."""
    if PUBLIC_URL:
        return PUBLIC_URL.rstrip("/")
    try:
        with open(os.path.join(STATE_DIR, "public_url.txt")) as f:
            return f.read().strip().rstrip("/")
    except OSError:
        return ""


def create_webhook(target_url: str | None = None) -> dict:
    """Subscribe our server to inbound messages. The signing secret is only returned here, once."""
    target_url = target_url or f"{public_url()}/webhooks/dial"
    return _post("/webhooks", {"targetUrl": target_url, "eventTypes": ["message.received"]})


def list_webhooks() -> dict:
    return _get("/webhooks")


def register_context_mcp(base_url: str) -> dict:
    """Attach our /mcp/ server so the voice agent can call similar_drives(serial) mid-call."""
    return _post("/context-mcps", {"name": "Precedent", "url": f"{base_url.rstrip('/')}/mcp/", "timeoutMs": 20000})


def test(to: str | None = None) -> None:
    """Send ONE text and watch its delivery for 30 s. Never resends."""
    to = to or ONCALL_PHONE
    if not (DIAL_API_KEY and _FROM and to):
        print("Need DIAL_API_KEY, DIAL_FROM_NUMBER_ID (pn_...) and ONCALL_PHONE in .env")
        return
    print(f"Sending one {ALERT_CHANNEL if ALERT_CHANNEL != 'call' else 'sms'} text {TEXT_FROM} -> {mask(to)}")
    msg = send_text(to, "Precedent test: two-way texting works. Reply 1 to confirm.")
    print("sent:", {k: msg.get(k) for k in ("id", "status", "deliveryState")})
    m = msg
    for _ in range(10):
        time.sleep(3)
        try:
            m = find_message(msg.get("id"), to) or m
        except Exception as e:
            print("poll error:", e)
            continue
        print(f"  deliveryState={m.get('deliveryState')} status={m.get('status')} error={m.get('deliveryError')}")
        if m.get("deliveryState") in ("delivered", "undelivered", "failed", "unconfirmed"):
            break
    err = (m.get("deliveryError") or m.get("statusError") or "").lower()
    if any(s in err for s in ("10dlc", "a2p", "unregistered", "registration", "campaign")):
        print("10DLC BLOCKED -> set ALERT_CHANNEL=imessage or call")
    elif m.get("deliveryState") in ("undelivered", "failed"):
        print(f"FAILED: {err or 'no reason given'} -> try ALERT_CHANNEL=imessage or call")
    elif m.get("deliveryState") == "delivered":
        print("DELIVERED. Reply 1 on the phone; the server's listener logs it.")
    else:
        print(f"Final state {m.get('deliveryState')}: check the phone.")


if __name__ == "__main__":
    cmd, *args = sys.argv[1:] or ["help"]
    if cmd == "test":
        test(args[0] if args else None)
    elif cmd == "send":
        print(send_text(args[0], args[1]))
    elif cmd == "call":
        print(place_call(args[0], args[1]))
    elif cmd == "webhook":
        print(create_webhook(args[0] if args else None))
    elif cmd == "webhooks":
        print(list_webhooks())
    elif cmd == "numbers":
        for n in list_numbers(refresh=True):
            role = [r for r, ref in (("calls", _FROM), ("texts", TEXT_FROM)) if ref in (n.get("id"), n.get("number"))]
            print(f"{n.get('id')}  {n.get('number')}  caps={n.get('capabilities')}  setup={n.get('setupStatus')}"
                  f"  nickname={n.get('nickname')!r}  {'<- ' + '+'.join(role) if role else ''}")
    elif cmd == "register-context-mcp":
        print(register_context_mcp(args[0]))
    else:
        print(__doc__)
