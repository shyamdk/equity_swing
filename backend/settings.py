"""Persisted user settings — DB values layered over the strategy_config defaults.

Capital / risk % / caps live in the `settings` table rather than the browser, because
Q4 (sizing) and Q5 (exit ladder, R-multiples) must agree on the same numbers. A value
absent from the table falls back to the strategy_config default.
"""
from __future__ import annotations

from loguru import logger
from sqlalchemy import text

from backend import strategy_config as C
from backend.db import get_engine, read_sql

# Only these may be overridden from the UI. Everything else stays code/env-controlled.
EDITABLE: dict[str, type] = {
    "CAPITAL": float,
    "RISK_PCT": float,
    "MAX_POSITION_PCT": float,
    "MAX_TOTAL_DEPLOYED_PCT": float,
    "MAX_OPEN_POSITIONS": int,
}


def get_settings() -> dict:
    """Effective settings = DB overrides on top of the code defaults."""
    effective = {k: getattr(C, k) for k in EDITABLE}
    rows = read_sql("SELECT key, value FROM settings")
    for _, r in rows.iterrows():
        key = r["key"]
        if key in EDITABLE:
            try:
                effective[key] = EDITABLE[key](r["value"])
            except (TypeError, ValueError):
                logger.warning(f"settings: bad value for {key!r}, using default")
    return effective


def save_settings(values: dict) -> dict:
    """Upsert the editable settings. Unknown/invalid keys are ignored."""
    rows = []
    for key, val in values.items():
        if key not in EDITABLE or val is None:
            continue
        try:
            EDITABLE[key](val)          # validate it coerces
        except (TypeError, ValueError):
            continue
        rows.append({"key": key, "value": str(val)})

    if rows:
        with get_engine().begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO settings (key, value) VALUES (:key, :value) "
                    "ON CONFLICT (key) DO UPDATE "
                    "SET value = EXCLUDED.value, updated_at = now()"
                ),
                rows,
            )
        logger.info(f"settings saved: {[r['key'] for r in rows]}")
    return get_settings()


def reset_settings() -> dict:
    """Drop all overrides and fall back to the code defaults."""
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM settings"))
    return get_settings()
