"""Streamlit UI: Ingestion Dashboard + Stock Explorer. Run with: streamlit run app.py"""
import time
import threading
from datetime import datetime, timedelta, date

import pandas as pd
import streamlit as st

from src.config import ALL_INTERVALS, DB_PATH, INITIAL_LOOKBACK_DAYS_DAILY
from src.database import (
    get_ingestion_status,
    get_latest_candles,
    get_symbols,
    get_db_stats,
    init_db,
    reset_ingestion_state,
)
from src import progress_store  # module-level dict — survives Streamlit reruns
from src.database import get_stale_symbols
from src.tag_loader import upsert_tags, get_tags_map
from src import monitor_store
from src.paper_portfolio import (
    ensure_table as _ensure_portfolio,
    open_trade, close_trade,
    get_open_trades, get_closed_trades,
    get_portfolio_summary, check_and_update_exits,
)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Equity Swing — Data Dashboard",
    page_icon="📈",
    layout="wide",
)

# ---------------------------------------------------------------------------
# One-time DB init (cached so it doesn't re-run on every rerun)
# ---------------------------------------------------------------------------

@st.cache_resource
def _init_db_once():
    init_db()
    return True

_init_db_once()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _staleness_label(last_at, interval: str = ""):
    if not last_at:
        return "⬜ Never"
    try:
        ts = datetime.fromisoformat(last_at)
        if ts.tzinfo is not None:
            ts = ts.replace(tzinfo=None)
        delta = datetime.now() - ts
        days = delta.days
        # For weekly data the last candle is always Friday — up to 7 days old is current
        if interval == "1week":
            return "🟢 Current" if days <= 7 else f"🔴 {days}d ago"
        # For daily/intraday use business-day-aware thresholds
        if days == 0:
            return "🟢 Today"
        elif days <= 3:   # covers weekend gap (Fri→Mon = 3 days)
            return f"🟡 {days}d ago"
        else:
            return f"🔴 {days}d ago"
    except Exception:
        return "❓ Unknown"


def _start_ingestion(dry_run: bool):
    """Reset the progress store and launch ingestion in a background thread."""
    from src.data_ingestor import run as ingest_run

    progress_store.reset()

    def _task():
        try:
            ingest_run(dry_run=dry_run, progress_callback=progress_store.on_progress)
            progress_store.on_done()
        except Exception as e:
            progress_store.on_error(str(e))

    threading.Thread(target=_task, daemon=True).start()


def _start_selective_ingestion(symbols: list[str]):
    """Launch a selective re-ingestion for the given symbols list."""
    from src.data_ingestor import run_selective

    progress_store.reset()

    def _task():
        try:
            run_selective(symbols, progress_callback=progress_store.on_progress)
            progress_store.on_done()
        except Exception as e:
            progress_store.on_error(str(e))

    threading.Thread(target=_task, daemon=True).start()


def _start_weekly_backfill():
    """Backfill 1-week candles from existing 1-day DB data (no API calls)."""
    from src.data_ingestor import backfill_weekly

    progress_store.reset()

    def _task():
        try:
            backfill_weekly(progress_callback=progress_store.on_progress)
            progress_store.on_done()
        except Exception as e:
            progress_store.on_error(str(e))

    threading.Thread(target=_task, daemon=True).start()


def _update_tags() -> int:
    """Read MW-*.csv files from data/ and upsert into symbol_tags table."""
    return upsert_tags(db_path=DB_PATH)


# ---------------------------------------------------------------------------
# Live monitor background task
# ---------------------------------------------------------------------------

def _notify_exits(exits: list[dict]):
    """Send push/email notifications for exit events."""
    from src.notifier import notify
    for ex in exits:
        emoji  = "🎯" if ex["exit_reason"] == "target" else "🛑"
        reason = "Target hit" if ex["exit_reason"] == "target" else "Stop-Loss hit"
        body   = (
            f"{reason}: {ex['symbol']}\n"
            f"Exit ₹{ex['exit_price']} | P&L {ex['pnl']:+.2f} ({ex['pnl_pct']:+.1f}%)"
        )
        notify(f"{emoji} {reason}: {ex['symbol']}", body, priority="urgent")


def _run_intraday_check():
    """Quick price fetch + exit check during market hours (no full scan)."""
    from src.quick_updater import fetch_latest_prices, check_exits_with_prices

    watchlist = monitor_store.get_watchlist()
    if not watchlist:
        log_line = f"{datetime.now().strftime('%H:%M')} [intraday] — watchlist empty, skipping"
        monitor_store.record_run([], [], log_line)
        return

    try:
        prices = fetch_latest_prices(watchlist)
        exits  = check_exits_with_prices(prices, DB_PATH) if prices else []

        log_line = (
            f"{datetime.now().strftime('%H:%M')} [intraday] — "
            f"prices: {len(prices)}/{len(watchlist)}, exits: {len(exits)}"
        )
        monitor_store.record_run([], exits, log_line)
        _notify_exits(exits)
    except Exception as e:
        monitor_store.set_error(str(e))


def _run_eod_scan(params: dict):
    """Full delta ingestion + Siva-95 scan (once per day after market close)."""
    from src.siva95_scanner import scan_siva95, scan_siva95_near
    from src.notifier import notify
    from src.data_ingestor import run as ingest_run

    try:
        # 1. Delta ingest all symbols so daily data is current
        ingest_run()

        # 2. Siva-95 signal scan
        today  = date.today()
        from_d = today - timedelta(days=7)
        results = scan_siva95(
            from_date=from_d,
            to_date=today,
            rsi_lo=params["rsi_lo"],
            rsi_hi=params["rsi_hi"],
            cci_min=params["cci_min"],
            require_cci=params["require_cci"],
            require_rsi_above_ma=params["require_rsi_ma"],
            rsi_below50_days=params["rsi_below50"],
            vol_compare_weeks=4,
            vol_ratio_min=1.0,
            min_avg_vol_5=params["min_vol"],
            min_price=params["min_price"],
            db_path=DB_PATH,
        )
        signals = results.to_dict("records") if not results.empty else []

        # 3. Check daily exits
        exits = check_and_update_exits(DB_PATH)

        log_line = (
            f"{datetime.now().strftime('%H:%M')} [EOD] — "
            f"{len(signals)} signal(s), {len(exits)} exit(s)"
        )
        new_signals = monitor_store.record_run(signals, exits, log_line)
        monitor_store.record_eod_date(date.today().isoformat())

        # 4. Notify new entry signals
        for s in new_signals:
            body = (
                f"Symbol: {s['symbol']}\n"
                f"Week: {s['week_date']}\n"
                f"Close: ₹{s['close']}\n"
                f"Weekly RSI: {s['weekly_rsi']}\n"
                f"Breakout: +{s['breakout_pct']}%"
            )
            html = (
                f"<h3>Siva-95 Entry Signal</h3>"
                f"<b>{s['symbol']}</b> — week of {s['week_date']}<br>"
                f"Close ₹{s['close']} &nbsp;|&nbsp; RSI {s['weekly_rsi']}<br>"
                f"Breakout +{s['breakout_pct']}% above 33-day prior high"
            )
            notify(f"📈 Siva-95: {s['symbol']}", body, html, priority="high")

        # 5. Notify exits
        _notify_exits(exits)

        # 6. Rebuild intraday watchlist: open trades + top near-condition stocks
        _refresh_monitor_watchlist(params)

    except Exception as e:
        monitor_store.set_error(str(e))


def _refresh_monitor_watchlist(params: dict):
    """Build watchlist = open trade symbols + top near-condition stocks."""
    from src.siva95_scanner import scan_siva95_near

    open_df = get_open_trades(DB_PATH)
    open_syms = open_df["symbol"].tolist() if not open_df.empty else []

    try:
        near_df = scan_siva95_near(
            DB_PATH,
            min_price=params.get("min_price", 25.0),
            min_avg_vol_5=int(params.get("min_vol", 100_000)),
        )
        near_syms = near_df["symbol"].head(50).tolist() if not near_df.empty else []
    except Exception:
        near_syms = []

    watchlist = list(dict.fromkeys(open_syms + near_syms))   # preserve order, dedupe
    monitor_store.update_watchlist(watchlist)


