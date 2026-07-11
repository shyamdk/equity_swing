# Build Progress — Equity Swing (Robust Swing v1 rebuild)

> Living log of the rebuild: what we built, **why**, and how to run it.
> Last updated: 2026-07-12. Repo: `github.com/shyamdk/equity_swing` (branch `main`).

---

## 0. Where this started & the goal

The project began as a **Streamlit monolith** (SQLite + `src/` modules) that ingested
NSE OHLCV data from Angel One and ran several ad-hoc scanners. We are **rebuilding it**
around a single, well-documented strategy — **"Robust Swing v1"** (see
[robust_swing_strategy.md](robust_swing_strategy.md)) — with a clean, loosely-coupled
architecture the user can *see and reason about at every stage*.

**Target architecture:** `Next.js frontend` ⇄ `FastAPI backend` ⇄ `Postgres + TimescaleDB`.

**Guiding principles (from the user):**
- The user is **very visual** — every strategy stage must be viewable and explainable
  (a page per stage, pass/fail checklists, charts).
- Charts use **TradingView `lightweight-charts`** (free GitHub lib).
- Keep everything reusable; archive the rest rather than deleting.
- Paper-trade first to prove the edge before real money.

---

## 1. The strategy in one screen (Q1 → Q5 + Q2.5)

Robust Swing v1 is a **funnel of five questions** (plus a sector-rotation preference
layer we added this round). Buy quiet stocks the moment they break out on big volume,
risk 1% per trade with an ATR stop, let a trailing stop ride winners.

| Stage | Question | Core rule |
|---|---|---|
| **Q1** | Is the market healthy? | NIFTY > 200-DMA **and** 50-DMA > 200-DMA (else no new buys) |
| **Q2** | Is this a good stock? | Liquid + in a tight base (RSI reset, <20% range, volume dry-up) |
| **Q2.5** | Is the sector in season? | Prefer stocks whose sector is *leading* the market (RRG); skip *lagging* |
| **Q3** | Is it waking up now? | Vol ≥1.5×, close > 15-day high, RSI>50 & rising, weekly confirms |
| **Q4** | How much to buy? | Qty = (1% of capital) ÷ (entry − stop); stop = tighter of swing-low / 2×ATR |
| **Q5** | When to exit? | Breakeven at +1R, book half at +2R, Chandelier trail (high − 3×ATR), 15-day time stop |

**Q2.5 was researched and written this round** — see §4.

---

## 2. Key decisions (and why)

| # | Decision | Why |
|---|---|---|
| D1 | **Universe = Nifty 500** (other index lists become *tags*, not universes) | Q2's liquidity filter already screens out thin names; tags let us slice (Nifty 100 vs midcaps) later |
| D2 | **Sector rotation = momentum/RRG model**, not the economic-cycle model | We *measure* leadership from price, we don't *forecast* the macro economy — same "follow strength" philosophy as the rest of the strategy |
| D3 | **Sector composites built from the CSV `Industry` column**, not official NSE sector indices | Self-consistent with the universe (the sector we score is made of the exact stocks we trade); NSE lacks clean indices for several of our 21 industries; no extra data pipeline |
| D4 | **Postgres 16 + TimescaleDB** (was SQLite) | Loosely-coupled FastAPI needs a DB *server*; concurrent ingest-writes + API-reads without SQLite write-locks; TimescaleDB hypertables/compression/continuous-aggregates are purpose-built for OHLCV |
| D5 | **Migrate only `ohlcv_1day` / `ohlcv_1week`** from old SQLite; re-ingest intraday | Daily/weekly = 2yr of valuable history (small, fast to move); the 5-min data was already stale and past its useful lookback window, so re-fetch it clean |
| D6 | **Benchmark = NIFTY500EW** (synthetic equal-weight composite of the 500 members) | Computable on migrated data *now* (no API needed), self-consistent with the sector composites; can swap to official NIFTY 50 later |
| D7 | **Single `ohlcv` hypertable** (interval as a column), not one table per interval | Cleaner API (`?interval=`), one chunk policy, easy to add intervals; indices stored here too via `is_index` |
| D8 | **SQLAlchemy 2.0 + psycopg 3** driver | Verified to install with binary wheels on the machine's bleeding-edge **Python 3.14.6** (psycopg2/pandas-ta/numba do **not** work on 3.14) |

