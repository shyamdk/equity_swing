# Frontend — Robust Swing v1

Next.js 16 (App Router) + Tailwind v4 + TradingView **lightweight-charts**.
Responsive (mobile → desktop), light + dark, one page per stage of the Q1→Q5 funnel.

## Run

The backend must be up first:

```bash
# terminal 1 — database
docker compose up -d

# terminal 2 — API (port 8001; 8000 is taken by another local project)
source venv/bin/activate
uvicorn backend.api.main:app --reload --port 8001

# terminal 3 — UI
cd frontend
npm run dev          # http://localhost:3000 (or 3001 if 3000 is busy)
```

`NEXT_PUBLIC_API_URL` in `.env.local` points at the API (default `http://localhost:8001`).

## Pages

| Route | Stage | Shows |
|---|---|---|
| `/` | — | Dashboard: the funnel as four numbers |
| `/regime` | **Q1** | 🟢/🔴 verdict, benchmark line chart + 50/200-DMA, why-checklist |
| `/watchlist` | **Q2** | Base candidates as cards, each with a pass/fail checklist + chart (lid & base low marked) |
| `/sectors` | **Q2.5** | RRG quadrant plot with rotation trails + ranked table |
| `/entries` | **Q3** | Breakouts, split into "ready to buy" vs "not yet" with the reason |
| `/sizing` | **Q4** | Live position-size calculator; explains which cap bound the size |
| `/positions` | **Q5** | The exit ladder + open paper trades |

## Design notes

- **The palette is validated, not eyeballed.** Quadrant/status hues pass the six checks
  (lightness band, chroma floor, CVD separation, contrast) in **both** light and dark.
  Yellow was rejected — it failed contrast on the light surface.
- **Colour is never the only channel.** Checklists are icon + label; RRG identity comes
  from direct labels and position, not hue (20 sectors far exceeds the 8 categorical
  slots, so we colour by *quadrant*, never by sector).
- **The benchmark uses a line, not candles** — it's a synthetic composite where
  open = high = low = close, so candles would render as meaningless specks.
- Tables scroll inside their own box; the page never scrolls sideways.
