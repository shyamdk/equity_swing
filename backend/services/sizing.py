"""Q4 — How much do I buy? (position sizing)

The golden rule: never risk more than 1% of capital on one trade. The STOP decides
the size, not a fixed quantity:

    qty = (capital x risk%) / (entry - stop)
    stop = the TIGHTER of: the base's swing low, or entry - 2xATR

A bouncier stock (bigger ATR → wider stop) automatically gets a smaller quantity,
so every trade risks the same rupees. See doc Part 8.
"""
from __future__ import annotations

import math

from backend import strategy_config as C


def compute_stop(entry: float, atr: float, swing_low: float | None = None) -> dict:
    """Initial stop = tighter (i.e. closest to entry) of swing-low / entry - N x ATR."""
    atr_stop = entry - C.ATR_STOP_MULT * atr
    if swing_low is not None and swing_low < entry:
        stop = max(atr_stop, swing_low)     # "tighter" = higher stop = smaller risk
        source = "swing_low" if swing_low > atr_stop else "atr"
    else:
        stop, source = atr_stop, "atr"
    return {"stop": round(stop, 2), "atr_stop": round(atr_stop, 2),
            "swing_low": swing_low, "stop_source": source}


def size_position(
    entry: float,
    atr: float,
    swing_low: float | None = None,
    capital: float = None,
    risk_pct: float = None,
) -> dict:
    """Return quantity, stop, and the risk breakdown for one trade."""
    capital = capital if capital is not None else C.CAPITAL
    risk_pct = risk_pct if risk_pct is not None else C.RISK_PCT

    s = compute_stop(entry, atr, swing_low)
    stop = s["stop"]
    risk_per_share = entry - stop

    if risk_per_share <= 0:
        return {**s, "qty": 0, "reason": "stop is at/above entry — no valid trade"}

    risk_amount = capital * risk_pct / 100.0
    qty = math.floor(risk_amount / risk_per_share)

    # Cap: no single position may exceed MAX_POSITION_PCT of capital.
    max_value = capital * C.MAX_POSITION_PCT / 100.0
    qty_cap = math.floor(max_value / entry) if entry > 0 else 0
    capped = qty > qty_cap
    qty = min(qty, qty_cap)

    position_value = qty * entry
    actual_risk = qty * risk_per_share

    return {
        **s,
        "entry": round(entry, 2),
        "atr": round(atr, 2),
        "qty": int(qty),
        "risk_per_share": round(risk_per_share, 2),   # = 1R per share
        "risk_amount": round(actual_risk, 2),         # rupees at risk if stop hits
        "risk_pct_of_capital": round(actual_risk / capital * 100.0, 2),
        "position_value": round(position_value, 2),
        "position_pct_of_capital": round(position_value / capital * 100.0, 2),
        "capped_by_max_position": capped,
        "capital": capital,
    }
