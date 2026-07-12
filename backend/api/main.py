"""FastAPI backend — one endpoint group per Q-stage of Robust Swing v1.

Run (from project root):
    uvicorn backend.api.main:app --reload --port 8000
Docs: http://localhost:8000/docs
"""
from __future__ import annotations

import math
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend import strategy_config as C
from backend.db import ping, read_sql, scalar
from backend.services import base as q2, entry as q3
from backend.services.exits import evaluate_exit
from backend.services.paper import replay, run_cycle, stats
from backend.services.regime import get_regime
from backend.services.sector import latest_ranking
from backend.services.sizing import size_position
from backend.settings import get_settings, reset_settings, save_settings

app = FastAPI(
    title="Equity Swing — Robust Swing v1",
    description="One endpoint group per stage of the Q1→Q5 funnel.",
    version="1.0.0",
)

# Next.js dev server. Next picks the first free port from 3000, so allow a range
# rather than pinning one — otherwise the browser silently CORS-blocks every call.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):(300\d|301\d)",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _clean(obj: Any) -> Any:
    """Make pandas/NumPy output JSON-safe (NaN/NaT → None)."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    if obj is pd.NaT or obj is None:
        return None
    if isinstance(obj, pd.Timestamp):
        return obj.strftime("%Y-%m-%d")
    if hasattr(obj, "item"):          # numpy scalar
        return _clean(obj.item())
    return obj


def _records(df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []
    return _clean(df.to_dict("records"))


# ---------------------------------------------------------------------------
# meta
# ---------------------------------------------------------------------------

@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok" if ping() else "db_unreachable"}


@app.get("/config", tags=["meta"])
def config() -> dict:
    """All strategy knobs (Part 14) — so the UI can display/explain the rules."""
    return _clean(C.as_dict())


@app.get("/meta", tags=["meta"])
def meta() -> dict:
    """Universe + data freshness.

    Nothing here auto-refreshes: candles land when the ingest is run, and the sector
    metrics are a STORED snapshot that must be rebuilt afterwards — so it can silently
    lag the candles. We surface both dates and flag the gap rather than hide it.
    """
    universe_n = scalar("SELECT count(*) FROM symbols WHERE is_index = FALSE") or 0

    candles = read_sql(
        "SELECT interval, count(DISTINCT symbol) AS symbols, "
        "max(ts AT TIME ZONE :tz)::date AS latest "
        "FROM ohlcv GROUP BY interval ORDER BY interval",
        {"tz": "Asia/Kolkata"},
    )
    latest_daily = scalar(
        "SELECT max(ts AT TIME ZONE 'Asia/Kolkata')::date FROM ohlcv WHERE interval='1day'"
    )
    last_run = scalar("SELECT max(updated_at) FROM ingestion_state")
    sectors_asof = scalar("SELECT max(ts) FROM sector_metrics")
    bench_asof = scalar(
        "SELECT max(ts AT TIME ZONE 'Asia/Kolkata')::date FROM ohlcv "
        "WHERE symbol = 'NIFTY500EW' AND interval = '1day'"
    )

    # Business days between the newest candle and today.
    stale_days = None
    if latest_daily:
        stale_days = int(
            pd.bdate_range(pd.Timestamp(latest_daily), pd.Timestamp.now().normalize()).size - 1
        )

    # Sector snapshot older than the candles → the RRG is showing stale rotation.
    sector_lag = None
    if sectors_asof and latest_daily:
        sector_lag = (pd.Timestamp(latest_daily) - pd.Timestamp(sectors_asof)).days

    return _clean({
        "universe": {
            "name": "Nifty 500",
            "symbols": int(universe_n),
            "source": "ind_nifty500list.csv",
            "note": "Other index lists (Nifty 50/100/Midcap…) are tags, not separate universes.",
        },
        "data_asof": latest_daily,
        "stale_business_days": stale_days,
        "last_ingest_run": last_run,
        "sectors_asof": sectors_asof,
        "sector_lag_days": sector_lag,
        "benchmark_asof": bench_asof,
        "refresh": {
            "mode": "manual",
            "note": "Nothing is scheduled — data changes only when you run these.",
            "steps": [
                "python -m backend.cli ingest",
                "python -c 'from backend.services.benchmark import build_benchmark; build_benchmark()'",
                "python -c 'from backend.services.sector import build_sector_metrics; build_sector_metrics()'",
            ],
        },
        "intervals": _records(candles),
    })


@app.get("/symbols", tags=["meta"])
def symbols() -> list[dict]:
    """The Nifty 500 universe with sector + index tags."""
    df = read_sql("""
        SELECT s.symbol, s.company_name, s.industry AS sector,
               COALESCE(array_agg(t.tag) FILTER (WHERE t.tag IS NOT NULL), '{}') AS tags
        FROM symbols s LEFT JOIN symbol_tags t ON t.symbol = s.symbol
        WHERE s.is_index = FALSE
        GROUP BY s.symbol, s.company_name, s.industry
        ORDER BY s.symbol
    """)
    return _records(df)


# ---------------------------------------------------------------------------
# Q1 — market regime
# ---------------------------------------------------------------------------

@app.get("/regime", tags=["Q1 · regime"])
def regime() -> dict:
    """Is the whole market healthy? 🟢 trade / 🔴 wait."""
    return _clean(get_regime())


# ---------------------------------------------------------------------------
# Q2.5 — sector rotation (RRG)
# ---------------------------------------------------------------------------

@app.get("/sectors", tags=["Q2.5 · sectors"])
def sectors() -> list[dict]:
    """Latest sector ranking with RRG quadrant + score (hottest first)."""
    return _records(latest_ranking())


@app.get("/sectors/rrg", tags=["Q2.5 · sectors"])
def sectors_rrg(tail: int = Query(8, ge=1, le=40)) -> list[dict]:
    """RRG plot data: the last `tail` points per sector (the rotation trails)."""
    df = read_sql("""
        SELECT sector, ts, rs_ratio, rs_momentum, quadrant
        FROM (
            SELECT *, row_number() OVER (PARTITION BY sector ORDER BY ts DESC) AS rn
            FROM sector_metrics
        ) t WHERE rn <= :tail ORDER BY sector, ts
    """, {"tail": tail})
    if df.empty:
        return []
    return [
        {"sector": sec,
         "points": _clean(g[["ts", "rs_ratio", "rs_momentum", "quadrant"]].to_dict("records"))}
        for sec, g in df.groupby("sector")
    ]


# ---------------------------------------------------------------------------
# Q2 — the base (watchlist)
# ---------------------------------------------------------------------------

@app.get("/watchlist", tags=["Q2 · base"])
def watchlist(only_passed: bool = True) -> list[dict]:
    """Stocks in a valid base. Each row carries its pass/fail checklist."""
    return _records(q2.scan(only_passed=only_passed))


# ---------------------------------------------------------------------------
# Q3 — entry trigger
# ---------------------------------------------------------------------------

@app.get("/entries", tags=["Q3 · entry"])
def entries(only_passed: bool = False, from_watchlist: bool = True) -> list[dict]:
    """Stocks breaking out right now (volume + breakout + RSI + weekly + no-chase)."""
    return _records(q3.scan(from_watchlist=from_watchlist, only_passed=only_passed))


# ---------------------------------------------------------------------------
# Q4 — position sizing
# ---------------------------------------------------------------------------

class SizeRequest(BaseModel):
    entry: float
    atr: float
    swing_low: float | None = None
    capital: float | None = None
    risk_pct: float | None = None
    deployed_value: float = 0.0
    open_positions: int = 0


@app.post("/size", tags=["Q4 · sizing"])
def size(req: SizeRequest) -> dict:
    """Position sizing: qty = min(risk-based, per-position cap, cash available)."""
    return _clean(size_position(**req.model_dump()))


class SettingsUpdate(BaseModel):
    CAPITAL: float | None = None
    RISK_PCT: float | None = None
    MAX_POSITION_PCT: float | None = None
    MAX_TOTAL_DEPLOYED_PCT: float | None = None
    MAX_OPEN_POSITIONS: int | None = None


@app.get("/settings", tags=["Q4 · sizing"])
def settings_get() -> dict:
    """Persisted portfolio settings (capital, risk %, caps)."""
    return _clean(get_settings())


@app.put("/settings", tags=["Q4 · sizing"])
def settings_put(req: SettingsUpdate) -> dict:
    """Save portfolio settings. Stored server-side so Q4 and Q5 agree on capital."""
    return _clean(save_settings(req.model_dump(exclude_none=True)))


@app.post("/settings/reset", tags=["Q4 · sizing"])
def settings_reset() -> dict:
    """Drop overrides, fall back to the strategy defaults."""
    return _clean(reset_settings())


# ---------------------------------------------------------------------------
# Q5 — exits / open positions
# ---------------------------------------------------------------------------

@app.get("/positions", tags=["Q5 · exits"])
def positions(
    status: str = Query("all", pattern="^(open|closed|all)$"),
    run_tag: str = Query("replay", pattern="^(live|replay)$"),
) -> list[dict]:
    """Paper trades with their exit-ladder state and the full captured context."""
    clauses = ["run_tag = :rt"]
    params: dict = {"rt": run_tag}
    if status != "all":
        clauses.append("status = :st")
        params["st"] = status
    df = read_sql(
        f"SELECT * FROM paper_trades WHERE {' AND '.join(clauses)} ORDER BY entry_ts DESC",
        params,
    )
    return _records(df)


@app.get("/paper/stats", tags=["Q5 · exits"])
def paper_stats(run_tag: str = Query("replay", pattern="^(live|replay)$")) -> dict:
    """The scoreboard: win rate, avg R, expectancy, max drawdown. Is the edge real?"""
    return _clean(stats(run_tag))


@app.post("/paper/run", tags=["Q5 · exits"])
def paper_run(asof: str | None = None) -> dict:
    """Run one automatic cycle: advance exits, then take any qualifying entries."""
    return _clean(run_cycle(asof=asof, run_tag="live"))


@app.post("/paper/replay", tags=["Q5 · exits"])
def paper_replay(start: str, end: str) -> dict:
    """Re-run the funnel day-by-day over history to rebuild the track record."""
    return _clean(replay(start, end, reset=True))


class ExitRequest(BaseModel):
    entry: float
    initial_stop: float
    current_stop: float
    highest_since_entry: float
    latest_close: float
    latest_high: float
    atr: float
    days_held: int
    moved_to_breakeven: bool = False
    partial_booked: bool = False


@app.post("/exits/evaluate", tags=["Q5 · exits"])
def exits_evaluate(req: ExitRequest) -> dict:
    """Advance the exit ladder one bar (breakeven / partial / trail / time stop)."""
    return _clean(evaluate_exit(**req.model_dump()))


# ---------------------------------------------------------------------------
# charts
# ---------------------------------------------------------------------------

@app.get("/candles/{symbol}", tags=["charts"])
def candles(
    symbol: str,
    interval: str = Query("1day", pattern="^(5min|75min|125min|1day|1week)$"),
    limit: int = Query(300, ge=10, le=5000),
) -> dict:
    """OHLCV + indicators, shaped for TradingView lightweight-charts."""
    df = read_sql("""
        SELECT (ts AT TIME ZONE 'Asia/Kolkata') AS t, open, high, low, close, volume,
               rsi, atr, ema20, ema50, ema200
        FROM ohlcv WHERE symbol = :s AND interval = :i
        ORDER BY ts DESC LIMIT :n
    """, {"s": symbol.upper(), "i": interval, "n": limit})
    if df.empty:
        raise HTTPException(404, f"no {interval} candles for {symbol}")

    df = df.iloc[::-1].reset_index(drop=True)      # oldest-first (charts need this)
    intraday = interval in ("5min", "75min", "125min")
    fmt = "%Y-%m-%d %H:%M:%S" if intraday else "%Y-%m-%d"
    t = pd.to_datetime(df["t"]).dt.strftime(fmt)

    return _clean({
        "symbol": symbol.upper(),
        "interval": interval,
        "candles": [
            {"time": ti, "open": o, "high": h, "low": l, "close": c}
            for ti, o, h, l, c in zip(t, df["open"], df["high"], df["low"], df["close"])
        ],
        "volume": [{"time": ti, "value": v} for ti, v in zip(t, df["volume"])],
        "indicators": {
            name: [{"time": ti, "value": v}
                   for ti, v in zip(t, df[name]) if pd.notna(v)]
            for name in ("rsi", "atr", "ema20", "ema50", "ema200")
        },
    })