---

## 3. Repository restructure

Moved from a flat `src/` + Streamlit layout to:

```
equity_swing/
├─ backend/            # FastAPI backend + reused engine (Python 3.14, venv/)
│  ├─ config.py        # env, intervals, DATABASE_URL, universe paths
│  ├─ db.py            # SQLAlchemy 2.0 engine + read_sql/execute/scalar/ping helpers
│  ├─ database.py      # ohlcv upsert, ingestion-state, read helpers (Postgres)
│  ├─ reference.py     # load symbols master (+ sector) and index tags
│  ├─ angel_client.py  # Angel One SmartAPI wrapper (auth, candles, scrip master)
│  ├─ indicators.py    # RSI/CCI/MACD/BB/EMA/ATR/VWAP via `ta`
│  ├─ data_ingestor.py # fetch → resample (75/125m, weekly) → indicators → upsert
│  ├─ cli.py           # management CLI: check / load-reference / stats / ingest
│  ├─ services/        # strategy Q-stage logic
│  │  ├─ benchmark.py  # NIFTY500EW equal-weight composite
│  │  ├─ regime.py     # Q1 market-regime verdict
│  │  └─ sector.py     # Q2.5 RRG sector-rotation metrics
│  ├─ scanner.py, siva_scanner.py, siva95_scanner.py, paper_portfolio.py, notifier.py
│  │                   # legacy strategy logic — TO BE PORTED into services/ (Q2/Q3/Q4/Q5)
│  └─ requirements.txt
├─ frontend/           # Next.js app (placeholder README; to be scaffolded)
├─ db/
│  ├─ init/01_schema.sql          # runs on first container boot
│  └─ migrate_sqlite_daily_weekly.sh
├─ data/               # equity_swing.db (3GB, gitignored) + MW-*.csv watchlists
├─ old/                # archived Streamlit UI + session glue (app.py, streamlit_app.py, …)
├─ docker-compose.yml  # TimescaleDB service
├─ ind_nifty500list.csv (universe + Industry/sector), EQUITY_L.csv
└─ robust_swing_strategy.md (+ .pdf), build_progress.md (this file)
```

`backend/config.ROOT_DIR = __file__.parent.parent` still resolves to the project root,
so DB/CSV paths kept working after the move.

**Legacy modules still on `from src.*` imports** (`scanner`, `siva_scanner`,
`siva95_scanner`, `paper_portfolio`, `notifier`) are **not yet ported** — they are kept
as reference for the Q2/Q3/Q5 rewrite and are not on the working import path.

---

## 4. Sector-rotation research → doc (Part 6.5)

Researched RRG methodology (Julius de Kempenaer's RS-Ratio / RS-Momentum, the four
quadrants, clockwise rotation) and its Indian-market adaptation, then wrote a new
**Part 6.5 "Q2.5: Is the sector in season?"** section into `robust_swing_strategy.md`:
the intuition (sector = "currents" under the Q1 "tide"), momentum-vs-cyclical models,
a **reproducible RS-Ratio/RS-Momentum recipe** (the exact JdK formula is proprietary),
a sortable **Sector Score**, the "build composites from the `Industry` column" data
decision, integration rules (skip *Lagging*, rank the rest), caveats, and 11 new rows in
the settings table.

---

## 5. Phase 0 — Data foundation ✅

**0.1 — TimescaleDB in Docker.** [docker-compose.yml](docker-compose.yml) runs
`timescale/timescaledb:latest-pg16` with a healthcheck; `.env` provides
`POSTGRES_USER/PASSWORD/DB/PORT` and `DATABASE_URL`.

**0.2 — Schema** ([db/init/01_schema.sql](db/init/01_schema.sql), runs on first boot):
- `symbols` — master (symbol, company, **industry/sector**, series, isin, `is_index`)
- `symbol_tags` — index membership (one row per `(symbol, tag)`)
- `ohlcv` — **hypertable** on `ts`, PK `(symbol, interval, ts)`, 30-day chunks, indicator columns
- `ingestion_state` — delta watermark `(symbol, interval, last_ingested_at)`
- `sector_metrics` — Q2.5 daily RRG output `(sector, ts, composite_close, rs, rs_ratio, rs_momentum, score, quadrant)`
- `signals` — Q2/Q3 scanner output with a JSONB `details` checklist (for the UI)
- `paper_trades` — Q4 sizing + Q5 exit-ladder state and results (in R)

