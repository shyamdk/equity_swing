-- ============================================================================
-- Robust Swing v1 — Postgres + TimescaleDB schema
-- Runs automatically on first container boot (docker-entrypoint-initdb.d).
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ----------------------------------------------------------------------------
-- Symbol master (from ind_nifty500list.csv). `industry` is the sector used by
-- Q2.5 sector rotation. Indices (e.g. 'NIFTY 500') are stored here too, marked
-- is_index = true, so their candles can live in the same ohlcv table.
-- ----------------------------------------------------------------------------
CREATE TABLE symbols (
    symbol        TEXT PRIMARY KEY,
    company_name  TEXT,
    industry      TEXT,               -- sector (21 values in Nifty 500)
    series        TEXT,
    isin          TEXT,
    is_index      BOOLEAN NOT NULL DEFAULT FALSE,
    added_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_symbols_industry ON symbols (industry);

-- Index-membership tags (Nifty50, Nifty100, Midcap150, …) from MW-*.csv.
CREATE TABLE symbol_tags (
    symbol  TEXT NOT NULL REFERENCES symbols(symbol) ON DELETE CASCADE,
    tag     TEXT NOT NULL,
    PRIMARY KEY (symbol, tag)
);

-- ----------------------------------------------------------------------------
-- OHLCV — one hypertable for all intervals & symbols (incl. indices).
-- interval ∈ {5min, 75min, 125min, 1day, 1week}. Indicator columns are
-- nullable so intraday and higher-timeframe rows can share the shape.
-- ----------------------------------------------------------------------------
CREATE TABLE ohlcv (
    symbol      TEXT        NOT NULL,
    interval    TEXT        NOT NULL,
    ts          TIMESTAMPTZ NOT NULL,
    open        DOUBLE PRECISION,
    high        DOUBLE PRECISION,
    low         DOUBLE PRECISION,
    close       DOUBLE PRECISION,
    volume      BIGINT,
    -- indicators (computed at ingest)
    rsi         DOUBLE PRECISION,
    cci         DOUBLE PRECISION,
    macd        DOUBLE PRECISION,
    macd_signal DOUBLE PRECISION,
    macd_hist   DOUBLE PRECISION,
    bb_upper    DOUBLE PRECISION,
    bb_mid      DOUBLE PRECISION,
    bb_lower    DOUBLE PRECISION,
    ema20       DOUBLE PRECISION,
    ema50       DOUBLE PRECISION,
    ema200      DOUBLE PRECISION,
    atr         DOUBLE PRECISION,
    vwap        DOUBLE PRECISION,
    PRIMARY KEY (symbol, interval, ts)
);
-- Hypertable partitioned on time; 30-day chunks suit the 5-min-heavy load.
SELECT create_hypertable('ohlcv', 'ts', chunk_time_interval => INTERVAL '30 days');
CREATE INDEX idx_ohlcv_interval_ts ON ohlcv (interval, ts DESC);

-- Delta-ingestion bookkeeping.
CREATE TABLE ingestion_state (
    symbol            TEXT NOT NULL,
    interval          TEXT NOT NULL,
    last_ingested_at  TIMESTAMPTZ,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, interval)
);

-- ----------------------------------------------------------------------------
-- Q2.5 sector rotation — daily composite + RRG metrics per sector.
-- ----------------------------------------------------------------------------
CREATE TABLE sector_metrics (
    sector          TEXT NOT NULL,
    ts              DATE NOT NULL,
    composite_close DOUBLE PRECISION,   -- equal-weight member composite
    rs              DOUBLE PRECISION,   -- 100 * sector/benchmark
    rs_ratio        DOUBLE PRECISION,   -- normalized, ~100
    rs_momentum     DOUBLE PRECISION,   -- normalized, ~100
    score           DOUBLE PRECISION,   -- 0.6*RS(3m)+0.4*RS(1m) vs benchmark
    quadrant        TEXT,               -- leading|improving|weakening|lagging
    PRIMARY KEY (sector, ts)
);

-- ----------------------------------------------------------------------------
-- Signals — scanner output for Q2 (base/watchlist) and Q3 (entry trigger).
-- `details` holds the per-sub-condition pass/fail checklist for the UI.
-- ----------------------------------------------------------------------------
CREATE TABLE signals (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    symbol      TEXT NOT NULL,
    ts          DATE NOT NULL,
    stage       TEXT NOT NULL,          -- 'Q2' | 'Q3'
    passed      BOOLEAN NOT NULL,
    details     JSONB,                  -- {"rsi_reset": true, "tight_base": false, ...}
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_signals_symbol_ts ON signals (symbol, ts DESC);
CREATE INDEX idx_signals_stage_ts  ON signals (stage, ts DESC);

-- ----------------------------------------------------------------------------
-- Paper trades — Q4 sizing + Q5 exit-ladder state and results (in R).
-- ----------------------------------------------------------------------------
CREATE TABLE paper_trades (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    symbol              TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'open',   -- 'open' | 'closed'
    -- entry / sizing (Q4)
    entry_ts            TIMESTAMPTZ NOT NULL,
    entry_price         DOUBLE PRECISION NOT NULL,
    qty                 INTEGER NOT NULL,
    initial_stop        DOUBLE PRECISION NOT NULL,
    r_value             DOUBLE PRECISION NOT NULL,       -- risk per share = entry - initial_stop
    -- exit-ladder state (Q5)
    current_stop        DOUBLE PRECISION NOT NULL,
    highest_since_entry DOUBLE PRECISION,
    moved_to_breakeven  BOOLEAN NOT NULL DEFAULT FALSE,
    partial_booked      BOOLEAN NOT NULL DEFAULT FALSE,
    -- exit / result
    exit_ts             TIMESTAMPTZ,
    exit_price          DOUBLE PRECISION,
    exit_reason         TEXT,           -- 'stop' | 'trail' | 'time' | 'target'
    pnl                 DOUBLE PRECISION,
    r_multiple          DOUBLE PRECISION,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_paper_trades_status ON paper_trades (status);
CREATE INDEX idx_paper_trades_symbol ON paper_trades (symbol);
