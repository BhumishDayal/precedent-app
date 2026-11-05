"""Operational database: SQLite (WAL) at STATE_DIR/precedent_ops.sqlite. One writer (this process), many readers.

events.publish() calls record(ev): the event row plus derived rows (incidents, decisions, messages).
The JSONL files stay as the append-only source; backfill() imports them on startup if the DB is new.
Every read helper uses an index + LIMIT.
"""
import json
import os
import sqlite3
import threading

from precedent.config import ONCALL_NAME, STATE_DIR

PATH = os.path.join(STATE_DIR, "precedent_ops.sqlite")
_wlock = threading.Lock()
_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, ts INTEGER, type TEXT, alert_id TEXT, serial TEXT,
                                   site TEXT, payload_json TEXT);
CREATE INDEX IF NOT EXISTS ev_type ON events(type, id);
CREATE INDEX IF NOT EXISTS ev_alert ON events(alert_id, id);
CREATE INDEX IF NOT EXISTS ev_serial ON events(serial, id);
CREATE INDEX IF NOT EXISTS ev_site ON events(site, id);
CREATE TABLE IF NOT EXISTS incidents (alert_id TEXT PRIMARY KEY, serial TEXT, model TEXT, pattern TEXT, verdict TEXT,
                                      status TEXT, site TEXT, n INTEGER, died INTEGER, created_ts INTEGER,
                                      decided_ts INTEGER, resolved_ts INTEGER, choice TEXT);
CREATE INDEX IF NOT EXISTS inc_serial ON incidents(serial);
CREATE INDEX IF NOT EXISTS inc_status ON incidents(status, created_ts);
CREATE TABLE IF NOT EXISTS decisions (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, alert_id TEXT, serial TEXT,
                                      choice TEXT, via TEXT, keewano_logged INTEGER);
CREATE INDEX IF NOT EXISTS dec_alert ON decisions(alert_id, id);
CREATE TABLE IF NOT EXISTS resolutions (id INTEGER PRIMARY KEY AUTOINCREMENT, alert_id TEXT, serial TEXT, model TEXT,
                                        pattern TEXT, action TEXT, note TEXT, by TEXT, ts INTEGER);
CREATE INDEX IF NOT EXISTS res_mp ON resolutions(model, pattern, ts);
CREATE INDEX IF NOT EXISTS res_alert ON resolutions(alert_id);
CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, alert_id TEXT, frm TEXT,
                                     too TEXT, body TEXT, direction TEXT, channel TEXT);
