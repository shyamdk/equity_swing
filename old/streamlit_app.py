"""Streamlit UI: Ingestion Dashboard + Stock Explorer."""
import threading
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from src.config import ALL_INTERVALS, DB_PATH
from src.database import (
    get_ingestion_status,
    get_latest_candles,
    get_symbols,
    get_db_stats,
    init_db,
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
# Helpers
# ---------------------------------------------------------------------------

def _staleness_label(last_at: str | None) -> str:
    if not last_at:
        return "⬜ Never"
    try:
        ts = datetime.fromisoformat(last_at)
        delta = datetime.now() - ts
        if delta.days == 0:
            return "🟢 Today"
        elif delta.days <= 2:
            return f"🟡 {delta.days}d ago"
        else:
            return f"🔴 {delta.days}d ago"
    except Exception:
        return "❓ Unknown"


def _run_ingestion_bg(dry_run: bool) -> None:
    """Run ingestion in a background thread (called from Streamlit button)."""
    from src.data_ingestor import run as ingest_run

    def _task():
        st.session_state["ingestion_running"] = True
        st.session_state["ingestion_log"] = []
        try:
            def progress(current, total, symbol):
                pct = int(current / total * 100)
                msg = f"[{current}/{total}] {symbol}"
                st.session_state["ingestion_progress"] = pct
                st.session_state["ingestion_current"] = msg
                st.session_state["ingestion_log"].append(msg)

            ingest_run(dry_run=dry_run, progress_callback=progress)
            st.session_state["ingestion_done"] = True
        except Exception as e:
            st.session_state["ingestion_error"] = str(e)
        finally:
            st.session_state["ingestion_running"] = False

    thread = threading.Thread(target=_task, daemon=True)
    thread.start()


# ---------------------------------------------------------------------------
# Session state init
# ---------------------------------------------------------------------------

for key, default in [
    ("ingestion_running", False),
    ("ingestion_progress", 0),
    ("ingestion_current", ""),
    ("ingestion_log", []),
    ("ingestion_done", False),
    ("ingestion_error", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------

st.sidebar.title("📈 Equity Swing")
page = st.sidebar.radio("Navigate", ["Ingestion Dashboard", "Stock Explorer"])


# ---------------------------------------------------------------------------
# Page 1: Ingestion Dashboard
# ---------------------------------------------------------------------------

if page == "Ingestion Dashboard":
    st.title("Data Ingestion Dashboard")

    # DB stats
    init_db()
    stats = get_db_stats(DB_PATH)
    col1, col2, col3 = st.columns(3)
    col1.metric("DB Size", f"{stats.get('db_size_mb', 0)} MB")
    daily_rows = stats.get("ohlcv_1day", 0)
    col2.metric("Daily Candles", f"{daily_rows:,}")
    intra_rows = stats.get("ohlcv_5min", 0)
    col3.metric("5-min Candles", f"{intra_rows:,}")

    st.divider()

    # Controls
    c1, c2, c3 = st.columns([1, 1, 4])
    run_btn = c1.button("▶ Run Ingestion", disabled=st.session_state["ingestion_running"])
    dry_btn = c2.button("🔍 Dry Run", disabled=st.session_state["ingestion_running"])

    if run_btn:
        _run_ingestion_bg(dry_run=False)
        st.rerun()

    if dry_btn:
        _run_ingestion_bg(dry_run=True)
        st.rerun()

    # Progress display
    if st.session_state["ingestion_running"]:
        st.progress(st.session_state["ingestion_progress"] / 100)
        st.info(st.session_state["ingestion_current"])
        st.rerun()  # keep refreshing while running

    if st.session_state["ingestion_done"]:
        st.success("Ingestion completed!")
        st.session_state["ingestion_done"] = False

    if st.session_state["ingestion_error"]:
        st.error(f"Ingestion error: {st.session_state['ingestion_error']}")
        st.session_state["ingestion_error"] = None

    # Recent log
    if st.session_state["ingestion_log"]:
        with st.expander("Ingestion log", expanded=False):
            st.text("\n".join(st.session_state["ingestion_log"][-50:]))

    st.divider()
    st.subheader("Ingestion Status by Symbol & Interval")

    status_df = get_ingestion_status(DB_PATH)
    if status_df.empty:
        st.info("No data ingested yet. Click 'Run Ingestion' to start.")
    else:
        # Pivot: symbol rows × interval columns
        pivot = status_df.pivot(index="symbol", columns="interval", values="last_ingested_at")
        # Reorder columns to match ALL_INTERVALS
        ordered_cols = [c for c in ALL_INTERVALS if c in pivot.columns]
        pivot = pivot[ordered_cols]

        # Apply staleness colouring
        def _style_cell(val):
            label = _staleness_label(val)
            if "🟢" in label:
                return "background-color: #d4edda"
            elif "🟡" in label:
                return "background-color: #fff3cd"
            elif "🔴" in label:
                return "background-color: #f8d7da"
            return ""

        display = pivot.applymap(lambda v: _staleness_label(v))
        st.dataframe(display, use_container_width=True)

        st.caption(
            "🟢 Today &nbsp;&nbsp; 🟡 1-2 days old &nbsp;&nbsp; "
            "🔴 Stale (>2 days) &nbsp;&nbsp; ⬜ Never ingested"
        )


# ---------------------------------------------------------------------------
# Page 2: Stock Explorer
# ---------------------------------------------------------------------------

elif page == "Stock Explorer":
    st.title("Stock Explorer")

    symbols = get_symbols(DB_PATH)
    if not symbols:
        st.warning("No data available yet. Run ingestion first.")
        st.stop()

    col_s, col_i, col_n = st.columns([2, 1, 1])
    selected_symbol = col_s.selectbox("Symbol", symbols)
    selected_interval = col_i.selectbox("Interval", ALL_INTERVALS, index=3)  # default 1day
    n_candles = col_n.number_input("Last N candles", min_value=10, max_value=500, value=50)

    df = get_latest_candles(selected_symbol, selected_interval, n=n_candles, db_path=DB_PATH)

    if df.empty:
        st.info(f"No data for {selected_symbol} [{selected_interval}].")
        st.stop()

    # Key metrics row
    last = df.iloc[-1]
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Close", f"₹{last['close']:.2f}" if pd.notnull(last.get("close")) else "—")
    m2.metric("RSI(14)", f"{last['rsi']:.1f}" if pd.notnull(last.get("rsi")) else "—")
    m3.metric("CCI(20)", f"{last['cci']:.1f}" if pd.notnull(last.get("cci")) else "—")
    m4.metric("ATR(14)", f"{last['atr']:.2f}" if pd.notnull(last.get("atr")) else "—")
    m5.metric("EMA 20", f"₹{last['ema_20']:.2f}" if pd.notnull(last.get("ema_20")) else "—")

    st.divider()

    # OHLCV + indicators table
    display_cols = [
        "timestamp", "open", "high", "low", "close", "volume",
        "rsi", "cci", "macd", "macd_signal", "bb_upper", "bb_middle", "bb_lower",
        "ema_20", "ema_50", "ema_200", "atr",
    ]
    if selected_interval in ["5min", "75min", "125min"]:
        display_cols.append("vwap")

    display_df = df[[c for c in display_cols if c in df.columns]].copy()
    # Round numeric columns
    num_cols = display_df.select_dtypes(include="number").columns
    display_df[num_cols] = display_df[num_cols].round(2)

    st.dataframe(display_df, use_container_width=True, height=400)

    # Quick RSI signal indicator
    if pd.notnull(last.get("rsi")):
        rsi_val = last["rsi"]
        if rsi_val >= 70:
            st.warning(f"RSI {rsi_val:.1f} — Overbought zone (≥70)")
        elif rsi_val <= 30:
            st.warning(f"RSI {rsi_val:.1f} — Oversold zone (≤30)")
        else:
            st.info(f"RSI {rsi_val:.1f} — Neutral zone (30–70)")
