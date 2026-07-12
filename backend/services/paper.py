"""Automatic paper-trading engine.

Runs the whole funnel and trades it **without discretion** — that is the point. If a
human hand-picked which breakouts to take, the resulting statistics would measure the
human, not the system, and the paper phase would prove nothing.

Each cycle, for a given as-of date:
  1. Advance the Q5 exit ladder on every open trade (exits before entries — a slot
     freed today can be reused today).
  2. If Q1 says the market is healthy, take every qualifying Q3 breakout, in Q2.5
     rank order, until slots or cash run out.

Every entry stores a **full Q1→Q4 snapshot** in `entry_context` (regime, sector,
base metrics, breakout metrics, sizing maths, settings and portfolio state at the
time). Nothing is recomputed later from today's data, so the record stays honest and
can be mined to tune the model.

Fills are at the CLOSE of the breakout day, per the strategy doc ("enter on the
breakout candle"). That is mildly optimistic — in reality you see the signal only
once the bar closes.
"""
from __future__ import annotations

import json
from datetime import datetime

import pandas as pd
from loguru import logger
from sqlalchemy import text

from backend import strategy_config as C
from backend.db import get_engine, read_sql
from backend.services import base as q2, entry as q3
from backend.services.exits import evaluate_exit
from backend.services.regime import get_regime
from backend.services.sizing import size_position
from backend.settings import get_settings


# ---------------------------------------------------------------------------
# portfolio state
# ---------------------------------------------------------------------------

def open_trades(run_tag: str = "live") -> pd.DataFrame:
    return read_sql(
        "SELECT * FROM paper_trades WHERE status = 'open' AND run_tag = :t "
        "ORDER BY entry_ts",
        {"t": run_tag},
    )


def _deployed(open_df: pd.DataFrame) -> float:
    if open_df.empty:
        return 0.0
    qty = open_df["qty_open"].fillna(open_df["qty"])
    return float((qty * open_df["entry_price"]).sum())


def _bar(symbol: str, asof: str) -> dict | None:
    """The symbol's most recent daily bar at or before `asof`."""
    df = read_sql(
        "SELECT (ts AT TIME ZONE 'Asia/Kolkata')::date AS d, open, high, low, close, atr "
        "FROM ohlcv WHERE symbol = :s AND interval = '1day' "
        "AND (ts AT TIME ZONE 'Asia/Kolkata')::date <= :a ORDER BY ts DESC LIMIT 1",
        {"s": symbol, "a": asof},
    )
    return None if df.empty else df.iloc[0].to_dict()


def _bars_held(symbol: str, entry_date, asof: str) -> int:
    """Trading days the position has been held (bars strictly after entry)."""
    n = read_sql(
        "SELECT count(*) AS n FROM ohlcv WHERE symbol = :s AND interval = '1day' "
        "AND (ts AT TIME ZONE 'Asia/Kolkata')::date > :e "
        "AND (ts AT TIME ZONE 'Asia/Kolkata')::date <= :a",
        {"s": symbol, "e": str(entry_date), "a": asof},
    )["n"].iloc[0]
    return int(n)


# ---------------------------------------------------------------------------
# Q5 — advance the exit ladder
# ---------------------------------------------------------------------------

