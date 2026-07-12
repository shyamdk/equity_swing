"""Q2 — Is THIS a good stock? (liquidity + the base)

Finds stocks in the "crouch before the jump": liquid, momentum reset, price coiled
in a tight sideways range, with volume drying up. Output is the **watchlist** —
candidates, not buys. Q3 decides when they actually wake up.

Each stock carries a `checklist` of sub-conditions so the UI can show *why* it
passed or failed. Sector (Q2.5) quadrant/score are attached for ranking.
"""
from __future__ import annotations

import pandas as pd
from loguru import logger

from backend import strategy_config as C
from backend.db import read_sql
from backend.services._data import recent_candles, sector_snapshot, universe

CRORE = 1e7
_NEEDED = 35            # candles required (vol dry-up needs 30)


def _evaluate(g: pd.DataFrame) -> dict | None:
    """Run the Q2 checks on one symbol's daily candles (oldest-first)."""
    if len(g) < _NEEDED:
        return None

    close = g["close"]
    high = g["high"]
    low = g["low"]
    vol = g["volume"].astype(float)
    rsi = g["rsi"]

    price = float(close.iloc[-1])

    # (0) Liquidity — can we get in and out?
    turnover_cr = float((close * vol).tail(20).mean() / CRORE)
    avg_vol_20 = float(vol.tail(20).mean())
    liquid = (turnover_cr >= C.MIN_TURNOVER_CR) or (avg_vol_20 >= C.MIN_AVG_VOL_20)
    price_ok = price >= C.MIN_PRICE

    # (a) Momentum reset — sellers exhausted, stock cooled off
    rsi_w = rsi.tail(C.RSI_MEAN_WINDOW)
    rsi_mean = float(rsi_w.mean())
    rsi_min = float(rsi_w.min())
    momentum_reset = (
        (C.RSI_MEAN_LO <= rsi_mean <= C.RSI_MEAN_HI) and (rsi_min < C.RSI_MIN_BELOW)
    )

    # (b) Base formation — tight sideways range (the coiled spring)
    w = g.tail(C.BASE_WINDOW)
    hi, lo = float(w["high"].max()), float(w["low"].min())
    range_pct = ((hi - lo) / lo * 100.0) if lo > 0 else float("inf")
    tight_base = range_pct < C.BASE_MAX_RANGE_PCT

    # (c) Volume dry-up — everyone stopped paying attention
    v_short = float(vol.tail(C.VOL_DRYUP_SHORT).mean())
    v_long = float(vol.tail(C.VOL_DRYUP_LONG).mean())
    vol_dryup = v_short < v_long

    checklist = {
        "price_above_min": price_ok,
        "liquid": liquid,
        "momentum_reset": momentum_reset,
        "tight_base": tight_base,
        "volume_dryup": vol_dryup,
    }

    return {
        "symbol": g["symbol"].iloc[0],
        "asof": g["timestamp"].iloc[-1],
        "close": round(price, 2),
        "turnover_cr": round(turnover_cr, 2),
        "avg_vol_20": int(avg_vol_20),
        "rsi_mean_25": round(rsi_mean, 1),
        "rsi_min_25": round(rsi_min, 1),
        "base_range_pct": round(range_pct, 1),
        "vol_10": int(v_short),
        "vol_30": int(v_long),
        "base_high": round(hi, 2),      # the "lid" Q3 needs to break
        "base_low": round(lo, 2),       # swing low for the Q4 stop
        "atr": round(float(g["atr"].iloc[-1]), 2) if pd.notna(g["atr"].iloc[-1]) else None,
        "checklist": checklist,
        "passed": all(checklist.values()),
    }


def scan(symbols: list[str] | None = None, only_passed: bool = False) -> pd.DataFrame:
    """Run Q2 across the universe. Returns one row per symbol with its checklist."""
    symbols = symbols or universe()
    candles = recent_candles("1day", _NEEDED, symbols)
    if candles.empty:
        return pd.DataFrame()

    rows = [r for _, g in candles.groupby("symbol", sort=False)
            if (r := _evaluate(g)) is not None]
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Attach sector (Q2.5) for preference/ranking.
    sectors = read_sql(
        "SELECT symbol, industry AS sector FROM symbols WHERE is_index = FALSE"
    )
    df = df.merge(sectors, on="symbol", how="left")
    df = df.merge(sector_snapshot(), on="sector", how="left")

    df = df.sort_values(["passed", "sector_score"], ascending=[False, False])
    df = df.reset_index(drop=True)

    if only_passed:
        df = df[df["passed"]].reset_index(drop=True)

    logger.info(f"Q2: {int(df['passed'].sum()) if 'passed' in df else 0} "
                f"of {len(df)} symbols in a valid base")
    return df
