"""SQLite database: schema creation, upsert, and ingestion-state management."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

import numpy as np
import pandas as pd
from loguru import logger

from src.config import DB_PATH, ALL_INTERVALS, INTRADAY_INTERVALS


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_CREATE_OHLCV_TABLE = """
CREATE TABLE IF NOT EXISTS ohlcv_{interval} (
    symbol       TEXT NOT NULL,
    timestamp    TEXT NOT NULL,
    open         REAL,
    high         REAL,
    low          REAL,
    close        REAL,
    volume       INTEGER,
    rsi          REAL,
    cci          REAL,
    macd         REAL,
    macd_signal  REAL,
    macd_hist    REAL,
    bb_upper     REAL,
    bb_middle    REAL,
    bb_lower     REAL,
    ema_20       REAL,
    ema_50       REAL,
    ema_200      REAL,
    atr          REAL,
    vwap         REAL,
    PRIMARY KEY (symbol, timestamp)
);
"""

_CREATE_INGESTION_STATE = """
CREATE TABLE IF NOT EXISTS ingestion_state (
    symbol           TEXT NOT NULL,
    interval         TEXT NOT NULL,
    last_ingested_at TEXT,
    PRIMARY KEY (symbol, interval)
);
"""


def init_db(db_path: Path = DB_PATH) -> None:
    """Create all required tables if they don't exist."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        for interval in ALL_INTERVALS:
            conn.execute(_CREATE_OHLCV_TABLE.format(interval=interval))
        conn.execute(_CREATE_INGESTION_STATE)
        conn.commit()
    logger.info(f"Database initialised at {db_path}")


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

@contextmanager
def connect(db_path: Path = DB_PATH) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Upsert helpers
# ---------------------------------------------------------------------------

def upsert_ohlcv(interval: str, df: pd.DataFrame, db_path: Path = DB_PATH) -> int:
    """
    Insert or replace rows from `df` into ohlcv_{interval}.

    Required columns: symbol, timestamp, open, high, low, close, volume.
    Indicator columns are optional (NaN → NULL).

    Returns the number of rows written.
    """
    if df.empty:
        return 0

    table = f"ohlcv_{interval}"
    cols = [
        "symbol", "timestamp", "open", "high", "low", "close", "volume",
        "rsi", "cci", "macd", "macd_signal", "macd_hist",
        "bb_upper", "bb_middle", "bb_lower",
        "ema_20", "ema_50", "ema_200", "atr", "vwap",
    ]
    # Add missing columns as None
    for col in cols:
        if col not in df.columns:
            df[col] = None

    # Strip VWAP for non-intraday
    if interval not in INTRADAY_INTERVALS:
        df["vwap"] = None

    rows = df[cols].where(pd.notnull(df[cols]), None).values.tolist()
    placeholders = ", ".join(["?"] * len(cols))
    sql = f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"

    with connect(db_path) as conn:
        conn.executemany(sql, rows)
        conn.commit()

    logger.debug(f"Upserted {len(rows)} rows into {table}")
    return len(rows)


# ---------------------------------------------------------------------------
# Ingestion state
# ---------------------------------------------------------------------------

def get_last_ingested_at(symbol: str, interval: str, db_path: Path = DB_PATH) -> str | None:
    """Return ISO8601 timestamp of the last ingested candle, or None on first run."""
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT last_ingested_at FROM ingestion_state WHERE symbol=? AND interval=?",
            (symbol, interval),
        ).fetchone()
    return row[0] if row else None