def _run_monitor_once(params: dict):
    """Decide mode (intraday vs EOD) and run appropriate check."""
    from src.quick_updater import is_market_open, market_closed_today

    last_eod = monitor_store.get_last_eod_date()

    if is_market_open():
        _run_intraday_check()
    elif market_closed_today(last_eod):
        _run_eod_scan(params)
    else:
        # Outside market hours and EOD already done — log a heartbeat
        log_line = f"{datetime.now().strftime('%H:%M')} — market closed, EOD done"
        monitor_store.record_run(monitor_store.get()["last_signals"], [], log_line)


def _start_monitor_loop(params: dict, interval_min: int):
    """Launch background thread that runs the monitor every interval_min minutes."""
    import time as _time

    def _loop():
        while monitor_store.is_running():
            _run_monitor_once(params)
            next_run = datetime.now() + timedelta(minutes=interval_min)
            monitor_store.set_next_run(next_run)
            # Sleep in 30-second ticks so stop() takes effect quickly
            slept = 0
            while slept < interval_min * 60 and monitor_store.is_running():
                _time.sleep(30)
                slept += 30

    t = threading.Thread(target=_loop, daemon=True)
    monitor_store.set_thread(t)
    t.start()


# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------

st.sidebar.title("📈 Equity Swing")
page = st.sidebar.radio("Navigate", [
    "Ingestion Dashboard", "Signal Scanner", "Siva Strategy",
    "Siva 95 Backtest", "Live Monitor", "Paper Portfolio", "Stock Explorer",
])

# ---------------------------------------------------------------------------
# Page 1: Ingestion Dashboard
# ---------------------------------------------------------------------------

if page == "Ingestion Dashboard":
    st.title("Data Ingestion Dashboard")

    # --- DB stats ---
    stats = get_db_stats(DB_PATH)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("DB Size",        f"{stats.get('db_size_mb', 0)} MB")
    c2.metric("Daily Candles",  f"{stats.get('ohlcv_1day', 0):,}")
    c3.metric("Weekly Candles", f"{stats.get('ohlcv_1week', 0):,}")
    c4.metric("5-min Candles",  f"{stats.get('ohlcv_5min', 0):,}")

    st.divider()

    # --- Buttons (disabled while running) ---
    ps = progress_store.get()
    b1, b2, b3, b4 = st.columns([1, 1, 1.5, 1.5])
    run_btn    = b1.button("▶ Run Ingestion",         disabled=ps["running"])
    dry_btn    = b2.button("🔍 Dry Run",               disabled=ps["running"])
    weekly_btn = b3.button("📅 Backfill Weekly Data",  disabled=ps["running"],
                            help="Generate 1-week candles from existing daily data — no API calls needed")
    tags_btn   = b4.button("🏷️ Update Tags",            disabled=ps["running"],
                            help="Read MW-*.csv index files from data/ and refresh symbol_tags table")

    if run_btn:
        _start_ingestion(dry_run=False)
        st.rerun()

    if dry_btn:
        _start_ingestion(dry_run=True)
        st.rerun()

    if weekly_btn:
        _start_weekly_backfill()
        st.rerun()

    if tags_btn:
        with st.spinner("Reading MW-*.csv files and updating tags…"):
            n = _update_tags()
        if n:
            st.success(f"✅ Tags updated — {n} symbols tagged.")
        else:
            st.warning("No MW-*.csv files found in data/ folder.")

    # --- Extend daily history panel ---
    with st.expander(
        f"📅 Extend Daily History ({INITIAL_LOOKBACK_DAYS_DAILY // 365} years) "
        "— needed for weekly analysis",
        expanded=False,
    ):
        st.markdown(
            f"Resets the **1-day** ingestion watermarks so the next run re-fetches "
            f"**{INITIAL_LOOKBACK_DAYS_DAILY} days (~{INITIAL_LOOKBACK_DAYS_DAILY // 365} years)** "
            f"of daily OHLCV for every symbol.  \n"
            "Intraday data (5-min) is **not affected** — it keeps its 100-day window.  \n"
            "After resetting, click **▶ Run Ingestion** to start the backfill.  \n\n"
            "⏱ Expected time: ~20–40 min with 3 workers at 1 req/s."
        )
        ps_ext = progress_store.get()
        ext_btn = st.button(
            "🔄 Reset daily history & prepare backfill",
            disabled=ps_ext["running"],
            key="ext_daily_btn",
            help="Clears 1-day ingestion state. Then click Run Ingestion to fetch 2 years."
        )
        if ext_btn:
            n_reset = reset_ingestion_state(intervals=["1day", "1week"], db_path=DB_PATH)
            st.success(
                f"✅ Reset {n_reset} ingestion records for **1day** and **1week**.  \n"
                "Now click **▶ Run Ingestion** to fetch 2 years of daily data."
            )

    # --- Live progress panel ---
    ps = progress_store.get()   # re-read after possible start

    if ps["running"]:
        pct   = ps["progress"]
        cur   = ps["current_idx"]
        total = ps["total"]
        sym   = ps["current"]
        log   = ps["log"]

        st.markdown(f"#### ⏳ Ingestion in progress — {pct}% complete")
        st.progress(pct / 100)

        p1, p2, p3 = st.columns(3)
        p1.metric("Symbols done",   f"{cur:,}")
        p2.metric("Total symbols",  f"{total:,}" if total else "loading…")
        p3.metric("Remaining",      f"{max(0, total - cur):,}" if total else "—")

        if sym:
            st.info(f"Currently processing: **{sym}**")

        if log:
            st.markdown("**Recent activity** (last 15 symbols):")
            st.code("\n".join(log[-15:]), language=None)

        time.sleep(1)   # give the background thread a second to make progress
        st.rerun()

    elif ps["done"]:
        st.success("✅ Ingestion complete!")
        progress_store._state["done"] = False   # clear the flag

    elif ps["error"]:
        st.error(f"❌ Ingestion error: {ps['error']}")
        progress_store._state["error"] = None

    # --- Completed log (shown after run finishes) ---
    if not ps["running"] and ps["log"]:
        with st.expander("Last ingestion log", expanded=False):
            st.code("\n".join(ps["log"]), language=None)

    st.divider()

    # --- Stale symbols panel ---
    st.subheader("Stale Data")
    stale_interval = st.selectbox(
        "Check staleness for interval", ALL_INTERVALS, index=3, key="stale_iv"
    )
    stale_syms = get_stale_symbols(interval=stale_interval, db_path=DB_PATH)

    if not stale_syms:
        st.success(f"All symbols are up to date for **{stale_interval}**.")
    else:
        st.warning(
            f"**{len(stale_syms)} symbol(s)** have stale or missing data for **{stale_interval}** "
            f"(>2 business days since last update — weekends excluded)."
        )
        with st.expander(f"View {len(stale_syms)} stale symbol(s)", expanded=False):
            st.write(", ".join(stale_syms))

        ps = progress_store.get()
        reingest_btn = st.button(
            f"🔄 Re-ingest {len(stale_syms)} stale symbol(s)",
            disabled=ps["running"],
            type="primary",
        )
        if reingest_btn:
            _start_selective_ingestion(stale_syms)
            st.rerun()

    st.divider()
    st.subheader("Ingestion Status by Symbol & Interval")

    status_df = get_ingestion_status(DB_PATH)
    if status_df.empty:
        st.info("No data ingested yet. Click 'Run Ingestion' to start.")
    else:
        pivot = status_df.pivot(index="symbol", columns="interval", values="last_ingested_at")
        ordered_cols = [c for c in ALL_INTERVALS if c in pivot.columns]
        pivot = pivot[ordered_cols]
        display = pivot.copy()
        for col in display.columns:
            display[col] = display[col].map(lambda v, c=col: _staleness_label(v, c))
        st.dataframe(display, use_container_width=True)
        st.caption("🟢 Today/Current   🟡 1-3 days old   🔴 Stale   ⬜ Never ingested")

