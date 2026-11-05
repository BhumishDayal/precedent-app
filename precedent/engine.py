"""The precedent engine: warning events -> outcomes -> counts per (model, pattern).

A "warning event" is a day where a drive's pattern changes to a new non-empty value. A pattern is
the non-zero SMART attrs plus a severity bucket of the largest raw count, e.g. "5+197:mid"
(low < 8, mid < 100, high >= 100). Outcome = did the drive fail within HORIZON_DAYS.
Drives that vanish before the horizon without failing are censored (dropped from counts).

Usage: python -m precedent.engine   (builds tables, prints top patterns + backtest)
"""
import datetime as dt
import os

import duckdb

from precedent.config import (CIRCULAR_ATTRS, DAILY_DIR, DATA, DATE_SHIFT_DAYS, DB_PATH, HORIZON_DAYS, MIN_N, MIN_RATE,
                              SMART_ATTRS, SWAPLIST_MIN_RATE)


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(DB_PATH, read_only=read_only)


def build(con: duckdb.DuckDBPyConnection) -> None:
    pattern = " || ".join(f"CASE WHEN s{a} > 0 THEN '+{a}' ELSE '' END" for a in SMART_ATTRS)
    con.execute(f"""
        CREATE OR REPLACE TABLE daily AS
        WITH base AS (
          SELECT *, ltrim({pattern}, '+') AS attrs,
                 greatest(coalesce(s5, 0), coalesce(s197, 0), coalesce(s198, 0), coalesce(s187, 0)) AS sev
          FROM read_parquet('{DAILY_DIR}/*.parquet', union_by_name=true)
        )
        SELECT date, serial, model, failure,
               CASE WHEN attrs = '' THEN '' ELSE attrs || ':' ||
                 CASE WHEN sev < 8 THEN 'low' WHEN sev < 100 THEN 'mid' ELSE 'high' END END AS pattern,
               {", ".join(f"s{a}" for a in SMART_ATTRS)}
        FROM base
    """)
    con.execute("""
        CREATE OR REPLACE TABLE drives AS
        SELECT serial, any_value(model) AS model, min(date) AS first_seen, max(date) AS last_seen,
               min(CASE WHEN failure = 1 THEN date END) AS failed_on
        FROM daily GROUP BY serial
    """)
    con.execute(f"""
        CREATE OR REPLACE TABLE warnings AS
        WITH seq AS (
          SELECT *, lag(pattern) OVER (PARTITION BY serial ORDER BY date) AS prev_pattern
          FROM daily
        )
        SELECT s.date AS warn_date, s.serial, s.model, s.pattern, s.prev_pattern,
               {", ".join(f"s.s{a}" for a in SMART_ATTRS)},
               d.failed_on, d.last_seen,
               (d.failed_on IS NOT NULL AND d.failed_on - s.date <= {HORIZON_DAYS}) AS died,
               (d.failed_on IS NULL AND d.last_seen - s.date < {HORIZON_DAYS}) AS censored,
               ({" OR ".join(f"s.pattern LIKE '%{a}%'" for a in CIRCULAR_ATTRS)}) AS circular
        FROM seq s JOIN drives d USING (serial)
        WHERE s.pattern <> '' AND s.prev_pattern IS NOT NULL AND s.pattern <> s.prev_pattern
          AND s.failure = 0
    """)


def precedent(con, model: str, pattern: str, as_of=None, exclude_serial=None) -> dict:
    """Count identical drives (same model + pattern) whose outcome was known before as_of.
    exclude_serial: leave the alerted drive itself out of its own history."""
    where = f"AND warn_date + {HORIZON_DAYS} <= DATE '{as_of}'" if as_of else ""  # as_of: internal dates only
    extra = []
    if exclude_serial:
        where += " AND serial <> ?"
        extra.append(str(exclude_serial))
    n, died, drives = con.execute(f"""
        SELECT count(*) AS n, count(*) FILTER (died) AS died, count(DISTINCT serial) AS drives
        FROM warnings WHERE NOT censored AND model = ? AND pattern = ? {where}
    """, [model, pattern, *extra]).fetchone()
    scope = "same model"
    if n < MIN_N:  # fall back to the same pattern on any model
        n, died, drives = con.execute(f"""
            SELECT count(*), count(*) FILTER (died), count(DISTINCT serial)
            FROM warnings WHERE NOT censored AND pattern = ? {where}
        """, [pattern, *extra]).fetchone()
        scope = "any model"
    rate = died / n if n else None
    return {
        "model": model, "pattern": pattern, "scope": scope, "n": n, "died": died, "drives": drives,
        "rate": rate, "enough": n >= MIN_N,
        "act": bool(n >= MIN_N and rate is not None and rate >= MIN_RATE),
        "circular": any(str(a) in pattern.split(":")[0].split("+") for a in CIRCULAR_ATTRS),
    }


