"""Nifty 500 equal-weight composite — the market benchmark for Q1 and Q2.5.

We build a synthetic index from the daily closes of the Nifty 500 members we
already hold, store it in the ohlcv hypertable as symbol 'NIFTY500EW', and reuse
it as (a) the market proxy for the Q1 regime filter and (b) the benchmark for
Q2.5 sector relative-strength.

Construction: equal-weight, daily-rebalanced. Each day's index return is the mean
of member daily returns (over members present on both days); the level compounds
from a base of 100.
"""
from __future__ import annotations

import pandas as pd
from loguru import logger
from sqlalchemy import text

from backend.db import get_engine, read_sql
from backend.database import upsert_ohlcv
from backend.indicators import calculate_indicators

BENCHMARK_SYMBOL = "NIFTY500EW"


# ---------------------------------------------------------------------------
# Composite construction (shared with sector.py)
# ---------------------------------------------------------------------------

def pivot_daily_closes(symbols: list[str] | None = None) -> pd.DataFrame:
    """Return a (date × symbol) DataFrame of daily closes.

    If `symbols` is None, uses the Nifty 500 members from the `symbols` table.
    """
    if symbols is None:
        df = read_sql(
            "SELECT (o.ts AT TIME ZONE 'Asia/Kolkata')::date AS d, o.symbol, o.close "
            "FROM ohlcv o JOIN symbols s ON s.symbol = o.symbol "
            "WHERE o.interval = '1day' AND s.is_index = FALSE"
        )
    else:
        df = read_sql(
            "SELECT (ts AT TIME ZONE 'Asia/Kolkata')::date AS d, symbol, close "
            "FROM ohlcv WHERE interval = '1day' AND symbol = ANY(:syms)",
            {"syms": symbols},
        )
    if df.empty:
        return df
    return df.pivot_table(index="d", columns="symbol", values="close").sort_index()


def equal_weight_level(pivot: pd.DataFrame, base: float = 100.0) -> pd.Series:
    """Compound the equal-weight (daily-rebalanced) index level from a close pivot."""
    if pivot.empty:
        return pd.Series(dtype=float)
    daily_ret = pivot.pct_change(fill_method=None)   # don't forward-fill stale prices
    mkt_ret = daily_ret.mean(axis=1)          # equal-weight across available names
    level = base * (1.0 + mkt_ret.fillna(0.0)).cumprod()
    return level


# ---------------------------------------------------------------------------
# Build + persist the benchmark
# ---------------------------------------------------------------------------

def _level_to_ohlcv(level: pd.Series, symbol: str) -> pd.DataFrame:
    """Wrap an index-level series into an OHLCV frame (O=H=L=C=level)."""
    df = pd.DataFrame({
        "symbol": symbol,
        "timestamp": pd.to_datetime(level.index),
        "open": level.values, "high": level.values,
        "low": level.values, "close": level.values,
        "volume": 0,
    })
    return df


def build_benchmark() -> dict:
    """Compute the NIFTY500EW composite (daily + weekly) and upsert into ohlcv."""
    pivot = pivot_daily_closes()
    if pivot.empty:
        raise RuntimeError("No daily data to build benchmark from.")

    level = equal_weight_level(pivot)
    level.index = pd.to_datetime(level.index)      # date → DatetimeIndex (for resample)
    daily = _level_to_ohlcv(level, BENCHMARK_SYMBOL)
    daily = calculate_indicators(daily, is_intraday=False)
    n_day = upsert_ohlcv("1day", daily)

    # Weekly (W-FRI) from the daily level.
    wk = (level.resample("W-FRI").last().dropna())
    weekly = _level_to_ohlcv(wk, BENCHMARK_SYMBOL)
    weekly = calculate_indicators(weekly, is_intraday=False)
    n_week = upsert_ohlcv("1week", weekly)

    # Register the synthetic symbol.
    with get_engine().begin() as conn:
        conn.execute(text(
            "INSERT INTO symbols (symbol, company_name, industry, series, isin, is_index) "
            "VALUES (:s, 'Nifty 500 Equal Weight (synthetic)', 'Index', 'IDX', '', TRUE) "
            "ON CONFLICT (symbol) DO UPDATE SET is_index = TRUE"
        ), {"s": BENCHMARK_SYMBOL})

    logger.success(f"Benchmark {BENCHMARK_SYMBOL}: {n_day} daily, {n_week} weekly rows")
    return {"daily": n_day, "weekly": n_week, "last_level": round(float(level.iloc[-1]), 2)}


def benchmark_daily(n: int = 300) -> pd.DataFrame:
    """Read the last N daily candles of the benchmark (oldest-first)."""
    from backend.database import get_latest_candles
    return get_latest_candles(BENCHMARK_SYMBOL, "1day", n)