# ---------------------------------------------------------------------------
# Page 2: Signal Scanner
# ---------------------------------------------------------------------------

elif page == "Signal Scanner":
    from src.scanner import scan

    st.title("Signal Scanner")
    st.caption(
        "Finds stocks where: **avg RSI (5 prior candles) < 50**, then a candle where "
        "**CCI > 100**, **RSI > 50**, and **volume ≥ 4× the 5-candle average**."
    )

    sc1, sc2, sc3 = st.columns([2, 1, 1])
    scan_interval  = sc1.selectbox("Interval", ALL_INTERVALS, index=3, key="scan_iv")
    scan_lookback  = sc2.number_input("Candles to scan", min_value=20, max_value=200, value=60)
    signal_age     = sc3.number_input("Max signal age (candles)", min_value=1, max_value=20, value=5)

    run_scan = st.button("🔍 Run Scan", type="primary")

    if run_scan:
        with st.spinner(f"Scanning all symbols on {scan_interval}…"):
            results = scan(
                interval=scan_interval,
                lookback=int(scan_lookback),
                max_signal_age=int(signal_age),
                db_path=DB_PATH,
            )

        if results.empty:
            st.info("No signals found. Try increasing 'Candles to scan' or 'Max signal age', or run ingestion first.")
        else:
            # Attach index membership tags
            _tags = get_tags_map(DB_PATH)
            results["tags"] = results["symbol"].map(lambda s: _tags.get(s, ""))

            stale_df   = results[results["stale"]]
            fresh_df   = results[~results["stale"]]
            n_stale    = len(stale_df)
            n_fresh    = len(fresh_df)

            if n_fresh:
                st.success(f"**{n_fresh} signal(s) found** with up-to-date data")
            if n_stale:
                stale_names = ", ".join(stale_df["symbol"].tolist())
                st.warning(
                    f"⚠️ **{n_stale} signal(s) have stale data (>2 days old):** {stale_names}  \n"
                    "These results may not reflect current market conditions. Run ingestion to refresh."
                )

            # Colour vol_ratio — higher = stronger signal
            def _colour_vol(val):
                if val >= 8:  return "background-color: #155724; color: white"
                if val >= 4:  return "background-color: #d4edda"
                return ""

            # candles_ago: 0 = latest candle, highlight freshest signals
            def _colour_age(val):
                if val == 0:  return "font-weight: bold; color: #155724"
                if val <= 2:  return "color: #856404"
                return "color: #6c757d"

            # Stale rows: orange background across all cells
            def _highlight_stale(row):
                if row.get("stale", False):
                    return ["background-color: #3d2200; color: #ffb347"] * len(row)
                return [""] * len(row)

            display = results.drop(columns=["stale", "tags"]).copy()
            display.insert(1, "tags", results["tags"])

            styled = (
                display.style
                .apply(_highlight_stale, axis=1)
                .map(_colour_vol, subset=["vol_ratio"])
                .map(_colour_age, subset=["candles_ago"])
            )
            st.dataframe(styled, use_container_width=True, hide_index=True)

            st.divider()
            st.caption(
                "**signal_date** = date/time when all conditions were met  ·  "
                "**candles_ago** = 0 means the most recent candle for that stock  ·  "
                "**vol_ratio** = signal volume ÷ 5-candle avg (dark green ≥ 8×)  ·  "
                "**data_age_days** = days since the stock's latest candle in DB  ·  "
                "🟠 Orange rows = stale data (>2 days)"
            )

# ---------------------------------------------------------------------------
# Page 3: Siva Strategy
# ---------------------------------------------------------------------------