def demo_drive(con, prefer_non_circular: bool = True) -> dict:
    """A real warning from the most recent month whose history (known before that day) says act."""
    rows = con.execute("""
        SELECT warn_date, serial, model, pattern, circular, died FROM warnings
        WHERE warn_date >= (SELECT max(warn_date) - 45 FROM warnings)
        ORDER BY circular, died DESC, warn_date DESC LIMIT 4000
    """).fetchall()
    best = None
    for warn_date, serial, model, pattern, circular, died in rows:
        if prefer_non_circular and circular and best:
            break
        p = precedent(con, model, pattern, as_of=warn_date)
        better = best is None or (died, p["rate"]) > (best["actually_died"], best["rate"])
        if p["act"] and p["scope"] == "same model" and better:
            best = {**p, "serial": serial, "warn_date": str(warn_date), "actually_died": bool(died)}
    return best or {}


def similar_drives(con, model: str, pattern: str, limit: int = 5, exclude_serial=None):
    """Most recent identical warnings (same model + pattern) with their outcomes, for the incident page / "3" reply."""
    ex = "AND serial <> ?" if exclude_serial else ""
    params = [model, pattern] + ([exclude_serial] if exclude_serial else [])
    return con.execute(f"""
        SELECT serial, warn_date, died, failed_on, censored FROM warnings
        WHERE model = ? AND pattern = ? {ex} ORDER BY warn_date DESC LIMIT {int(limit)}
    """, params).df()


LOCATIONS = os.path.join(DATA, "locations.parquet")  # written by precedent.locations


def _severity(v: int) -> str:
    return "low" if v < 8 else ("mid" if v < 100 else "high")


def _loc_sql() -> str:
    if os.path.exists(LOCATIONS):
        return f"read_parquet('{LOCATIONS}')"
    return "(SELECT NULL::VARCHAR serial, NULL::VARCHAR datacenter, NULL::VARCHAR cluster_id, NULL::VARCHAR vault_id, NULL::VARCHAR pod_id, NULL::VARCHAR pod_slot_num WHERE false)"


def pattern_of(smart: dict) -> str:
    """{"5": 12, "197": 3, ...} -> "5+197:mid" ("" when healthy). Same rule as the warnings table."""
    vals = {a: int(smart.get(str(a)) or smart.get(a) or 0) for a in SMART_ATTRS}
    attrs = [str(a) for a in SMART_ATTRS if vals[a] > 0]
    if not attrs:
        return ""
    return "+".join(attrs) + ":" + _severity(max(vals[5], vals[197], vals[198], vals[187]))


def evaluate_reading(con, model: str, smart: dict, serial=None) -> dict:
    """A live SMART reading from any fleet -> its pattern and what history says. Used by /v1/telemetry and MCP."""
    pattern = pattern_of(smart)
    if not pattern:
        return {"model": model, "pattern": "", "verdict": "healthy", "act": False, "precedent": None}
    p = precedent(con, model, pattern, exclude_serial=serial)
    if p["act"]:
        verdict = "act"
    elif p["enough"]:
        verdict = "watch" if (p["rate"] or 0) >= SWAPLIST_MIN_RATE else "quiet"
    else:
        verdict = "not enough history"
    return {"model": model, "pattern": pattern, "verdict": verdict, "act": p["act"], "precedent": p}


