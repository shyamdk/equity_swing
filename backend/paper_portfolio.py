"""Paper trading portfolio — open/close trades, trailing SL, P&L tracking.

All trades use quantity = 1 by default.
Exit conditions (checked against latest daily close from DB):
  - Target hit : close >= entry * (1 + target_pct / 100)
  - SL hit     : close <= current_sl
  - Trailing SL: current_sl rises to latest_close * (1 - sl_pct / 100) whenever
                 latest_close makes a new high since entry.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
from loguru import logger

from src.config import DB_PATH

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_CREATE_PAPER_TRADES = """
CREATE TABLE IF NOT EXISTS paper_trades (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol            TEXT    NOT NULL,
    signal_week       TEXT,
    entry_date        TEXT    NOT NULL,
    entry_price       REAL    NOT NULL,
    qty               INTEGER NOT NULL DEFAULT 1,
    target_pct        REAL    NOT NULL DEFAULT 5.0,
    sl_pct            REAL    NOT NULL DEFAULT 5.0,
    trail_sl          INTEGER NOT NULL DEFAULT 0,
    target_price      REAL    NOT NULL,
    sl_price          REAL    NOT NULL,
    current_sl        REAL    NOT NULL,
    high_since_entry  REAL    NOT NULL,
    status            TEXT    NOT NULL DEFAULT 'open',
    exit_date         TEXT,
    exit_price        REAL,
    exit_reason       TEXT,
    pnl               REAL,
    pnl_pct           REAL,
    notes             TEXT
);
"""


def ensure_table(db_path: Path = DB_PATH) -> None:
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(_CREATE_PAPER_TRADES)
        conn.commit()


# ---------------------------------------------------------------------------
# Open / close
# ---------------------------------------------------------------------------

def open_trade(
    symbol: str,
    entry_price: float,
    signal_week: str = "",
    qty: int = 1,
    target_pct: float = 5.0,
    sl_pct: float = 5.0,
    trail_sl: bool = False,
    notes: str = "",
    db_path: Path = DB_PATH,
) -> int:
    """Open a paper trade. Returns the new trade id."""
    ensure_table(db_path)
    target     = round(entry_price * (1 + target_pct / 100), 2)
    sl         = round(entry_price * (1 - sl_pct   / 100), 2)
    entry_date = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    with sqlite3.connect(str(db_path)) as conn:
        cur = conn.execute(
            """INSERT INTO paper_trades
               (symbol, signal_week, entry_date, entry_price, qty,
                target_pct, sl_pct, trail_sl, target_price, sl_price,
                current_sl, high_since_entry, status, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (symbol, signal_week, entry_date, entry_price, qty,
             target_pct, sl_pct, int(trail_sl), target, sl,
             sl, entry_price, "open", notes),
        )
        conn.commit()
        trade_id = cur.lastrowid

    logger.info(
        f"Paper trade opened: {symbol} @ ₹{entry_price:.2f} | "
        f"target ₹{target:.2f} | SL ₹{sl:.2f} (id={trade_id})"
    )
    return trade_id


def close_trade(
    trade_id: int,
    exit_price: float,
    exit_reason: str = "manual",
    db_path: Path = DB_PATH,
) -> float:
    """Close a trade at exit_price. Returns realised P&L (₹)."""
    with sqlite3.connect(str(db_path)) as conn:
        row = conn.execute(
            "SELECT entry_price, qty FROM paper_trades WHERE id=?", (trade_id,)
        ).fetchone()
        if not row:
            return 0.0
        entry_price, qty = row
        pnl     = round((exit_price - entry_price) * qty, 2)
        pnl_pct = round((exit_price / entry_price - 1) * 100, 2)
        conn.execute(
            """UPDATE paper_trades SET
               status='closed', exit_date=?, exit_price=?,
               exit_reason=?, pnl=?, pnl_pct=?
               WHERE id=?""",
            (datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
             exit_price, exit_reason, pnl, pnl_pct, trade_id),
        )
        conn.commit()

    logger.info(
        f"Trade {trade_id} closed @ ₹{exit_price:.2f} | "
        f"reason={exit_reason} | P&L={pnl:+.2f} ({pnl_pct:+.1f}%)"
    )
    return pnl


