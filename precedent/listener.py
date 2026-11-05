"""Inbound Dial messages without a tunnel: a daemon thread long-polling POST /events/wait.

Started by server.py on startup when DIAL_API_KEY is set and DIAL_INBOUND != "webhook".
The event stream is presence-based, so only replies that arrive while the server runs are seen.
"""
import logging
import threading
import time

import httpx

from precedent import dial

log = logging.getLogger(__name__)
_started = False


def _loop(handler) -> None:
    log.info("long-polling Dial /events/wait for message.received")
    while True:
        try:
            event = dial.wait_event("message.received", timeout=55)
            if event is None:  # 408: nothing arrived, poll again
                continue
            data = event.get("data") or {}
            if data.get("source") == "internal":
                continue
            log.info("message %s from ...%s", event.get("id"), str(data.get("from"))[-4:])
            handler(event)
        except httpx.TimeoutException:
            continue
        except Exception:
            log.exception("listener error; retrying in 2 s")
            time.sleep(2)


def start(handler) -> None:
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, args=(handler,), daemon=True, name="dial-listener").start()
