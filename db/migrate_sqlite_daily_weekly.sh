#!/usr/bin/env bash
# ============================================================================
# One-time migration: copy ohlcv_1day / ohlcv_1week from the legacy SQLite DB
# into the new Postgres/TimescaleDB `ohlcv` hypertable. Driver-free (sqlite3 CSV
# piped into psql \copy), so it does not depend on a Python Postgres driver.
#
# Naive SQLite timestamps (e.g. 2025-11-20T00:00:00) are NSE/IST candle times,
# so the session TimeZone is set to Asia/Kolkata before the copy.
#
# Idempotent-ish: uses a TEMP staging table + INSERT ... ON CONFLICT DO NOTHING,
# so re-running won't duplicate rows.
# ============================================================================
set -euo pipefail

SQLITE_DB="${SQLITE_PATH:-data/equity_swing.db}"
CONTAINER="equity_swing_db"
PGUSER="${POSTGRES_USER:-equity}"
PGDB="${POSTGRES_DB:-equity_swing}"

# new ohlcv column order for COPY
COLS="symbol,interval,ts,open,high,low,close,volume,rsi,cci,macd,macd_signal,macd_hist,bb_upper,bb_mid,bb_lower,ema20,ema50,ema200,atr,vwap"

migrate_interval () {
  local src_table="$1"      # ohlcv_1day
  local interval_label="$2" # 1day
  echo "→ migrating ${src_table} as interval='${interval_label}' ..."

  # SQLite SELECT columns must match COLS order (bb_middle→bb_mid, ema_N→emaN).
  sqlite3 -csv "${SQLITE_DB}" \
    "SELECT symbol, '${interval_label}', timestamp, open, high, low, close, volume,
            rsi, cci, macd, macd_signal, macd_hist,
            bb_upper, bb_middle, bb_lower, ema_20, ema_50, ema_200, atr, vwap
     FROM ${src_table};" \
  | docker exec -i "${CONTAINER}" psql -q -U "${PGUSER}" -d "${PGDB}" \
      -c "SET TimeZone='Asia/Kolkata';" \
      -c "CREATE TEMP TABLE _stage (LIKE ohlcv INCLUDING DEFAULTS);" \
      -c "\copy _stage(${COLS}) FROM STDIN WITH (FORMAT csv)" \
      -c "INSERT INTO ohlcv (${COLS}) SELECT ${COLS} FROM _stage ON CONFLICT (symbol, interval, ts) DO NOTHING;"
}

migrate_interval ohlcv_1day  1day
migrate_interval ohlcv_1week 1week

echo "=== post-migration counts (Postgres) ==="
docker exec -i "${CONTAINER}" psql -U "${PGUSER}" -d "${PGDB}" -c \
  "SELECT interval, count(*) AS rows, min(ts)::date AS first, max(ts)::date AS last
   FROM ohlcv GROUP BY interval ORDER BY interval;"
