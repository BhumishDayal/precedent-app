import datetime as dt
import os

from dotenv import load_dotenv

load_dotenv()

# A blank var in .env (HORIZON_DAYS=) reads as "", not as unset, so non-empty defaults use `or`.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
DAILY_DIR = os.path.join(DATA, "daily")          # one parquet per day
DB_PATH = os.path.join(DATA, "precedent.duckdb")
STATE_DIR = os.getenv("PRECEDENT_STATE_DIR") or DATA  # alerts, decisions and the ops DB; smoke test points it elsewhere
DECISIONS_PATH = os.path.join(STATE_DIR, "decisions.jsonl")

SMART_ATTRS = [5, 187, 188, 197, 198]
CIRCULAR_ATTRS = {187}   # Backblaze replaces drives once 187 > 0, so 187 -> "failure" is partly self-fulfilling

HORIZON_DAYS = int(os.getenv("HORIZON_DAYS") or 30)
MIN_N = int(os.getenv("MIN_N") or 15)
MIN_RATE = float(os.getenv("MIN_RATE") or 0.25)
SWAPLIST_MIN_N = int(os.getenv("SWAPLIST_MIN_N") or 10)
SWAPLIST_MIN_RATE = float(os.getenv("SWAPLIST_MIN_RATE") or 0.10)
ACK_SECONDS = int(os.getenv("ACK_SECONDS") or os.getenv("ESCALATE_SECONDS") or 300)  # unanswered page -> escalate

ONCALL_NAME = os.getenv("ONCALL_NAME") or "On-call engineer"
TECH_NAME = os.getenv("TECH_NAME") or "Technician"

DIAL_API_KEY = os.getenv("DIAL_API_KEY", "")
DIAL_API_BASE = os.getenv("DIAL_API_BASE") or "https://api.getdial.ai/api/v1"
DIAL_FROM_NUMBER_ID = os.getenv("DIAL_FROM_NUMBER_ID", "")  # pn_... from `dial number list`
DIAL_FROM = os.getenv("DIAL_FROM") or DIAL_FROM_NUMBER_ID   # older name; dial.py falls back to it
ONCALL_PHONE = os.getenv("ONCALL_PHONE", "")       # on-call phone, E.164
KEEWANO_PAT = os.getenv("KEEWANO_PAT", "")                  # kwpat-... for MCP / SQL
KEEWANO_INGEST_KEY = os.getenv("KEEWANO_INGEST_KEY", "")    # project API key for ingest
KEEWANO_PROJECT_ID = os.getenv("KEEWANO_PROJECT_ID", "")
DARWIN_API_KEY = os.getenv("DARWIN_API_KEY", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "")           # public tunnel URL that Dial webhooks reach

# The Backblaze record (Jan 1 - Jun 30 2026) is displayed shifted so it ends yesterday. Counts are unchanged,
# only the shown dates move. DATE_SHIFT_DAYS=0 turns it off.
RECORD_END = dt.date(2026, 6, 30)
DATE_SHIFT_DAYS = int(os.getenv("DATE_SHIFT_DAYS") or (dt.date.today() - dt.timedelta(days=1) - RECORD_END).days)