def drive_profile(con, serial: str, live_record_date=None) -> dict:
    """Everything about one drive: identity, physical location, SMART history, warnings with outcomes."""
    d = con.execute(f"""
        SELECT d.serial, d.model, d.first_seen, d.last_seen, d.failed_on, l.datacenter, l.cluster_id, l.vault_id,
               l.pod_id, l.pod_slot_num
        FROM drives d LEFT JOIN {_loc_sql()} l USING (serial) WHERE d.serial = ?
    """, [serial]).fetchone()
    if not d:
        return {}
    keys = ["serial", "model", "first_seen", "last_seen", "failed_on", "datacenter", "cluster_id", "vault_id", "pod_id", "pod_slot_num"]
    out = {k: (str(v) if v is not None else None) for k, v in zip(keys, d)}
    out["location"] = {k: out.pop(k) for k in ("datacenter", "cluster_id", "vault_id", "pod_id", "pod_slot_num")}
    out["smart_history"] = [
        {"date": str(r[0]), "s5": r[1], "s187": r[2], "s188": r[3], "s197": r[4], "s198": r[5], "pattern": r[6]}
        for r in con.execute("SELECT date, s5, s187, s188, s197, s198, pattern FROM daily WHERE serial = ? ORDER BY date", [serial]).fetchall()
    ]
    out["warnings"] = [
        {"warn_date": str(r[0]), "pattern": r[1], "died": bool(r[2]), "circular": bool(r[3])}
        for r in con.execute("SELECT warn_date, pattern, died, circular FROM warnings WHERE serial = ? ORDER BY warn_date", [serial]).fetchall()
    ]
    if live_record_date:  # warning live today: hide everything after that reading
        cut = str(live_record_date)[:10]
        out["smart_history"] = [r for r in out["smart_history"] if r["date"] <= cut]
        out["warnings"] = [r for r in out["warnings"] if r["warn_date"] <= cut]
        out["last_seen"], out["failed_on"] = cut, None
    _shift_rows([out], ("first_seen", "last_seen", "failed_on"), live_record_date)
    _shift_rows(out["smart_history"], ("date",), live_record_date)
    _shift_rows(out["warnings"], ("warn_date",), live_record_date)
    return out


def fleet_map(con, datacenter=None, vault_id=None, pod_id=None) -> dict:
    """Map data. No args: datacenters. datacenter: its pods (vault/pod) with health counts.
    datacenter+vault_id+pod_id: every slot in that pod with its drive and status (failed / warned / ok)."""
    loc = _loc_sql()
    status = """CASE WHEN d.failed_on IS NOT NULL THEN 'failed'
                     WHEN d.serial IN (SELECT serial FROM warnings) THEN 'warned' ELSE 'ok' END"""
    if pod_id is not None:
        rows = con.execute(f"""
            SELECT l.pod_slot_num, d.serial, d.model, {status} AS status
            FROM {loc} l JOIN drives d USING (serial)
            WHERE l.datacenter = ? AND l.vault_id = ? AND l.pod_id = ? ORDER BY l.pod_slot_num
        """, [datacenter, str(vault_id), str(pod_id)]).fetchall()
        return {"level": "pod", "datacenter": datacenter, "vault_id": vault_id, "pod_id": pod_id,
                "slots": [{"slot": r[0], "serial": r[1], "model": r[2], "status": r[3]} for r in rows]}
    if datacenter is not None:
        rows = con.execute(f"""
            SELECT l.vault_id, l.pod_id, count(*) AS drives,
                   count(*) FILTER (WHERE {status} = 'failed') AS failed,
                   count(*) FILTER (WHERE {status} = 'warned') AS warned
            FROM {loc} l JOIN drives d USING (serial) WHERE l.datacenter = ?
            GROUP BY ALL ORDER BY failed DESC, warned DESC LIMIT 400
        """, [datacenter]).fetchall()
        return {"level": "datacenter", "datacenter": datacenter,
                "pods": [{"vault_id": r[0], "pod_id": r[1], "drives": r[2], "failed": r[3], "warned": r[4]} for r in rows]}
    rows = con.execute(f"""
        SELECT l.datacenter, count(*) AS drives, count(*) FILTER (WHERE d.failed_on IS NOT NULL) AS failed,
               count(DISTINCT l.vault_id || '/' || l.pod_id) AS pods
        FROM {loc} l JOIN drives d USING (serial) GROUP BY 1 ORDER BY drives DESC
    """).fetchall()
    return {"level": "fleet", "datacenters": [{"datacenter": r[0], "drives": r[1], "failed": r[2], "pods": r[3]} for r in rows]}