elif page == "Siva Strategy":
    from src.siva_scanner import scan_stage1, scan_stage2

    st.title("Siva Swing Strategy")
    st.caption(
        "Identifies stocks in **momentum reset + accumulation phase** preparing for a breakout. "
        "Strategy works in two stages — Stage 1 builds the watchlist, Stage 2 detects the entry."
    )

    stage1_tab, stage2_tab = st.tabs(["Stage 1 — Watchlist Builder", "Stage 2 — Entry Detection"])

    # -----------------------------------------------------------------------
    # Stage 1
    # -----------------------------------------------------------------------
    with stage1_tab:
        st.markdown(
            "**Purpose:** Find stocks that have *cooled off* (RSI reset), are *consolidating* "
            "(tight price range), and show *volume drying up* — classic accumulation signs."
        )
        st.divider()

        # --- Configuration ---
        with st.expander("⚙️ Scanner Configuration", expanded=True):
            cfg_col1, cfg_col2, cfg_col3 = st.columns(3)

            with cfg_col1:
                st.markdown("**RSI — Momentum Reset**")
                rsi_lo = st.number_input(
                    "RSI mean lower bound", min_value=20.0, max_value=45.0,
                    value=35.0, step=1.0, key="s1_rsi_lo",
                    help="Mean RSI of last 25 candles must be ≥ this"
                )
                rsi_hi = st.number_input(
                    "RSI mean upper bound", min_value=35.0, max_value=60.0,
                    value=48.0, step=1.0, key="s1_rsi_hi",
                    help="Mean RSI of last 25 candles must be ≤ this"
                )
                rsi_dip = st.number_input(
                    "RSI min dip threshold", min_value=15.0, max_value=45.0,
                    value=35.0, step=1.0, key="s1_rsi_dip",
                    help="At least one of the 25 RSI values must have touched below this"
                )

            with cfg_col2:
                st.markdown("**Price & Volume**")
                base_range = st.number_input(
                    "Max base range %", min_value=5.0, max_value=40.0,
                    value=20.0, step=1.0, key="s1_base",
                    help="(Highest high − Lowest low) / Lowest low over last 20 candles"
                )
                min_vol = st.number_input(
                    "Min avg volume (20-day)", min_value=50_000, max_value=10_000_000,
                    value=200_000, step=50_000, key="s1_vol",
                    help="Liquidity filter: avg daily volume over last 20 candles"
                )
                min_turnover = st.number_input(
                    "Min avg turnover (₹ Cr, 20-day)", min_value=1.0, max_value=100.0,
                    value=5.0, step=1.0, key="s1_to",
                    help="Liquidity filter (OR with volume): avg daily turnover in Crore ₹"
                )

            with cfg_col3:
                st.markdown("**Other Filters**")
                use_price_filter = st.checkbox("Enable price filter", value=True, key="s1_pf_on")
                min_price = st.number_input(
                    "Min price (₹)", min_value=1.0, max_value=5000.0,
                    value=80.0, step=10.0, key="s1_pf",
                    disabled=not use_price_filter,
                    help="Exclude penny stocks below this price"
                )
                interval = st.selectbox(
                    "Interval", ALL_INTERVALS, index=3, key="s1_interval",
                    help="Strategy designed for 1day; other intervals are experimental"
                )
                lookback = st.number_input(
                    "Candles to load per symbol", min_value=40, max_value=200,
                    value=70, step=10, key="s1_lb",
                    help="Must be ≥ 30 (needed for 30-day volume average)"
                )

        run_s1 = st.button("🔍 Run Stage 1 Scan", type="primary", key="run_s1")

        if run_s1:
            with st.spinner("Scanning all symbols…"):
                s1_results = scan_stage1(
                    interval=interval,
                    lookback=int(lookback),
                    rsi_mean_lo=float(rsi_lo),
                    rsi_mean_hi=float(rsi_hi),
                    rsi_dip_thresh=float(rsi_dip),
                    base_range_pct=float(base_range),
                    min_avg_vol_20=int(min_vol),
                    min_turnover_cr=float(min_turnover),
                    min_price=float(min_price) if use_price_filter else None,
                    db_path=DB_PATH,
                )

            if s1_results.empty:
                st.info("No stocks matched Stage 1 conditions. Try relaxing the parameters or run ingestion first.")
                st.session_state.pop("s1_symbols", None)
            else:
                # Attach index membership tags
                _s1_tags = get_tags_map(DB_PATH)
                s1_results = s1_results.copy()
                s1_results.insert(1, "tags", s1_results["symbol"].map(lambda s: _s1_tags.get(s, "")))

                st.session_state["s1_symbols"] = s1_results["symbol"].tolist()
                st.success(f"**{len(s1_results)} watchlist candidate(s) found** — saved to Stage 2 watchlist")

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Candidates",        len(s1_results))
                m2.metric("Avg RSI mean",       f"{s1_results['rsi_mean_25'].mean():.1f}")
                m3.metric("Avg base range",     f"{s1_results['price_range_pct'].mean():.1f}%")
                m4.metric("Avg vol compression",f"{s1_results['vol_compression'].mean():.2f}×")

                st.divider()

                # --- Styling ---
                def _colour_rsi_mean(val):
                    if val <= 38:   return "background-color: #155724; color: white"
                    if val <= 43:   return "background-color: #d4edda"
                    return "background-color: #fff3cd"   # near upper bound

                def _colour_range(val):
                    if val <= 8:    return "background-color: #155724; color: white"
                    if val <= 13:   return "background-color: #d4edda"
                    if val <= 17:   return "background-color: #fff3cd"
                    return "background-color: #f8d7da"   # near the limit

                def _colour_compression(val):
                    if val <= 0.55: return "background-color: #155724; color: white"
                    if val <= 0.70: return "background-color: #d4edda"
                    if val <= 0.85: return "background-color: #fff3cd"
                    return ""

                styled = (
                    s1_results.style
                    .map(_colour_rsi_mean,    subset=["rsi_mean_25"])
                    .map(_colour_range,       subset=["price_range_pct"])
                    .map(_colour_compression, subset=["vol_compression"])
                    .format({
                        "close":           "₹{:.2f}",
                        "price_range_pct": "{:.1f}%",
                        "vol_compression": "{:.2f}×",
                        "avg_vol_20":      "{:,}",
                        "turnover_cr":     "₹{:.2f} Cr",
                        "tags":            "{}",
                    })
                )
                st.dataframe(styled, use_container_width=True, hide_index=True)

                st.divider()
                st.caption(
                    "**rsi_mean_25** = mean of RSI(14) over last 25 days · "
                    "**rsi_min_25** = lowest RSI in that window (confirms the dip) · "
                    "**price_range_pct** = (25-day high − low) / low — lower = tighter base · "
                    "**vol_compression** = avg vol (10-day) ÷ avg vol (30-day) — lower = more dried up · "
                    "**turnover_cr** = avg daily ₹ turnover (20-day)  ·  "
                    "🟢 Dark green = strongest signal in that column"
                )

    # -----------------------------------------------------------------------
    # Stage 2 — Entry Detection
    # -----------------------------------------------------------------------
    with stage2_tab:
        st.markdown(
            "**Purpose:** Find entry signals on the Stage 1 watchlist — "
            "volume expansion, RSI momentum shift, and structural price breakout all firing together."
        )

        # Watchlist source selector
        has_watchlist = bool(st.session_state.get("s1_symbols"))
        if has_watchlist:
            wl_symbols = st.session_state["s1_symbols"]
            use_watchlist = st.checkbox(
                f"Use Stage 1 watchlist ({len(wl_symbols)} stocks)", value=True, key="s2_use_wl"
            )
            if use_watchlist:
                st.caption(f"Scanning: {', '.join(wl_symbols[:10])}{'…' if len(wl_symbols) > 10 else ''}")
            else:
                st.caption("Scanning: full NSE universe")
        else:
            use_watchlist = False
            st.info("Run Stage 1 first to narrow the scan to watchlist stocks. Currently scanning full universe.")

        st.divider()

        # --- Configuration ---
        with st.expander("⚙️ Stage 2 Configuration", expanded=True):
            s2c1, s2c2, s2c3 = st.columns(3)

            with s2c1:
                st.markdown("**RSI — Entry Zone**")
                s2_rsi_lo = st.number_input(
                    "RSI lower bound", min_value=30.0, max_value=70.0,
                    value=50.0, step=1.0, key="s2_rsi_lo",
                    help="RSI today must be ≥ this (momentum has crossed into bullish)"
                )
                s2_rsi_hi = st.number_input(
                    "RSI upper bound", min_value=50.0, max_value=100.0,
                    value=80.0, step=1.0, key="s2_rsi_hi",
                    help="RSI today must be ≤ this (avoid over-extended entries)"
                )
                st.caption(f"Entry RSI range: **{s2_rsi_lo:.0f} – {s2_rsi_hi:.0f}**")

            with s2c2:
                st.markdown("**Volume Expansion**")
                s2_vol_min = st.number_input(
                    "Min vol ratio (×avg 20)", min_value=1.0, max_value=5.0,
                    value=1.5, step=0.1, key="s2_vol_min",
                    help="Today's volume ÷ avg of prior 20 days must be ≥ this"
                )
                s2_vol_strong = st.number_input(
                    "Strong signal threshold", min_value=1.5, max_value=10.0,
                    value=2.0, step=0.5, key="s2_vol_strong",
                    help="Vol ratio ≥ this is flagged as a Strong signal"
                )

            with s2c3:
                st.markdown("**CCI Confirmation (optional)**")
                s2_use_cci = st.checkbox("Require CCI confirmation", value=False, key="s2_cci_on")
                s2_cci_thresh = st.number_input(
                    "CCI threshold", min_value=-200.0, max_value=200.0,
                    value=0.0, step=10.0, key="s2_cci_thresh",
                    disabled=not s2_use_cci,
                    help="CCI today must be > this value"
                )
                s2_lookback = st.number_input(
                    "Candles to load per symbol", min_value=25, max_value=100,
                    value=40, step=5, key="s2_lb",
                    help="Must be ≥ 22 (20 prior vol days + today + buffer)"
                )

        run_s2 = st.button("🚀 Run Stage 2 Scan", type="primary", key="run_s2")

        if run_s2:
            scan_symbols = wl_symbols if (has_watchlist and use_watchlist) else None
            label = f"{len(wl_symbols)}-stock watchlist" if (has_watchlist and use_watchlist) else "full universe"

            with st.spinner(f"Scanning {label} for entry signals…"):
                s2_results = scan_stage2(
                    symbols=scan_symbols,
                    interval="1day",
                    lookback=int(s2_lookback),
                    rsi_lo=float(s2_rsi_lo),
                    rsi_hi=float(s2_rsi_hi),
                    vol_ratio_min=float(s2_vol_min),
                    vol_ratio_strong=float(s2_vol_strong),
                    use_cci=s2_use_cci,
                    cci_thresh=float(s2_cci_thresh),
                    db_path=DB_PATH,
                )

            if s2_results.empty:
                st.info("No entry signals found. Try relaxing the RSI range or volume threshold, or run Stage 1 + re-scan.")
            else:
                # Attach index membership tags
                _s2_tags = get_tags_map(DB_PATH)
                s2_results = s2_results.copy()
                s2_results.insert(1, "tags", s2_results["symbol"].map(lambda s: _s2_tags.get(s, "")))
                strong_count = len(s2_results[s2_results["vol_signal"] == "Strong"])
                st.success(
                    f"**{len(s2_results)} entry signal(s)** — "
                    f"{strong_count} Strong 🔥, {len(s2_results) - strong_count} Moderate"
                )

                e1, e2, e3, e4 = st.columns(4)
                e1.metric("Total signals",    len(s2_results))
                e2.metric("Strong signals",   strong_count)
                e3.metric("Avg RSI",          f"{s2_results['rsi'].mean():.1f}")
                e4.metric("Avg vol ratio",    f"{s2_results['vol_ratio'].mean():.2f}×")

                st.divider()

                # --- Styling ---
                def _colour_vol_signal(val):
                    if val == "Strong":   return "background-color: #155724; color: white; font-weight: bold"
                    if val == "Moderate": return "background-color: #fff3cd; color: #856404"
                    return ""

                def _colour_vol_ratio(val):
                    if val >= 3.0:  return "background-color: #155724; color: white"
                    if val >= 2.0:  return "background-color: #d4edda"
                    if val >= 1.5:  return "background-color: #fff3cd"
                    return ""

                def _colour_rsi(val):
                    # Ideal entry zone is 50-60 per strategy
                    if 50 <= val <= 60: return "background-color: #155724; color: white"
                    if 60 < val <= 70:  return "background-color: #d4edda"
                    return "background-color: #fff3cd"

                def _colour_breakout(val):
                    if val >= 3.0:  return "background-color: #155724; color: white"
                    if val >= 1.5:  return "background-color: #d4edda"
                    return ""

                def _colour_rsi_trend(val):
                    if val >= 10: return "background-color: #155724; color: white"
                    if val >= 5:  return "background-color: #d4edda"
                    return ""

                display_cols = ["symbol", "tags", "close", "rsi", "rsi_trend", "vol_ratio",
                                "vol_signal", "breakout_pct", "high_15", "avg_vol_20"]
                if s2_use_cci and "cci" in s2_results.columns:
                    display_cols.insert(4, "cci")

                styled2 = (
                    s2_results[display_cols].style
                    .map(_colour_vol_signal, subset=["vol_signal"])
                    .map(_colour_vol_ratio,  subset=["vol_ratio"])
                    .map(_colour_rsi,        subset=["rsi"])
                    .map(_colour_breakout,   subset=["breakout_pct"])
                    .map(_colour_rsi_trend,  subset=["rsi_trend"])
                    .format({
                        "close":        "₹{:.2f}",
                        "high_15":      "₹{:.2f}",
                        "vol_ratio":    "{:.2f}×",
                        "breakout_pct": "+{:.2f}%",
                        "rsi_trend":    "+{:.1f}",
                        "avg_vol_20":   "{:,}",
                    })
                )
                st.dataframe(styled2, use_container_width=True, hide_index=True)

                st.divider()
                st.caption(
                    "**rsi** = RSI(14) on latest candle · "
                    "**rsi_trend** = RSI today − RSI 5 days ago (positive = momentum building) · "
                    "**vol_ratio** = today's vol ÷ avg prior 20-day vol · "
                    "**vol_signal** = Strong ≥ {:.1f}×, Moderate ≥ {:.1f}× · "
                    "**breakout_pct** = % above prior 15-day high · "
                    "**high_15** = prior 15-day high (the breakout level)  ·  "
                    "Ideal entry RSI zone: 50–60".format(s2_vol_strong, s2_vol_min)
                )

