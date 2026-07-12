"""Robust Swing v1 — all tunable strategy knobs in one place.

Mirrors "Part 14 — All settings in one place" of robust_swing_strategy.md.
Every value is overridable via environment variable.
"""
from __future__ import annotations

import os


def _f(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _i(name: str, default: int) -> int:
    return int(os.getenv(name, default))


# --- Q2: universe / liquidity -------------------------------------------------
MIN_PRICE = _f("MIN_PRICE", 80.0)                 # ₹
MIN_TURNOVER_CR = _f("MIN_TURNOVER_CR", 5.0)      # avg 20d turnover, ₹ crore
MIN_AVG_VOL_20 = _i("MIN_AVG_VOL_20", 200_000)    # OR avg 20d volume (shares)

# --- Q2: the base ("crouch before the jump") ---------------------------------
RSI_MEAN_WINDOW = _i("RSI_MEAN_WINDOW", 25)
RSI_MEAN_LO = _f("RSI_MEAN_LO", 35.0)             # momentum reset band
RSI_MEAN_HI = _f("RSI_MEAN_HI", 48.0)
RSI_MIN_BELOW = _f("RSI_MIN_BELOW", 35.0)         # must have dipped below this
BASE_WINDOW = _i("BASE_WINDOW", 20)
BASE_MAX_RANGE_PCT = _f("BASE_MAX_RANGE_PCT", 20.0)   # (hi-lo)/lo over BASE_WINDOW
VOL_DRYUP_SHORT = _i("VOL_DRYUP_SHORT", 10)       # avg vol(10) < avg vol(30)
VOL_DRYUP_LONG = _i("VOL_DRYUP_LONG", 30)

# --- Q2.5: sector rotation ----------------------------------------------------
SECTOR_SKIP_LAGGING = os.getenv("SECTOR_SKIP_LAGGING", "true").lower() == "true"
SECTOR_AGGRESSIVE = os.getenv("SECTOR_AGGRESSIVE", "false").lower() == "true"
# aggressive = only trade Leading + Improving quadrants

# --- Q3: the breakout ---------------------------------------------------------
BREAKOUT_LOOKBACK = _i("BREAKOUT_LOOKBACK", 15)   # close > highest high of prior N days
VOL_EXPANSION = _f("VOL_EXPANSION", 1.5)          # today vol >= N x avg(20)
VOL_EXPANSION_STRONG = _f("VOL_EXPANSION_STRONG", 2.0)
RSI_ENTRY_MIN = _f("RSI_ENTRY_MIN", 50.0)         # RSI > 50 …
RSI_RISING_LAG = _i("RSI_RISING_LAG", 5)          # … and rising vs N days ago
WEEKLY_RSI_MIN = _f("WEEKLY_RSI_MIN", 55.0)       # MTF: weekly close>EMA20 OR wRSI>55
NO_CHASE_PCT = _f("NO_CHASE_PCT", 8.0)            # skip if >N% past breakout level

# --- Q4: position sizing ------------------------------------------------------
CAPITAL = _f("CAPITAL", 100_000.0)                # ₹
RISK_PCT = _f("RISK_PCT", 1.0)                    # % of capital risked per trade
ATR_STOP_MULT = _f("ATR_STOP_MULT", 2.0)          # initial stop = entry - N x ATR
MAX_POSITION_PCT = _f("MAX_POSITION_PCT", 20.0)   # max % of capital in one stock
MAX_OPEN_POSITIONS = _i("MAX_OPEN_POSITIONS", 6)

# --- Q5: the exit ladder ------------------------------------------------------
BREAKEVEN_R = _f("BREAKEVEN_R", 1.0)              # move stop to entry at +1R
PARTIAL_R = _f("PARTIAL_R", 2.0)                  # book half at +2R
PARTIAL_FRACTION = _f("PARTIAL_FRACTION", 0.5)
CHANDELIER_MULT = _f("CHANDELIER_MULT", 3.0)      # trail = highest high - N x ATR
TIME_STOP_DAYS = _i("TIME_STOP_DAYS", 15)         # exit if flat after N trading days
TIME_STOP_MIN_GAIN_PCT = _f("TIME_STOP_MIN_GAIN_PCT", 5.0)


def as_dict() -> dict:
    """All settings (for the /config API endpoint + UI display)."""
    return {k: v for k, v in globals().items()
            if k.isupper() and not k.startswith("_")}
