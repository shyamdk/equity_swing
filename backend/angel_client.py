"""Angel One SmartAPI wrapper: authentication, instrument master, and OHLCV data."""
import threading
import time
from datetime import datetime, timedelta

import pyotp
import requests
import pandas as pd
from loguru import logger
from SmartApi import SmartConnect

from src.config import (
    ANGEL_API_KEY,
    ANGEL_CLIENT_ID,
    ANGEL_PIN,
    ANGEL_TOTP_SECRET,
    SCRIP_MASTER_URL,
    API_RATE_PER_SECOND,
    API_MAX_RETRIES,
    API_RETRY_WAIT,
)

_RATE_LIMIT_PHRASES = ("access denied", "access rate", "exceeding")

# ---------------------------------------------------------------------------
# Shared thread-safe rate limiter
# Ensures all worker threads combined never exceed API_RATE_PER_SECOND.
# ---------------------------------------------------------------------------
_rate_lock  = threading.Lock()
_last_call  = 0.0
_min_gap    = 1.0 / API_RATE_PER_SECOND   # seconds between consecutive API calls


def _throttle() -> None:
    """Block the calling thread until it is safe to make the next API call."""
    global _last_call
    with _rate_lock:
        now  = time.monotonic()
        wait = _min_gap - (now - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def _is_rate_limit(msg: str) -> bool:
    m = msg.lower()
    return any(p in m for p in _RATE_LIMIT_PHRASES)


class AngelClient:
    """Thin wrapper around SmartConnect for authentication and historical data."""

    def __init__(self):
        self._api: SmartConnect | None = None
        self._session_token: str | None = None
        self._token_map: dict[str, str] | None = None

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def login(self) -> None:
        if not ANGEL_API_KEY:
            raise RuntimeError("ANGEL_API_KEY is not set. Please fill in your .env file.")
        for attempt in range(1, API_MAX_RETRIES + 1):
            try:
                totp = pyotp.TOTP(ANGEL_TOTP_SECRET).now()
                self._api = SmartConnect(api_key=ANGEL_API_KEY)
                data = self._api.generateSession(ANGEL_CLIENT_ID, ANGEL_PIN, totp)
            except Exception as e:
                if _is_rate_limit(str(e)) and attempt < API_MAX_RETRIES:
                    wait = API_RETRY_WAIT * attempt
                    logger.warning(f"Rate limit on login (attempt {attempt}/{API_MAX_RETRIES}), waiting {wait:.0f}s…")
                    time.sleep(wait)
                    continue
                raise
            if not data.get("status"):
                raise RuntimeError(f"Angel One login failed: {data.get('message')}")
            self._session_token = data["data"]["jwtToken"]
            logger.info(f"Logged in to Angel One as {ANGEL_CLIENT_ID}")
            return
        raise RuntimeError("Angel One login failed: rate limit retries exhausted")

    def _ensure_logged_in(self) -> None:
        if self._api is None or self._session_token is None:
            self.login()

    # ------------------------------------------------------------------
    # Instrument master (symbol → token)
    # ------------------------------------------------------------------

    def load_instrument_master(self) -> None:
        logger.info("Downloading instrument master...")
        resp = requests.get(SCRIP_MASTER_URL, timeout=30)
        resp.raise_for_status()
        instruments = resp.json()
        self._token_map = {}
        for item in instruments:
            if item.get("exch_seg") == "NSE" and item.get("symbol", "").endswith("-EQ"):
                clean = item["symbol"].replace("-EQ", "")
                self._token_map[clean] = item["token"]
        logger.info(f"Loaded {len(self._token_map)} NSE equity tokens")

    def get_token(self, symbol: str) -> str | None:
        if self._token_map is None:
            self.load_instrument_master()
        return self._token_map.get(symbol)

    # ------------------------------------------------------------------
    # Historical OHLCV
    # ------------------------------------------------------------------

    def get_candles(
        self,
        symbol: str,
        interval: str,
        from_date: datetime,
        to_date: datetime,
    ) -> pd.DataFrame:
        self._ensure_logged_in()
        token = self.get_token(symbol)
        if token is None:
            logger.warning(f"No token found for {symbol}, skipping")
            return pd.DataFrame()

        from_str = from_date.strftime("%Y-%m-%d %H:%M")
        to_str   = to_date.strftime("%Y-%m-%d %H:%M")

        rate_limit_attempts = 0

        while rate_limit_attempts < API_MAX_RETRIES:
            # --- Throttle BEFORE the call so all workers share the limit correctly ---
            _throttle()

            # --- Call API ---
            try:
                resp = self._api.getCandleData({
                    "exchange": "NSE",
                    "symboltoken": token,
                    "interval": interval,
                    "fromdate": from_str,
                    "todate": to_str,
                })
            except Exception as e:
                # SmartAPI library raises when it can't parse the response (e.g. rate-limit
                # responses are plain text, not JSON → JSONDecodeError / KeyError).
                # Check if the underlying cause is a rate limit and retry if so.
                if _is_rate_limit(str(e)):
                    rate_limit_attempts += 1
                    wait = API_RETRY_WAIT * rate_limit_attempts
                    logger.warning(
                        f"Rate limit (parse error) for {symbol} {interval} "
                        f"(attempt {rate_limit_attempts}/{API_MAX_RETRIES}), "
                        f"waiting {wait:.0f}s…"
                    )
                    time.sleep(wait)
                    continue
                # Any other library error — no point retrying, skip this call.
                logger.warning(f"Skipping {symbol} {interval}: library error — {e}")
                return pd.DataFrame()

            # --- Inspect response ---
            if not resp:
                logger.warning(f"Null response for {symbol} {interval}, skipping")
                return pd.DataFrame()

            msg = str(resp.get("message", ""))

            # Rate limit → wait and retry
            if _is_rate_limit(msg):
                rate_limit_attempts += 1
                wait = API_RETRY_WAIT * rate_limit_attempts
                logger.warning(
                    f"Rate limit for {symbol} {interval} "
                    f"(attempt {rate_limit_attempts}/{API_MAX_RETRIES}), "
                    f"waiting {wait:.0f}s..."
                )
                time.sleep(wait)
                continue

            # No data (symbol not available for this interval / date range) → skip
            if not resp.get("status") or not resp.get("data"):
                logger.debug(f"No data for {symbol} {interval}: {msg}")
                return pd.DataFrame()

            # --- Parse successful response ---
            data = resp["data"]
            df = pd.DataFrame(
                data, columns=["timestamp", "open", "high", "low", "close", "volume"]
            )
            # Normalize to naive IST — fixes "Unknown" staleness labels
            df["timestamp"] = (
                pd.to_datetime(df["timestamp"], utc=True)
                .dt.tz_convert("Asia/Kolkata")
                .dt.tz_localize(None)
            )
            for col in ["open", "high", "low", "close"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce").astype("Int64")
            df["symbol"] = symbol
            return df

        logger.error(f"Rate limit retries exhausted for {symbol} {interval}")
        return pd.DataFrame()

    def get_candles_chunked(
        self,
        symbol: str,
        interval: str,
        from_date: datetime,
        to_date: datetime,
        chunk_days: int = 60,
    ) -> pd.DataFrame:
        """Fetch in date chunks (Angel One limits intraday to ~60 days/request)."""
        all_frames = []
        current = from_date
        while current < to_date:
            chunk_end = min(current + timedelta(days=chunk_days), to_date)
            df = self.get_candles(symbol, interval, current, chunk_end)
            if not df.empty:
                all_frames.append(df)
            current = chunk_end + timedelta(minutes=1)

        if not all_frames:
            return pd.DataFrame()

        combined = pd.concat(all_frames, ignore_index=True)
        combined.drop_duplicates(subset=["symbol", "timestamp"], inplace=True)
        combined.sort_values("timestamp", inplace=True)
        combined.reset_index(drop=True, inplace=True)
        return combined
