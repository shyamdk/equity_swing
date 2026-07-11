"""Postgres/TimescaleDB access: ohlcv upsert, ingestion state, and read helpers.

The physical schema is a single `ohlcv` hypertable keyed by (symbol, interval, ts),
created by db/init/01_schema.sql on first container boot. This module speaks to it
while preserving the *column names the rest of the codebase expects* (timestamp,
bb_middle, ema_20/50/200) on reads, so ported scanner/resample code keeps working.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
from loguru import logger
from sqlalchemy import text

from backend.config import ALL_INTERVALS, INTRADAY_INTERVALS, MARKET_TZ
from backend.db import get_engine, read_sql, scalar

# Physical ohlcv columns (new schema).
_OHLCV_COLS = [
    "symbol", "interval", "ts", "open", "high", "low", "close", "volume",
    "rsi", "cci", "macd", "macd_signal", "macd_hist",
    "bb_upper", "bb_mid", "bb_lower", "ema20", "ema50", "ema200", "atr", "vwap",
]
# Legacy indicator/column names (as produced by indicators.py) → physical names.
_RENAME_TO_PHYSICAL = {
    "timestamp": "ts", "bb_middle": "bb_mid",
    "ema_20": "ema20", "ema_50": "ema50", "ema_200": "ema200",
}


# ---------------------------------------------------------------------------
# Schema / connectivity
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Verify the Postgres schema is present (created by docker init script)."""
    exists = scalar(
        "SELECT to_regclass('public.ohlcv') IS NOT NULL"
    )
    if not exists:
        raise RuntimeError(
            "Table 'ohlcv' not found. Start the database with "
            "`docker compose up -d` (the schema is created on first boot)."
        )
    logger.debug("Postgres schema verified (ohlcv present).")


# ---------------------------------------------------------------------------
# OHLCV upsert
# ---------------------------------------------------------------------------

def upsert_ohlcv(interval: str, df: pd.DataFrame) -> int:
    """Insert/update rows for one (symbol, interval) into the ohlcv hypertable.

    Accepts a DataFrame using the legacy column names (timestamp, bb_middle,
    ema_20…). Naive timestamps are treated as IST. Returns rows written.
    """
    if df is None or df.empty:
        return 0

    df = df.rename(columns=_RENAME_TO_PHYSICAL).copy()
    df["interval"] = interval

    # Normalize ts → tz-aware IST so storage is unambiguous regardless of server TZ.
    ts = pd.to_datetime(df["ts"])
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize(MARKET_TZ)
    df["ts"] = ts

    # VWAP only meaningful intraday.
    if interval not in INTRADAY_INTERVALS:
        df["vwap"] = None

    for col in _OHLCV_COLS:
        if col not in df.columns:
            df[col] = None

    df = df[_OHLCV_COLS]
    records = df.astype(object).where(pd.notnull(df), None).to_dict("records")

    cols = ", ".join(_OHLCV_COLS)
    placeholders = ", ".join(f":{c}" for c in _OHLCV_COLS)
    updates = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in _OHLCV_COLS
        if c not in ("symbol", "interval", "ts")
    )
    sql = text(
        f"INSERT INTO ohlcv ({cols}) VALUES ({placeholders}) "
        f"ON CONFLICT (symbol, interval, ts) DO UPDATE SET {updates}"
    )
    with get_engine().begin() as conn:
        conn.execute(sql, records)

    logger.debug(f"Upserted {len(records)} rows into ohlcv [{interval}]")
    return len(records)


# ---------------------------------------------------------------------------
# Ingestion state  (last_ingested_at stored as timestamptz, exchanged as IST ISO str)
# ---------------------------------------------------------------------------

def get_last_ingested_at(symbol: str, interval: str) -> str | None:
    """Return the last ingested candle time as a naive-IST ISO8601 string, or None."""
    df = read_sql(
        "SELECT (last_ingested_at AT TIME ZONE :tz) AS t "
        "FROM ingestion_state WHERE symbol = :s AND interval = :i",
        {"tz": MARKET_TZ, "s": symbol, "i": interval},
    )
    if df.empty or pd.isna(df["t"].iloc[0]):
        return None
    return pd.Timestamp(df["t"].iloc[0]).strftime("%Y-%m-%dT%H:%M:%S")