# Each Backblaze datacenter stands in for one customer of the Precedent network (fictional names).
TENANTS = {"phx1": "Atlas GPU Cloud", "sac0": "Beacon Storage", "sac2": "Cedar Compute",
           "iad1": "Delta Colo", "ams5": "Ember AI", "yyz1": "Fjord Cloud"}


def tenant_of(con, serial: str):
    row = con.execute(f"SELECT datacenter FROM {_loc_sql()} WHERE serial = ?", [serial]).fetchone()
    return TENANTS.get(row[0]) if row else None


def precedent_scoped(con, model: str, pattern: str, tenant=None, exclude_serial=None) -> dict:
    """The network effect: this customer's own history vs the pooled Precedent network.
    tenant defaults to the tenant of exclude_serial's datacenter."""
    if tenant is None and exclude_serial:
        tenant = tenant_of(con, exclude_serial)
    dcs = [dc for dc, t in TENANTS.items() if t == tenant]
    ex = "AND w.serial <> ?" if exclude_serial else ""
    base = [model, pattern] + ([exclude_serial] if exclude_serial else [])
    by_dc = dict((r[0], (r[1], r[2])) for r in con.execute(f"""
        SELECT l.datacenter, count(*), count(*) FILTER (WHERE w.died)
        FROM warnings w JOIN {_loc_sql()} l USING (serial)
        WHERE NOT w.censored AND w.model = ? AND w.pattern = ? {ex} GROUP BY 1
    """, base).fetchall())
    n = sum(by_dc.get(dc, (0, 0))[0] for dc in dcs)
    died = sum(by_dc.get(dc, (0, 0))[1] for dc in dcs)
    rate = died / n if n else None
    own = {"model": model, "pattern": pattern, "scope": "your fleet", "n": n, "died": died, "rate": rate,
           "enough": n >= MIN_N, "act": bool(n >= MIN_N and rate is not None and rate >= MIN_RATE)}
    network = precedent(con, model, pattern, exclude_serial=exclude_serial)
    contributors = sorted({TENANTS.get(dc, dc) for dc, (cnt, _) in by_dc.items() if cnt})
    return {"tenant": tenant, "own": own, "network": {**network, "scope": "Precedent network"},
            "tenants_contributing": len(contributors), "contributors": contributors,
            "by_tenant": {TENANTS.get(dc, dc): {"n": c[0], "died": c[1]} for dc, c in by_dc.items()}}


def shift_date(d):
    """A fleet-record date as displayed (time-shifted so the record ends yesterday). Accepts date or ISO string."""
    if d is None or d == "":
        return d
    if isinstance(d, str):
        try:
            d = dt.date.fromisoformat(d[:10])
        except ValueError:
            return d
    return str(d + dt.timedelta(days=DATE_SHIFT_DAYS))


def _shift_rows(rows: list, keys: tuple, live_record_date=None) -> list:
    """Shift record dates for display. With live_record_date (a drive replayed as warning live today), that drive's
    own story is shifted so that record date lands on today."""
    days = None
    if live_record_date:
        days = (dt.date.today() - dt.date.fromisoformat(str(live_record_date)[:10])).days
    for r in rows:
        for k in keys:
            if k in r and r[k] not in (None, ""):
                if days is None:
                    r[k] = shift_date(r[k])
                else:
                    r[k] = str(dt.date.fromisoformat(str(r[k])[:10]) + dt.timedelta(days=days))
    return rows


_MATRIX_CACHE: dict = {}