# ---------------------------------------------------------------------------
# Page: Live Monitor
# ---------------------------------------------------------------------------

elif page == "Live Monitor":
    from src.siva95_scanner import scan_siva95_near, get_data_quality as _dq_mon
    from src.config import NTFY_TOPIC, SMTP_USER, NOTIFY_EMAIL
    from src.notifier import test_notifications

    st.title("Siva-95 Live Monitor")
    st.caption(
        "Automatically scans for Siva-95 entry signals on a schedule and sends "
        "push + email notifications. Also maintains a near-condition watchlist "
        "of stocks approaching the full trigger."
    )

    # --- Notification status ---
    with st.expander("🔔 Notification Setup", expanded=not (NTFY_TOPIC or SMTP_USER)):
        nc1, nc2 = st.columns(2)
        with nc1:
            st.markdown("**Push (ntfy.sh)**")
            if NTFY_TOPIC:
                st.success(f"✅ Topic: `{NTFY_TOPIC}`")
                st.caption(f"Subscribe on phone: **ntfy.sh/{NTFY_TOPIC}**")
            else:
                st.warning("Not configured — set `NTFY_TOPIC` in your `.env` file")
        with nc2:
            st.markdown("**Email**")
            if SMTP_USER:
                st.success(f"✅ Sending from `{SMTP_USER}` to `{NOTIFY_EMAIL}`")
            else:
                st.warning("Not configured — set `SMTP_USER` / `SMTP_PASSWORD` / `NOTIFY_EMAIL` in `.env`")

        if st.button("📤 Send test notification", key="test_notif"):
            res = test_notifications()
            if res["push"] or res["email"]:
                st.success(f"Sent — push: {'✅' if res['push'] else '❌'}  email: {'✅' if res['email'] else '❌'}")
            else:
                st.error("Both channels failed — check your .env credentials")

    st.divider()

    # --- Monitor controls ---
    ms = monitor_store.get()

    with st.expander("⚙️ Monitor Configuration", expanded=True):
        mcol1, mcol2 = st.columns(2)
        with mcol1:
            st.markdown("**Intraday Check Interval**")
            interval_options = {
                "15 minutes": 15,
                "20 minutes": 20,
                "30 minutes": 30,
            }
            sel_interval = st.selectbox(
                "Check interval (market hours)", list(interval_options.keys()),
                index=0, key="mon_interval",
                help="During 9:15–15:30 IST: fetches latest prices for your watchlist and checks paper trade exits. After 15:30: runs full EOD scan + Siva-95 signal detection (once per day)."
            )
            interval_min = interval_options[sel_interval]
            st.info(
                "💡 **Two-mode monitoring:**\n"
                "- **Intraday** (9:15–15:30): quick price fetch for open trades + near-condition watchlist → checks exits every interval\n"
                "- **EOD** (after 15:30, once/day): full delta ingestion + Siva-95 scan + rebuild watchlist"
            )
        with mcol2:
            st.markdown("**Scanner Parameters**")
            mon_rsi_lo     = st.number_input("RSI lower", 30.0, 60.0, 50.0, 1.0, key="mon_rsi_lo")
            mon_rsi_hi     = st.number_input("RSI upper", 50.0, 90.0, 75.0, 1.0, key="mon_rsi_hi")
            mon_cci_min    = st.number_input("Min weekly CCI", 0.0, 200.0, 90.0, 5.0, key="mon_cci")
            mon_req_cci    = st.checkbox("Require CCI", value=_dq_mon(DB_PATH)["cci20_ok"], key="mon_req_cci")
            mon_req_rsi_ma = st.checkbox("Require RSI > MA", value=False, key="mon_req_rsi_ma")
            mon_rsi_dip    = st.number_input("Min RSI dip days", 1, 10, 5, 1, key="mon_rsi_dip")
            mon_min_vol    = st.number_input("Min 5d avg vol", 10_000, 5_000_000, 100_000, 10_000, key="mon_vol")
            mon_min_price  = st.number_input("Min price (₹)", 1.0, 500.0, 25.0, 5.0, key="mon_price")

    mon_params = dict(
        rsi_lo=mon_rsi_lo, rsi_hi=mon_rsi_hi, cci_min=mon_cci_min,
        require_cci=mon_req_cci, require_rsi_ma=mon_req_rsi_ma,
        rsi_below50=int(mon_rsi_dip), min_vol=int(mon_min_vol), min_price=mon_min_price,
    )

    # --- Start / Stop buttons ---
    b_start, b_stop, b_now, b_wl = st.columns(4)
    if b_start.button("▶ Start Monitor", disabled=ms["running"], type="primary"):
        monitor_store.start(interval_min)
        _refresh_monitor_watchlist(mon_params)   # build watchlist immediately
        _start_monitor_loop(mon_params, interval_min)
        st.rerun()

    if b_stop.button("⏹ Stop Monitor", disabled=not ms["running"]):
        monitor_store.stop()
        st.rerun()

    if b_now.button("🔍 EOD Scan Now"):
        with st.spinner("Running full EOD scan…"):
            _run_eod_scan(mon_params)
        st.rerun()

    if b_wl.button("🔄 Refresh Watchlist"):
        with st.spinner("Rebuilding watchlist…"):
            _refresh_monitor_watchlist(mon_params)
        st.rerun()

    # --- Status panel ---
    ms = monitor_store.get()
    if ms["running"]:
        st.success(f"✅ Monitor running — intraday check every {ms['interval_min']} min | EOD scan once/day after 15:30 IST")
    else:
        st.info("Monitor stopped. Click ▶ Start Monitor to begin.")

    if ms["last_run"]:
        eod_label = f"  |  Last EOD: {ms['last_eod_date']}" if ms.get("last_eod_date") else ""
        st.caption(f"Last check: {ms['last_run'][:16]}   |   Next: {(ms['next_run'] or '—')[:16]}{eod_label}")

    if ms["error"]:
        st.error(f"Monitor error: {ms['error']}")

    # --- Intraday watchlist ---
    watchlist = ms.get("watchlist", [])
    if watchlist:
        with st.expander(f"📋 Intraday Watchlist ({len(watchlist)} symbols)", expanded=False):
            st.caption("Prices fetched every interval during market hours to monitor paper trade exits.")
            st.write(", ".join(watchlist))
    else:
        st.caption("Intraday watchlist is empty — click **🔄 Refresh Watchlist** or start the monitor to populate it.")

    st.divider()

    # --- Current signals ---
    st.subheader("Current Signals")
    if ms["last_signals"]:
        _tags_mon = get_tags_map(DB_PATH)
        sig_df = pd.DataFrame(ms["last_signals"])
        sig_df.insert(1, "tags", sig_df["symbol"].map(lambda s: _tags_mon.get(s, "")))

        # Quick-add to paper portfolio
        st.markdown("Select signals to add to Paper Portfolio:")
        sel_signals = st.multiselect(
            "Add to paper portfolio",
            options=sig_df["symbol"].tolist(),
            key="mon_add_to_paper",
        )
        add_col1, add_col2, add_col3 = st.columns(3)
        add_target = add_col1.number_input("Target %", 1.0, 50.0, 5.0, 0.5, key="mon_target")
        add_sl     = add_col2.number_input("SL %",     1.0, 50.0, 5.0, 0.5, key="mon_sl")
        add_trail  = add_col3.checkbox("Trailing SL", value=False, key="mon_trail")

        if st.button("➕ Add selected to Paper Portfolio", disabled=not sel_signals):
            for sym in sel_signals:
                row = sig_df[sig_df["symbol"] == sym].iloc[0]
                open_trade(
                    symbol=sym,
                    entry_price=float(row["close"]),
                    signal_week=str(row["week_date"]),
                    target_pct=add_target,
                    sl_pct=add_sl,
                    trail_sl=add_trail,
                    db_path=DB_PATH,
                )
            st.success(f"Added {len(sel_signals)} trade(s) to Paper Portfolio.")
            st.rerun()

        st.dataframe(sig_df, use_container_width=True, hide_index=True)
    else:
        st.info("No signals in the last scan. Click **🔍 Scan Now** to run manually.")

    # --- Near-condition watchlist ---
    st.divider()
    st.subheader("Near-Condition Watchlist")
    st.caption("Stocks scoring 3+ out of 5 relaxed conditions — candidates to watch for full trigger.")

    if st.button("🔭 Refresh Near-Condition Watchlist", key="near_refresh"):
        with st.spinner("Scanning…"):
            near_df = scan_siva95_near(DB_PATH, min_price=mon_min_price, min_avg_vol_5=int(mon_min_vol))
        if near_df.empty:
            st.info("No near-condition stocks found.")
        else:
            _tags_near = get_tags_map(DB_PATH)
            near_df.insert(1, "tags", near_df["symbol"].map(lambda s: _tags_near.get(s, "")))
            top = near_df[near_df["conditions_met"] >= 3]
            st.success(f"{len(top)} stocks scoring ≥ 3/5 conditions")
            st.dataframe(
                top.style.map(
                    lambda v: "background-color: #155724; color: white" if v == 5
                    else ("background-color: #d4edda" if v == 4 else ""),
                    subset=["conditions_met"],
                ),
                use_container_width=True, hide_index=True,
            )

    # --- Monitor log ---
    if ms["log"]:
        with st.expander("Monitor log", expanded=False):
            st.code("\n".join(reversed(ms["log"])), language=None)

