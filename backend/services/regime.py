"""Q1 — Market regime filter.

Rule (robust_swing_strategy.md Part 5): only take new buys when the market is
ABOVE its 200-day MA AND its 50-day MA is above its 200-day MA. We use the
NIFTY500EW composite as the market proxy and simple moving averages (DMA).
"""
from __future__ import annotations

import pandas as pd

from backend.services.benchmark import BENCHMARK_SYMBOL, benchmark_daily


def get_regime() -> dict:
    """Return the current market-regime verdict with a pass/fail checklist."""
    df = benchmark_daily(260)
    if df.empty or len(df) < 200:
        return {"benchmark": BENCHMARK_SYMBOL, "healthy": False,
                "reason": "insufficient benchmark history", "checklist": {}}

    close = df["close"]
    price = float(close.iloc[-1])
    dma50 = float(close.rolling(50).mean().iloc[-1])
    dma200 = float(close.rolling(200).mean().iloc[-1])

    above_200 = price > dma200
    golden = dma50 > dma200
    healthy = above_200 and golden

    return {
        "benchmark": BENCHMARK_SYMBOL,
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
