"""Q1 — Market regime filter.

Rule (robust_swing_strategy.md Part 5): only take new buys when the market is
ABOVE its 200-day MA AND its 50-day MA is above its 200-day MA. We use the
NIFTY500EW composite as the market proxy and simple moving averages (DMA).
"""
from __future__ import annotations

import pandas as pd

from backend import strategy_config as C
from backend.services._data import recent_candles


def get_regime(asof: str | None = None, benchmark: str | None = None) -> dict:
    """Market-regime verdict with a pass/fail checklist, as it stood on `asof`.

    Uses the REAL index (NIFTY 50 by default) — see strategy_config.REGIME_BENCHMARK
    for why the synthetic equal-weight composite was the wrong choice here.
    """
    bm = benchmark or C.REGIME_BENCHMARK
    df = recent_candles("1day", 260, [bm], asof=asof)
    if df.empty or len(df) < 200:
        return {"benchmark": bm, "healthy": False,
                "reason": "insufficient benchmark history", "checklist": {}}

    close = df["close"]
    price = float(close.iloc[-1])
    dma50 = float(close.rolling(50).mean().iloc[-1])
    dma200 = float(close.rolling(200).mean().iloc[-1])

    above_200 = price > dma200
    golden = dma50 > dma200
    healthy = above_200 and golden

    return {
        "benchmark": bm,
        "asof": pd.Timestamp(df["timestamp"].iloc[-1]).strftime("%Y-%m-%d"),
        "healthy": healthy,
        "light": "🟢" if healthy else "🔴",
        "price": round(price, 2),
        "dma50": round(dma50, 2),
        "dma200": round(dma200, 2),
        "checklist": {
            "price_above_200dma": above_200,
            "50dma_above_200dma": golden,
        },
    }
