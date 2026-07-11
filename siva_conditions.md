# Signal Scanner — Conditions & Controls

## What it does
Scans all ingested NSE 500 symbols on the selected interval for a **momentum breakout setup**: a period of weakness followed by a volume-confirmed bullish spike.

---

## Signal Conditions (all four must be true on the same candle)

| # | Condition | Value |
|---|-----------|-------|
| 1 | **Avg RSI of the 5 candles immediately before the signal candle** | < 50 (stock was in weak/oversold baseline) |
| 2 | **Signal candle RSI** | > 50 (momentum crossed into bullish territory) |
| 3 | **Signal candle CCI** | > 100 (bullish momentum spike) |
| 4 | **Signal candle Volume** | ≥ 4× the average volume of those same 5 prior candles |

---

## UI Controls (dropdowns / inputs)

| Control | Type | Options / Range | Default |
|---------|------|-----------------|---------|
| **Interval** | Dropdown | `5min`, `75min`, `125min`, `1day`, `1week` | `1day` |
| **Candles to scan** | Number input | 20 – 200 | 60 |
| **Max signal age (candles)** | Number input | 1 – 20 | 5 |

- **Candles to scan** — how many recent candles are loaded per symbol to look for the pattern.
- **Max signal age** — a signal is only reported if it occurred within the last N candles from the most recent data. `0` = current candle, `1` = one candle ago, etc.

---

## Output Columns

| Column | Meaning |
|--------|---------|
| `symbol` | NSE ticker |
| `signal_date` | Date/time the signal candle formed |
| `candles_ago` | 0 = most recent candle; higher = older |
| `close` | Close price on signal candle |
| `rsi` | RSI value on signal candle |
| `cci` | CCI value on signal candle |
| `volume` | Volume on signal candle |
| `avg_rsi_5_prior` | Mean RSI of the 5 candles before the signal |
| `avg_vol_5_prior` | Mean volume of the 5 candles before the signal |
| `vol_ratio` | Signal volume ÷ avg_vol_5_prior (higher = stronger surge) |

Results are sorted freshest signal first. `vol_ratio ≥ 8` is highlighted dark green; `vol_ratio ≥ 4` light green.
