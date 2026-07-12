"""Shared bulk candle loading + signal persistence for the Q-stage services."""
from __future__ import annotations

import json

import pandas as pd
from sqlalchemy import text

from backend.db import get_engine, read_sql


def recent_candles(
    interval: str,
    n: int,
    symbols: list[str] | None = None,
    asof: str | None = None,
) -> pd.DataFrame:
    """Last `n` candles per symbol at or before `asof`, oldest-first, in ONE query.

    Far cheaper than a query per symbol (500 symbols → 1 round-trip).
    `asof` (YYYY-MM-DD) is what makes historical replay possible: it guarantees a
    scan only ever sees candles that existed on that date — no look-ahead.
    Returns legacy column names (timestamp, ema_20, …).
    """
    sql = """
        SELECT symbol, (ts AT TIME ZONE 'Asia/Kolkata') AS timestamp,
               open, high, low, close, volume, rsi, cci, atr,
               bb_upper, bb_mid AS bb_middle, bb_lower,
               ema20 AS ema_20, ema50 AS ema_50, ema200 AS ema_200
        FROM (
            SELECT *, row_number() OVER (PARTITION BY symbol ORDER BY ts DESC) AS rn
            FROM ohlcv
            WHERE interval = :i
              {asof_filter}
              {sym_filter}
        ) t
        WHERE rn <= :n
    """.format(
        asof_filter="AND (ts AT TIME ZONE 'Asia/Kolkata')::date <= :asof" if asof else "",
        sym_filter="AND symbol = ANY(:syms)" if symbols else "",
    )

    params: dict = {"i": interval, "n": n}
    if symbols:
        params["syms"] = symbols
    if asof:
        params["asof"] = asof
    df = read_sql(sql, params)
    if df.empty:
        return df
    return df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)


def universe() -> list[str]:
    """Tradable universe: Nifty 500 members (excludes synthetic indices)."""
    return read_sql(
        "SELECT symbol FROM symbols WHERE is_index = FALSE ORDER BY symbol"
    )["symbol"].tolist()


def sector_snapshot(asof: str | None = None) -> pd.DataFrame:
    """Q2.5 metrics per sector as they stood on `asof` (latest if None)."""
    where = "WHERE ts <= :asof" if asof else ""
    return read_sql(
        f"SELECT DISTINCT ON (sector) sector, quadrant, score AS sector_score, "
        f"rs_ratio, rs_momentum, ts "
        f"FROM sector_metrics {where} ORDER BY sector, ts DESC",
        {"asof": asof} if asof else {},
    )


def trading_days(start: str, end: str) -> list[str]:
    """Dates on which the benchmark actually traded — the replay clock."""
    df = read_sql(
        "SELECT DISTINCT (ts AT TIME ZONE 'Asia/Kolkata')::date AS d FROM ohlcv "
        "WHERE interval = '1day' AND symbol = 'NIFTY500EW' "
        "AND (ts AT TIME ZONE 'Asia/Kolkata')::date BETWEEN :s AND :e ORDER BY d",
        {"s": start, "e": end},
    )
    return [str(d) for d in df["d"].tolist()]


def save_signals(df: pd.DataFrame, stage: str) -> int:
    """Persist scanner results to `signals` (details = the pass/fail checklist)."""
    if df.empty:
        return 0
    rows = [
        {
            "symbol": r["symbol"],
            "ts": pd.Timestamp(r["asof"]).date(),
            "stage": stage,
            "passed": bool(r["passed"]),
            "details": json.dumps(r["checklist"]),
        }
        for _, r in df.iterrows()
    ]
    sql = text(
        "INSERT INTO signals (symbol, ts, stage, passed, details) "
        "VALUES (:symbol, :ts, :stage, :passed, CAST(:details AS jsonb))"
    )
    with get_engine().begin() as conn:
        conn.execute(sql, rows)
    return len(rows)