**0.3 — Migration** ([db/migrate_sqlite_daily_weekly.sh](db/migrate_sqlite_daily_weekly.sh)):
driver-free (`sqlite3 -csv | psql \copy` into a temp table → `INSERT … ON CONFLICT`).
Naive SQLite timestamps are NSE/IST, so `SET TimeZone='Asia/Kolkata'` before copy.
**Result: 960,104 daily + 87,808 weekly rows (2024-03 → 2026-03), verified faithful**
(IST round-trips back to the exact source dates/closes — an early "off-by-a-day" scare
was just a UTC display artifact).

Column mapping old→new: `timestamp→ts`, `bb_middle→bb_mid`, `ema_20/50/200→ema20/50/200`.

---

## 6. Phase 1.4 — Engine ported to Postgres ✅

- **`backend/db.py`** — one cached SQLAlchemy engine + `read_sql / execute / scalar / ping`.
- **`backend/database.py`** — rewritten for the single `ohlcv` hypertable. Crucially it
  **preserves the legacy column names on reads** (`timestamp`, `bb_middle`, `ema_20…`) so
  ported scanner/resample code keeps working. Timestamps stored as `timestamptz`;
  exchanged with the app as **naive-IST ISO strings** via `AT TIME ZONE 'Asia/Kolkata'`
  (both directions), so tz handling is unambiguous regardless of server TZ.
- **`backend/reference.py`** — loads the `symbols` master (with `industry`) from
  `ind_nifty500list.csv` and full-refreshes `symbol_tags` from the MW-*.csv files.
- **`data_ingestor.py` / `angel_client.py`** — imports moved to `backend.*`; universe
  switched to **Nifty 500**; upsert path and weekly backfill go through the new layer.
- **`backend/cli.py`** — `check`, `load-reference`, `stats`, `ingest [--dry-run]`,
  `ingest-symbols …`.

**Smoke test (all green):** DB connectivity + schema check; reference load
(**498 symbols + 2,298 tags**); read helpers (legacy col names, correct tz);
upsert + ingestion-state round-trip; and the ingestor's weekly-resample path writing to
Postgres with real data.

> ⚠️ **Live-data blocker:** Angel **login succeeds** but the historical endpoint returns
> `Invalid API Key (AG8004)`. This is a **credentials** issue — consistent with the API
> key being rotated (see §8) — **not** a code issue. Fresh ingestion resumes once `.env`
> holds the new key. Everything else runs on the migrated data.

---

## 7. Phase 1.5 (slice 1) — Benchmark + Q1 + Q2.5 ✅

- **`services/benchmark.py`** — builds **NIFTY500EW**, an equal-weight, daily-rebalanced
  composite of the 500 members (index return = mean of member daily returns, compounded
  from 100). Stored in `ohlcv` as a synthetic `is_index` symbol (daily + weekly). Uses
  `pct_change(fill_method=None)` so stale prices aren't forward-filled into returns.
  Shared composite helpers are reused by the sector service.
- **`services/regime.py` (Q1)** — reads the benchmark, computes 50/200-day **SMA** (DMA),
  returns `{healthy, light 🟢/🔴, price, dma50, dma200, checklist{…}}`.
- **`services/sector.py` (Q2.5)** — per `Industry` sector: equal-weight composite →
  `RS = 100·sector/benchmark` → `RS-Ratio = 100 + z₆₃(RS)` →
  `RS-Momentum = 100 + z₆₃(RS-Ratio − RS-Ratio[−21])` → `SectorScore` (0.6·3m + 0.4·1m
  relative return) → quadrant (leading/improving/weakening/lagging). Full daily series
  persisted to `sector_metrics`; `latest_ranking()` returns the hottest-first snapshot.

**Test on migrated data:** benchmark 495d/105w; Q1 verdict computed (🔴 at the last data
date — composite below both DMAs); **20 sectors ranked** (Forest Materials skipped, <3
members), 7,000 `sector_metrics` rows, coherent quadrants (Power/Metals leading, IT/Realty
lagging).

