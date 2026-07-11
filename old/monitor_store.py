"""Module-level monitor state — persists across Streamlit reruns (same process).

Usage:
    from src import monitor_store
    ms = monitor_store.get()
    if ms["running"]: ...
"""
from __future__ import annotations

import threading
from datetime import datetime

_lock  = threading.Lock()
_state: dict = {
    "running":          False,
    "last_run":         None,       # ISO8601 string
    "next_run":         None,       # ISO8601 string
    "interval_min":     15,         # intraday check interval (minutes)
    "last_signals":     [],         # list of signal dicts from last scan
    "notified_signals": set(),      # set of (symbol, week_date) already notified
    "last_exits":       [],         # exit events from last check
    "log":              [],         # last 50 log lines
    "error":            None,
    "_thread":          None,
    # Intraday / EOD tracking
    "watchlist":        [],         # symbols to price-check during market hours
    "last_eod_date":    None,       # "YYYY-MM-DD" of last completed EOD scan
}


def get() -> dict:
    with _lock:
        s = dict(_state)
        s["notified_signals"] = set(_state["notified_signals"])
        s["watchlist"] = list(_state["watchlist"])
        return s


def is_running() -> bool:
    with _lock:
        return bool(_state["running"])


def start(interval_min: int) -> None:
    with _lock:
        _state["running"]      = True
        _state["interval_min"] = interval_min
        _state["error"]        = None


def stop() -> None:
    with _lock:
        _state["running"] = False


def record_run(signals: list, exits: list, log_line: str) -> list[dict]:
    """Update state after a scan. Returns only NEW signals (not previously notified)."""
    with _lock:
        prev = _state["notified_signals"]
        new_signals = [
            s for s in signals
            if (s["symbol"], s["week_date"]) not in prev
        ]
        for s in new_signals:
            prev.add((s["symbol"], s["week_date"]))

        _state["last_run"]     = datetime.now().isoformat()
        _state["last_signals"] = signals
        _state["last_exits"]   = exits
        _state["log"].append(log_line)
        _state["log"]          = _state["log"][-50:]
        return new_signals


def set_next_run(dt: datetime) -> None:
    with _lock:
        _state["next_run"] = dt.isoformat()


def set_error(msg: str) -> None:
    with _lock:
        _state["error"]   = msg
        _state["running"] = False


def set_thread(t) -> None:
    with _lock:
        _state["_thread"] = t


def update_watchlist(symbols: list[str]) -> None:
    """Replace the intraday watchlist with a new list of symbols."""
    with _lock:
        _state["watchlist"] = list(symbols)


def get_watchlist() -> list[str]:
    with _lock:
        return list(_state["watchlist"])


def record_eod_date(date_str: str) -> None:
    """Record that the EOD scan completed for this date (YYYY-MM-DD)."""
    with _lock:
        _state["last_eod_date"] = date_str


def get_last_eod_date() -> str | None:
    with _lock:
        return _state["last_eod_date"]