def manage_exits(asof: str, run_tag: str = "live") -> list[dict]:
    events: list[dict] = []
    trades = open_trades(run_tag)

    for _, t in trades.iterrows():
        bar = _bar(t["symbol"], asof)
        if not bar or pd.isna(bar["close"]):
            continue
        atr = float(bar["atr"]) if pd.notna(bar["atr"]) else float(t["r_value"]) / C.ATR_STOP_MULT
        entry_date = pd.Timestamp(t["entry_ts"]).tz_convert("Asia/Kolkata").date()
        held = _bars_held(t["symbol"], entry_date, asof)

        qty_open = int(t["qty_open"] if pd.notna(t["qty_open"]) else t["qty"])
        if qty_open <= 0:
            continue

        r = evaluate_exit(
            entry=float(t["entry_price"]),
            initial_stop=float(t["initial_stop"]),
            current_stop=float(t["current_stop"]),
            highest_since_entry=float(t["highest_since_entry"] or t["entry_price"]),
            latest_close=float(bar["close"]),
            latest_high=float(bar["high"]),
            latest_low=float(bar["low"]),
            latest_open=float(bar["open"]),
            atr=atr,
            days_held=held,
            moved_to_breakeven=bool(t["moved_to_breakeven"]),
            partial_booked=bool(t["partial_booked"]),
        )
        if "error" in r:
            continue

        realized = float(t["realized_pnl"] or 0.0)
        updates: dict = {
            "id": int(t["id"]),
            "current_stop": r["current_stop"],
            "highest_since_entry": r["highest_since_entry"],
            "moved_to_breakeven": r["moved_to_breakeven"],
            "partial_booked": r["partial_booked"],
        }

        # book half at +2R
        if r["book_fraction"] > 0 and not bool(t["partial_booked"]):
            pqty = int(qty_open * r["book_fraction"])
            if pqty > 0:
                realized += pqty * (float(bar["close"]) - float(t["entry_price"]))
                qty_open -= pqty
                updates |= {
                    "partial_ts": f"{asof} 15:30:00+05:30",
                    "partial_price": float(bar["close"]),
                    "partial_qty": pqty,
                }
                events.append({"symbol": t["symbol"], "action": "partial", "qty": pqty,
                               "price": float(bar["close"]), "asof": asof})

        updates |= {"qty_open": qty_open, "realized_pnl": realized}

        if r["exit"] and qty_open > 0:
            # Fill where the exit actually happened: a stop fills AT the stop (or the
            # gap-down open), not at the close. Only a time stop fills at the close.
            exit_px = float(r["exit_price"] if r.get("exit_price") is not None else bar["close"])
            pnl = realized + qty_open * (exit_px - float(t["entry_price"]))
            r_mult = pnl / (float(t["r_value"]) * int(t["qty"]))
            updates |= {
                "status": "closed",
                "exit_ts": f"{asof} 15:30:00+05:30",
                "exit_price": exit_px,
                "exit_reason": r["exit_reason"],
                "pnl": pnl,
                "r_multiple": r_mult,
                "days_held": held,
                "qty_open": 0,
                "exit_context": json.dumps({
                    "asof": asof, "reason": r["exit_reason"], "close": exit_px,
                    "stop_at_exit": r["current_stop"], "days_held": held,
                    "r_multiple": round(r_mult, 3), "ladder": r["checklist"],
                }),
            }
            events.append({"symbol": t["symbol"], "action": "exit",
                           "reason": r["exit_reason"], "r": round(r_mult, 2), "asof": asof})

        _update_trade(updates)

    return events


def _update_trade(u: dict) -> None:
    tid = u.pop("id")
    sets = ", ".join(f"{k} = :{k}" for k in u)
    casts = sets.replace("exit_context = :exit_context",
                         "exit_context = CAST(:exit_context AS jsonb)")
    with get_engine().begin() as conn:
        conn.execute(text(f"UPDATE paper_trades SET {casts} WHERE id = :id"),
                     {**u, "id": tid})


# ---------------------------------------------------------------------------
# Q1→Q4 — take entries
# ---------------------------------------------------------------------------

