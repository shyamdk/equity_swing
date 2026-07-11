"""
Data ingestion orchestrator.

Flow per symbol:
  1. Look up Angel One instrument token
  2. Determine date range (first-run: 100 days; delta: since last ingestion)
  3. Fetch 5-min candles → resample to 75-min and 125-min
  4. Fetch 1-day and 1-week candles directly
  5. Calculate indicators for each interval
  6. Upsert into SQLite, update ingestion state
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, date
from typing import Callable

import pandas as pd
from loguru import logger

from backend.config import (
    INITIAL_LOOKBACK_DAYS,
    INITIAL_LOOKBACK_DAYS_DAILY,
    ANGEL_INTERVALS,
    RESAMPLE_RULES,
    ALL_INTERVALS,
    INTRADAY_INTERVALS,
    NIFTY500_CSV,
    API_MAX_WORKERS,
)
from backend.angel_client import AngelClient
from backend.database import (
    init_db,
    upsert_ohlcv,
    get_last_ingested_at,
    set_last_ingested_at,
    get_latest_candles,
)
from backend.db import read_sql
from backend.indicators import calculate_indicators


# ---------------------------------------------------------------------------
# Symbol loader
# ---------------------------------------------------------------------------

def load_symbols() -> list[str]:
    """Read the Nifty 500 universe (EQ series) from ind_nifty500list.csv."""
    df = pd.read_csv(NIFTY500_CSV)
    df.columns = df.columns.str.strip()
    df = df[df["Series"].str.strip() == "EQ"]
    symbols = df["Symbol"].dropna().str.strip().tolist()
    logger.info(f"Loaded {len(symbols)} symbols from {NIFTY500_CSV.name}")
    return symbols


# ---------------------------------------------------------------------------
# Resampling helpers
# ---------------------------------------------------------------------------

def _resample_daily_to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Resample daily OHLCV to weekly candles (week ending Friday, NSE convention).

    Uses the last N daily candles already stored in the DB — no extra API call needed.
    INSERT OR REPLACE semantics in upsert mean partial weeks are overwritten correctly
    each time ingestion runs.
    """
    if df.empty:
        return df
    df = df.copy()
    df = df.set_index("timestamp").sort_index()
    df.index = pd.DatetimeIndex(df.index)
    resampled = (
        df.resample("W-FRI")
        .agg({"open": "first", "high": "max", "low": "min",
              "close": "last", "volume": "sum", "symbol": "first"})
        .dropna(subset=["open"])
        .reset_index()
    )
    return resampled


def _resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """
    Resample a 5-min OHLCV DataFrame to the given pandas offset rule.
    Market open is 09:15 IST; we anchor the first bar to 09:15.
    """
    if df.empty:
        return df

    df = df.copy()
    df = df.set_index("timestamp").sort_index()
    df.index = pd.DatetimeIndex(df.index)

    # Resample with market-open offset so bars start at 09:15
    offset = pd.tseries.frequencies.to_offset(rule)
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
        "symbol": "first",
    }
    resampled = (
        df.resample(offset, offset="9h15min")
        .agg(agg)
        .dropna(subset=["open"])
        .reset_index()
    )
    resampled.rename(columns={"index": "timestamp"}, inplace=True)
    return resampled


# ---------------------------------------------------------------------------
# Up-to-date check helpers
# ---------------------------------------------------------------------------

def _last_trading_day() -> date:
    """Return the most recent weekday (Mon–Fri). Ignores public holidays."""
    d = datetime.now().date()
    while d.weekday() >= 5:          # 5=Sat, 6=Sun
        d -= timedelta(days=1)
    return d


def _is_symbol_current(symbol: str) -> bool:
    """Return True if 1-day data is already ingested up to the last trading day.

    Skipping current symbols is the single biggest speed-up for daily delta runs:
    a symbol already at Mar-20 on a Mar-21 run will be skipped instantly.
    """
    last = get_last_ingested_at(symbol, "1day")
    if not last:
        return False
    try:
        return datetime.fromisoformat(last).date() >= _last_trading_day()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Per-interval date range
# ---------------------------------------------------------------------------