---

## 8. Security incident & remediation ⚠️

During Phase 1 we found **`.env.example` contained real, live Angel One credentials**
(API key, client id, PIN, TOTP secret) and it had been **pushed to GitHub** in the first
commit. (`.env` itself — with the Dhan token + Gmail app password — was gitignored and
**not** pushed.)

**Actions taken:**
- Sanitized `.env.example` to placeholders; added DB vars.
- **Rewrote the single initial commit** (amend) and **force-pushed**, then expired reflog
  + `git gc` — the secret no longer appears in branch history (verified 0 matches).

**Action still required by the user (urgent):** *rotate the Angel One credentials* —
new API key (developer.angelone.in), new trading PIN, re-setup TOTP. Force-push removes
them from branch history, but GitHub can retain unreachable commits by SHA and any prior
clone/fork keeps them — **rotation is the only guaranteed fix**. This is almost certainly
why live ingestion now returns `Invalid API Key` (§6).

`.gitignore` excludes: `.env`, `*.db`/`*.sqlite`, `venv/`, `logs/`, caches, node_modules.

---

## 9. How to run (current state)

```bash
# 1. Start the database (schema auto-applies on first boot)
docker compose up -d

# 2. Python env
source venv/bin/activate
pip install -r backend/requirements.txt          # psycopg3, SQLAlchemy, ta, fastapi, …

# 3. One-time migration of daily/weekly history (already done once)
bash db/migrate_sqlite_daily_weekly.sh

# 4. Load reference data + verify
python -m backend.cli check
python -m backend.cli load-reference             # 498 symbols + 2298 tags
python -m backend.cli stats

# 5. Build the analytics (on migrated data)
python -c "from backend.services.benchmark import build_benchmark; print(build_benchmark())"
python -c "from backend.services.regime import get_regime; print(get_regime())"
python -c "from backend.services.sector import build_sector_metrics, latest_ranking; \
           build_sector_metrics(); print(latest_ranking().to_string())"

# 6. Live ingestion — BLOCKED until Angel API key is rotated in .env
# python -m backend.cli ingest-symbols RELIANCE TCS INFY
# python -m backend.cli ingest            # full Nifty 500 delta
```

---

## 10. Status & next steps

**Done:** Phase 0 (DB + migration), Phase 1.4 (engine port), Phase 1.5 slice 1
(benchmark, Q1, Q2.5).

**Next — Phase 1.5 slice 2:** port the per-stock scanners into `services/`:
- **Q2** base/liquidity → watchlist (from `siva_scanner`/`scanner`)
- **Q3** breakout entry + weekly MTF confirm
- **Q4** position sizing (pure math)
- **Q5** exit ladder (breakeven / partial / Chandelier trail / time stop)

Each emits a **pass/fail checklist** persisted to `signals.details` (JSONB) for the UI.

**Then:**
- **Phase 1.6** — FastAPI app, one endpoint group per Q-stage
  (`/regime`, `/watchlist`, `/sectors`, `/entries`, `/positions`).
- **Phase 2** — Next.js scaffold + one page per Q-stage with checklists, annotated
  `lightweight-charts`, and the RRG quadrant plot.

**Open items:**
- 🔴 Rotate Angel One credentials, update `.env`, then run a full ingest to refresh the
  stale (→2026-03-23) data.
- Optionally wire official NIFTY 50 as an alternate benchmark once creds work (D6).

---

## 11. Programmer To Do (tasks that need **you**)

These are the items only you can do (accounts, credentials, decisions). Ordered by
priority. Check them off as you go.

### 🔴 T1 — Rotate the leaked Angel One credentials  *(security-critical, blocks live data)*
The old key/PIN/TOTP were exposed in git history (§8) **and** the historical API now
rejects the old key. Do a full rotation:

1. **API key** — log in to <https://smartapi.angelbroking.com/> (developer portal) →
   **My Apps**. Delete the app whose key is `FOYSHNRk`, then **Create App**.
   - App type must have **Historical Data** access (this is why `getCandleData` returned
     `Invalid API Key` even though login worked — see T2).
   - Copy the **new API key**.