def take_entries(asof: str, run_tag: str = "live") -> list[dict]:
    regime = get_regime(asof=asof)
    if not regime.get("healthy"):
        return []                       # 🔴 no new buys, full stop

    wl = q2.scan(only_passed=True, asof=asof)
    if wl.empty:
        return []
    breakouts = q3.scan(symbols=wl["symbol"].tolist(), only_passed=True, asof=asof)
    if breakouts.empty:
        return []

    # base_low / base_high live on the Q2 row — needed for the stop.
    wl_by = wl.set_index("symbol").to_dict("index")

    cfg = get_settings()
    opened: list[dict] = []

    for _, e in breakouts.iterrows():          # already ranked by sector score
        cur = open_trades(run_tag)
        held = set(cur["symbol"])
        if e["symbol"] in held:
            continue                            # never pyramid into the same name
        if len(cur) >= int(cfg["MAX_OPEN_POSITIONS"]):
            break

        b = wl_by.get(e["symbol"], {})
        atr = e.get("atr") or b.get("atr")
        if not atr or pd.isna(atr):
            continue

        sizing = size_position(
            entry=float(e["close"]),
            atr=float(atr),
            swing_low=float(b["base_low"]) if b.get("base_low") else None,
            deployed_value=_deployed(cur),
            open_positions=len(cur),
        )
        if sizing["qty"] <= 0:
            continue                            # no cash / no slot

        context = {
            "captured_at": datetime.utcnow().isoformat(),
            "asof": asof,
            "q1_regime": regime,
            "q2_base": {k: b.get(k) for k in (
                "close", "turnover_cr", "avg_vol_20", "rsi_mean_25", "rsi_min_25",
                "base_range_pct", "base_high", "base_low", "atr", "checklist")},
            "q2_5_sector": {
                "sector": e.get("sector"), "quadrant": e.get("quadrant"),
                "score": _num(e.get("sector_score")),
                "rs_ratio": _num(e.get("rs_ratio")),
                "rs_momentum": _num(e.get("rs_momentum")),
            },
            "q3_entry": {k: _num(e.get(k)) for k in (
                "close", "breakout_level", "past_breakout_pct", "vol_ratio",
                "strong_volume", "rsi", "rsi_5d_ago", "weekly_close",
                "weekly_ema20", "weekly_rsi", "atr")} | {"checklist": e.get("checklist")},
            "q4_sizing": sizing,
            "settings": cfg,
            "portfolio_at_entry": {
                "open_positions": len(cur),
                "deployed_value": _deployed(cur),
            },
        }

        _insert_trade(e, sizing, context, cfg, asof, run_tag)
        opened.append({"symbol": e["symbol"], "action": "entry", "qty": sizing["qty"],
                       "price": float(e["close"]), "stop": sizing["stop"], "asof": asof})

    return opened


def _num(v):
    """JSON-safe scalar (numpy/NaN → python/None)."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if pd.isna(v) if not isinstance(v, (dict, list, str, bool)) else False:
        return None
    return v.item() if hasattr(v, "item") else v


def _text(v) -> str | None:
    """NaN → NULL for text columns. Pandas merges yield NaN, not None, for misses —
    e.g. a sector whose RRG metrics haven't warmed up yet."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return str(v)


def _json_safe(obj):
    """Recursively strip NaN/numpy from the context before it becomes JSON.

    json.dumps happily emits a bare `NaN` token, which is not valid JSON — Postgres
    rejects it outright. Any pandas-sourced value can be NaN, so sanitize the whole
    tree rather than each field by hand.
    """
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (bool, str)) or obj is None:
        return obj
    if hasattr(obj, "item"):                       # numpy scalar
        obj = obj.item()
    if isinstance(obj, float) and (pd.isna(obj) or obj in (float("inf"), float("-inf"))):
        return None
    return obj


