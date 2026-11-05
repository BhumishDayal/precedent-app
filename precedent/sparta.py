"""Sparta Worlds step after a "swap": open EXACTLY ONE remote-hands Zendesk ticket, idempotent on alert_id.

Sparta Worlds runs locally: `npm install sparta_worlds@0.9.0-beta.5`, then `npx --no-install worlds serve --port 4242`;
POST /admin/worlds {"seed":"zendesk-support-v1"} -> {world_id, base_url (bare origin), api_key}. The Zendesk API is
<base_url>/api/v2 (https://www.usesparta.co/docs/zendesk-native); the api_key (Bearer sk_twin_w_...) selects the world.
Comment bodies must be plain text (Markdown/HTML -> 422), so _plain() strips those characters.
No duplicates: Idempotency-Key = precedent-<alert_id> (Sparta replays the original ticket, header
x-idempotency-lookup: hit), plus a local check of actions.jsonl. Retries only on 429/5xx/network errors.

Env: SPARTA_ZENDESK_URL (e.g. http://127.0.0.1:4242/api/v2), SPARTA_API_KEY. Empty = dry-run log line.
     SPARTA_INJECT_FAULT=1 (+ SPARTA_WORLD_ID): the live swap first gets one injected 500, so the retry shows.
     For `fault`: SPARTA_ADMIN_URL (http://127.0.0.1:4242), SPARTA_WORLD_ID, SPARTA_ADMIN_TOKEN (optional on loopback).

CLI:  python -m precedent.sparta selftest   # offline: simulated Sparta, injected 500 + key expiry, proves no duplicate
      python -m precedent.sparta fault      # live world: applies a one-shot 500 scenario, opens a ticket, replays it
"""
import contextlib
import json
import logging
import os
import re
import sys
import time
import uuid

import httpx

from precedent.actions import log_action, read_actions
from precedent.config import DIAL_API_KEY, HORIZON_DAYS

log = logging.getLogger(__name__)
ZENDESK_URL = os.getenv("SPARTA_ZENDESK_URL", "").rstrip("/")
API_KEY = os.getenv("SPARTA_API_KEY", "")
ADMIN_URL = os.getenv("SPARTA_ADMIN_URL", "http://127.0.0.1:4242").rstrip("/")
WORLD_ID = os.getenv("SPARTA_WORLD_ID", "")
ADMIN_TOKEN = os.getenv("SPARTA_ADMIN_TOKEN", "")
INJECT_FAULT = os.getenv("SPARTA_INJECT_FAULT", "") == "1"
RETRYABLE = {429, 500, 502, 503, 504}


def _plain(text: str) -> str:
    """Sparta's native Zendesk profile refuses Markdown/HTML in comment bodies."""
    return re.sub(r"[*_`\[\]<>{}#|~]", " ", text)


def _ticket(alert: dict) -> dict:
    return {"ticket": {
        "subject": f"Swap drive {alert['serial']} {alert['model']}",
        "comment": {"body": _plain(f"Remote hands: please swap drive {alert['serial']} ({alert['model']}).\n"
                                   f"Evidence: {alert['died']} of {alert['n']} identical drives with SMART warning "
                                   f"{alert['pattern']} died within {HORIZON_DAYS} days.\n"
                                   f"Decision logged by the on-call via Precedent, alert {alert['alert_id']}.")},
        "priority": "high", "tags": ["precedent", "drive-swap"], "external_id": f"precedent-{alert['alert_id']}",
    }}


def open_ticket(alert: dict, client: httpx.Client | None = None, attempts: int = 3) -> dict:
    """POST /tickets.json once per alert. Returns {status, ticket_id, attempts, recovered, replay, errors}."""
    headers = {"Idempotency-Key": f"precedent-{alert['alert_id']}"}
    errors = []
    own = httpx.Client(base_url=ZENDESK_URL, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=15) if client is None else None
    with own or contextlib.nullcontext(client) as c:  # close only the client we opened
        for i in range(1, attempts + 1):
            try:
                r = c.post("/tickets.json", json=_ticket(alert), headers=headers)
            except httpx.HTTPError as e:
                errors.append(f"network: {e}")
            else:
                if r.status_code < 300:
                    t = r.json().get("ticket", {})
                    return {"status": "opened", "ticket_id": t.get("id"), "attempts": i, "recovered": len(errors),
                            "replay": r.headers.get("x-idempotency-lookup") == "hit", "errors": errors}
                errors.append(f"{r.status_code}: {r.text[:120]}")
                if r.status_code not in RETRYABLE:  # 401 expired key / 400: retrying won't help, stop clean
                    break
            if i < attempts:
                time.sleep(min(2 ** (i - 1), 4))
    return {"status": "error", "ticket_id": None, "attempts": i, "recovered": 0, "replay": False, "errors": errors}