2. **Trading PIN** — in the Angel One app: Profile → Settings → **Reset PIN**. Choose a
   new 4-digit PIN (the old `6791` is compromised).
3. **TOTP secret** — Angel One app: Profile → Security → **Enable/Reset TOTP**. Remove the
   old entry from your authenticator app, scan the new QR, and **save the new base32
   secret string** (shown next to/under the QR).
4. **Update `.env`** (see T3), then **verify**:
   ```bash
   source venv/bin/activate
   python -m backend.cli ingest-symbols RELIANCE
   # expect: "5min/1day … rows" written, NOT "Invalid API Key"
   ```

### 🔴 T2 — Confirm Historical Data API entitlement
Login succeeds but `getCandleData` fails, which usually means the app key lacks historical
access. When creating the app in T1:
- Ensure the app is enabled for **Historical Data** (SmartAPI historical/candle endpoint).
- If the portal separates "Trading" vs "Historical Data" / "Market Feed" apps, use the key
  from the one with historical enabled.
- Sanity check after rotation: the RELIANCE command in T1.4 should return candles.

### 🔴 T3 — Update `.env` with the new secrets
Edit `/Users/shyamdk/Developer/equity_swing/.env` (this file is gitignored — safe):
```
ANGEL_API_KEY=<new key from T1>
ANGEL_CLIENT_ID=S57280135          # unchanged (not a secret, but fine to keep)
ANGEL_PIN=<new PIN from T1>
ANGEL_TOTP_SECRET=<new base32 secret from T1>
```
Do **not** put these in `.env.example`. After saving, run T1.4 to confirm.

### 🟠 T4 — Run a full data refresh (after T1–T3)
The migrated data is stale (→ 2026-03-23). Once live ingest works:
```bash
source venv/bin/activate
python -m backend.cli ingest            # full Nifty 500 delta (parallel, rate-limited)
python -m backend.cli stats             # confirm row counts grew & dates are current
# then rebuild analytics on fresh data:
python -c "from backend.services.benchmark import build_benchmark; print(build_benchmark())"
python -c "from backend.services.sector import build_sector_metrics; print(build_sector_metrics())"
```
Note: a first full intraday backfill for 500 symbols at ~1 req/s takes a while (tens of
minutes). Keep the machine awake.

### 🟡 T5 — Decide paper-trading parameters (input for Q4/Q5, slice 2)
Before I build the sizing/exit services, confirm the defaults or give your numbers:
- **Starting capital** (₹) — used by Q4 to size positions. (doc example uses ₹1,00,000)
- **Risk per trade** — default **1%** of capital.
- **Max open positions** — default **6**; **max per position** — default **20%**.
- **Exit ladder** — breakeven +1R, book half +2R, Chandelier 3×ATR trail, 15-day time stop.

Reply with "use defaults" or your overrides; I'll wire them into `services/` + config.

### 🟡 T6 — Keep infra running while working
- **Docker Desktop** must be running for the DB (`docker compose up -d`; check with
  `docker ps` — container `equity_swing_db`).
- If you reboot: `docker compose up -d` again (data persists in the `pgdata` volume).

### 🟢 T7 — (Optional) Notifications
If you want ntfy push / email alerts later:
- **ntfy**: install the ntfy app, subscribe to a unique topic, set `NTFY_TOPIC` in `.env`.
- **Email**: create a Gmail **App Password** (Google Account → Security → App Passwords)
  and set `SMTP_USER` / `SMTP_PASSWORD` / `NOTIFY_EMAIL`. (An app password is already in
  `.env`; verify it still works or regenerate.)

### 🟢 T8 — (Optional, before any non-local deployment) Harden the DB password
`POSTGRES_PASSWORD`/`DATABASE_URL` currently use `equity_local_pw` (fine for localhost).
If this ever runs outside your machine, set a strong password in `.env` and
`docker compose down && docker compose up -d` (note: changing the password after the volume
is initialized requires either recreating the role or resetting the `pgdata` volume).

### ✅ Already satisfied (no action)
- **Node.js** v25.8.1 + **npm** 11 installed → frontend (Phase 2) prerequisite met.
- **Python** 3.14.6 venv with `psycopg[binary]` + SQLAlchemy verified.
- **gh** CLI installed; SSH push to GitHub working.
