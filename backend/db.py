"""SQLAlchemy engine + low-level helpers for Postgres / TimescaleDB.

All higher-level DB access (database.py, reference.py, services) goes through here
so there is a single engine/connection-pool for the process.
"""
from __future__ import annotations

from functools import lru_cache

import pandas as pd
from loguru import logger
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from backend.config import DATABASE_URL


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return a process-wide SQLAlchemy engine (lazy, cached)."""
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
    logger.debug(f"DB engine created for {engine.url.render_as_string(hide_password=True)}")
    return engine


def read_sql(sql: str, params: dict | None = None) -> pd.DataFrame:
    """Run a SELECT and return a DataFrame."""
    with get_engine().connect() as conn:
        return pd.read_sql_query(text(sql), conn, params=params or {})


def execute(sql: str, params: dict | list[dict] | None = None) -> None:
    """Run a write statement (optionally executemany when params is a list)."""
    with get_engine().begin() as conn:
        conn.execute(text(sql), params if params is not None else {})


def scalar(sql: str, params: dict | None = None):
    """Return the first column of the first row (or None)."""
    with get_engine().connect() as conn:
        return conn.execute(text(sql), params or {}).scalar()


def ping() -> bool:
    """True if the database is reachable."""
    try:
        return scalar("SELECT 1") == 1
    except Exception as e:  # pragma: no cover
        logger.error(f"DB ping failed: {e}")
        return False