def _act_patterns(con) -> set:
    rows = con.execute(f"""
        SELECT model, pattern FROM warnings WHERE NOT censored GROUP BY ALL
        HAVING count(*) >= {MIN_N} AND count(*) FILTER (died) / count(*) >= {MIN_RATE}
    """).fetchall()
    return {(m, p) for m, p in rows}


def fleet_matrix(con, datacenter: str, highlight_serial=None) -> dict:
    """One cell per drive for a whole datacenter, ordered vault > pod > slot.
    statuses: one char per drive: 0 healthy, 1 warned, 2 warned with an act-level pattern, 3 failed."""
    if datacenter not in _MATRIX_CACHE:
        rows = con.execute(f"""
            WITH last_warn AS (SELECT serial, arg_max(model, warn_date) AS model, arg_max(pattern, warn_date) AS pattern
                               FROM warnings GROUP BY serial)
            SELECT l.serial, l.vault_id, d.failed_on IS NOT NULL AS failed, w.model, w.pattern
            FROM {_loc_sql()} l JOIN drives d USING (serial) LEFT JOIN last_warn w USING (serial)
            WHERE l.datacenter = ? ORDER BY l.vault_id, l.pod_id, l.pod_slot_num
        """, [datacenter]).fetchall()
        act = _act_patterns(con)
        serials, chars, breaks, prev = [], [], [], None
        for i, (serial, vault, failed, model, pattern) in enumerate(rows):
            if vault != prev and i:
                breaks.append(i)
            prev = vault
            serials.append(serial)
            chars.append("3" if failed else "2" if (model, pattern) in act else "1" if pattern else "0")
        _MATRIX_CACHE[datacenter] = {"serials": serials, "statuses": "".join(chars), "vault_breaks": breaks}
    m = _MATRIX_CACHE[datacenter]
    n = len(m["serials"])
    counts = {k: m["statuses"].count(c) for k, c in (("healthy", "0"), ("warned", "1"), ("urgent", "2"), ("failed", "3"))}
    out = {"datacenter": datacenter, "n": n, "cols": max(60, int((n * 16 / 9) ** 0.5) // 60 * 60), "statuses": m["statuses"],
           "vault_breaks": m["vault_breaks"], "counts": counts}
    if highlight_serial and highlight_serial in m["serials"]:
        out["highlight_index"] = m["serials"].index(highlight_serial)
    return out


def fleet_cell(con, datacenter: str, i: int) -> dict:
    """The drive at matrix index i (lazy hover/click lookup)."""
    if datacenter not in _MATRIX_CACHE:
        fleet_matrix(con, datacenter)
    m = _MATRIX_CACHE[datacenter]
    if not 0 <= i < len(m["serials"]):
        return {}
    serial = m["serials"][i]
    d = con.execute(f"""SELECT d.serial, d.model, d.failed_on, l.vault_id, l.pod_id, l.pod_slot_num
                        FROM drives d JOIN {_loc_sql()} l USING (serial) WHERE d.serial = ?""", [serial]).fetchone()
    status = {"0": "healthy", "1": "warned", "2": "urgent", "3": "failed"}[m["statuses"][i]]
    return {"i": i, "serial": d[0], "model": d[1], "failed_on": str(d[2]) if d[2] else None,
            "vault_id": d[3], "pod_id": d[4], "slot": d[5], "status": status}


def handling_history(con, model: str, pattern: str, exclude_serial=None, limit: int = 8) -> dict:
    """How this exact warning went before: each earlier identical warning and its outcome from the fleet record.
    For a new pattern (no identical history) it falls back to the closest precedent and says so."""
    def rows_for(where: str, params: list):
        ex = "AND w.serial <> ?" if exclude_serial else ""
        q = con.execute(f"""
            SELECT w.warn_date, w.serial, w.model, w.pattern, w.died, w.censored, d.failed_on, d.last_seen
            FROM warnings w JOIN drives d USING (serial)
            WHERE {where} {ex} ORDER BY w.censored, w.warn_date DESC LIMIT {int(limit)}
        """, params + ([exclude_serial] if exclude_serial else [])).fetchall()
        out = []
        days = lambda n: f"{n} day" + ("" if n == 1 else "s")
        for wd, serial, m, p, died, censored, failed_on, last_seen in q:
            if died:
                outcome, handled = f"failed {days((failed_on - wd).days)} later", "Failed in service, then replaced"
            elif failed_on:
                outcome, handled = f"failed {days((failed_on - wd).days)} later (outside the 30-day window)", "Failed in service, then replaced"
            elif censored:
                outcome, handled = "outcome not known yet", "Kept in service, being watched"
            else:
                outcome, handled = f"still running {days((last_seen - wd).days)}+ later", "Kept in service"
            out.append({"warn_date": shift_date(wd), "serial": serial, "model": m, "pattern": p, "outcome": outcome,
                        "handled": handled, "died": bool(died), "source": "fleet record"})
        return out

    exact = rows_for("w.model = ? AND w.pattern = ?", [model, pattern])
    if exact:
        return {"exact": True, "basis": "same model, same warning", "rows": exact}
    attrs = pattern.split(":")[0]
    for basis, where, params in (
        ("same warning on other drive models", "w.pattern = ?", [pattern]),
        ("same model, same counters at another severity", "w.model = ? AND split_part(w.pattern, ':', 1) = ?", [model, attrs]),
        ("same counters on any model", "split_part(w.pattern, ':', 1) = ?", [attrs]),
    ):
        rows = rows_for(where, params)
        if rows:
            return {"exact": False, "basis": basis, "rows": rows}
    return {"exact": False, "basis": "no comparable history", "rows": []}


def drives_list(con, status=None, q=None, site=None, limit: int = 50, offset: int = 0) -> dict:
    """Paged drive table. status: urgent (latest warning has an act-level pattern) | warning | failed | healthy."""
    act = _act_patterns(con)
    con.execute("CREATE TEMP TABLE IF NOT EXISTS _act (model VARCHAR, pattern VARCHAR)")
    if not con.execute("SELECT count(*) FROM _act").fetchone()[0] and act:
        con.executemany("INSERT INTO _act VALUES (?, ?)", list(act))
    where, params = [], []
    if site:
        where.append("l.datacenter = ?"); params.append(site)
    if q:
        where.append("(d.serial ILIKE ? OR d.model ILIKE ?)"); params += [f"%{q}%", f"%{q}%"]
    st = """CASE WHEN d.failed_on IS NOT NULL THEN 'failed'
                 WHEN a.model IS NOT NULL THEN 'urgent'
                 WHEN w.pattern IS NOT NULL THEN 'warning' ELSE 'healthy' END"""
    if status:
        where.append(f"{st} = ?"); params.append(status)
    sql_where = ("WHERE " + " AND ".join(where)) if where else ""
    base = f"""
        FROM drives d LEFT JOIN {_loc_sql()} l USING (serial)
        LEFT JOIN (SELECT serial, arg_max(pattern, warn_date) AS pattern, max(warn_date) AS warn_date FROM warnings GROUP BY serial) w USING (serial)
        LEFT JOIN _act a ON a.model = d.model AND a.pattern = w.pattern
        LEFT JOIN (SELECT model, pattern, count(*) AS n, count(*) FILTER (died) AS died FROM warnings WHERE NOT censored GROUP BY ALL) h
               ON h.model = d.model AND h.pattern = w.pattern
        {sql_where}"""
    total = con.execute(f"SELECT count(*) {base}", params).fetchone()[0]
    rows = con.execute(f"""
        SELECT d.serial, d.model, l.datacenter, l.vault_id, l.pod_id, l.pod_slot_num, {st} AS status,
               w.warn_date, w.pattern, h.n, h.died, d.failed_on
        {base}
        ORDER BY CASE {st} WHEN 'urgent' THEN 0 WHEN 'failed' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END,
                 coalesce(d.failed_on, w.warn_date) DESC NULLS LAST, d.serial
        LIMIT {int(limit)} OFFSET {int(offset)}""", params).fetchall()
    keys = ["serial", "model", "datacenter", "vault_id", "pod_id", "slot", "status", "last_warn_date", "last_pattern", "n", "died", "failed_on"]
    return {"total": total, "rows": [{k: (shift_date(v) if k in ("last_warn_date", "failed_on") and v is not None else v)
                                      for k, v in zip(keys, r)} for r in rows]}


def drive_timeline(con, serial: str, until=None, live_record_date=None) -> list:
    """A drive's whole life from the fleet record: first seen, every SMART counter change, every warning with
    what history said at that moment, the failure, last seen. Oldest first."""
    names = {"s5": "reallocated sectors (5)", "s187": "reported uncorrectable (187)", "s188": "command timeouts (188)",
             "s197": "pending sectors (197)", "s198": "offline uncorrectable (198)"}
    d = con.execute("SELECT model, first_seen, last_seen, failed_on FROM drives WHERE serial = ?", [serial]).fetchone()
    if not d:
        return []
    model, first_seen, last_seen, failed_on = d
    out = [{"ts": str(first_seen), "kind": "first_seen", "text": f"First seen in the fleet ({model}).", "data": {}}]
    prev = {}
    for row in con.execute("SELECT date, s5, s187, s188, s197, s198 FROM daily WHERE serial = ? ORDER BY date", [serial]).fetchall():
        date, vals = row[0], dict(zip(names, row[1:]))
        changes = [(k, prev.get(k) or 0, v or 0) for k, v in vals.items() if (v or 0) != (prev.get(k) or 0)]
        if prev and changes:
            txt = "; ".join(f"{names[k]} {a} → {b}" for k, a, b in changes)
            out.append({"ts": str(date), "kind": "smart_change", "text": f"SMART: {txt}.", "data": {k: b for k, _, b in changes}})
        elif not prev and any(vals.values()):
            out.append({"ts": str(date), "kind": "smart_change",
                        "text": "SMART at first reading: " + "; ".join(f"{names[k]} {v}" for k, v in vals.items() if v) + ".", "data": vals})
        prev = vals
    for wd, pattern in con.execute("SELECT warn_date, pattern FROM warnings WHERE serial = ? ORDER BY warn_date", [serial]).fetchall():
        p = precedent(con, model, pattern, exclude_serial=serial)
        verdict = "urgent" if p["act"] else ("watch" if p["enough"] and (p["rate"] or 0) >= SWAPLIST_MIN_RATE else
                                             "harmless" if p["enough"] else "not enough history")
        out.append({"ts": str(wd), "kind": "warning",
                    "text": f"Warning {pattern}: {p['died']} of {p['n']} identical drives died within {HORIZON_DAYS} days → {verdict}.",
                    "data": {"pattern": pattern, "n": p["n"], "died": p["died"], "verdict": verdict}})
    if failed_on:
        first_warn = con.execute("SELECT min(warn_date) FROM warnings WHERE serial = ?", [serial]).fetchone()[0]
        lead = f", {(failed_on - first_warn).days} days after its first warning" if first_warn else " with no prior warning"
        out.append({"ts": str(failed_on), "kind": "failed", "text": f"Failed{lead}. Replaced (fleet record).", "data": {}})
    else:
        out.append({"ts": str(last_seen), "kind": "last_seen", "text": "Last reading in the fleet record.", "data": {}})
    order = {"first_seen": 0, "smart_change": 1, "warning": 2, "failed": 3, "last_seen": 4}
    out = sorted(out, key=lambda r: (r["ts"], order[r["kind"]]))
    until = until or live_record_date
    if until:  # stop the story at a record date (e.g. a drive replayed as warning today)
        out = [r for r in out if r["ts"] <= str(until)[:10]]
    return _shift_rows(out, ("ts",), live_record_date)


def swap_list(con, limit: int = 15, days: int = 7, min_n: int = 10, min_rate: float = 0.10):
    """Morning swap list: drives that warned in the last `days` days of data, ranked by their pattern's death rate."""
    return con.execute(f"""
        WITH hist AS (
          SELECT model, pattern, count(*) AS n, count(*) FILTER (died) AS died
          FROM warnings WHERE NOT censored GROUP BY ALL
        ), recent AS (
          SELECT serial, model, pattern, max(warn_date) AS warn_date, any_value(circular) AS circular FROM warnings
          WHERE warn_date > (SELECT max(warn_date) - {days} FROM warnings) GROUP BY ALL
        )
        SELECT r.serial, r.model, r.pattern, r.warn_date, h.n, h.died,
               round(h.died / h.n, 3) AS rate, r.circular
        FROM recent r JOIN hist h USING (model, pattern)
        WHERE h.n >= {min_n} AND h.died / h.n >= {min_rate}
        ORDER BY rate DESC, h.n DESC LIMIT {limit}
    """).df()


def top_patterns(con, limit: int = 25):
    return con.execute(f"""
        SELECT model, pattern, count(*) AS n, count(*) FILTER (died) AS died,
               round(count(*) FILTER (died) / count(*), 3) AS rate, any_value(circular) AS circular
        FROM warnings WHERE NOT censored
        GROUP BY ALL HAVING count(*) >= 10 ORDER BY died DESC LIMIT {limit}
    """).df()


def backtest(con, cutoff: str, min_n: int = MIN_N, min_rate: float = MIN_RATE, include_circular: bool = False) -> dict:
    """Rule learned from warnings whose outcome was known before cutoff; scored on warnings after it."""
    circ = "" if include_circular else "AND NOT circular"
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE train AS
        SELECT model, pattern, count(*) AS n, count(*) FILTER (died) AS died
        FROM warnings WHERE NOT censored AND warn_date + {HORIZON_DAYS} <= DATE '{cutoff}' {circ}
        GROUP BY ALL
    """)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE test AS
        SELECT w.*, t.n AS hist_n, t.died AS hist_died, t.died / t.n AS hist_rate,
               coalesce(t.n >= {min_n} AND t.died / t.n >= {min_rate}, false) AS alert
        FROM warnings w LEFT JOIN train t USING (model, pattern)
        WHERE NOT w.censored AND w.warn_date >= DATE '{cutoff}' {circ.replace('circular', 'w.circular')}
    """)
    N, L, M, K = con.execute("""
        SELECT count(*), count(*) FILTER (died), count(*) FILTER (alert), count(*) FILTER (alert AND died) FROM test
    """).fetchone()
    calib = con.execute("""
        SELECT floor(hist_rate * 10) / 10 AS bucket, count(*) AS n, round(avg(died::INT), 3) AS actual
        FROM test WHERE hist_n >= 10 GROUP BY 1 ORDER BY 1
    """).df()
    return {"cutoff": cutoff, "min_n": min_n, "min_rate": min_rate,
            "N_checks_today": N, "L_failures": L, "M_checks_precedent": M, "K_caught": K,
            "calibration": calib.to_dict("records")}


