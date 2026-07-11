"""Load reference data into Postgres:

  - `symbols`      ← ind_nifty500list.csv  (symbol, company, industry/sector, series, isin)
  - `symbol_tags`  ← MW-*.csv index membership files  (symbol, tag) one row per tag

`industry` on the symbols table is the sector used by Q2.5 sector rotation.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from loguru import logger
from sqlalchemy import text

from backend.config import NIFTY500_CSV, ROOT_DIR
from backend.db import get_engine, read_sql

DATA_DIR = ROOT_DIR / "data"

# MW-*.csv filename (date-stripped) → clean tag.
_TAG_MAP: dict[str, str] = {
    "MW-NIFTY-50": "Nifty50", "MW-NIFTY-NEXT-50": "NiftyNext50",
    "MW-NIFTY-100": "Nifty100", "MW-NIFTY-200": "Nifty200", "MW-NIFTY-500": "Nifty500",
    "MW-NIFTY-BANK": "BankNifty", "MW-NIFTY-FINANCIAL-SERVICES": "NiftyFinServ",
    "MW-NIFTY-LARGEMIDCAP-250": "LargeMidcap250",
    "MW-NIFTY-MIDCAP-50": "Midcap50", "MW-NIFTY-MIDCAP-100": "Midcap100",
    "MW-NIFTY-MIDCAP-150": "Midcap150", "MW-NIFTY-MIDCAP-SELECT": "MidcapSelect",
    "MW-NIFTY-MIDSMALLCAP-400": "MidSmallcap400",
    "MW-NIFTY-SMALLCAP-50": "Smallcap50", "MW-NIFTY-SMALLCAP-100": "Smallcap100",
    "MW-NIFTY-SMALLCAP-250": "Smallcap250",
}
_DATE_RE = re.compile(r"-\d{1,2}-[A-Za-z]{3}-\d{4}$")


# ---------------------------------------------------------------------------
# Symbols master
# ---------------------------------------------------------------------------

def load_symbols_master() -> int:
    """Upsert the Nifty 500 list (with sector) into the `symbols` table."""
    df = pd.read_csv(NIFTY500_CSV)
    df.columns = df.columns.str.strip()
    df = df.rename(columns={
        "Company Name": "company_name", "Industry": "industry",
        "Symbol": "symbol", "Series": "series", "ISIN Code": "isin",
    })
    df = df[df["series"].str.strip() == "EQ"]
    for c in ("symbol", "company_name", "industry", "series", "isin"):
        df[c] = df[c].astype(str).str.strip()

    records = df[["symbol", "company_name", "industry", "series", "isin"]].to_dict("records")
    sql = text(
        "INSERT INTO symbols (symbol, company_name, industry, series, isin, is_index) "
        "VALUES (:symbol, :company_name, :industry, :series, :isin, FALSE) "
        "ON CONFLICT (symbol) DO UPDATE SET "
        "company_name = EXCLUDED.company_name, industry = EXCLUDED.industry, "
        "series = EXCLUDED.series, isin = EXCLUDED.isin"
    )
    with get_engine().begin() as conn:
        conn.execute(sql, records)
    logger.success(f"symbols master: {len(records)} rows upserted")
    return len(records)


# ---------------------------------------------------------------------------
# Index-membership tags
# ---------------------------------------------------------------------------

def _file_to_tag(path: Path) -> str:
    base = _DATE_RE.sub("", path.stem)
    tag = _TAG_MAP.get(base)
    if tag is None:
        tag = base.replace("MW-", "").title().replace("-", "")
        logger.warning(f"Unknown index file '{base}' — auto-tag '{tag}'")
    return tag


def _read_symbols(path: Path) -> list[str]:
    df = pd.read_csv(path, encoding="utf-8-sig")
    df.columns = df.columns.str.strip()
    syms = df["SYMBOL"].dropna().str.strip().tolist()
    # Index-name rows contain spaces (e.g. "NIFTY 50"); real NSE tickers never do.
    return [s for s in syms if s and " " not in s]


def load_tags(data_dir: Path | None = None) -> int:
    """Full-refresh symbol_tags (one row per (symbol, tag)) from MW-*.csv files."""
    data_dir = data_dir or DATA_DIR
    files = sorted(data_dir.glob("MW-*.csv"))
    if not files:
        logger.warning(f"No MW-*.csv files in {data_dir}")
        return 0

    rows: list[dict] = []
    for path in files:
        tag = _file_to_tag(path)
        syms = _read_symbols(path)
        logger.info(f"{path.name} → '{tag}', {len(syms)} symbols")
        rows.extend({"symbol": s, "tag": tag} for s in syms)

    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM symbol_tags"))
        # Only tag symbols we know about (FK to symbols).
        conn.execute(text(
            "INSERT INTO symbol_tags (symbol, tag) "
            "SELECT :symbol, :tag WHERE EXISTS (SELECT 1 FROM symbols WHERE symbol = :symbol) "
            "ON CONFLICT DO NOTHING"
        ), rows)

    n = read_sql("SELECT count(*) AS n FROM symbol_tags")["n"].iloc[0]
    logger.success(f"symbol_tags: {int(n)} rows written")
    return int(n)


def load_all() -> dict:
    """Load symbols master then tags. Returns counts."""
    n_sym = load_symbols_master()
    n_tags = load_tags()
    return {"symbols": n_sym, "symbol_tags": n_tags}
