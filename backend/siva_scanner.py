"""
Siva Swing Strategy — Stage 1 & Stage 2 Scanners.

Stage 1 (Watchlist Builder):
  C1  Momentum Reset        : 35 ≤ mean(RSI_last_25) ≤ 48
                               AND min(RSI_last_25) < 35
  C2  Price Base Formation  : (HH_last20 − LL_last20) / LL_last20 < base_range_pct
  C3  Volume Compression    : avg(vol_last10) < avg(vol_last30)
  C4  Liquidity Filter      : avg_vol_20 > min_avg_vol_20
                               OR avg_daily_turnover_20 > min_turnover_20
  C5  Price Filter (opt)    : latest_close > min_price

Stage 2 (Entry Detection — runs on Stage 1 watchlist or all symbols):
  C1  Volume Expansion      : vol_today ≥ vol_ratio_min × avg(vol_prior_20)
  C2  RSI Momentum Shift    : rsi_lo ≤ RSI_today ≤ rsi_hi
                               AND RSI_today > RSI_5_days_ago
  C3  Price Breakout        : close_today > max(high_prior_15)
  C4  CCI Confirmation(opt) : CCI_today > cci_thresh
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from src.config import DB_PATH


def scan_stage1(
    interval: str = "1day",
    lookback: int = 70,
    rsi_mean_lo: float = 35.0,
    rsi_mean_hi: float = 48.0,
    rsi_dip_thresh: float = 35.0,
    base_range_pct: float = 20.0,
    min_avg_vol_20: int = 200_000,
    min_turnover_cr: float = 5.0,          # Crore rupees
    min_price: float | None = 80.0,
    db_path: Path = DB_PATH,
) -> pd.DataFrame:
    """Scan all symbols and return those matching Stage 1 conditions."""
    table = f"ohlcv_{interval}"
    results = []

    with sqlite3.connect(str(db_path)) as conn:
        symbols = [
            r[0] for r in conn.execute(
                f"SELECT DISTINCT symbol FROM {table} ORDER BY symbol"
            ).fetchall()
        ]

        for symbol in symbols:
            df = pd.read_sql_query(
                f"""
                SELECT timestamp, close, high, low, volume, rsi
                FROM   {table}
                WHERE  symbol = ?
                  AND  rsi   IS NOT NULL
                  AND  close IS NOT NULL
                  AND  volume IS NOT NULL
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                conn,
                params=(symbol, lookback),
            )

            if len(df) < 30:
                continue

            df = df.iloc[::-1].reset_index(drop=True)   # oldest → newest

            row = _evaluate(
                df, symbol,
                rsi_mean_lo, rsi_mean_hi, rsi_dip_thresh,
                base_range_pct,
                min_avg_vol_20, min_turnover_cr * 1e7,
                min_price,
            )
            if row:
                results.append(row)

    if not results:
        return pd.DataFrame()

    out = pd.DataFrame(results)
    # Sort: deepest RSI consolidation first (lowest mean = most oversold)
    out = out.sort_values("rsi_mean_25").reset_index(drop=True)
    return out


# ---------------------------------------------------------------------------
# Internal evaluator
# ---------------------------------------------------------------------------

def _evaluate(
    df: pd.DataFrame,
    symbol: str,
    rsi_mean_lo: float,
    rsi_mean_hi: float,
    rsi_dip_thresh: float,
    base_range_pct: float,
    min_avg_vol_20: int,
    min_turnover_20: float,       # rupees
    min_price: float | None,
) -> dict | None:
    n = len(df)
    latest = df.iloc[-1]
    close  = float(latest["close"])

    # — C5: Price filter (cheapest check first) —
    if min_price is not None and close <= min_price:
        return None

    # — C1: Momentum Reset —
    rsi_25 = df["rsi"].iloc[max(0, n - 25):n]
    if len(rsi_25) < 25 or rsi_25.isna().any():
        return None
    rsi_mean = float(rsi_25.mean())
    rsi_min  = float(rsi_25.min())
    if not (rsi_mean_lo <= rsi_mean <= rsi_mean_hi):
        return None
    if rsi_min >= rsi_dip_thresh:
        return None

    # — C2: Price Base Formation —
    last_20   = df.iloc[max(0, n - 20):n]
    hi20      = float(last_20["high"].max())
    lo20      = float(last_20["low"].min())
    if lo20 <= 0:
        return None
    range_pct = (hi20 - lo20) / lo20 * 100.0
    if range_pct >= base_range_pct:
        return None

    # — C3: Volume Compression —
    vol_10 = df["volume"].iloc[max(0, n - 10):n]
    vol_30 = df["volume"].iloc[max(0, n - 30):n]
    if len(vol_10) < 10 or len(vol_30) < 30:
        return None
    avg_10 = float(vol_10.mean())
    avg_30 = float(vol_30.mean())
    if avg_30 == 0 or avg_10 >= avg_30:
        return None

    # — C4: Liquidity —
    vol_20   = df["volume"].iloc[max(0, n - 20):n]
    close_20 = df["close"].iloc[max(0, n - 20):n]
    avg_vol_20     = float(vol_20.mean())
    avg_turnover   = float((vol_20.values * close_20.values).mean())
    if avg_vol_20 <= min_avg_vol_20 and avg_turnover <= min_turnover_20:
        return None

    return {
        "symbol":          symbol,
        "close":           round(close, 2),
        "rsi_latest":      round(float(latest["rsi"]), 1),
        "rsi_mean_25":     round(rsi_mean, 1),
        "rsi_min_25":      round(rsi_min, 1),
        "price_range_pct": round(range_pct, 1),
        "vol_compression": round(avg_10 / avg_30, 2),   # <1 = compressed; lower = better
        "avg_vol_20":      int(avg_vol_20),
        "turnover_cr":     round(avg_turnover / 1e7, 2),
    }


