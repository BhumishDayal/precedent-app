"""Dial Context MCP: lets the voice agent answer "which drives are like this?" during a call.

One tool, similar_drives(serial): the five most recent identical drives (same model + pattern) with outcomes.
It answers only for drives in alerts.jsonl whose phone matches Dial's X-Dial-User-Number header,
so a caller can only ask about alerts sent to them. Mounted by server.py at /mcp/ (streamable HTTP).
Dial must reach it over public HTTPS (tunnel), then: python -m precedent.dial register-context-mcp <public_url>
"""
import json

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from precedent import decisions, engine
from precedent.config import HORIZON_DAYS

mcp = MCPServer("Precedent")


def recent_like(alert: dict, limit: int = 5) -> list[dict]:
    con = engine.connect(read_only=True)
    try:
        rows = con.execute(f"""
            SELECT serial, warn_date, died, failed_on FROM warnings
            WHERE NOT censored AND serial <> ? AND model = ? AND pattern = ?
            ORDER BY warn_date DESC LIMIT {int(limit)}
        """, [alert["serial"], alert["model"], alert["pattern"]]).fetchall()
    finally:
        con.close()
    sd = engine.shift_date  # fleet-record dates are displayed time-shifted (record ends yesterday)
    return [{"serial": s, "warned": str(sd(w)), "outcome": f"died {sd(f)}" if d else f"alive {HORIZON_DAYS} days later"}
            for s, w, d, f in rows]


def _alert_for(serial: str, phone: str | None) -> dict | None:
    alerts = [a for a in decisions._read(decisions.ALERTS_PATH)
              if a["phone"] == phone and a["serial"].upper().endswith(serial.strip().upper())]
    return alerts[-1] if alerts else None


@mcp.tool()
def similar_drives(serial: str, ctx: Context) -> str:
    """Five most recent identical drives (same model and SMART warning pattern) as the alerted drive, with
    whether each one died. `serial` may be the full serial or its last 4 characters."""
    phone = (ctx.headers or {}).get("x-dial-user-number")
    alert = _alert_for(serial, phone)
    if alert is None:
        return "No drive alert with that serial was sent to this phone number."
    rows = recent_like(alert)
    died = sum(r["outcome"].startswith("died") for r in rows)
    return json.dumps({"drive": alert["serial"], "model": alert["model"], "history": f"{alert['died']} of {alert['n']} died",
                       "recent_similar": rows, "summary": f"{died} of the last {len(rows)} identical drives died."})


def asgi_app():
    """Streamable-HTTP app for mounting; stateless + JSON so each Dial request stands alone.
    DNS-rebinding protection is off because requests arrive via the tunnel's Host header."""
    return mcp.streamable_http_app(streamable_http_path="/", stateless_http=True, json_response=True,
                                   transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
