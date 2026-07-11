# Siva Swing Strategy

## Overview

The **Siva Swing Strategy** identifies stocks that have gone through a
**momentum reset followed by accumulation** and are preparing for a
**high-volume breakout**.

Timeframe: **Daily (1D)**

Indicators used: - Price Action - Volume - RSI - CCI (optional)

The strategy works in two stages:

1.  **Scanner Level‑1 --- Watchlist Builder**
2.  **Scanner Level‑2 --- Entry Detection**

------------------------------------------------------------------------

# Stage 1 -- Scanner Level‑1 (Watchlist Builder)

Purpose: Identify stocks that are **consolidating after a decline** and
preparing for a move.

## Condition 1 -- Momentum Reset

Average RSI over last 25 periods:

35 ≤ RSI_mean_25 ≤ 48

Additional confirmation:

min(RSI_last_25) \< 35

Meaning: momentum cooled and sellers exhausted.

------------------------------------------------------------------------

## Condition 2 -- Price Base Formation

Sideways consolidation rule:

(HighestHigh_last20 − LowestLow_last20) / LowestLow_last20 \< 20%

Meaning: volatility contraction and base building.

------------------------------------------------------------------------

## Condition 3 -- Volume Compression

avg(volume_last10) \< avg(volume_last30)

Meaning: supply drying up during consolidation.

------------------------------------------------------------------------

## Condition 4 -- Liquidity Filter

avg(volume_last20) \> 200000

or

avg_turnover_last20 \> ₹5 Cr

------------------------------------------------------------------------

## Condition 5 -- Price Filter (Optional)

price \> ₹80

------------------------------------------------------------------------

## Output of Scanner Level‑1

Example Watchlist

-   KPI Green Energy
-   Regal Resources
-   RVNL
-   IRFC
-   Suzlon

These are **watch candidates**, not entries yet.

------------------------------------------------------------------------

# Stage 2 -- Scanner Level‑2 (Entry Detection)

Purpose: Monitor the watchlist and detect **entry signals**.

------------------------------------------------------------------------

## Condition 1 -- Volume Expansion

Volume_today ≥ 1.5 × avg(volume_last20)

Strong signal:

Volume_today ≥ 2 × avg(volume_last20)

------------------------------------------------------------------------

## Condition 2 -- RSI Momentum Shift

RSI_today \> 50

Momentum confirmation:

RSI_today \> RSI_5_days_ago

------------------------------------------------------------------------

## Condition 3 -- Price Strength

Close_today \> HighestHigh_last15

Meaning: structural breakout.

------------------------------------------------------------------------

## Condition 4 -- CCI Confirmation (Optional)

CCI_today \> 0

------------------------------------------------------------------------

# Entry Trigger

Entry candidate when:

Volume spike AND RSI \> 50 AND Price breaks 15‑day high

------------------------------------------------------------------------

# Entry Zone

Avoid chasing breakout candles.

Preferred RSI entry range:

45 ≤ RSI ≤ 55

Meaning: healthy pullback inside bullish momentum.

------------------------------------------------------------------------

# Risk Management

Option 1 --- Swing Low

Stop = Recent swing low

Option 2 --- Fixed Risk

Stop Loss = 5% -- 7%

------------------------------------------------------------------------

# Target Expectation

Typical swing moves:

15% -- 30%

Average holding period:

10 -- 25 trading days

------------------------------------------------------------------------

# Ideal Market Conditions

Works best in:

-   Midcap stocks
-   Smallcap stocks
-   Infrastructure
-   Energy
-   Capital goods

Avoid:

-   Large banks
-   Mega IT stocks

------------------------------------------------------------------------

# Strategy Flow

NSE Universe → Scanner Level‑1 (Accumulation Detection) → Watchlist →
Scanner Level‑2 (Breakout Detection) → Entry Alert → Swing Trade

------------------------------------------------------------------------

# Strategy Principle

Strong moves begin after a **momentum reset and accumulation phase**.

When **RSI stays below 50 for an extended period** and then **volume
expansion occurs**, the probability of a **swing breakout increases
significantly**.