def _date_range(symbol: str, interval: str) -> tuple[datetime, datetime]:
    """Return (from_date, to_date) for a symbol/interval pair.

    Intraday intervals (5min, 75min, 125min) use a shorter lookback to avoid
    bloating the DB with years of high-frequency data.
    Daily uses a longer lookback (2 years) so weekly indicators have enough history.
    """
    to_date = datetime.now()
    last = get_last_ingested_at(symbol, interval)
    if last is None:
        lookback = (
            INITIAL_LOOKBACK_DAYS
            if interval in INTRADAY_INTERVALS
            else INITIAL_LOOKBACK_DAYS_DAILY
        )
        from_date = to_date - timedelta(days=lookback)
    else:
        from_date = datetime.fromisoformat(last) + timedelta(minutes=1)
    return from_date, to_date


# ---------------------------------------------------------------------------
# Core ingestion
# ---------------------------------------------------------------------------

def _process_and_store(
    symbol: str,
    interval: str,
    df: pd.DataFrame,
    is_intraday: bool,
) -> None:
    """Calculate indicators and upsert a DataFrame for one (symbol, interval)."""
    if df.empty:
        return
    df["symbol"] = symbol
    df = calculate_indicators(df, is_intraday=is_intraday)
    df["timestamp"] = pd.to_datetime(df["timestamp"])   # naive IST; upsert localizes
    count = upsert_ohlcv(interval, df)
    if count > 0:
        latest = pd.Timestamp(df["timestamp"].max()).strftime("%Y-%m-%dT%H:%M:%S")
        set_last_ingested_at(symbol, interval, latest)
        logger.debug(f"{symbol} [{interval}] → {count} rows, latest={latest}")


def ingest_symbol(symbol: str, client: AngelClient, dry_run: bool = False) -> dict:
    """
    Ingest all intervals for one symbol.
    Returns a summary dict with counts per interval.
    """
    summary = {interval: 0 for interval in ALL_INTERVALS}

    # --- 5-min fetch (used for 75-min and 125-min resampling) ---
    from_5, to_5 = _date_range(symbol, "5min")
    df_5min = client.get_candles_chunked(symbol, "FIVE_MINUTE", from_5, to_5, chunk_days=55)

    # --- 5-min storage ---
    if not dry_run:
        _process_and_store(symbol, "5min", df_5min.copy(), is_intraday=True)
        summary["5min"] = len(df_5min)

    # --- 75-min resample ---
    df_75 = _resample_ohlcv(df_5min.copy(), "75min")
    if not dry_run:
        _process_and_store(symbol, "75min", df_75, is_intraday=True)
        summary["75min"] = len(df_75)

    # --- 125-min resample ---
    df_125 = _resample_ohlcv(df_5min.copy(), "125min")
    if not dry_run:
        _process_and_store(symbol, "125min", df_125, is_intraday=True)
        summary["125min"] = len(df_125)

    # --- 1-day ---
    from_1d, to_1d = _date_range(symbol, "1day")
    df_1d = client.get_candles_chunked(symbol, "ONE_DAY", from_1d, to_1d, chunk_days=100)
    if not dry_run:
        _process_and_store(symbol, "1day", df_1d, is_intraday=False)
        summary["1day"] = len(df_1d)

    # --- 1-week (resampled from 1-day stored in DB) ---
    # Read the last 60 daily candles from DB (already includes the candles stored above).
    # Resampling from DB avoids an extra API call and guarantees correct full-week OHLCV
    # even on delta runs (INSERT OR REPLACE handles partial weeks automatically).
    if not dry_run:
        df_1d_db = get_latest_candles(symbol, "1day", n=60)
        if not df_1d_db.empty:
            df_1d_db["symbol"] = symbol
            df_1w = _resample_daily_to_weekly(df_1d_db)
            _process_and_store(symbol, "1week", df_1w, is_intraday=False)
            summary["1week"] = len(df_1w)

    return summary


# ---------------------------------------------------------------------------
# Client pool — one AngelClient per worker thread
# ---------------------------------------------------------------------------

def _build_client_pool(size: int) -> list[AngelClient]:
    """Login `size` independent AngelClient instances sharing one token map.

    Sharing the token map avoids downloading the ~3 MB scrip master JSON N times.
    The map is read-only after loading so sharing across threads is safe.
    """
    primary = AngelClient()
    primary.login()
    primary.load_instrument_master()
    shared_map = primary._token_map

    pool = [primary]
    for _ in range(size - 1):
        time.sleep(3)          # stagger logins — rapid successive sessions trigger rate limit
        c = AngelClient()
        c.login()
        c._token_map = shared_map      # read-only share
        pool.append(c)

    logger.info(f"Client pool ready ({size} sessions)")
    return pool


# ---------------------------------------------------------------------------
# Parallel runner core
# ---------------------------------------------------------------------------