def set_last_ingested_at(symbol: str, interval: str, ts: str, db_path: Path = DB_PATH) -> None:
    """Upsert the ingestion watermark for a (symbol, interval) pair."""
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO ingestion_state (symbol, interval, last_ingested_at)
            VALUES (?, ?, ?)
            ON CONFLICT(symbol, interval) DO UPDATE SET last_ingested_at=excluded.last_ingested_at
            """,
            (symbol, interval, ts),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Read helpers (for Streamlit UI)
# ---------------------------------------------------------------------------

def reset_ingestion_state(
    intervals: list[str] | None = None,
    db_path: Path = DB_PATH,
) -> int:
    """Delete ingestion_state rows for the given intervals (or all if None).

    This forces the next ingestion run to treat affected symbols as first-run,
    so they re-fetch the full lookback window instead of just the delta.
    Returns the number of rows deleted.
    """
    with connect(db_path) as conn:
        if intervals is None:
            n = conn.execute("DELETE FROM ingestion_state").rowcount
        else:
            placeholders = ",".join("?" * len(intervals))
            n = conn.execute(
                f"DELETE FROM ingestion_state WHERE interval IN ({placeholders})",
                intervals,
            ).rowcount
        conn.commit()
    logger.info(f"Reset ingestion state: {n} rows deleted (intervals={intervals or 'all'})")
    return n


def get_ingestion_status(db_path: Path = DB_PATH) -> pd.DataFrame:
    """Return a DataFrame of all (symbol, interval, last_ingested_at) rows."""
    with connect(db_path) as conn:
        df = pd.read_sql_query("SELECT * FROM ingestion_state ORDER BY symbol, interval", conn)
    return df


def get_latest_candles(
    symbol: str, interval: str, n: int = 100, db_path: Path = DB_PATH
) -> pd.DataFrame:
    """Fetch the last N candles for a given symbol and interval."""
    table = f"ohlcv_{interval}"
    with connect(db_path) as conn:
        df = pd.read_sql_query(
            f"SELECT * FROM {table} WHERE symbol=? ORDER BY timestamp DESC LIMIT ?",
            conn,
            params=(symbol, n),
        )
    return df.iloc[::-1].reset_index(drop=True)  # oldest first


def get_stale_symbols(
    interval: str = "1day",
    stale_business_days: int = 2,
    db_path: Path = DB_PATH,
) -> list[str]:
    """Return symbols whose data is stale (or never ingested) for the given interval.

    Staleness is measured in *business days* (Mon–Fri, no holiday calendar) so that
    stocks last updated on a Friday are not flagged as stale over a weekend.

    A symbol is considered stale if:
      - it has never been ingested (no row in ingestion_state), OR
      - the number of business days between last_ingested_at and today > stale_business_days
    """
    today = np.datetime64(datetime.now().date(), "D")

    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT symbol, last_ingested_at FROM ingestion_state WHERE interval = ?",
            (interval,),
        ).fetchall()

    stale = []
    seen = {symbol for symbol, _ in rows}

    for symbol, last_at in rows:
        if not last_at:
            stale.append(symbol)
            continue
        try:
            last_date = np.datetime64(datetime.fromisoformat(last_at).date(), "D")
            bdays = int(np.busday_count(last_date, today))
            if bdays > stale_business_days:
                stale.append(symbol)
        except Exception:
            stale.append(symbol)

    # Also include symbols in the OHLCV table but missing from ingestion_state
    table = f"ohlcv_{interval}"
    try:
        with connect(db_path) as conn:
            all_in_table = {
                r[0]
                for r in conn.execute(
                    f"SELECT DISTINCT symbol FROM {table}"
                ).fetchall()
            }
        for sym in all_in_table - seen:
            stale.append(sym)
    except Exception:
        pass

    return sorted(set(stale))


def get_symbols(db_path: Path = DB_PATH) -> list[str]:
    """Return distinct symbols present in ingestion_state."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT symbol FROM ingestion_state ORDER BY symbol"
        ).fetchall()
    return [r[0] for r in rows]


def get_db_stats(db_path: Path = DB_PATH) -> dict:
    """Return row counts per table and file size."""
    stats = {}
    if db_path.exists():
        stats["db_size_mb"] = round(db_path.stat().st_size / 1024 / 1024, 2)
    with connect(db_path) as conn:
        for interval in ALL_INTERVALS:
            table = f"ohlcv_{interval}"
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            stats[table] = row[0]
    return stats
