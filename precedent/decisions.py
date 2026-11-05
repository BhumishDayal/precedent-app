"""Decision log and pending alerts in config.STATE_DIR (decisions.jsonl, alerts.jsonl), append-only JSONL.

Decision row: {ts, serial, model, pattern, choice: "swap"|"wait"|"show"|"unclear", phone, alert_id, n, died,
               keewano_logged: bool, via}
Alert row:    {ts, alert_id, serial, model, pattern, phone, n, died, rate, channel, message_id, call_id}
"""
import json
import logging
import os
import threading
from datetime import datetime, timezone

from precedent.config import DECISIONS_PATH, STATE_DIR

log = logging.getLogger(__name__)
ALERTS_PATH = os.path.join(STATE_DIR, "alerts.jsonl")
_lock = threading.Lock()  # without it, appends from several threads lost rows on Windows


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _append(path: str, row: dict) -> dict:
    line = json.dumps(row, default=str) + "\n"
    with _lock, open(path, "a") as f:
        f.write(line)
    return row


def _read(path: str) -> list[dict]:
    """All rows; a line cut short by a crash mid-write is skipped, not fatal."""
    if not os.path.exists(path):
        return []
    rows = []
    with open(path) as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except ValueError:
                if line.strip():
                    log.warning("skipped an unreadable line in %s", path)
    return rows


def log_decision(alert: dict, choice: str, keewano_logged: bool = False, ts: str | None = None,
                 via: str | None = None) -> dict:
    """keewano_logged: did keewano.push_event actually succeed (False in dry-run / for "unclear")."""
    return _append(DECISIONS_PATH, {
        "ts": ts or now(), "serial": alert["serial"], "model": alert["model"], "pattern": alert["pattern"],
        "choice": choice, "phone": alert["phone"], "alert_id": alert["alert_id"],
        "n": alert["n"], "died": alert["died"], "keewano_logged": bool(keewano_logged), "via": via,
    })


def read_decisions(limit: int | None = None) -> list[dict]:
    rows = _read(DECISIONS_PATH)
    return rows[-limit:] if limit else rows


def add_alert(alert: dict) -> dict:
    return _append(ALERTS_PATH, {"ts": now(), **alert})


def get_alert(alert_id: str) -> dict | None:
    return next((a for a in reversed(_read(ALERTS_PATH)) if a["alert_id"] == alert_id), None)


def latest_alert() -> dict | None:
    rows = _read(ALERTS_PATH)
    return rows[-1] if rows else None


def latest_alert_for(phone: str) -> dict | None:
    """Most recent alert texted to this phone (the one a bare "1"/"2"/"3" reply refers to)."""
    return next((a for a in reversed(_read(ALERTS_PATH)) if a["phone"] == phone), None)


def is_resolved(alert_id: str) -> bool:
    """True once swap, wait or apply has been chosen ("show" only asks for evidence)."""
    return any(d["alert_id"] == alert_id and d["choice"] in ("swap", "wait", "apply") for d in _read(DECISIONS_PATH))