def _insert_trade(e, sizing: dict, context: dict, cfg: dict, asof: str, run_tag: str) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text("""
            INSERT INTO paper_trades (
                symbol, status, entry_ts, entry_price, qty, qty_open,
                initial_stop, r_value, current_stop, highest_since_entry,
                sector, sector_quadrant, capital_at_entry, risk_pct_at_entry,
                realized_pnl, run_tag, entry_context
            ) VALUES (
                :symbol, 'open', :entry_ts, :entry_price, :qty, :qty,
                :stop, :r_value, :stop, :entry_price,
                :sector, :quadrant, :capital, :risk_pct,
                0, :run_tag, CAST(:ctx AS jsonb)
            )"""),
            {
                "symbol": e["symbol"],
                "entry_ts": f"{asof} 15:30:00+05:30",
                "entry_price": float(e["close"]),
                "qty": int(sizing["qty"]),
                "stop": float(sizing["stop"]),
                "r_value": float(sizing["risk_per_share"]),
                "sector": _text(e.get("sector")),
                "quadrant": _text(e.get("quadrant")),
                "capital": float(cfg["CAPITAL"]),
                "risk_pct": float(cfg["RISK_PCT"]),
                "run_tag": run_tag,
                "ctx": json.dumps(_json_safe(context), default=str),
            },
        )


# ---------------------------------------------------------------------------
# cycles
# ---------------------------------------------------------------------------

def run_cycle(asof: str | None = None, run_tag: str = "live") -> dict:
    """One trading day: manage exits, then take entries."""
    if asof is None:
        asof = str(read_sql(
            "SELECT max((ts AT TIME ZONE 'Asia/Kolkata')::date) AS d "
            "FROM ohlcv WHERE interval = '1day'"
        )["d"].iloc[0])

    exits = manage_exits(asof, run_tag)
    entries = take_entries(asof, run_tag)
    return {"asof": asof, "exits": exits, "entries": entries}


def replay(start: str, end: str, reset: bool = True) -> dict:
    """Re-run the whole funnel day by day over history to build a track record.

    Every scan is `asof`-bounded, so no future data can leak into a decision.
    """
    from backend.services._data import trading_days

    if reset:
        with get_engine().begin() as conn:
            conn.execute(text("DELETE FROM paper_trades WHERE run_tag = 'replay'"))

    days = trading_days(start, end)
    logger.info(f"Replaying {len(days)} trading days ({start} → {end})…")

    n_entries = n_exits = 0
    for i, d in enumerate(days, 1):
        out = run_cycle(asof=d, run_tag="replay")
        n_entries += len(out["entries"])
        n_exits += len([e for e in out["exits"] if e["action"] == "exit"])
        if i % 25 == 0 or i == len(days):
            logger.info(f"  [{i}/{len(days)}] {d} — {n_entries} entries, {n_exits} exits")

    return {"days": len(days), "entries": n_entries, "exits": n_exits, **stats("replay")}


# ---------------------------------------------------------------------------
# the scoreboard
# ---------------------------------------------------------------------------

def stats(run_tag: str = "live") -> dict:
    """Win rate, average R, expectancy, max drawdown — is the edge real?"""
    df = read_sql(
        "SELECT r_multiple, pnl, exit_reason, entry_ts FROM paper_trades "
        "WHERE status = 'closed' AND run_tag = :t ORDER BY entry_ts",
        {"t": run_tag},
    )
    if df.empty:
        return {"closed_trades": 0}

    r = df["r_multiple"].dropna()
    wins = r[r > 0]
    losses = r[r <= 0]
    equity = df["pnl"].cumsum()
    peak = equity.cummax()
    dd = (equity - peak).min()

    return {
        "closed_trades": len(df),
        "win_rate_pct": round(len(wins) / len(r) * 100, 1) if len(r) else 0.0,
        "avg_win_R": round(float(wins.mean()), 2) if len(wins) else 0.0,
        "avg_loss_R": round(float(losses.mean()), 2) if len(losses) else 0.0,
        "expectancy_R": round(float(r.mean()), 3) if len(r) else 0.0,
        "total_pnl": round(float(df["pnl"].sum()), 2),
        "max_drawdown": round(float(dd), 2) if pd.notna(dd) else 0.0,
        "open_trades": int(read_sql(
            "SELECT count(*) AS n FROM paper_trades WHERE status='open' AND run_tag=:t",
            {"t": run_tag})["n"].iloc[0]),
        "exit_reasons": df["exit_reason"].value_counts().to_dict(),
    }