# ---------------------------------------------------------------------------
# Page: Paper Portfolio
# ---------------------------------------------------------------------------

elif page == "Paper Portfolio":
    _ensure_portfolio(DB_PATH)

    st.title("Paper Portfolio")
    st.caption(
        "Paper trades opened automatically by the monitor or manually from scan results. "
        "Exit conditions (target / stop-loss) are evaluated against latest daily close from the DB."
    )

    # --- Check exits ---
    exits = check_and_update_exits(DB_PATH)
    if exits:
        from src.notifier import notify as _notify
        for ex in exits:
            emoji  = "🎯" if ex["exit_reason"] == "target" else "🛑"
            reason = "Target hit" if ex["exit_reason"] == "target" else "Stop-Loss hit"
            st.toast(f"{emoji} {reason}: {ex['symbol']}  P&L {ex['pnl']:+.2f}", icon="📊")
            _notify(f"{emoji} {reason}: {ex['symbol']}",
                    f"Exit ₹{ex['exit_price']} | P&L {ex['pnl']:+.2f} ({ex['pnl_pct']:+.1f}%)")

    # --- Portfolio summary ---
    summary = get_portfolio_summary(DB_PATH)
    pm1, pm2, pm3, pm4, pm5 = st.columns(5)
    pm1.metric("Open trades",   summary["open_trades"])
    pm2.metric("Closed trades", summary["closed_trades"])
    pm3.metric("Total P&L",     f"₹{summary['total_pnl']:+.2f}")
    pm4.metric("Win rate",      f"{summary['win_rate']:.0f}%")
    pm5.metric("Avg win / loss",
               f"₹{summary['avg_win']:.0f} / ₹{summary['avg_loss']:.0f}"
               if summary["closed_trades"] else "—")

    st.divider()

    # --- Open trades table ---
    st.subheader("Open Trades")
    open_df = get_open_trades(DB_PATH)

    if open_df.empty:
        st.info("No open paper trades. Run the Live Monitor or add trades from the Siva 95 Backtest page.")
    else:
        # Enrich with current price and unrealised P&L
        rows = []
        for _, t in open_df.iterrows():
            from src.database import get_latest_candles as _glc
            c = _glc(t["symbol"], "1day", n=1, db_path=DB_PATH)
            ltp = float(c.iloc[-1]["close"]) if not c.empty else None
            upnl     = round((ltp - float(t["entry_price"])) * int(t["qty"]), 2) if ltp else None
            upnl_pct = round((ltp / float(t["entry_price"]) - 1) * 100, 2)       if ltp else None
            rows.append({
                "id":          int(t["id"]),
                "symbol":      t["symbol"],
                "entry_date":  str(t["entry_date"])[:10],
                "entry_price": float(t["entry_price"]),
                "ltp":         ltp,
                "target":      float(t["target_price"]),
                "sl":          float(t["current_sl"]),
                "trail_sl":    bool(t["trail_sl"]),
                "unrealised":  upnl,
                "unreal_%":    upnl_pct,
                "signal_week": t["signal_week"],
            })
        open_display = pd.DataFrame(rows)

        def _clr_pnl(val):
            if val is None or pd.isna(val): return ""
            return "color: #28a745; font-weight: bold" if val >= 0 else "color: #dc3545; font-weight: bold"

        st.dataframe(
            open_display.style
            .map(_clr_pnl, subset=["unrealised", "unreal_%"])
            .format({
                "entry_price": "₹{:.2f}", "ltp": "₹{:.2f}",
                "target": "₹{:.2f}",     "sl":  "₹{:.2f}",
                "unrealised": "₹{:+.2f}", "unreal_%": "{:+.2f}%",
            }, na_rep="—"),
            use_container_width=True, hide_index=True,
        )

        st.divider()

        # --- Manual close / settings update ---
        with st.expander("Manage trades", expanded=False):
            trade_ids  = open_display["id"].tolist()
            trade_syms = open_display["symbol"].tolist()
            options    = [f"#{i} {s}" for i, s in zip(trade_ids, trade_syms)]

            sel_label = st.selectbox("Select trade", options, key="pp_sel_trade")
            sel_id    = trade_ids[options.index(sel_label)]

            mc1, mc2, mc3 = st.columns(3)
            new_target = mc1.number_input("Target %", 1.0, 50.0, 5.0, 0.5, key="pp_new_target")
            new_sl     = mc2.number_input("SL %",     1.0, 50.0, 5.0, 0.5, key="pp_new_sl")
            new_trail  = mc3.checkbox("Trailing SL",  value=False, key="pp_new_trail")

            pp_col1, pp_col2 = st.columns(2)
            if pp_col1.button("📝 Update target / SL", key="pp_update"):
                import sqlite3 as _sl3
                row = open_display[open_display["id"] == sel_id].iloc[0]
                ep  = float(row["entry_price"])
                with _sl3.connect(str(DB_PATH)) as _conn:
                    _conn.execute(
                        """UPDATE paper_trades SET
                           target_pct=?, sl_pct=?, trail_sl=?,
                           target_price=?, sl_price=?, current_sl=?
                           WHERE id=?""",
                        (new_target, new_sl, int(new_trail),
                         round(ep * (1 + new_target / 100), 2),
                         round(ep * (1 - new_sl / 100), 2),
                         round(ep * (1 - new_sl / 100), 2),
                         sel_id),
                    )
                    _conn.commit()
                st.success("Trade updated.")
                st.rerun()

            if pp_col2.button("❌ Close at market (latest close)", key="pp_close", type="primary"):
                from src.database import get_latest_candles as _glc2
                sel_sym = trade_syms[trade_ids.index(sel_id)]
                c2 = _glc2(sel_sym, "1day", n=1, db_path=DB_PATH)
                if not c2.empty:
                    pnl2 = close_trade(sel_id, float(c2.iloc[-1]["close"]), "manual", DB_PATH)
                    st.success(f"Trade closed. P&L: ₹{pnl2:+.2f}")
                    st.rerun()

    # --- Closed trades ---
    st.divider()
    st.subheader("Closed Trades")
    closed_df = get_closed_trades(DB_PATH)

    if closed_df.empty:
        st.info("No closed trades yet.")
    else:
        display_closed = closed_df[[
            "symbol", "entry_date", "exit_date", "entry_price",
            "exit_price", "exit_reason", "pnl", "pnl_pct", "signal_week",
        ]].copy()
        display_closed["entry_date"] = display_closed["entry_date"].str[:10]
        display_closed["exit_date"]  = display_closed["exit_date"].str[:10]

        def _clr_exit(val):
            if val == "target": return "background-color: #d4edda; color: #155724"
            if val == "sl":     return "background-color: #f8d7da; color: #721c24"
            return ""

        st.dataframe(
            display_closed.style
            .map(_clr_exit, subset=["exit_reason"])
            .map(_clr_pnl,  subset=["pnl", "pnl_pct"])
            .format({
                "entry_price": "₹{:.2f}", "exit_price": "₹{:.2f}",
                "pnl": "₹{:+.2f}",       "pnl_pct": "{:+.2f}%",
            }),
            use_container_width=True, hide_index=True,
        )

