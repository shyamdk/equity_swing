"""Siva-95 backtest scanner.

Checks the following conditions on each weekly candle within a date range.
All weekly indicators are computed on-the-fly from stored daily OHLCV — this avoids
dependency on the sparse pre-computed weekly RSI/CCI columns.

Conditions:
  1. Weekly RSI(14)         between rsi_lo and rsi_hi  (default 50–75)
  2. Weekly RSI             > 10-period RSI-MA  (momentum confirmation)
  3. Weekly CCI(20)         ≥ cci_min           (default 90)
  4. Daily RSI < 50         on at least 5 of the last 10 daily candles
  5. Daily volume           increasing for last 4 consecutive periods
  6. Weekly high            > max daily high of the 33 trading days before this week
  7. Close                  ≥ min_price         (default ₹25)
  8. 5-day avg daily volume ≥ min_avg_vol_5     (default 100,000)
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime

import pandas as pd
import ta
from loguru import logger

from src.config import DB_PATH


# ---------------------------------------------------------------------------
# Data loader
# ---------------------------------------------------------------------------

def _load_all_daily(db_path, to_ts: str) -> dict[str, pd.DataFrame]:
    """Return {symbol: daily_df} for all symbols, daily data up to to_ts."""
    with sqlite3.connect(str(db_path)) as conn:
        df = pd.read_sql_query(
            """SELECT symbol, timestamp, open, high, low, close, volume, rsi AS d_rsi
               FROM ohlcv_1day
               WHERE timestamp <= ?
               ORDER BY symbol, timestamp""",
            conn,
            params=(to_ts,),
        )
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return {sym: grp.reset_index(drop=True) for sym, grp in df.groupby("symbol")}


def _build_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    """Resample daily OHLCV to weekly (W-FRI) and compute RSI, CCI, RSI-MA on the fly."""
    d = daily.set_index("timestamp").sort_index()
    wk = (
        d[["open", "high", "low", "close", "volume"]]
        .resample("W-FRI")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna(subset=["close"])
        .reset_index()
    )
    if len(wk) < 3:
        return pd.DataFrame()
    wk["rsi"]    = ta.momentum.rsi(wk["close"],  window=14)
    wk["cci"]    = ta.trend.cci(wk["high"], wk["low"], wk["close"], window=20)
    wk["rsi_ma"] = wk["rsi"].rolling(10).mean()
    return wk


# ---------------------------------------------------------------------------
# Core scanner
# ---------------------------------------------------------------------------

def scan_siva95(
    from_date: date,
    to_date: date,
    rsi_lo: float = 50.0,
    rsi_hi: float = 75.0,
    cci_min: float = 90.0,
    require_cci: bool = True,
    require_rsi_above_ma: bool = True,
    rsi_below50_days: int = 5,
    rsi_lookback_days: int = 10,
    vol_compare_weeks: int = 4,        # current week's vol > avg of last N weekly vols
    vol_ratio_min: float = 1.0,        # current_week_vol / prior_N_week_avg must be >= this
    min_avg_vol_5: int = 100_000,
    min_price: float = 25.0,
    db_path=DB_PATH,
) -> pd.DataFrame:
    """Scan all symbols for Siva-95 conditions in [from_date, to_date].

    Returns DataFrame with one row per (symbol, week_date) where all conditions are met.
    """
    to_ts   = to_date.isoformat() + "T23:59:59"
    from_ts = from_date.isoformat()

    logger.info(f"Siva-95 scan: {from_ts} → {to_ts}")

    all_daily = _load_all_daily(db_path, to_ts)
    logger.info(f"Loaded daily data for {len(all_daily)} symbols")

    results = []
    skipped_no_data = 0
    skipped_indicator = 0

    for symbol, daily in all_daily.items():
        if daily.empty:
            skipped_no_data += 1
            continue

        # Price filter — quick reject on latest price
        if daily["close"].iloc[-1] < min_price:
            continue

        weekly = _build_weekly(daily)
        if weekly.empty:
            skipped_no_data += 1
            continue

        # Filter weekly candles to the requested date range
        mask = (weekly["timestamp"] >= pd.Timestamp(from_ts)) & \
               (weekly["timestamp"] <= pd.Timestamp(to_date.isoformat() + "T23:59:59"))
        week_range = weekly[mask]
        if week_range.empty:
            continue

        for pos, (idx, w) in enumerate(week_range.iterrows()):
            week_end = w["timestamp"]

            # ---- 1. Weekly RSI in range ----
            w_rsi = w["rsi"]
            if pd.isna(w_rsi) or not (rsi_lo <= w_rsi <= rsi_hi):
                continue

            # ---- 2. Weekly RSI > RSI-MA (skip condition when MA can't be computed) ----
            rsi_ma_val = w["rsi_ma"]
            if require_rsi_above_ma:
                if pd.isna(rsi_ma_val):
                    skipped_indicator += 1
                    continue
                if w_rsi <= rsi_ma_val:
                    continue

            # ---- 3. Weekly CCI ≥ cci_min ----
            w_cci = w["cci"]
            if require_cci:
                if pd.isna(w_cci) or w_cci < cci_min:
                    skipped_indicator += 1
                    continue

            # ---- 4. Close ≥ min_price ----
            if w["close"] < min_price:
                continue

            # Get daily data up to this week's end
            daily_to_week = daily[daily["timestamp"] <= week_end]
            if len(daily_to_week) < max(33 + 5, rsi_lookback_days + 2):
                continue

            # ---- 5. Weekly high > max daily high of prior 33 trading days ----
            # "Prior" = before this week's Monday (Friday - 4 calendar days ≈ Monday)
            week_start_approx = week_end - pd.Timedelta(days=4)
            daily_before = daily[daily["timestamp"] < week_start_approx]
            if len(daily_before) < 33:
                continue
            high_33 = float(daily_before["high"].tail(33).max())
            if w["high"] <= high_33:
                continue

            # ---- 6. Daily RSI < 50 on at least N of last 10 days ----
            last_10_rsi = daily_to_week["d_rsi"].tail(rsi_lookback_days).dropna()
            if len(last_10_rsi) < rsi_lookback_days:
                continue
            days_below_50 = int((last_10_rsi < 50).sum())
            if days_below_50 < rsi_below50_days:
                continue

            # ---- 7. Current week volume > avg of prior N weekly volumes ----
            # "Volume is increasing (≥4 periods)" → current week vol above recent weekly average
            wk_iloc = weekly[weekly["timestamp"] == week_end].index
            if len(wk_iloc) == 0:
                continue
            wk_pos = wk_iloc[0]
            if wk_pos < vol_compare_weeks:
                continue
            prior_vols = weekly.loc[wk_pos - vol_compare_weeks: wk_pos - 1, "volume"]
            prior_vol_avg = float(prior_vols.mean())
            if prior_vol_avg <= 0:
                continue
            current_vol_ratio = float(w["volume"]) / prior_vol_avg
            if current_vol_ratio < vol_ratio_min:
                continue

            # ---- 8. 5-day avg volume ≥ min_avg_vol_5 ----
            avg_vol_5 = float(daily_to_week["volume"].tail(5).mean())
            if avg_vol_5 < min_avg_vol_5:
                continue

            results.append({
                "symbol":           symbol,
                "week_date":        week_end.strftime("%Y-%m-%d"),
                "close":            round(float(w["close"]), 2),
                "weekly_high":      round(float(w["high"]), 2),
                "high_33d_prior":   round(float(high_33), 2),
                "breakout_pct":     round((float(w["high"]) / high_33 - 1) * 100, 2),
                "weekly_rsi":       round(float(w_rsi), 1),
                "rsi_ma":           round(float(rsi_ma_val), 1) if pd.notna(rsi_ma_val) else None,
                "weekly_cci":       round(float(w_cci), 1) if pd.notna(w_cci) else None,
                "rsi_days_below50": days_below_50,
                "vol_ratio":        round(current_vol_ratio, 2),
                "avg_vol_5d":       int(avg_vol_5),
            })

    logger.info(
        f"Siva-95 done: {len(results)} hits, "
        f"{skipped_no_data} no-data, {skipped_indicator} indicator-insufficient"
    )

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)
    df = df.sort_values(["week_date", "breakout_pct"], ascending=[False, False])
    df = df.reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# Near-condition scanner — finds stocks approaching (but not yet at) full trigger
# ---------------------------------------------------------------------------

def scan_siva95_near(
    db_path=DB_PATH,
    rsi_lo: float = 40.0,
    rsi_hi: float = 80.0,
    cci_min: float = 50.0,
    rsi_below50_days: int = 3,
    min_avg_vol_5: int = 50_000,
    min_price: float = 25.0,
) -> pd.DataFrame:
    """Find stocks in the neighbourhood of Siva-95 conditions (relaxed thresholds).

    Used by the monitor to keep a small focused watchlist instead of scanning
    all 1,600+ symbols every time. Returns a DataFrame with a 'conditions_met'
    score column (0–5) sorted descending so closest-to-trigger stocks appear first.
    """
    to_ts = date.today().isoformat() + "T23:59:59"
    all_daily = _load_all_daily(db_path, to_ts)

    results = []
    for symbol, daily in all_daily.items():
        if daily.empty or float(daily["close"].iloc[-1]) < min_price:
            continue
        wk = _build_weekly(daily)
        if wk.empty or len(wk) < 3:
            continue

        w = wk.iloc[-1]   # most recent weekly candle
        w_rsi = w["rsi"]
        if pd.isna(w_rsi) or not (rsi_lo <= w_rsi <= rsi_hi):
            continue

        score = 0
        details = {}

        # 1. RSI in relaxed zone
        score += 1
        details["weekly_rsi"] = round(float(w_rsi), 1)

        # 2. CCI approaching (relaxed)
        w_cci = w["cci"]
        if pd.notna(w_cci) and w_cci >= cci_min:
            score += 1
        details["weekly_cci"] = round(float(w_cci), 1) if pd.notna(w_cci) else None

        # 3. Daily RSI dip (relaxed — 3 of last 10 days)
        daily_to_week = daily[daily["timestamp"] <= w["timestamp"]]
        last_10 = daily_to_week["d_rsi"].tail(10).dropna()
        dip_days = int((last_10 < 50).sum()) if len(last_10) >= 8 else 0
        if dip_days >= rsi_below50_days:
            score += 1
        details["rsi_days_below50"] = dip_days

        # 4. Volume liquidity
        avg_vol = float(daily_to_week["volume"].tail(5).mean())
        if avg_vol >= min_avg_vol_5:
            score += 1
        details["avg_vol_5d"] = int(avg_vol)

        # 5. Price within 5% of prior 33-day high (approaching breakout)
        week_start = w["timestamp"] - pd.Timedelta(days=4)
        daily_before = daily[daily["timestamp"] < week_start]
        if len(daily_before) >= 33:
            high_33 = float(daily_before["high"].tail(33).max())
            pct_below = (high_33 - float(w["high"])) / high_33 * 100
            if pct_below <= 5.0:   # within 5% of the breakout level
                score += 1
            details["pct_below_33d_high"] = round(pct_below, 1)
        else:
            details["pct_below_33d_high"] = None

        results.append({
            "symbol":            symbol,
            "close":             round(float(w["close"]), 2),
            "conditions_met":    score,
            **details,
        })

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)
    df = df.sort_values(["conditions_met", "weekly_rsi"], ascending=[False, False])
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Data quality helper — tells the UI what we can and can't compute
# ---------------------------------------------------------------------------

def get_data_quality(db_path=DB_PATH) -> dict:
    """Return info about how much history is available for weekly indicator computation."""
    with sqlite3.connect(str(db_path)) as conn:
        r = conn.execute(
            "SELECT MIN(timestamp), MAX(timestamp), COUNT(DISTINCT symbol) "
            "FROM ohlcv_1day"
        ).fetchone()
    if not r or not r[0]:
        return {"min_date": None, "max_date": None, "n_symbols": 0, "n_weeks": 0}

    min_d = datetime.fromisoformat(r[0]).date()
    max_d = datetime.fromisoformat(r[1]).date()
    n_weeks = ((max_d - min_d).days) // 7
    return {
        "min_date": min_d,
        "max_date": max_d,
        "n_symbols": r[2],
        "n_weeks":   n_weeks,
        # Minimum weeks needed for each indicator to produce a value
        "rsi14_ok":    n_weeks >= 14,   # RSI(14) on weekly
        "cci20_ok":    n_weeks >= 20,   # CCI(20) on weekly
        "rsi_ma10_ok": n_weeks >= 24,   # RSI(14) + MA(10) on weekly
    }
