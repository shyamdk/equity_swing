const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";

export type Checklist = Record<string, boolean>;
export type Quadrant = "leading" | "improving" | "weakening" | "lagging" | "n/a";

export interface Regime {
  benchmark: string;
  asof: string;
  healthy: boolean;
  light: string;
  price: number;
  dma50: number;
  dma200: number;
  checklist: Checklist;
}

export interface Sector {
  sector: string;
  ts: string;
  rs_ratio: number;
  rs_momentum: number;
  score: number;
  quadrant: Quadrant;
}

export interface RRGSeries {
  sector: string;
  points: { ts: string; rs_ratio: number; rs_momentum: number; quadrant: Quadrant }[];
}

export interface BaseRow {
  symbol: string;
  asof: string;
  sector: string | null;
  quadrant: Quadrant | null;
  sector_score: number | null;
  close: number;
  turnover_cr: number;
  rsi_mean_25: number;
  base_range_pct: number;
  base_high: number;
  base_low: number;
  atr: number | null;
  checklist: Checklist;
  passed: boolean;
}

export interface EntryRow {
  symbol: string;
  asof: string;
  sector: string | null;
  quadrant: Quadrant | null;
  close: number;
  breakout_level: number;
  past_breakout_pct: number;
  vol_ratio: number;
  strong_volume: boolean;
  rsi: number;
  weekly_rsi: number | null;
  atr: number | null;
  checklist: Checklist;
  passed: boolean;
}

export interface Sizing {
  entry: number;
  atr: number;
  stop: number;
  stop_source: string;
  qty: number;
  qty_uncapped: number;
  risk_per_share: number;
  risk_amount: number;
  risk_pct_of_capital: number;
  position_value: number;
  position_pct_of_capital: number;
  binding_constraint: string | null;
  capital: number;
  reason?: string;
}

export interface Candles {
  symbol: string;
  interval: string;
  candles: { time: string; open: number; high: number; low: number; close: number }[];
  volume: { time: string; value: number }[];
  indicators: Record<string, { time: string; value: number }[]>;
}

export interface Meta {
  universe: { name: string; symbols: number; source: string; note: string };
  data_asof: string | null;
  stale_business_days: number | null;
  last_ingest_run: string | null;
  sectors_asof: string | null;
  sector_lag_days: number | null;
  benchmark_asof: string | null;
  refresh: { mode: string; note: string; steps: string[] };
  intervals: { interval: string; symbols: number; latest: string }[];
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}

export interface Trade {
  id: number;
  symbol: string;
  status: "open" | "closed";
  entry_ts: string;
  entry_price: number;
  qty: number;
  qty_open: number | null;
  initial_stop: number;
  current_stop: number;
  r_value: number;
  highest_since_entry: number | null;
  moved_to_breakeven: boolean;
  partial_booked: boolean;
  partial_ts: string | null;
  partial_price: number | null;
  partial_qty: number | null;
  exit_ts: string | null;
  exit_price: number | null;
  exit_reason: string | null;
  pnl: number | null;
  r_multiple: number | null;
  days_held: number | null;
  sector: string | null;
  sector_quadrant: Quadrant | null;
  capital_at_entry: number | null;
  entry_context: Record<string, any> | null;
  exit_context: Record<string, any> | null;
}

export interface PaperStats {
  closed_trades: number;
  win_rate_pct?: number;
  avg_win_R?: number;
  avg_loss_R?: number;
  expectancy_R?: number;
  total_pnl?: number;
  max_drawdown?: number;
  open_trades?: number;
  exit_reasons?: Record<string, number>;
}

export interface Settings {
  CAPITAL: number;
  RISK_PCT: number;
  MAX_POSITION_PCT: number;
  MAX_TOTAL_DEPLOYED_PCT: number;
  MAX_OPEN_POSITIONS: number;
}

export const api = {
  meta: () => get<Meta>("/meta"),
  settings: () => get<Settings>("/settings"),
  saveSettings: async (body: Partial<Settings>): Promise<Settings> => {
    const res = await fetch(`${BASE}/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`/settings → ${res.status}`);
    return res.json();
  },
  regime: () => get<Regime>("/regime"),
  sectors: () => get<Sector[]>("/sectors"),
  rrg: (tail = 8) => get<RRGSeries[]>(`/sectors/rrg?tail=${tail}`),
  watchlist: (onlyPassed = true) => get<BaseRow[]>(`/watchlist?only_passed=${onlyPassed}`),
  entries: (onlyPassed = false) => get<EntryRow[]>(`/entries?only_passed=${onlyPassed}`),
  candles: (symbol: string, interval = "1day", limit = 250) =>
    get<Candles>(`/candles/${symbol}?interval=${interval}&limit=${limit}`),
  config: () => get<Record<string, number | string | boolean>>("/config"),
  positions: (status = "all", runTag = "replay") =>
    get<Trade[]>(`/positions?status=${status}&run_tag=${runTag}`),
  paperStats: (runTag = "replay") => get<PaperStats>(`/paper/stats?run_tag=${runTag}`),
  size: async (body: Record<string, number | null>): Promise<Sizing> => {
    const res = await fetch(`${BASE}/size`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`/size → ${res.status}`);
    return res.json();
  },
};

export const QUADRANT_COLOR: Record<string, string> = {
  leading: "var(--leading)",
  improving: "var(--improving)",
  weakening: "var(--weakening)",
  lagging: "var(--lagging)",
  "n/a": "var(--ink-muted)",
};

/** Human labels for checklist keys — the UI never shows a raw snake_case key. */
export const CHECK_LABELS: Record<string, string> = {
  price_above_min: "Price above minimum",
  liquid: "Liquid enough to trade",
  momentum_reset: "Momentum reset (sellers exhausted)",
  tight_base: "Tight base (coiled spring)",
  volume_dryup: "Volume dried up",
  volume_expansion: "Volume expansion (crowd arrived)",
  price_breakout: "Broke above the lid",
  momentum_confirms: "Momentum confirms (RSI>50, rising)",
  weekly_confirms: "Weekly chart agrees",
  not_chasing: "Not chasing (still near breakout)",
  sector_in_season: "Sector in season",
  price_above_200dma: "Market above its 200-DMA",
  "50dma_above_200dma": "50-DMA above 200-DMA",
};