elif page == "Stock Explorer":
    st.title("Stock Explorer")

    symbols = get_symbols(DB_PATH)
    if not symbols:
        st.warning("No data available yet. Run ingestion first.")
        st.stop()

    col_s, col_i, col_n = st.columns([2, 1, 1])
    selected_symbol   = col_s.selectbox("Symbol",   symbols)
    selected_interval = col_i.selectbox("Interval", ALL_INTERVALS, index=3)
    n_candles = col_n.number_input("Last N candles", min_value=10, max_value=500, value=50)

    df = get_latest_candles(selected_symbol, selected_interval, n=n_candles, db_path=DB_PATH)

    if df.empty:
        st.info(f"No data for {selected_symbol} [{selected_interval}].")
        st.stop()

    # Show index membership tags for selected symbol
    _exp_tags = get_tags_map(DB_PATH)
    _sym_tags = _exp_tags.get(selected_symbol, "")
    if _sym_tags:
        st.markdown(f"**Index membership:** {_sym_tags}")
    else:
        st.caption("No index tags found — run **Update Tags** on the Ingestion Dashboard.")

    last = df.iloc[-1]
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Close",   f"₹{last['close']:.2f}"  if pd.notnull(last.get("close"))  else "—")
    m2.metric("RSI(14)", f"{last['rsi']:.1f}"      if pd.notnull(last.get("rsi"))    else "—")
    m3.metric("CCI(20)", f"{last['cci']:.1f}"      if pd.notnull(last.get("cci"))    else "—")
    m4.metric("ATR(14)", f"{last['atr']:.2f}"      if pd.notnull(last.get("atr"))    else "—")
    m5.metric("EMA 20",  f"₹{last['ema_20']:.2f}"  if pd.notnull(last.get("ema_20")) else "—")

    st.divider()

    display_cols = [
        "timestamp", "open", "high", "low", "close", "volume",
        "rsi", "cci", "macd", "macd_signal", "bb_upper", "bb_middle", "bb_lower",
        "ema_20", "ema_50", "ema_200", "atr",
    ]
    if selected_interval in ["5min", "75min", "125min"]:
        display_cols.append("vwap")

    display_df = df[[c for c in display_cols if c in df.columns]].copy()
    num_cols = display_df.select_dtypes(include="number").columns
    display_df[num_cols] = display_df[num_cols].round(2)
    st.dataframe(display_df, use_container_width=True, height=400)

    if pd.notnull(last.get("rsi")):
        rsi_val = last["rsi"]
        if rsi_val >= 70:
            st.warning(f"RSI {rsi_val:.1f} — Overbought zone (≥70)")
        elif rsi_val <= 30:
            st.warning(f"RSI {rsi_val:.1f} — Oversold zone (≤30)")
        else:
            st.info(f"RSI {rsi_val:.1f} — Neutral zone (30–70)")

# ---------------------------------------------------------------------------
# Page 5: Siva 95 Backtest
# ---------------------------------------------------------------------------

