"""What agents did after a decision: STATE_DIR/actions.jsonl, one JSON object per line.

Row: {ts, alert_id, sponsor: "sparta"|"darwin"|..., status, detail: one plain sentence, data: raw result}
"""
import logging
import os

from precedent import decisions, events, lifecycle, notify
from precedent.config import STATE_DIR

log = logging.getLogger(__name__)
ACTIONS_PATH = os.path.join(STATE_DIR, "actions.jsonl")


def log_action(alert_id: str, sponsor: str, status: str, detail: str, data=None) -> dict:
    row = decisions._append(ACTIONS_PATH, {"ts": decisions.now(), "alert_id": alert_id, "sponsor": sponsor,
                                           "status": status, "detail": detail, "data": data})
    events.publish("action_result", {"sponsor": sponsor, "status": status, "detail": detail,
                                     "data": data if isinstance(data, dict) else None}, alert_id)
    if sponsor == "sparta" and status in ("opened", "dry-run"):
        try:
            lifecycle.transition(alert_id, "actioned", "Sparta agent", "agent",
                                 "Remote-hands ticket is open." if status == "opened" else "Remote-hands ticket ready (practice mode).")
        except Exception:
            log.exception("lifecycle transition failed for %s", alert_id)
    notify.notify("action", {**(decisions.get_alert(alert_id) or {"alert_id": alert_id}),
                             "sponsor": sponsor, "status": status, "detail": detail})
    return row


def read_actions(limit: int | None = 50) -> list[dict]:
    rows = decisions._read(ACTIONS_PATH)
    return rows[-limit:] if limit else rows
