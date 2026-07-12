"""Q3 — Is it waking up NOW? (the entry trigger)

A watchlist stock becomes a BUY only when the spring actually uncoils:
  1. Volume expansion  — today's vol >= 1.5x avg(20)      ("the crowd arrives")
  2. Price breakout    — close > highest high of prior 15  ("over the ceiling")
  3. Momentum confirms — RSI > 50 AND rising vs 5 days ago ("fresh energy")
  4. MTF confirm       — weekly close > weekly EMA20, or weekly RSI > 55
  5. Don't chase       — skip if already >8% past the breakout level

Q2.5 acts as a soft gate here: breakouts in a LAGGING sector are skipped, and the
survivors are ranked by SectorScore (doc Part 6.5).
"""
from __future__ import annotations

import pandas as pd
from loguru import logger

from backend import strategy_config as C
from backend.services._data import recent_candles, sector_snapshot, universe
from backend.services import base as q2

_DAILY_NEEDED = 25      # breakout lookback (15) + RSI lag (5) + headroom
_WEEKLY_NEEDED = 3


def _evaluate(g: pd.DataFrame, wk: pd.DataFrame | None) -> dict | None:
    """Run the Q3 checks on one symbol's daily candles (oldest-first)."""
    if len(g) < _DAILY_NEEDED:
        return None

    close = g["close"]
    today_close = float(close.iloc[-1])
    today_vol = float(g["volume"].iloc[-1])

    # 1. Volume expansion (vs the 20 days BEFORE today)
    avg_vol_20 = float(g["volume"].iloc[-21:-1].astype(float).mean())
    vol_ratio = (today_vol / avg_vol_20) if avg_vol_20 > 0 else 0.0
    vol_expansion = vol_ratio >= C.VOL_EXPANSION

    # 2. Price breakout over the lid = highest high of the PRIOR N days (excl. today)
    prior = g.iloc[-(C.BREAKOUT_LOOKBACK + 1):-1]
    breakout_level = float(prior["high"].max())
    breakout = today_close > breakout_level

    # 3. Momentum confirms
    rsi_now = float(g["rsi"].iloc[-1]) if pd.notna(g["rsi"].iloc[-1]) else 0.0
    rsi_prev = float(g["rsi"].iloc[-1 - C.RSI_RISING_LAG]) \
        if pd.notna(g["rsi"].iloc[-1 - C.RSI_RISING_LAG]) else 0.0
    momentum = (rsi_now > C.RSI_ENTRY_MIN) and (rsi_now > rsi_prev)

    # 4. Multi-timeframe confirm (don't fight the weekly chart)
    mtf = False
    w_close = w_ema20 = w_rsi = None
    if wk is not None and len(wk) >= _WEEKLY_NEEDED:
        w_close = float(wk["close"].iloc[-1])
        w_ema20 = float(wk["ema_20"].iloc[-1]) if pd.notna(wk["ema_20"].iloc[-1]) else None
        w_rsi = float(wk["rsi"].iloc[-1]) if pd.notna(wk["rsi"].iloc[-1]) else None
        mtf = ((w_ema20 is not None and w_close > w_ema20)
               or (w_rsi is not None and w_rsi > C.WEEKLY_RSI_MIN))

    # 5. Don't chase — how far past the lid are we already?
    past_pct = ((today_close - breakout_level) / breakout_level * 100.0) \
        if breakout_level > 0 else 0.0
    no_chase = past_pct <= C.NO_CHASE_PCT

    checklist = {
        "volume_expansion": vol_expansion,
        "price_breakout": breakout,
        "momentum_confirms": momentum,
        "weekly_confirms": mtf,
        "not_chasing": no_chase,
    }

    return {
        "symbol": g["symbol"].iloc[0],
        "asof": g["timestamp"].iloc[-1],
        "close": round(today_close, 2),
        "breakout_level": round(breakout_level, 2),
        "past_breakout_pct": round(past_pct, 1),
        "vol_ratio": round(vol_ratio, 2),
        "strong_volume": vol_ratio >= C.VOL_EXPANSION_STRONG,
        "rsi": round(rsi_now, 1),
        "rsi_5d_ago": round(rsi_prev, 1),
        "weekly_close": round(w_close, 2) if w_close else None,
        "weekly_ema20": round(w_ema20, 2) if w_ema20 else None,
        "weekly_rsi": round(w_rsi, 1) if w_rsi else None,
        "atr": round(float(g["atr"].iloc[-1]), 2) if pd.notna(g["atr"].iloc[-1]) else None,
        "checklist": checklist,
        "passed": all(checklist.values()),
    }


def scan(symbols: list[str] | None = None, from_watchlist: bool = True,
         only_passed: bool = False) -> pd.DataFrame:
    """Run Q3. By default only over stocks that passed Q2 (the watchlist)."""
    if symbols is None:
        if from_watchlist:
            wl = q2.scan(only_passed=True)
            symbols = wl["symbol"].tolist() if not wl.empty else []
        else:
            symbols = universe()
    if not symbols:
        logger.info("Q3: empty watchlist — nothing to check")
        return pd.DataFrame()

    daily = recent_candles("1day", _DAILY_NEEDED, symbols)
    weekly = recent_candles("1week", 5, symbols)
    if daily.empty:
        return pd.DataFrame()

    wk_by_sym = {s: g for s, g in weekly.groupby("symbol", sort=False)} if not weekly.empty else {}

    rows = [r for s, g in daily.groupby("symbol", sort=False)
            if (r := _evaluate(g, wk_by_sym.get(s))) is not None]
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # --- Q2.5 sector layer: soft-gate + rank ---
    from backend.db import read_sql
    sectors = read_sql(
        "SELECT symbol, industry AS sector FROM symbols WHERE is_index = FALSE"
    )
    df = df.merge(sectors, on="symbol", how="left").merge(
        sector_snapshot(), on="sector", how="left")

    df["sector_ok"] = True
    if C.SECTOR_AGGRESSIVE:
        df["sector_ok"] = df["quadrant"].isin(["leading", "improving"])
    elif C.SECTOR_SKIP_LAGGING:
        df["sector_ok"] = df["quadrant"] != "lagging"

    # Sector is a gate on the *trade*, recorded in the checklist for the UI.
    df["checklist"] = [
        {**c, "sector_in_season": bool(ok)}
        for c, ok in zip(df["checklist"], df["sector_ok"])
    ]
    df["passed"] = df["passed"] & df["sector_ok"]

    df = df.sort_values(["passed", "sector_score", "vol_ratio"],
                        ascending=[False, False, False]).reset_index(drop=True)
    if only_passed:
        df = df[df["passed"]].reset_index(drop=True)

    logger.info(f"Q3: {int(df['passed'].sum())} of {len(df)} breaking out now")
    return df
