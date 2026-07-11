"""Q2.5 — Sector rotation (Relative Rotation Graph).

For each `Industry` sector we build an equal-weight composite from its Nifty 500
members, measure its relative strength vs the NIFTY500EW benchmark, and derive:

  RS(t)          = 100 * sector_level / benchmark_level
  RS-Ratio(t)    = 100 + zscore_63(RS)                       # is it strong?
  RS-Momentum(t) = 100 + zscore_63( RS-Ratio - RS-Ratio[-21] ) # strength rising?
  SectorScore    = 0.6*(sec-bench 3m return) + 0.4*(sec-bench 1m return)
  quadrant       = leading | improving | weakening | lagging

Results (full daily series) are stored in `sector_metrics`. See doc Part 6.5.
"""
from __future__ import annotations

import pandas as pd
from loguru import logger
from sqlalchemy import text

from backend.db import get_engine, read_sql
from backend.services.benchmark import pivot_daily_closes, equal_weight_level

RS_WINDOW = 63      # ~3 months, for z-score normalization
MOM_LAG = 21        # ~1 month, RS-Ratio change horizon


def _zscore_recentred(s: pd.Series, window: int) -> pd.Series:
    """(x - rolling_mean) / rolling_std, recentred on 100."""
    mean = s.rolling(window).mean()
    std = s.rolling(window).std(ddof=0)
    return 100.0 + (s - mean) / std.replace(0.0, pd.NA)


def _quadrant(ratio: float, mom: float) -> str:
    if pd.isna(ratio) or pd.isna(mom):
        return "n/a"
    if ratio >= 100 and mom >= 100:
        return "leading"
    if ratio < 100 and mom >= 100:
        return "improving"
    if ratio >= 100 and mom < 100:
        return "weakening"
    return "lagging"


def _sector_members() -> dict[str, list[str]]:
    """Return {industry: [symbols]} for Nifty 500 members."""
    df = read_sql(
        "SELECT symbol, industry FROM symbols WHERE is_index = FALSE AND industry IS NOT NULL"
    )
    return {sec: g["symbol"].tolist() for sec, g in df.groupby("industry")}


def compute_sector_metrics() -> pd.DataFrame:
    """Compute the full daily RRG metric series for every sector (long format)."""
    pivot = pivot_daily_closes()
    if pivot.empty:
        raise RuntimeError("No daily data to compute sector metrics.")

    bench = equal_weight_level(pivot)
    members = _sector_members()

    frames: list[pd.DataFrame] = []
    for sector, syms in members.items():
        cols = [s for s in syms if s in pivot.columns]
        if len(cols) < 3:                       # need a few names for a stable composite
            continue
        level = equal_weight_level(pivot[cols])
        rs = 100.0 * level / bench
        rs_ratio = _zscore_recentred(rs, RS_WINDOW)
        mom_raw = rs_ratio - rs_ratio.shift(MOM_LAG)
        rs_mom = _zscore_recentred(mom_raw, RS_WINDOW)

        sec_ret_3m = level / level.shift(RS_WINDOW) - 1
        sec_ret_1m = level / level.shift(MOM_LAG) - 1
        bench_ret_3m = bench / bench.shift(RS_WINDOW) - 1
        bench_ret_1m = bench / bench.shift(MOM_LAG) - 1
        score = 100.0 * (0.6 * (sec_ret_3m - bench_ret_3m) + 0.4 * (sec_ret_1m - bench_ret_1m))

        f = pd.DataFrame({
            "sector": sector,
            "ts": pd.to_datetime(level.index),
            "composite_close": level.values,
            "rs": rs.values,
            "rs_ratio": rs_ratio.values,
            "rs_momentum": rs_mom.values,
            "score": score.values,
        })
        f["quadrant"] = [_quadrant(r, m) for r, m in zip(f["rs_ratio"], f["rs_momentum"])]
        frames.append(f)

    out = pd.concat(frames, ignore_index=True)
    out = out.dropna(subset=["rs_ratio", "rs_momentum"])      # drop warmup rows
    return out


def build_sector_metrics() -> int:
    """Compute and upsert the full sector metric series into sector_metrics."""
    df = compute_sector_metrics()
    df = df.copy()
    df["ts"] = pd.to_datetime(df["ts"]).dt.date
    records = df.astype(object).where(pd.notnull(df), None).to_dict("records")

    cols = ["sector", "ts", "composite_close", "rs", "rs_ratio", "rs_momentum", "score", "quadrant"]
    placeholders = ", ".join(f":{c}" for c in cols)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c not in ("sector", "ts"))
    sql = text(
        f"INSERT INTO sector_metrics ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT (sector, ts) DO UPDATE SET {updates}"
    )
    with get_engine().begin() as conn:
        conn.execute(sql, records)
    logger.success(f"sector_metrics: {len(records)} rows upserted "
                   f"({df['sector'].nunique()} sectors)")
    return len(records)


def latest_ranking() -> pd.DataFrame:
    """Latest snapshot per sector, ranked by SectorScore (hottest first)."""
    return read_sql(
        "SELECT DISTINCT ON (sector) sector, ts, rs_ratio, rs_momentum, score, quadrant "
        "FROM sector_metrics ORDER BY sector, ts DESC"
    ).sort_values("score", ascending=False).reset_index(drop=True)