# ---------------------------------------------------------------------------
# Exit checker — run daily after ingestion
# ---------------------------------------------------------------------------

def check_and_update_exits(db_path: Path = DB_PATH) -> list[dict]:
    """Check every open trade against the latest daily close stored in DB.

    Auto-closes trades that hit target or SL.
    Updates trailing SL if trade uses it.
    Returns list of exit-event dicts for notification.
    """
    from src.database import get_latest_candles

    ensure_table(db_path)
    open_df = get_open_trades(db_path)
    if open_df.empty:
        return []

    exits = []

    for _, trade in open_df.iterrows():
        candles = get_latest_candles(trade["symbol"], "1day", n=1, db_path=db_path)
        if candles.empty:
            continue

        latest_close     = float(candles.iloc[-1]["close"])
        trade_id         = int(trade["id"])
        trail_sl         = bool(trade["trail_sl"])
        current_sl       = float(trade["current_sl"])
        target_price     = float(trade["target_price"])
        high_since_entry = float(trade["high_since_entry"])
        sl_pct           = float(trade["sl_pct"])

        # --- Update trailing SL if new high ---
        if trail_sl and latest_close > high_since_entry:
            new_sl = round(latest_close * (1 - sl_pct / 100), 2)
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    "UPDATE paper_trades SET current_sl=?, high_since_entry=? WHERE id=?",
                    (new_sl, latest_close, trade_id),
                )
                conn.commit()
            current_sl = new_sl
            logger.debug(f"Trail SL updated for trade {trade_id}: new SL=₹{new_sl:.2f}")

        # --- Check exit ---
        reason = None
        if latest_close >= target_price:
            reason = "target"
        elif latest_close <= current_sl:
            reason = "sl"

        if reason:
            pnl = close_trade(trade_id, latest_close, reason, db_path)
            exits.append({
                "symbol":       trade["symbol"],
                "trade_id":     trade_id,
                "exit_reason":  reason,
                "exit_price":   latest_close,
                "entry_price":  float(trade["entry_price"]),
                "pnl":          pnl,
                "pnl_pct":      round((latest_close / float(trade["entry_price"]) - 1) * 100, 2),
            })

    return exits


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def get_open_trades(db_path: Path = DB_PATH) -> pd.DataFrame:
    ensure_table(db_path)
    with sqlite3.connect(str(db_path)) as conn:
        return pd.read_sql_query(
            "SELECT * FROM paper_trades WHERE status='open' ORDER BY entry_date DESC", conn
        )


def get_closed_trades(db_path: Path = DB_PATH) -> pd.DataFrame:
    ensure_table(db_path)
    with sqlite3.connect(str(db_path)) as conn:
        return pd.read_sql_query(
            "SELECT * FROM paper_trades WHERE status='closed' ORDER BY exit_date DESC", conn
        )


def get_portfolio_summary(db_path: Path = DB_PATH) -> dict:
    """Return summary stats for the paper portfolio."""
    closed = get_closed_trades(db_path)
    open_t = get_open_trades(db_path)

    if closed.empty:
        total_pnl = wins = losses = 0
        win_rate  = 0.0
        avg_win   = avg_loss = 0.0
    else:
        total_pnl = float(closed["pnl"].sum())
        wins      = int((closed["pnl"] > 0).sum())
        losses    = int((closed["pnl"] < 0).sum())
        win_rate  = wins / len(closed) * 100 if len(closed) else 0.0
        avg_win   = float(closed.loc[closed["pnl"] > 0, "pnl"].mean()) if wins  else 0.0
        avg_loss  = float(closed.loc[closed["pnl"] < 0, "pnl"].mean()) if losses else 0.0

    return {
        "open_trades":   len(open_t),
        "closed_trades": len(closed),
        "total_pnl":     total_pnl,
        "wins":          wins,
        "losses":        losses,
        "win_rate":      win_rate,
        "avg_win":       avg_win,
        "avg_loss":      avg_loss,
    }
