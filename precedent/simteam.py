"""Simulated ops team for ambient-replay incidents, clearly labelled "Ops team (simulated)".

Replay incidents (status "paged (replay)") never ring a phone. So the console doesn't fill up with hundreds of open
incidents, this sweeper handles them like a real team would:
  20-40 s after opening (by serial hash): decide replace  -> "Ops team (simulated) said replace."
  30-60 s after that:                     resolve replaced -> "Ops team (simulated) replaced drive X."
No Dial, Sparta or Darwin side effects, and no playbooks (simulated fixes must never become suggestions).
Never touches the pinned drive or PAGE_SERIALS. State lives in SQLite, so it resumes after a restart.
A backlog older than 30 min is closed quietly (no event flood).
"""
import logging
import threading
import time
import zlib

from precedent import db, events
from precedent.public_api import _pinned

log = logging.getLogger(__name__)
ACTOR, VIA = db.SIM_TEAM, "replay"
PER_TICK = 6
_started = False


def _delay(serial: str, lo: int, hi: int) -> int:
    return lo + zlib.crc32((serial or "").encode()) % (hi - lo + 1)


def tick(now_ms: int | None = None) -> dict:
    now = now_ms or int(time.time() * 1000)
    c, prot, out = db.conn(), _pinned(), {"decided": 0, "resolved": 0, "closed_backlog": 0}
    # quiet close for a stale backlog (e.g. hours of replay while the server was down)
    with db._wlock:
        cur = c.execute("""UPDATE incidents SET status='resolved (auto-closed)', resolved_ts=? WHERE status='paged (replay)'
                           AND choice IS NULL AND created_ts < ?""", (now, now - 30 * 60 * 1000))
        c.commit()
        out["closed_backlog"] = cur.rowcount
    for r in c.execute("""SELECT alert_id, serial, created_ts FROM incidents WHERE status='paged (replay)' AND choice IS NULL
                          ORDER BY created_ts LIMIT 200""").fetchall():
        if out["decided"] >= PER_TICK:
            break
        if r["serial"] in prot or now - r["created_ts"] < _delay(r["serial"], 20, 40) * 1000:
            continue
        events.publish("decision", {"choice": "swap", "via": VIA, "by": ACTOR, "keewano_logged": False, "simulated": True},
                       r["alert_id"], r["serial"])
        out["decided"] += 1
    for r in c.execute("""SELECT alert_id, serial, decided_ts, model, pattern FROM incidents WHERE status='decided'
                          AND choice='swap' AND alert_id IN (SELECT alert_id FROM decisions WHERE via=?)
                          ORDER BY decided_ts LIMIT 200""", (VIA,)).fetchall():
        if out["resolved"] >= PER_TICK:
            break
        if r["serial"] in prot or now - (r["decided_ts"] or now) < _delay(r["serial"][::-1], 30, 60) * 1000:
            continue
        events.publish("incident_resolved", {"action": "replaced", "note": "", "by": ACTOR, "model": r["model"],
                                             "pattern": r["pattern"], "simulated": True}, r["alert_id"], r["serial"])
        out["resolved"] += 1
    return out


def _loop() -> None:
    while True:
        try:
            tick()
        except Exception:
            log.exception("simulated team tick failed")
        time.sleep(3)


def start() -> None:
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name="simteam").start()