elif page == "Siva 95 Backtest":
    from src.siva95_scanner import scan_siva95, get_data_quality
    from src.tag_loader import get_tags_map as _get_tags

    st.title("Siva 95 — Backtest Scanner")
    st.caption(
        "Finds weekly breakout setups: RSI reset + CCI momentum + price breaking prior highs + "
        "volume expansion. Select a date range to see every week a stock met all conditions."
    )

    # --- Data quality banner ---
    dq = get_data_quality(DB_PATH)
    n_weeks = dq["n_weeks"]
    if not dq["rsi14_ok"]:
        st.error(
            f"⚠️ Only ~{n_weeks} weeks of history available. "
            "Weekly RSI(14) needs ≥14 weeks. Run ingestion to build more history "
            f"(current range: {dq['min_date']} → {dq['max_date']})."
        )
    elif not dq["cci20_ok"]:
        st.warning(
            f"⚠️ ~{n_weeks} weeks of history — weekly CCI(20) needs ≥20 weeks. "
            "Enable **'Require CCI'** only once you have more data. "
            "RSI-based conditions will still work."
        )
    elif not dq["rsi_ma10_ok"]:
        st.info(
            f"ℹ️ ~{n_weeks} weeks of history — RSI-MA(10) needs ≥24 weeks (14 for RSI + 10 for MA). "
            "Some signals may be skipped."
        )
    else:
        st.success(f"✅ {n_weeks} weeks of history — all weekly indicators computable.")

    st.divider()

    # --- Date range ---
    dr_col1, dr_col2 = st.columns(2)
    default_from = dq["min_date"] if dq["min_date"] else date(2025, 1, 1)
    default_to   = dq["max_date"] if dq["max_date"] else date.today()
    s95_from = dr_col1.date_input("From date", value=default_from, key="s95_from")
    s95_to   = dr_col2.date_input("To date",   value=default_to,   key="s95_to")

    if s95_from > s95_to:
        st.error("'From date' must be before 'To date'.")
        st.stop()

    st.divider()

    # --- Configuration ---
    with st.expander("⚙️ Scanner Configuration", expanded=True):
        cfg1, cfg2, cfg3 = st.columns(3)

        with cfg1:
            st.markdown("**Weekly RSI**")
            s95_rsi_lo = st.number_input(
                "RSI lower bound", min_value=30.0, max_value=60.0,
                value=50.0, step=1.0, key="s95_rsi_lo",
                help="Weekly RSI(14) must be ≥ this"
            )
            s95_rsi_hi = st.number_input(
                "RSI upper bound", min_value=50.0, max_value=90.0,
                value=75.0, step=1.0, key="s95_rsi_hi",
                help="Weekly RSI(14) must be ≤ this"
            )
            st.caption(f"RSI window: **{s95_rsi_lo:.0f} – {s95_rsi_hi:.0f}**")

        with cfg2:
            st.markdown("**CCI & RSI-MA**")
            s95_req_cci = st.checkbox(
                "Require Weekly CCI", value=dq["cci20_ok"],
                key="s95_cci_on",
                help="Disable if <20 weeks of history (CCI(20) won't compute)"
            )
            s95_cci_min = st.number_input(
                "Weekly CCI minimum", min_value=0.0, max_value=200.0,
                value=90.0, step=5.0, key="s95_cci",
                disabled=not s95_req_cci,
                help="Weekly CCI(20) must be ≥ this"
            )
            s95_req_rsi_ma = st.checkbox(
                "Require RSI > RSI-MA", value=dq["rsi_ma10_ok"],
                key="s95_rsi_ma_on",
                help="Disable if <24 weeks of history (needs 14 for RSI + 10 for MA)"
            )
            s95_min_price = st.number_input(
                "Min close (₹)", min_value=1.0, max_value=500.0,
                value=25.0, step=5.0, key="s95_price"
            )

        with cfg3:
            st.markdown("**Volume & RSI Behaviour**")
            s95_min_vol = st.number_input(
                "Min 5-day avg volume", min_value=10_000, max_value=5_000_000,
                value=100_000, step=10_000, key="s95_vol",
                help="5-day average daily volume must be ≥ this"
            )
            s95_rsi_below50 = st.number_input(
                "Min days RSI < 50 (last 10)", min_value=1, max_value=10,
                value=5, step=1, key="s95_rsi_dip",
                help="In the 10 daily candles before week close, at least N must have RSI < 50"
            )
            s95_vol_periods = st.number_input(
                "Weekly vol compare periods", min_value=2, max_value=8,
                value=4, step=1, key="s95_vol_inc",
                help="Current week's volume vs avg of this many prior weekly candles"
            )
            s95_vol_ratio = st.number_input(
                "Min vol ratio (current/avg)", min_value=0.5, max_value=5.0,
                value=1.0, step=0.1, key="s95_vol_ratio",
                help="Current week volume ÷ avg of prior N weeks must be ≥ this (1.0 = above average)"
            )

    run_s95 = st.button("🔍 Run Siva-95 Scan", type="primary", key="run_s95")

    if run_s95:
        with st.spinner(f"Scanning {dq['n_symbols']} symbols from {s95_from} to {s95_to}…"):
            s95_results = scan_siva95(
                from_date=s95_from,
                to_date=s95_to,
                rsi_lo=float(s95_rsi_lo),
                rsi_hi=float(s95_rsi_hi),
                cci_min=float(s95_cci_min),
                require_cci=s95_req_cci,
                require_rsi_above_ma=s95_req_rsi_ma,
                rsi_below50_days=int(s95_rsi_below50),
                rsi_lookback_days=10,
                vol_compare_weeks=int(s95_vol_periods),
                vol_ratio_min=float(s95_vol_ratio),
                min_avg_vol_5=int(s95_min_vol),
                min_price=float(s95_min_price),
                db_path=DB_PATH,
            )

        if s95_results.empty:
            st.info(
                "No signals found in the selected date range. "
                "Try: wider date range, lower CCI threshold (or disable CCI), "
                "wider RSI range, or ensure ingestion is complete."
            )
        else:
            # Attach tags
            _s95_tags = _get_tags(DB_PATH)
            s95_results.insert(1, "tags", s95_results["symbol"].map(lambda s: _s95_tags.get(s, "")))

            n_syms  = s95_results["symbol"].nunique()
            n_weeks_hit = s95_results["week_date"].nunique()

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Total signals",    len(s95_results))
            m2.metric("Unique symbols",   n_syms)
            m3.metric("Weeks with hits",  n_weeks_hit)
            m4.metric("Avg weekly RSI",   f"{s95_results['weekly_rsi'].mean():.1f}")

            st.divider()

            # --- Signals per week chart ---
            with st.expander("📊 Signal distribution by week", expanded=False):
                per_week = (
                    s95_results.groupby("week_date")
                    .size()
                    .rename("signals")
                    .reset_index()
                )
                st.bar_chart(per_week.set_index("week_date")["signals"])

            # --- Symbol filter ---
            all_symbols_hit = sorted(s95_results["symbol"].unique())
            filter_sym = st.multiselect(
                "Filter by symbol (leave empty to show all)",
                options=all_symbols_hit,
                key="s95_sym_filter",
            )
            display_df = s95_results if not filter_sym else s95_results[s95_results["symbol"].isin(filter_sym)]

            # --- Styling ---
            def _clr_rsi(val):
                if 50 <= val <= 60: return "background-color: #155724; color: white"
                if 60 < val <= 70:  return "background-color: #d4edda"
                return "background-color: #fff3cd"

            def _clr_cci(val):
                if val is None or pd.isna(val): return ""
                if val >= 150: return "background-color: #155724; color: white"
                if val >= 100: return "background-color: #d4edda"
                return "background-color: #fff3cd"

            def _clr_breakout(val):
                if val >= 5.0:  return "background-color: #155724; color: white"
                if val >= 2.0:  return "background-color: #d4edda"
                return ""

            def _clr_dip(val):
                if val >= 8:  return "background-color: #155724; color: white"
                if val >= 6:  return "background-color: #d4edda"
                return ""

            fmt = {
                "close":            "₹{:.2f}",
                "weekly_high":      "₹{:.2f}",
                "high_33d_prior":   "₹{:.2f}",
                "breakout_pct":     "+{:.2f}%",
                "weekly_rsi":       "{:.1f}",
                "rsi_ma":           "{:.1f}",
                "vol_ratio":        "{:.2f}×",
                "avg_vol_5d":       "{:,}",
            }
            if s95_req_cci:
                fmt["weekly_cci"] = "{:.1f}"

            cols_to_show = [
                "week_date", "symbol", "tags", "close",
                "weekly_rsi", "rsi_ma", "weekly_high", "high_33d_prior", "breakout_pct",
                "rsi_days_below50", "vol_ratio", "avg_vol_5d",
            ]
            if s95_req_cci and "weekly_cci" in display_df.columns:
                cols_to_show.insert(6, "weekly_cci")

            subset_cci = ["weekly_cci"] if (s95_req_cci and "weekly_cci" in display_df.columns) else []

            styled95 = (
                display_df[cols_to_show].style
                .map(_clr_rsi,      subset=["weekly_rsi"])
                .map(_clr_breakout, subset=["breakout_pct"])
                .map(_clr_dip,      subset=["rsi_days_below50"])
                .format(fmt)
            )
            if subset_cci:
                styled95 = styled95.map(_clr_cci, subset=subset_cci)

            st.dataframe(styled95, use_container_width=True, hide_index=True)

            st.divider()
            st.caption(
                "**week_date** = Friday of the qualifying week · "
                "**weekly_rsi** = RSI(14) on weekly candles (computed from daily data) · "
                "**rsi_ma** = 10-period MA of weekly RSI · "
                "**weekly_high** = highest price in that week · "
                "**high_33d_prior** = max daily high of 33 trading days before that week · "
                "**breakout_pct** = how far above the 33-day prior high the week closed · "
                "**rsi_days_below50** = # of the 10 daily candles with RSI < 50 (before week end) · "
                "**avg_vol_5d** = 5-day avg daily volume · "
                "🟢 Dark green = strongest signal in that column"
            )
