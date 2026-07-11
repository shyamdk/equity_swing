"""
Signal Scanner — identifies momentum breakout setups.

Criteria (all three must be met on the same candle):
  1. Average RSI of the 5 candles immediately before the signal candle < 50
     (stock was in a weak/oversold baseline)
  2. Signal candle: CCI > 100  (bullish momentum spike)
  3. Signal candle: RSI > 50   (momentum crossed into bullish territory)
  4. Signal candle: volume > 4× the average volume of those 5 prior candles
     (volume confirmation)

Returns the most recent such signal per symbol (if it occurred within
`max_signal_age_candles` candles from the latest data).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.config import DB_PATH, ALL_INTERVALS


def scan(
    interval: str,
    lookback: int = 60,          # candles fetched per symbol for scanning
    max_signal_age: int = 10,    # only report signals in the last N candles
    db_path: Path = DB_PATH,
) -> pd.DataFrame:
    """
    Run the signal scan across all symbols for a given interval.

    Returns a DataFrame with columns:
        symbol, signal_time, close, rsi, cci, volume,
        avg_rsi_5_prior, avg_vol_5_prior, vol_ratio
    sorted by signal_time descending (freshest first).
    """
    table = f"ohlcv_{interval}"
    results = []

    with sqlite3.connect(str(db_path)) as conn:
        # Get all symbols that have data in this interval
        symbols = [
            r[0]
            for r in conn.execute(
                f"SELECT DISTINCT symbol FROM {table} ORDER BY symbol"
            ).fetchall()
        ]

        for symbol in symbols:
            df = pd.read_sql_query(
                f"""
                SELECT timestamp, close, volume, rsi, cci
                FROM {table}
                WHERE symbol = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                conn,
                params=(symbol, lookback),
            )

            if len(df) < 7:   # need at least 5 prior + 1 signal + 1 spare
                continue

            # Oldest first for rolling logic
            df = df.iloc[::-1].reset_index(drop=True)

            signal = _find_latest_signal(df, max_signal_age)
            if signal:
                signal["symbol"] = symbol
                signal["last_candle"] = df["timestamp"].max()
                results.append(signal)

    if not results:
        return pd.DataFrame()

    out = pd.DataFrame(results)
    out = out.sort_values("signal_time", ascending=False).reset_index(drop=True)

    # Format signal_time as a readable date string
    out["signal_date"] = pd.to_datetime(out["signal_time"]).dt.strftime("%d %b %Y  %H:%M")

    # Staleness: days since the symbol's latest candle
    now = datetime.now()
    out["last_candle"] = pd.to_datetime(out["last_candle"])
    out["data_age_days"] = (now - out["last_candle"]).dt.days
    out["stale"] = out["data_age_days"] > 2

    cols = [
        "symbol", "signal_date", "candles_ago", "close",
        "rsi", "cci", "volume",
        "avg_rsi_5_prior", "avg_vol_5_prior", "vol_ratio",
        "data_age_days", "stale",
    ]
    return out[[c for c in cols if c in out.columns]]


def _find_latest_signal(df: pd.DataFrame, max_signal_age: int) -> dict | None:
    """
    Scan df (oldest→newest) for the most recent candle satisfying all criteria.
    Only considers candles within the last `max_signal_age` rows.
    """
    n = len(df)
    latest_signal = None

    # Start at index 5 so we always have 5 prior candles
    for i in range(5, n):
        prior = df.iloc[i - 5: i]
        row   = df.iloc[i]

        # Skip if any required indicator is missing
        if (
            prior["rsi"].isna().any()
            or pd.isna(row.get("rsi"))
            or pd.isna(row.get("cci"))
            or pd.isna(row.get("volume"))
        ):
            continue

        avg_rsi_prior = prior["rsi"].mean()
        avg_vol_prior = prior["volume"].mean()

        if avg_vol_prior == 0:
            continue

        vol_ratio = row["volume"] / avg_vol_prior

        # All three signal conditions
        if (
            avg_rsi_prior < 50          # weak RSI baseline
            and row["rsi"]  > 50        # RSI crossed into bullish
            and row["cci"]  > 100       # CCI momentum spike
            and vol_ratio   >= 4.0      # volume surge ≥ 4×
        ):
            # Only keep signals within the last max_signal_age candles
            if i >= n - max_signal_age:
                candles_ago = n - 1 - i   # 0 = most recent candle
                latest_signal = {
                    "signal_time":     row["timestamp"],
                    "candles_ago":     candles_ago,
                    "close":           round(float(row["close"]), 2),
                    "rsi":             round(float(row["rsi"]), 1),
                    "cci":             round(float(row["cci"]), 1),
                    "volume":          int(row["volume"]),
                    "avg_rsi_5_prior": round(avg_rsi_prior, 1),
                    "avg_vol_5_prior": round(avg_vol_prior, 0),
                    "vol_ratio":       round(vol_ratio, 1),
                }

    return latest_signal