CREATE INDEX IF NOT EXISTS msg_ts ON messages(ts);
"""


def conn() -> sqlite3.Connection:
    c = getattr(_local, "c", None)
    if c is None:
        c = sqlite3.connect(PATH, timeout=10, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        _local.c = c
    return c


SIM_TEAM = "Ops team (simulated)"


def init() -> None:
    with _wlock:
        c = conn()
        c.executescript(SCHEMA)
        if "assigned_to" not in {r["name"] for r in c.execute("PRAGMA table_info(incidents)")}:
            c.execute("ALTER TABLE incidents ADD COLUMN assigned_to TEXT")
            c.execute("CREATE INDEX IF NOT EXISTS inc_assigned ON incidents(assigned_to, status)")
        # backfill: replay incidents (and anything the simulated team decided) belong to the simulated team
        c.execute("""UPDATE incidents SET assigned_to = CASE WHEN status LIKE 'paged (replay)%' OR status LIKE '%auto-closed%'
                      OR alert_id IN (SELECT alert_id FROM decisions WHERE via='replay') THEN ? ELSE ? END
                      WHERE assigned_to IS NULL""", (SIM_TEAM, ONCALL_NAME))
        c.commit()


def _site(ev: dict) -> str | None:
    d = ev.get("data") or {}
    return d.get("site") or (d.get("alert") or {}).get("site")


def record(ev: dict) -> None:
    """Insert one event and keep the derived tables current. Called under events' lock (ids are ordered)."""
    d, t = ev.get("data") or {}, ev["type"]
    with _wlock:
        c = conn()
        c.execute("INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?,?)",
                  (ev["id"], ev["ts"], t, ev.get("alert_id"), ev.get("serial"), _site(ev), json.dumps(d, default=str)))
        aid = ev.get("alert_id")
        if t == "alert_created" or (t == "incident_opened" and aid):
            a = d.get("alert") or d
            status = a.get("status", "open")
            assigned = a.get("assigned_to") or (SIM_TEAM if str(status).startswith("paged (replay)") else ONCALL_NAME)
            c.execute("""INSERT OR IGNORE INTO incidents (alert_id, serial, model, pattern, verdict, status, site, n, died,
                         created_ts, assigned_to) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                      (aid, ev.get("serial"), a.get("model"), a.get("pattern"), a.get("verdict", "act"),
                       status, a.get("site"), a.get("n"), a.get("died"), ev["ts"], assigned))
        elif t == "decision" and aid:
            c.execute("INSERT INTO decisions (ts, alert_id, serial, choice, via, keewano_logged) VALUES (?,?,?,?,?,?)",
                      (ev["ts"], aid, ev.get("serial"), d.get("choice"), d.get("via"), int(bool(d.get("keewano_logged")))))
            if d.get("choice") in ("swap", "wait"):
                c.execute("UPDATE incidents SET status='decided', decided_ts=?, choice=? WHERE alert_id=? AND status!='resolved'",
                          (ev["ts"], d.get("choice"), aid))
        elif t == "incident_resolved" and aid:
            c.execute("""INSERT INTO resolutions (alert_id, serial, model, pattern, action, note, by, ts)
                         VALUES (?,?,?,?,?,?,?,?)""", (aid, ev.get("serial"), d.get("model"), d.get("pattern"),
                                                       d.get("action"), d.get("note"), d.get("by"), ev["ts"]))
            c.execute("UPDATE incidents SET status='resolved', resolved_ts=? WHERE alert_id=?", (ev["ts"], aid))
        elif t in ("message_sent", "message_received"):
            c.execute("INSERT INTO messages (ts, alert_id, frm, too, body, direction, channel) VALUES (?,?,?,?,?,?,?)",
                      (ev["ts"], aid, d.get("from"), d.get("to"), d.get("body"), t.split("_")[1], d.get("channel")))
        c.commit()


def backfill(events_path: str) -> int:
    """Import events.jsonl rows the DB doesn't have yet (startup). Returns how many were added."""
    init()
    have = conn().execute("SELECT coalesce(max(id), 0) FROM events").fetchone()[0]
    n = 0
    if os.path.exists(events_path):
        with open(events_path) as f:
            for line in f:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("id", 0) > have:
                    record(ev)
                    n += 1
    return n


def archive_and_clear(dest_dir: str) -> dict:
    """Copy the DB to dest_dir (SQLite backup API, consistent while running), then empty the operational tables."""
    os.makedirs(dest_dir, exist_ok=True)
    with _wlock:
        c = conn()
        bak = sqlite3.connect(os.path.join(dest_dir, "precedent_ops.sqlite"))
        c.backup(bak)
        bak.close()
        counts = {t: c.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                  for t in ("events", "incidents", "decisions", "resolutions", "messages")}
        for t in counts:
            c.execute(f"DELETE FROM {t}")
        c.commit()
    return counts


def _ev(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "ts": r["ts"], "type": r["type"], "alert_id": r["alert_id"], "serial": r["serial"],
            "data": json.loads(r["payload_json"] or "{}")}


def events_after(after_id: int = 0, alert_id: str | None = None, limit: int = 5000) -> list[dict]:
    if alert_id:
        q = "SELECT * FROM events WHERE alert_id=? AND id>? ORDER BY id LIMIT ?"
        args = (alert_id, after_id, limit)
    else:
        q, args = "SELECT * FROM events WHERE id>? ORDER BY id LIMIT ?", (after_id, limit)
    return [_ev(r) for r in conn().execute(q, args)]


def serial_events(serial: str, types: tuple, limit: int = 200) -> list[dict]:
    q = f"SELECT * FROM events WHERE serial=? AND type IN ({','.join('?' * len(types))}) ORDER BY id DESC LIMIT ?"
    return [_ev(r) for r in conn().execute(q, (serial, *types, limit))][::-1]


def feed(since_id: int = 0, limit: int = 100, kinds: list | None = None, site: str | None = None) -> list[dict]:
    where, args = ["id > ?"], [since_id]
    if kinds:
        where.append(f"type IN ({','.join('?' * len(kinds))})")
        args += kinds
    if site:
        where.append("site = ?")
        args.append(site)
    q = f"SELECT * FROM events WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT ?"
    return [_ev(r) for r in conn().execute(q, (*args, max(0, min(int(limit), 1000))))]  # SQLite: LIMIT -1 = no limit


def incident(alert_id: str) -> dict | None:
    r = conn().execute("SELECT * FROM incidents WHERE alert_id=?", (alert_id,)).fetchone()
    return dict(r) if r else None


def incident_for_serial(serial: str) -> dict | None:
    r = conn().execute("SELECT * FROM incidents WHERE serial=? ORDER BY created_ts DESC LIMIT 1", (serial,)).fetchone()
    return dict(r) if r else None


def resolutions(model: str, pattern: str, exclude_serial: str | None = None, limit: int = 50) -> list[dict]:
    rows = conn().execute("SELECT * FROM resolutions WHERE model=? AND pattern=? ORDER BY ts DESC LIMIT ?",
                          (model, pattern, limit))
    return [dict(r) for r in rows if r["serial"] != exclude_serial]


def resolutions_for(alert_id: str) -> list[dict]:
    return [dict(r) for r in conn().execute("SELECT * FROM resolutions WHERE alert_id=? ORDER BY ts", (alert_id,))]
