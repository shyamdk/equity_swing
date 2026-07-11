"""Load index membership tags from MW-*.csv watchlist files.

For each file like MW-NIFTY-50-22-Mar-2026.csv, every stock symbol found in it
gets a tag (e.g. "Nifty50"). Tags are stored comma-separated in the symbol_tags table.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pandas as pd
from loguru import logger

from src.config import DB_PATH

# ---------------------------------------------------------------------------
# Filename → tag mapping
# Strip date suffix from filename, then map the base name to a clean tag.
# ---------------------------------------------------------------------------

_TAG_MAP: dict[str, str] = {
    "MW-NIFTY-50":                 "Nifty50",
    "MW-NIFTY-NEXT-50":            "NiftyNext50",
    "MW-NIFTY-100":                "Nifty100",
    "MW-NIFTY-200":                "Nifty200",
    "MW-NIFTY-500":                "Nifty500",
    "MW-NIFTY-BANK":               "BankNifty",
    "MW-NIFTY-FINANCIAL-SERVICES": "NiftyFinServ",
    "MW-NIFTY-LARGEMIDCAP-250":    "LargeMidcap250",
    "MW-NIFTY-MIDCAP-50":          "Midcap50",
    "MW-NIFTY-MIDCAP-100":         "Midcap100",
    "MW-NIFTY-MIDCAP-150":         "Midcap150",
    "MW-NIFTY-MIDCAP-SELECT":      "MidcapSelect",
    "MW-NIFTY-MIDSMALLCAP-400":    "MidSmallcap400",
    "MW-NIFTY-SMALLCAP-50":        "Smallcap50",
    "MW-NIFTY-SMALLCAP-100":       "Smallcap100",
    "MW-NIFTY-SMALLCAP-250":       "Smallcap250",
}

# Regex to strip the trailing date portion: -22-Mar-2026
_DATE_RE = re.compile(r"-\d{1,2}-[A-Za-z]{3}-\d{4}$")


def _file_to_tag(path: Path) -> str | None:
    """Derive a tag from the CSV filename. Returns None for unrecognised files."""
    stem = path.stem                          # e.g. "MW-NIFTY-50-22-Mar-2026"
    base = _DATE_RE.sub("", stem)             # e.g. "MW-NIFTY-50"
    tag  = _TAG_MAP.get(base)
    if tag is None:
        # Fallback: convert MW-NIFTY-FOO-BAR → NiftyFooBar
        tag = base.replace("MW-", "").title().replace("-", "")
        logger.warning(f"Unknown index file '{base}' — using auto-tag '{tag}'")
    return tag


def _read_symbols(path: Path) -> list[str]:
    """Return clean stock symbols from a MW watchlist CSV (skip index-name rows)."""
    df = pd.read_csv(path, encoding="utf-8-sig")
    df.columns = df.columns.str.strip()
    syms = df["SYMBOL"].dropna().str.strip().tolist()
    # The first entry is always the index name itself (e.g. "NIFTY 50") — drop it
    # More generally, skip any entry containing a space (index names have spaces,
    # stock symbols never do on NSE).
    return [s for s in syms if s and " " not in s]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

_CREATE_TAGS = """
CREATE TABLE IF NOT EXISTS symbol_tags (
    symbol  TEXT PRIMARY KEY,
    tags    TEXT NOT NULL DEFAULT ''
);
"""


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_TAGS)
    conn.commit()


def load_tags(
    data_dir: Path | None = None,
    db_path: Path = DB_PATH,
) -> dict[str, list[str]]:
    """Read all MW-*.csv files and return {symbol: [tag, ...]} mapping."""
    if data_dir is None:
        data_dir = db_path.parent          # data/ folder next to the DB

    csv_files = sorted(data_dir.glob("MW-*.csv"))
    if not csv_files:
        logger.warning(f"No MW-*.csv files found in {data_dir}")
        return {}

    symbol_tags: dict[str, set[str]] = {}
    for path in csv_files:
        tag = _file_to_tag(path)
        if not tag:
            continue
        symbols = _read_symbols(path)
        logger.info(f"{path.name} → tag '{tag}', {len(symbols)} symbols")
        for sym in symbols:
            symbol_tags.setdefault(sym, set()).add(tag)

    return {sym: sorted(tags) for sym, tags in symbol_tags.items()}


def upsert_tags(
    data_dir: Path | None = None,
    db_path: Path = DB_PATH,
) -> int:
    """Load tags from CSV files and upsert into the symbol_tags table.

    Existing tags are completely replaced (full refresh).
    Returns the number of symbols written.
    """
    mapping = load_tags(data_dir, db_path)
    if not mapping:
        return 0

    rows = [(sym, ",".join(tags)) for sym, tags in mapping.items()]

    with sqlite3.connect(str(db_path)) as conn:
        _ensure_table(conn)
        conn.execute("DELETE FROM symbol_tags")          # full refresh
        conn.executemany(
            "INSERT INTO symbol_tags (symbol, tags) VALUES (?, ?)", rows
        )
        conn.commit()

    logger.success(f"Tags upserted: {len(rows)} symbols")
    return len(rows)


def get_tags_map(db_path: Path = DB_PATH) -> dict[str, str]:
    """Return {symbol: tags_csv_string} for all symbols in symbol_tags."""
    try:
        with sqlite3.connect(str(db_path)) as conn:
            rows = conn.execute(
                "SELECT symbol, tags FROM symbol_tags"
            ).fetchall()
        return {r[0]: r[1] for r in rows}
    except Exception:
        return {}
