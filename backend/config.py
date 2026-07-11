"""Configuration: loads env vars and defines constants."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
ROOT_DIR = Path(__file__).parent.parent
load_dotenv(ROOT_DIR / ".env")

# --- Angel One credentials ---
ANGEL_API_KEY = os.getenv("ANGEL_API_KEY", "")
ANGEL_CLIENT_ID = os.getenv("ANGEL_CLIENT_ID", "")
ANGEL_PIN = os.getenv("ANGEL_PIN", "")
ANGEL_TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET", "")

# --- Database (Postgres + TimescaleDB) ---
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://equity:equity_local_pw@localhost:5432/equity_swing",
)
# Legacy SQLite path — kept only for the one-time daily/weekly migration.
SQLITE_PATH = ROOT_DIR / os.getenv("SQLITE_PATH", "data/equity_swing.db")
# Back-compat alias (some legacy modules still import DB_PATH).
DB_PATH = SQLITE_PATH

# --- Universe (Nifty 500) ---
# ind_nifty500list.csv has columns: Company Name, Industry, Symbol, Series, ISIN Code.
# `Industry` is the sector used by Q2.5 sector rotation.
NIFTY500_CSV = ROOT_DIR / "ind_nifty500list.csv"
# Full NSE EQ master (fallback / reference only).
SYMBOL_CSV = ROOT_DIR / "EQUITY_L.csv"
# Timezone all naive candle timestamps are expressed in.
MARKET_TZ = "Asia/Kolkata"

# --- Instrument master (Angel One public file) ---
SCRIP_MASTER_URL = (
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
)

# --- Intervals ---
ANGEL_INTERVALS = {
    "5min": "FIVE_MINUTE",
    "1day": "ONE_DAY",
    "1week": "ONE_WEEK",
}

RESAMPLE_RULES = {
    "75min": "75min",
    "125min": "125min",
}

ALL_INTERVALS = ["5min", "75min", "125min", "1day", "1week"]
INTRADAY_INTERVALS = ["5min", "75min", "125min"]

# --- Ingestion rate limiting ---
# Angel One historical API limit: ~1 req/sec per session.
# Using 0.5 req/s (1 call every 2s) gives a safe margin even with 3 parallel workers.
# The throttle is applied BEFORE each API call so all workers share the limit correctly.
API_RATE_PER_SECOND = 1.0    # max requests per second (shared across all workers)
API_RETRY_WAIT      = 15.0   # seconds to wait before each retry on rate-limit error
API_MAX_RETRIES     = 5      # max retry attempts per API call
API_MAX_WORKERS     = 3      # parallel ingestion threads

# Keep for backwards compatibility (used nowhere critical now)
API_DELAY_SECONDS   = 1.0 / API_RATE_PER_SECOND

# --- Notifications ---
# Push: install free ntfy app → subscribe to your topic (e.g. "equity-swing-yourname")
NTFY_TOPIC      = os.getenv("NTFY_TOPIC", "")
# Email: use a Gmail App Password (Google Account → Security → App Passwords)
SMTP_USER       = os.getenv("SMTP_USER", "")
SMTP_PASSWORD   = os.getenv("SMTP_PASSWORD", "")
NOTIFY_EMAIL    = os.getenv("NOTIFY_EMAIL", "shyamdk@gmail.com")

# --- Ingestion history ---
INITIAL_LOOKBACK_DAYS          = 100   # days of history for intraday intervals (5min)
INITIAL_LOOKBACK_DAYS_DAILY    = 730   # days of history for 1day (2 years → ~100 weekly candles)

# NSE market session start (IST)
MARKET_OPEN_TIME = "09:15"
