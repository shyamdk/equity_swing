"""Intraday quick price updater.

Fetches the latest 5-min candle close for a small watchlist of symbols.
Used by the Live Monitor to check paper trade exits during market hours
without running a full ingestion cycle.

Typical call: every 15-20 minutes for ~50-100 stocks.
At 1 req/s with the shared rate limiter, 50 stocks = ~50 seconds per cycle.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta

import pandas as pd
from loguru import logger

_IST_OFFSET = timedelta(hours=5, minutes=30)
_MARKET_OPEN  = (9,  15)   # HH, MM IST
_MARKET_CLOSE = (15, 30)   # HH, MM IST

# Shared persistent client — avoids re-login on every cycle
_client_lock = threading.Lock()
_shared_client = None


def _ist_now() -> datetime:
    """Return current time in IST (naive)."""
    return datetime.utcnow() + _IST_OFFSET


def is_market_open() -> bool:
    """Return True if NSE market is currently open (Mon–Fri, 09:15–15:30 IST)."""
    now = _ist_now()
    if now.weekday() >= 5:    # Sat / Sun
        return False
    open_  = now.replace(hour=_MARKET_OPEN[0],  minute=_MARKET_OPEN[1],  second=0, microsecond=0)
    close_ = now.replace(hour=_MARKET_CLOSE[0], minute=_MARKET_CLOSE[1], second=0, microsecond=0)
    return open_ <= now <= close_


def market_closed_today(last_eod_date: str | None) -> bool:
    """Return True if market has closed today AND we haven't done the EOD scan yet."""
    now = _ist_now()
    if now.weekday() >= 5:
        return False
    eod_threshold = now.replace(hour=_MARKET_CLOSE[0], minute=_MARKET_CLOSE[1] + 5,
                                 second=0, microsecond=0)
    if now < eod_threshold:
        return False
    # Already ran EOD today?
    if last_eod_date and last_eod_date == now.strftime("%Y-%m-%d"):
        return False
    return True


def _get_or_create_client():
    """Return (or create) a shared AngelClient for quick price fetches."""
    global _shared_client
    from src.angel_client import AngelClient
    with _client_lock:
        if _shared_client is None:
            c = AngelClient()
            c.login()
            c.load_instrument_master()
            _shared_client = c
            logger.info("Quick-updater: AngelClient session created")
        return _shared_client


def reset_client():
    """Force re-login on next fetch (call after session errors)."""
    global _shared_client
    with _client_lock:
        _shared_client = None


def fetch_latest_prices(symbols: list[str]) -> dict[str, float]:
    """Return {symbol: latest_close} using the most recent 5-min candle.

    Logs warnings for symbols that return no data.
    Returns an empty dict if the client can't be created.
    """
    if not symbols:
        return {}

    try:
        client = _get_or_create_client()
    except Exception as e:
        logger.error(f"Quick-updater: login failed — {e}")
        reset_client()
        return {}

    to_dt   = datetime.now()
    from_dt = to_dt - timedelta(minutes=60)    # last 60 min → at least a few candles
    prices  = {}

    for sym in symbols:
        try:
            df = client.get_candles(sym, "FIVE_MINUTE", from_dt, to_dt)
            if not df.empty:
                prices[sym] = float(df.iloc[-1]["close"])
        except Exception as e:
            logger.warning(f"Quick-updater: price fetch failed for {sym} — {e}")
            if "rate" in str(e).lower() or "session" in str(e).lower():
                reset_client()
                break

    logger.info(f"Quick prices fetched: {len(prices)}/{len(symbols)} symbols")
    return prices


def check_exits_with_prices(
    prices: dict[str, float],
    db_path,
) -> list[dict]:
    """Check open paper trades against intraday prices. Auto-close on target/SL.

    Similar to paper_portfolio.check_and_update_exits() but uses the provided
    prices dict instead of loading from the DB.
    """
    import sqlite3
    from src.paper_portfolio import close_trade, get_open_trades

    open_df = get_open_trades(db_path)
    if open_df.empty:
        return []

    exits = []
    for _, trade in open_df.iterrows():
        sym   = trade["symbol"]
        price = prices.get(sym)
        if price is None:
            continue

        trade_id     = int(trade["id"])
        trail_sl     = bool(trade["trail_sl"])
        current_sl   = float(trade["current_sl"])
        target_price = float(trade["target_price"])
        high_since   = float(trade["high_since_entry"])
        sl_pct       = float(trade["sl_pct"])

        # Update trailing SL
        if trail_sl and price > high_since:
            new_sl = round(price * (1 - sl_pct / 100), 2)
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    "UPDATE paper_trades SET current_sl=?, high_since_entry=? WHERE id=?",
                    (new_sl, price, trade_id),
                )
                conn.commit()
            current_sl = new_sl

        reason = None
        if price >= target_price:
            reason = "target"
        elif price <= current_sl:
            reason = "sl"

        if reason:
            pnl = close_trade(trade_id, price, reason, db_path)
            exits.append({
                "symbol":      sym,
                "trade_id":    trade_id,
                "exit_reason": reason,
                "exit_price":  price,
                "entry_price": float(trade["entry_price"]),
                "pnl":         pnl,
                "pnl_pct":     round((price / float(trade["entry_price"]) - 1) * 100, 2),
            })

    return exits