# ===========================================================================
# Stage 2 — Entry Detection
# ===========================================================================

def scan_stage2(
    symbols: list[str] | None = None,   # None = scan all in DB
    interval: str = "1day",
    lookback: int = 40,
    rsi_lo: float = 50.0,
    rsi_hi: float = 80.0,
    vol_ratio_min: float = 1.5,         # moderate signal threshold
    vol_ratio_strong: float = 2.0,      # strong signal threshold
    use_cci: bool = False,
    cci_thresh: float = 0.0,
    db_path: Path = DB_PATH,
) -> pd.DataFrame:
    """
    Stage 2 scanner: detects breakout entry signals.

    Runs on the provided symbol list (Stage 1 watchlist) or the full DB universe.
    Evaluates the MOST RECENT candle against prior-period benchmarks.
    """
    table = f"ohlcv_{interval}"
    results = []

    with sqlite3.connect(str(db_path)) as conn:
        if symbols:
            universe = symbols
        else:
            universe = [
                r[0] for r in conn.execute(
                    f"SELECT DISTINCT symbol FROM {table} ORDER BY symbol"
                ).fetchall()
            ]

        for symbol in universe:
            df = pd.read_sql_query(
                f"""
                SELECT timestamp, close, high, low, volume, rsi, cci
                FROM   {table}
                WHERE  symbol = ?
                  AND  close  IS NOT NULL
                  AND  volume IS NOT NULL
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                conn,
                params=(symbol, lookback),
            )

            # Need today + 20 prior (vol avg) + 15 prior (breakout) + 5 prior (RSI trend)
            if len(df) < 22:
                continue

            df = df.iloc[::-1].reset_index(drop=True)   # oldest → newest

            row = _evaluate_stage2(
                df, symbol,
                rsi_lo, rsi_hi,
                vol_ratio_min, vol_ratio_strong,
                use_cci, cci_thresh,
            )
            if row:
                results.append(row)

    if not results:
        return pd.DataFrame()

    out = pd.DataFrame(results)
    # Sort: strongest signal (highest vol_ratio) first
    out = out.sort_values("vol_ratio", ascending=False).reset_index(drop=True)
    return out


def _evaluate_stage2(
    df: pd.DataFrame,
    symbol: str,
    rsi_lo: float,
    rsi_hi: float,
    vol_ratio_min: float,
    vol_ratio_strong: float,
    use_cci: bool,
    cci_thresh: float,
) -> dict | None:
    n      = len(df)
    today  = df.iloc[-1]
    close  = float(today["close"])
    vol_today = float(today["volume"]) if today["volume"] else 0.0

    # Prior slices (exclude today)
    prior_20_vol  = df["volume"].iloc[max(0, n - 21): n - 1]
    prior_15_high = df["high"].iloc[max(0, n - 16): n - 1]

    if len(prior_20_vol) < 20 or len(prior_15_high) < 15:
        return None

    avg_vol_20 = float(prior_20_vol.mean())
    if avg_vol_20 == 0:
        return None

    # — C1: Volume Expansion —
    vol_ratio = vol_today / avg_vol_20
    if vol_ratio < vol_ratio_min:
        return None

    # — C2: RSI Momentum Shift —
    rsi_today = today.get("rsi")
    if rsi_today is None or (hasattr(rsi_today, '__class__') and str(rsi_today) == 'nan'):
        return None
    try:
        rsi_today = float(rsi_today)
    except (TypeError, ValueError):
        return None
    if not (rsi_lo <= rsi_today <= rsi_hi):
        return None

    # RSI must be rising vs 5 candles ago
    if n < 6:
        return None
    rsi_5ago = df["rsi"].iloc[n - 6]
    if pd.isna(rsi_5ago) or rsi_today <= float(rsi_5ago):
        return None

    # — C3: Price Breakout — close above the prior 15-day high
    high_15 = float(prior_15_high.max())
    if close <= high_15:
        return None
    breakout_pct = (close - high_15) / high_15 * 100.0

    # — C4: CCI (optional) —
    if use_cci:
        cci_val = today.get("cci")
        try:
            if cci_val is None or float(cci_val) <= cci_thresh:
                return None
        except (TypeError, ValueError):
            return None

    vol_signal = "Strong" if vol_ratio >= vol_ratio_strong else "Moderate"

    return {
        "symbol":        symbol,
        "close":         round(close, 2),
        "rsi":           round(rsi_today, 1),
        "rsi_5d_ago":    round(float(rsi_5ago), 1),
        "rsi_trend":     round(rsi_today - float(rsi_5ago), 1),
        "cci":           round(float(today["cci"]), 1) if today.get("cci") and not pd.isna(today["cci"]) else None,
        "vol_ratio":     round(vol_ratio, 2),
        "vol_signal":    vol_signal,
        "breakout_pct":  round(breakout_pct, 2),
        "high_15":       round(high_15, 2),
        "avg_vol_20":    int(avg_vol_20),
    }
