"""Q5 — When do I get out? (the exit ladder)

Everything is measured in **R** = the initial risk per share (entry - initial_stop).

  1. Initial stop (-1R)  : if hit, lose exactly 1R. No emotions.
  2. Breakeven at +1R    : raise stop to entry — the trade can no longer lose money.
  3. Book half at +2R    : lock in real profit; the rest rides.
  4. Chandelier trail    : stop = (highest high since entry) - 3 x ATR.
  5. Time stop           : flat (< +5%) after 15 trading days → exit, free the capital.

We deliberately do NOT exit on "RSI > 80" or a 10-day MA cross — those chop you out
of the big winners (doc Part 9).
"""
from __future__ import annotations

from backend import strategy_config as C


def evaluate_exit(
    entry: float,
    initial_stop: float,
    current_stop: float,
    highest_since_entry: float,
    latest_close: float,
    latest_high: float,
    atr: float,
    days_held: int,
    moved_to_breakeven: bool = False,
    partial_booked: bool = False,
    latest_low: float | None = None,
    latest_open: float | None = None,
) -> dict:
    """Advance the exit ladder one bar. Returns the new state + any exit action.

    Pure function — no DB. Caller persists the result to `paper_trades`.
    """
    r = entry - initial_stop                       # 1R per share
    if r <= 0:
        return {"error": "invalid initial stop (>= entry)"}

    high_water = max(highest_since_entry, latest_high)
    gain = latest_close - entry
    r_multiple = gain / r
    gain_pct = gain / entry * 100.0

    new_stop = current_stop
    actions: list[str] = []

    # 2. Breakeven at +1R
    if not moved_to_breakeven and r_multiple >= C.BREAKEVEN_R:
        new_stop = max(new_stop, entry)
        moved_to_breakeven = True
        actions.append(f"stop→breakeven at +{C.BREAKEVEN_R:g}R")

    # 3. Book half at +2R
    book_fraction = 0.0
    if not partial_booked and r_multiple >= C.PARTIAL_R:
        book_fraction = C.PARTIAL_FRACTION
        partial_booked = True
        actions.append(f"book {C.PARTIAL_FRACTION:.0%} at +{C.PARTIAL_R:g}R")

    # 4. Chandelier trail — only ratchets UP, never down
    chandelier = high_water - C.CHANDELIER_MULT * atr
    if partial_booked and chandelier > new_stop:
        new_stop = chandelier
        actions.append("chandelier trail raised")

    # --- exit conditions ---
    # A stop is a resting order: it triggers on the intraday LOW, and it FILLS at the
    # stop price — not at the day's close. Filling at the close is what let losers run
    # past the 1R cap the whole strategy depends on. If the bar gapped straight through
    # the stop, the honest fill is that gap-down open.
    low = latest_low if latest_low is not None else latest_close
    opn = latest_open if latest_open is not None else latest_close

    exit_now, exit_reason, exit_price = False, None, None
    if low <= new_stop:
        exit_now = True
        exit_reason = "stop" if not moved_to_breakeven else "trail"
        exit_price = min(new_stop, opn)      # gap-down → you fill at the open, worse
    elif (
        days_held >= C.TIME_STOP_DAYS
        and gain_pct < C.TIME_STOP_MIN_GAIN_PCT
        and r_multiple < C.TIME_STOP_MIN_R      # …and not making R progress either
    ):
        exit_now = True
        exit_reason = "time"          # dead money is a cost
        exit_price = latest_close

    return {
        "r_value": round(r, 2),
        "r_multiple": round(r_multiple, 2),
        "gain_pct": round(gain_pct, 2),
        "highest_since_entry": round(high_water, 2),
        "current_stop": round(new_stop, 2),
        "chandelier_stop": round(chandelier, 2),
        "moved_to_breakeven": moved_to_breakeven,
        "partial_booked": partial_booked,
        "book_fraction": book_fraction,
        "actions": actions,
        "exit": exit_now,
        "exit_reason": exit_reason,
        "exit_price": round(exit_price, 2) if exit_price is not None else None,
        "checklist": {
            "above_stop": latest_close > new_stop,
            "reached_breakeven": moved_to_breakeven,
            "booked_partial": partial_booked,
            "trailing_active": partial_booked,
            "time_stop_ok": not (days_held >= C.TIME_STOP_DAYS
                                 and gain_pct < C.TIME_STOP_MIN_GAIN_PCT),
        },
    }