def after_swap(alert: dict) -> dict:
    """Never raises. One ticket per alert_id even if called twice (local log + Sparta idempotency)."""
    done = [a for a in read_actions(None) if a["alert_id"] == alert["alert_id"]
            and a["sponsor"] == "sparta" and a["status"] in ("opened", "dry-run")]
    if done:
        return done[-1]
    subject = _ticket(alert)["ticket"]["subject"]
    if not (ZENDESK_URL and API_KEY) or not DIAL_API_KEY:  # dry run like the rest of the app: no live ticket
        log.info("dry run: would open ticket %r", subject)
        return log_action(alert["alert_id"], "sparta", "dry-run",
                          f"Sparta (dry-run): would open remote-hands ticket '{subject}'", {"subject": subject})
    try:
        if INJECT_FAULT and WORLD_ID:
            _admin("POST", "/scenario", json={"scenario_doc": _ONE_500})
        res = open_ticket(alert)
    except Exception as e:
        log.exception("opening the ticket failed")
        res = {"status": "error", "attempts": 0, "recovered": 0, "errors": [str(e)]}
    finally:
        if INJECT_FAULT and WORLD_ID:
            try:
                _admin("DELETE", "/scenario")
            except httpx.HTTPError as e:
                log.warning("could not clear the injected fault scenario: %s", e)
    log.info("ticket result: %s", res)
    return log_action(alert["alert_id"], "sparta", res["status"], stage_line(res), res)


def stage_line(res: dict) -> str:
    if res["status"] != "opened":
        last = (res.get("errors") or ["unknown error"])[-1][:80]
        return f"Sparta: ticket not opened after {res.get('attempts')} attempt(s) ({last}); stopped, no duplicate"
    n = res.get("recovered", 0)
    rec = f"{n} injected failure{'s' if n != 1 else ''} recovered" if n else "opened first try"
    return f"Sparta: remote-hands ticket #{res['ticket_id']} opened, {rec}, no duplicates"


_ONE_500 = {"name": "precedent-one-500", "rules": [{"match": {"method": "POST", "path": "/api/v2/tickets.json"}, "duration_requests": 1,
                       "respond": {"status": 500, "stripe_error": "api_error"}}]}


def _admin(method: str, path: str, **kw) -> httpx.Response:
    h = {"Authorization": f"Bearer {ADMIN_TOKEN}"} if ADMIN_TOKEN else {}
    return httpx.request(method, f"{ADMIN_URL}/admin/worlds/{WORLD_ID}{path}", headers=h, timeout=15, **kw)


def _demo_alert() -> dict:
    return {"alert_id": "fault" + uuid.uuid4().hex[:5], "serial": "1QHPN2VX", "model": "WDC WUH722222ALE6L4",
            "pattern": "197:high", "n": 59, "died": 26}


def fault() -> None:
    """Live: one injected 500 on ticket create, then recovery, then a replay that must return the same ticket."""
    if not (ZENDESK_URL and API_KEY and WORLD_ID):
        print("Need SPARTA_ZENDESK_URL, SPARTA_API_KEY and SPARTA_WORLD_ID")
        return
    print("apply scenario:", _admin("POST", "/scenario", json={"scenario_doc": _ONE_500}).status_code)
    alert = _demo_alert()
    first = open_ticket(alert)
    again = open_ticket(alert)
    print("first:", first, "\nreplay:", again)
    print("same ticket, no duplicate:", first["ticket_id"] == again["ticket_id"] and again["replay"])
    log_action(alert["alert_id"], "sparta", first["status"], stage_line(first), {**first, "fault_test": True, "replay": again})
    _admin("DELETE", "/scenario")


def selftest() -> bool:
    """Offline: a fake Zendesk that 500s once, honours Idempotency-Key, and expires keys -> no duplicate ticket."""
    tickets, by_key, calls = {}, {}, {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if req.headers.get("authorization") == "Bearer expired":
            return httpx.Response(401, json={"error": "api_key_expired"})
        if calls["n"] == 1:
            return httpx.Response(500, json={"error": "injected api_error"})
        key = req.headers["idempotency-key"]
        if key in by_key:
            return httpx.Response(201, json={"ticket": tickets[by_key[key]]}, headers={"x-idempotency-lookup": "hit"})
        tid = len(tickets) + 1
        tickets[tid] = {"id": tid, **json.loads(req.content)["ticket"]}
        by_key[key] = tid
        return httpx.Response(201, json={"ticket": tickets[tid]})

    global time
    real_time, time = time, type("t", (), {"sleep": staticmethod(lambda s: None)})
    try:
        mk = lambda tok: httpx.Client(base_url="http://sparta.test/api/v2", headers={"Authorization": f"Bearer {tok}"},
                                      transport=httpx.MockTransport(handler))
        alert = _demo_alert()
        a = open_ticket(alert, mk("sk_twin_ok"))
        b = open_ticket(alert, mk("sk_twin_ok"))
        c = open_ticket(alert, mk("expired"))
    finally:
        time = real_time
    print("1st (500 injected):", a)
    print("2nd (replay)      :", b)
    print("3rd (expired key) :", c)
    ok = (a["status"] == "opened" and a["recovered"] == 1 and b["replay"] and b["ticket_id"] == a["ticket_id"]
          and c["status"] == "error" and c["attempts"] == 1 and len(tickets) == 1)
    print("stage line:", stage_line(a))
    print(f"tickets created: {len(tickets)} -> SELFTEST {'OK' if ok else 'FAILED'}")
    return ok


if __name__ == "__main__":
    cmd = (sys.argv[1:] or ["help"])[0]
    if cmd == "selftest":
        sys.exit(0 if selftest() else 1)
    elif cmd == "fault":
        fault()
    else:
        print(__doc__)
