"""
Thread-safe progress store for background ingestion.

Lives in an imported module so it persists in sys.modules across Streamlit
reruns — unlike script-level globals which are reset on every rerun.
Both the Streamlit main thread and background threads can safely read/write _state.
"""
from datetime import datetime

_state: dict = {
    "running": False,
    "progress": 0,
    "current_idx": 0,
    "total": 0,
    "current": "",
    "log": [],
    "done": False,
    "error": None,
}


def reset() -> None:
    _state.update({
        "running": True,
        "progress": 0,
        "current_idx": 0,
        "total": 0,
        "current": "",
        "log": [],
        "done": False,
        "error": None,
    })


def get() -> dict:
    return dict(_state)


def on_progress(current: int, total: int, symbol: str) -> None:
    _state["progress"] = int(current / total * 100)
    _state["current_idx"] = current
    _state["total"] = total
    _state["current"] = symbol
    _state["log"].append(
        f"{datetime.now().strftime('%H:%M:%S')}  [{current}/{total}]  {symbol}"
    )


def on_done() -> None:
    _state["done"] = True
    _state["running"] = False


def on_error(msg: str) -> None:
    _state["error"] = msg
    _state["running"] = False