def default_cutoff(con) -> str:
    lo, hi = con.execute("SELECT min(warn_date), max(warn_date) FROM warnings").fetchone()
    return str(lo + (hi - lo) * 6 // 10)


def tune(con, cutoff: str):
    """Pick (min_n, min_rate) on the train window only: split train in half again."""
    lo = con.execute("SELECT min(warn_date) FROM warnings").fetchone()[0]
    c = dt.date.fromisoformat(cutoff)
    inner = str(lo + (c - lo) // 2)
    best = None
    for n in (10, 15, 20, 30):
        for r in (0.1, 0.15, 0.2, 0.3, 0.5):
            b = backtest(con, inner, n, r)
            if b["L_failures"] == 0 or b["M_checks_precedent"] == 0:
                continue
            precision = b["K_caught"] / b["M_checks_precedent"]
            recall = b["K_caught"] / b["L_failures"]
            score = 2 * precision * recall / (precision + recall) if precision + recall else 0
            if best is None or score > best[0]:
                best = (score, n, r)
    return best


if __name__ == "__main__":
    con = connect()
    build(con)
    print(con.execute("SELECT count(*) AS days_rows FROM daily").fetchone(),
          con.execute("SELECT count(*) AS warnings, count(*) FILTER (died) AS died FROM warnings WHERE NOT censored").fetchone())
    print(top_patterns(con).to_string())
    cut = default_cutoff(con)
    print("tuned (f1, min_n, min_rate):", tune(con, cut))
    print(backtest(con, cut))