def set_last_ingested_at(symbol: str, interval: str, ts: str) -> None:
    """Upsert the watermark. `ts` is a naive-IST ISO8601 string."""
    sql = text(
        "INSERT INTO ingestion_state (symbol, interval, last_ingested_at) "
        "VALUES (:s, :i, (CAST(:ts AS timestamp) AT TIME ZONE :tz)) "
        "ON CONFLICT (symbol, interval) DO UPDATE "
        "SET last_ingested_at = EXCLUDED.last_ingested_at, updated_at = now()"
    )
    with get_engine().begin() as conn:
        conn.execute(sql, {"s": symbol, "i": interval, "ts": ts, "tz": MARKET_TZ})


def reset_ingestion_state(intervals: list[str] | None = None) -> int:
    """Delete ingestion_state rows (all, or for given intervals) to force full re-fetch."""
    with get_engine().begin() as conn:
        if intervals is None:
            res = conn.execute(text("DELETE FROM ingestion_state"))
        else:
            res = conn.execute(
                text("DELETE FROM ingestion_state WHERE interval = ANY(:ivals)"),
                {"ivals": intervals},
            )
        n = res.rowcount
    logger.info(f"Reset ingestion state: {n} rows (intervals={intervals or 'all'})")
    return n


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def get_ingestion_status() -> pd.DataFrame:
    """All (symbol, interval, last_ingested_at[IST]) rows."""
    return read_sql(
        "SELECT symbol, interval, (last_ingested_at AT TIME ZONE :tz) AS last_ingested_at "
        "FROM ingestion_state ORDER BY symbol, interval",
        {"tz": MARKET_TZ},
    )


def get_latest_candles(symbol: str, interval: str, n: int = 100) -> pd.DataFrame:
    """Last N candles (oldest-first) for symbol/interval, with legacy column names."""
    df = read_sql(
        "SELECT symbol, (ts AT TIME ZONE :tz) AS timestamp, open, high, low, close, volume, "
        "rsi, cci, macd, macd_signal, macd_hist, bb_upper, bb_mid AS bb_middle, bb_lower, "
        "ema20 AS ema_20, ema50 AS ema_50, ema200 AS ema_200, atr, vwap "
        "FROM ohlcv WHERE symbol = :s AND interval = :i ORDER BY ts DESC LIMIT :n",
        {"tz": MARKET_TZ, "s": symbol, "i": interval, "n": n},
    )
    return df.iloc[::-1].reset_index(drop=True)


def get_symbols() -> list[str]:
    """Distinct symbols present in ingestion_state."""
    df = read_sql("SELECT DISTINCT symbol FROM ingestion_state ORDER BY symbol")
    return df["symbol"].tolist()


def get_stale_symbols(interval: str = "1day", stale_business_days: int = 2) -> list[str]:
    """Symbols whose data is stale (or never ingested) for the given interval.

    Staleness measured in business days (Mon–Fri, no holiday calendar).
    """
    today = np.datetime64(datetime.now().date(), "D")
    rows = read_sql(
        "SELECT symbol, (last_ingested_at AT TIME ZONE :tz) AS last_at "
        "FROM ingestion_state WHERE interval = :i",
        {"tz": MARKET_TZ, "i": interval},
    )

    stale: list[str] = []
    seen = set(rows["symbol"].tolist())
    for _, r in rows.iterrows():
        last_at = r["last_at"]
        if pd.isna(last_at):
            stale.append(r["symbol"])
            continue
        last_date = np.datetime64(pd.Timestamp(last_at).date(), "D")
        if int(np.busday_count(last_date, today)) > stale_business_days:
            stale.append(r["symbol"])

    # Symbols with candles but no ingestion_state row.
    in_table = read_sql(
        "SELECT DISTINCT symbol FROM ohlcv WHERE interval = :i", {"i": interval}
    )["symbol"].tolist()
    stale.extend(set(in_table) - seen)

    return sorted(set(stale))


def get_db_stats() -> dict:
    """Row counts per interval + total."""
    df = read_sql(
        "SELECT interval, count(*) AS rows FROM ohlcv GROUP BY interval ORDER BY interval"
    )
    stats = {f"ohlcv_{r['interval']}": int(r["rows"]) for _, r in df.iterrows()}
    stats["total_rows"] = int(df["rows"].sum()) if not df.empty else 0
    return stats
