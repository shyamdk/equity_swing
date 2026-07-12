"""Control strategies — the yardstick that makes the Robust Swing numbers interpretable.

Right now we cannot tell whether Robust Swing is a bad strategy or whether the REPLAY
ENGINE is wrong. Every number is uninterpretable without a baseline. These controls fix
that by running alternative ENTRIES through the exact same engine (same exits, same
sizing, same regime gate, same fills):

  robust  — the real thing: Q2 base → Q2.5 sector → Q3 breakout
  52w     — a classic, well-understood momentum entry: close at a 52-week high
  random  — random liquid stocks, no signal at all

Read the results like this:

  random ≈ robust        → our ENTRY adds no value; the signal is noise.
  random ≪ robust        → the entry IS doing work; the problem is elsewhere (exits).
  52w and robust BOTH ≪ 0 → suspect the ENGINE / data / fills, not the strategy.
  52w > 0 while robust < 0 → the engine is fine; Robust Swing specifically is weak.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backend import strategy_config as C
from backend.services._data import recent_candles, universe

CRORE = 1e7
_LOOKBACK = 260          # a 52-week high needs ~250 sessions


def _liquid(g: pd.DataFrame) -> bool:
    close, vol = g["close"], g["volume"].astype(float)
    turnover_cr = float((close * vol).tail(20).mean() / CRORE)
    return (
        float(close.iloc[-1]) >= C.MIN_PRICE
        and (turnover_cr >= C.MIN_TURNOVER_CR or float(vol.tail(20).mean()) >= C.MIN_AVG_VOL_20)
    )


def _row(g: pd.DataFrame, why: dict) -> dict:
    """Shape a candidate like a Q3 row, so the engine can size and store it unchanged."""
    return {
        "symbol": g["symbol"].iloc[0],
        "asof": g["timestamp"].iloc[-1],
        "close": float(g["close"].iloc[-1]),
        "atr": float(g["atr"].iloc[-1]) if pd.notna(g["atr"].iloc[-1]) else None,
        "base_low": float(g["low"].tail(20).min()),      # stop reference
        "base_high": float(g["high"].tail(20).max()),
        "sector": None,
        "quadrant": None,
        "sector_score": None,
        "checklist": why,
        "passed": True,
    }


def fifty_two_week_high(asof: str | None = None) -> pd.DataFrame:
    """Classic momentum entry: today's close is the highest in 52 weeks, on volume.

    Deliberately simple and widely documented — if this loses money through our engine
    too, the engine is the suspect, not the strategy.
    """
    candles = recent_candles("1day", _LOOKBACK, universe(), asof=asof)
    if candles.empty:
        return pd.DataFrame()

    rows = []
    for _, g in candles.groupby("symbol", sort=False):
        if len(g) < 200 or not _liquid(g):
            continue
        close = float(g["close"].iloc[-1])
        prior_high = float(g["high"].iloc[:-1].max())      # excludes today
        vol_ratio = float(g["volume"].iloc[-1]) / float(g["volume"].iloc[-21:-1].mean() or 1)
        if close > prior_high and vol_ratio >= 1.0:
            rows.append(_row(g, {"new_52w_high": True, "volume_ok": vol_ratio >= 1.0}))

    df = pd.DataFrame(rows)
    return df.sort_values("close", ascending=False).reset_index(drop=True) if not df.empty else df


def random_entry(asof: str | None = None, n: int = 3, seed: int | None = None) -> pd.DataFrame:
    """No signal at all — random liquid stocks.

    This is the control that matters most. If random entries through our exits perform
    about as well as Robust Swing's entries, then the entry signal is worthless and the
    whole Q2/Q3 funnel is decoration.
    """
    rng = np.random.default_rng(seed if seed is not None else abs(hash(asof)) % (2**32))
    candles = recent_candles("1day", 40, universe(), asof=asof)
    if candles.empty:
        return pd.DataFrame()

    eligible = [g for _, g in candles.groupby("symbol", sort=False)
                if len(g) >= 30 and _liquid(g) and pd.notna(g["atr"].iloc[-1])]
    if not eligible:
        return pd.DataFrame()

    picks = rng.choice(len(eligible), size=min(n, len(eligible)), replace=False)
    return pd.DataFrame([_row(eligible[i], {"random": True}) for i in picks])


SIGNALS = {
    "52w": fifty_two_week_high,
    "random": random_entry,
}