_progress_lock = threading.Lock()


def _run_parallel(
    symbols: list[str],
    client_pool: list[AngelClient],
    dry_run: bool,
    progress_callback: Callable[[int, int, str], None] | None,
    label: str,
) -> None:
    """Process `symbols` in parallel using the given client pool."""
    total     = len(symbols)
    counter   = [0]            # mutable int shared across threads
    n_workers = len(client_pool)

    # Assign each worker thread a fixed client from the pool
    _local = threading.local()
    pool_cycle = list(enumerate(client_pool))   # [(0, c0), (1, c1), ...]

    def _worker(symbol: str) -> tuple[str, dict]:
        # Lazily assign a client to this thread (round-robin by thread id)
        if not hasattr(_local, "client"):
            idx = hash(threading.current_thread().name) % n_workers
            _local.client = client_pool[idx]
        return symbol, ingest_symbol(symbol, _local.client, dry_run=dry_run)

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = {pool.submit(_worker, sym): sym for sym in symbols}
        for future in as_completed(futures):
            sym = futures[future]
            with _progress_lock:
                counter[0] += 1
                idx = counter[0]
            if progress_callback:
                progress_callback(idx, total, sym)
            try:
                _, summary = future.result()
                logger.info(f"[{idx}/{total}] {sym}: {summary}")
            except Exception as e:
                logger.error(f"[{idx}/{total}] {sym} failed: {e}")

    logger.success(f"{label} complete — {total} symbols processed.")


# ---------------------------------------------------------------------------
# Public runners
# ---------------------------------------------------------------------------

def run(
    dry_run: bool = False,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> None:
    """Run the full ingestion pipeline with parallel workers.

    Skips symbols whose 1-day data is already up to the last trading day —
    on a daily delta run this eliminates the bulk of the work instantly.
    """
    if not dry_run:
        init_db()

    all_symbols = load_symbols()

    if dry_run:
        logger.info("DRY RUN — validating API access for first 5 symbols")
        symbols = all_symbols[:5]
    else:
        # Skip symbols already current — biggest speed-up on repeated daily runs
        symbols = [s for s in all_symbols if not _is_symbol_current(s)]
        skipped = len(all_symbols) - len(symbols)
        if skipped:
            logger.info(f"Skipping {skipped} already-current symbols — {len(symbols)} to ingest")

    if not symbols:
        logger.success("All symbols are already up to date. Nothing to do.")
        if progress_callback:
            progress_callback(0, 0, "")
        return

    workers = 1 if dry_run else API_MAX_WORKERS
    pool    = _build_client_pool(workers)
    _run_parallel(symbols, pool, dry_run, progress_callback, "Ingestion")


def run_selective(
    symbols: list[str],
    dry_run: bool = False,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> None:
    """Re-ingest a specific list of symbols (e.g. stale stocks) with parallel workers."""
    if not symbols:
        logger.info("run_selective: no symbols provided, nothing to do.")
        return

    if not dry_run:
        init_db()

    workers = API_MAX_WORKERS
    pool    = _build_client_pool(workers)
    _run_parallel(symbols, pool, dry_run, progress_callback, "Selective ingestion")


def backfill_weekly(
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> int:
    """Generate 1-week candles for every symbol that has 1-day data in the DB.

    Pure DB operation — no API calls. Reads the last 200 daily candles per symbol,
    resamples to weekly (W-FRI), and upserts into ohlcv_1week.

    Returns the total number of weekly candles written.
    """
    symbols = read_sql(
        "SELECT DISTINCT symbol FROM ohlcv WHERE interval = '1day' ORDER BY symbol"
    )["symbol"].tolist()

    total = len(symbols)
    written = 0
    logger.info(f"Backfilling 1-week candles for {total} symbols…")

    for idx, symbol in enumerate(symbols, 1):
        if progress_callback:
            progress_callback(idx, total, symbol)
        try:
            df_1d = get_latest_candles(symbol, "1day", n=200)
            if df_1d.empty:
                continue
            df_1d["symbol"] = symbol
            df_1w = _resample_daily_to_weekly(df_1d)
            if df_1w.empty:
                continue
            _process_and_store(symbol, "1week", df_1w, is_intraday=False)
            written += len(df_1w)
        except Exception as e:
            logger.error(f"Backfill failed for {symbol}: {e}")

    logger.success(f"Weekly backfill complete — {written} candles across {total} symbols.")
    return written
