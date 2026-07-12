"use client";

import CandleChart, { Marker, PriceLine } from "@/components/CandleChart";
import { api, PaperStats, Trade } from "@/lib/api";
import {
  Card,
  ChecklistView,
  Empty,
  ErrorBox,
  Loading,
  QuadrantBadge,
  SectionTitle,
  StatTile,
} from "@/components/ui";
import { useEffect, useState } from "react";

const LADDER = [
  { step: "Initial stop (−1R)", detail: "Tighter of the swing low or 2×ATR below entry. If hit, you lose exactly 1R." },
  { step: "Breakeven at +1R", detail: "Stop moves up to entry. From here the trade can no longer lose money." },
  { step: "Book half at +2R", detail: "Sell half. Real profit locked in; the rest rides." },
  { step: "Chandelier trail", detail: "Stop = highest high since entry − 3×ATR. Rises with the stock, never falls." },
  { step: "Time stop", detail: "Flat (under +5%) after 15 trading days? Exit. Dead money is a cost." },
];

const day = (ts: string | null) => (ts ? ts.slice(0, 10) : "");

export default function PositionsPage() {
  const [trades, setTrades] = useState<Trade[] | null>(null);
  const [st, setSt] = useState<PaperStats | null>(null);
  const [runTag, setRunTag] = useState("replay");
  const [filter, setFilter] = useState("all");
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setTrades(null);
    Promise.all([api.positions("all", runTag), api.paperStats(runTag)])
      .then(([t, s]) => {
        setTrades(t);
        setSt(s);
      })
      .catch((e) => setErr(String(e)));
  }, [runTag]);

  if (err) return <ErrorBox error={err} />;

  const view = (trades ?? []).filter((t) => filter === "all" || t.status === filter);
  const edge = st?.expectancy_R ?? 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold sm:text-2xl">Q5 · When do I get out?</h1>
        <p className="mt-1 max-w-2xl text-sm text-ink-2">
          Trades are taken <strong className="text-ink">automatically</strong> — no discretion. If a
          human picked which breakouts to take, these numbers would measure the human, not the
          system. Every exit is planned before the buy.
        </p>
      </div>

      {/* the scoreboard — the only thing that matters */}
      {st && st.closed_trades > 0 && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
            <StatTile
              label="Expectancy"
              value={`${edge > 0 ? "+" : ""}${edge.toFixed(3)}R`}
              sub={edge > 0 ? "positive edge" : "loses money per trade"}
              accent={edge > 0 ? "var(--good)" : "var(--critical)"}
            />
            <StatTile label="Win rate" value={`${st.win_rate_pct}%`} sub={`${st.closed_trades} closed trades`} />
            <StatTile
              label="Avg win / loss"
              value={`+${st.avg_win_R}R / ${st.avg_loss_R}R`}
              sub={
                (st.avg_win_R ?? 0) < Math.abs(st.avg_loss_R ?? 0)
                  ? "⚠ winners smaller than losers"
                  : "winners bigger than losers"
              }
            />
            <StatTile
              label="Total P&L"
              value={`₹${(st.total_pnl ?? 0).toLocaleString("en-IN")}`}
              sub={`max drawdown ₹${(st.max_drawdown ?? 0).toLocaleString("en-IN")}`}
              accent={(st.total_pnl ?? 0) >= 0 ? "var(--good)" : "var(--critical)"}
            />
          </div>

          {edge <= 0 && (
            <div
              className="rounded-xl border border-hairline border-l-4 bg-surface px-4 py-3 text-sm"
              style={{ borderLeftColor: "var(--critical)" }}
            >
              <strong className="text-ink">This strategy loses money on this sample.</strong>{" "}
              <span className="text-ink-2">
                Expectancy is {edge.toFixed(3)}R per trade. The design needs winners of 2–5R to pay
                for the 1R losers — but exits here are{" "}
                {Object.entries(st.exit_reasons ?? {})
                  .map(([k, v]) => `${v} ${k}`)
                  .join(", ")}
                , and no trade reached +2R to book a partial. Treat this as a{" "}
                <strong className="text-ink">blocker on trading it for real</strong>, not a
                verdict — {st.closed_trades} trades is a small sample and the period was hostile.
              </span>
            </div>
          )}
        </>
      )}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <label className="inline-flex items-center gap-2 text-sm text-ink-2">
          Book:
          <select
            value={runTag}
            onChange={(e) => setRunTag(e.target.value)}
            className="rounded-lg border border-hairline bg-surface px-2 py-1 text-sm text-ink"
          >
            <option value="replay">Replay (historical backtest)</option>
            <option value="live">Live (forward paper trading)</option>
          </select>
        </label>
        <label className="inline-flex items-center gap-2 text-sm text-ink-2">
          Show:
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="rounded-lg border border-hairline bg-surface px-2 py-1 text-sm text-ink"
          >
            <option value="all">All trades</option>
            <option value="open">Open only</option>
            <option value="closed">Closed only</option>
          </select>
        </label>
        <span className="text-sm text-ink-muted">{view.length} trades</span>
      </div>

      <Card>
        <SectionTitle hint="R = your initial risk per share. Everything is measured in R.">
          The exit ladder
        </SectionTitle>
        <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {LADDER.map((l, i) => (
            <li key={l.step} className="flex gap-2 rounded-lg bg-page p-2.5">
              <span className="tnum mt-0.5 h-5 w-5 shrink-0 rounded-full bg-ink-muted text-center text-xs font-bold leading-5 text-white">
                {i + 1}
              </span>
              <div className="min-w-0">
                <div className="text-sm font-medium text-ink">{l.step}</div>
                <div className="text-sm text-ink-2">{l.detail}</div>
              </div>
            </li>
          ))}
        </ol>
      </Card>

      {!trades ? (
        <Loading what="trades" />
      ) : view.length === 0 ? (
        <Empty>
          No trades in this book yet. Run a replay to build the historical record, or a live cycle
          once today&apos;s data is in.
        </Empty>
      ) : (
        <div className="space-y-4">
          {view.map((t) => (
            <TradeCard key={t.id} t={t} />
          ))}
        </div>
      )}
    </div>
  );
}

function TradeCard({ t }: { t: Trade }) {
  const [open, setOpen] = useState(false);
  const closed = t.status === "closed";
  const r = t.r_multiple ?? 0;
  const good = r > 0;

  const markers: Marker[] = [
    { time: day(t.entry_ts), kind: "entry", text: `BUY ${t.qty} @ ${t.entry_price}` },
  ];
  if (t.partial_ts)
    markers.push({
      time: day(t.partial_ts),
      kind: "partial",
      text: `BOOK ${t.partial_qty} @ ${t.partial_price}`,
    });
  if (t.exit_ts)
    markers.push({
      time: day(t.exit_ts),
      kind: "exit",
      text: `${t.exit_reason?.toUpperCase()} @ ${t.exit_price}`,
    });

  const lines: PriceLine[] = [
    { price: t.entry_price, title: "entry" },
    { price: t.initial_stop, title: "initial stop", color: "var(--critical)", dashed: true },
  ];
  if (closed && t.current_stop !== t.initial_stop)
    lines.push({ price: t.current_stop, title: "final stop", color: "var(--improving)", dashed: true });

  const ctx = t.entry_context ?? {};

  // Zoom to the trade: ~2 months of the base before entry, a few weeks after the exit.
  const shift = (d: string, days: number) => {
    const x = new Date(d);
    x.setDate(x.getDate() + days);
    return x.toISOString().slice(0, 10);
  };
  const focus = {
    from: shift(day(t.entry_ts), -70),
    to: shift(day(t.exit_ts ?? t.entry_ts), 25),
  };

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold text-ink">{t.symbol}</h3>
            <span
              className="rounded-full px-2 py-0.5 text-xs font-semibold text-white"
              style={{
                background: closed
                  ? good
                    ? "var(--good)"
                    : "var(--critical)"
                  : "var(--improving)",
              }}
            >
              {closed ? `${r > 0 ? "+" : ""}${r.toFixed(2)}R · ${t.exit_reason}` : "OPEN"}
            </span>
            <QuadrantBadge quadrant={t.sector_quadrant} />
          </div>
          <div className="mt-1 text-sm text-ink-2">
            {t.sector ?? "—"} · bought {day(t.entry_ts)}
            {closed && ` · sold ${day(t.exit_ts)} · held ${t.days_held}d`}
          </div>
        </div>
        <div className="tnum shrink-0 text-right text-sm">
          <div className="font-semibold text-ink">
            {t.qty} @ ₹{t.entry_price.toLocaleString("en-IN")}
          </div>
          <div className="text-ink-muted">
            stop ₹{t.initial_stop} · 1R = ₹{t.r_value}/sh
          </div>
          {closed && (
            <div style={{ color: good ? "var(--good)" : "var(--critical)" }}>
              P&L ₹{(t.pnl ?? 0).toLocaleString("en-IN")}
            </div>
          )}
        </div>
      </div>

      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="mt-3 rounded-lg border border-hairline px-3 py-1.5 text-sm text-ink-2 hover:text-ink"
      >
        {open ? "Hide chart & decision record" : "Show chart & why it was bought"}
      </button>

      {open && (
        <div className="mt-4 space-y-4">
          <div>
            <CandleChart
              symbol={t.symbol}
              height={320}
              limit={400}
              markers={markers}
              priceLines={lines}
              overlays={["ema50"]}
              focus={focus}
            />
            <p className="mt-2 text-sm text-ink-muted">
              ▲ entry · ● partial · ▼ exit. Dashed red = initial stop.
            </p>
          </div>

          {/* the full decision record captured AT THE TIME — not recomputed today */}
          <div className="grid gap-3 lg:grid-cols-2">
            <Snap title="Q1 · Market regime" when={ctx.asof}>
              {ctx.q1_regime ? (
                <>
                  <KV k="Verdict" v={ctx.q1_regime.healthy ? "🟢 healthy" : "🔴 wait"} />
                  <KV k="Benchmark" v={ctx.q1_regime.price} />
                  <KV k="50 / 200-DMA" v={`${ctx.q1_regime.dma50} / ${ctx.q1_regime.dma200}`} />
                </>
              ) : (
                <Muted />
              )}
            </Snap>

            <Snap title="Q2.5 · Sector">
              {ctx.q2_5_sector ? (
                <>
                  <KV k="Sector" v={ctx.q2_5_sector.sector} />
                  <KV k="Quadrant" v={ctx.q2_5_sector.quadrant} />
                  <KV k="Score" v={ctx.q2_5_sector.score?.toFixed?.(2)} />
                </>
              ) : (
                <Muted />
              )}
            </Snap>

            <Snap title="Q2 · The base">
              {ctx.q2_base ? (
                <>
                  <KV k="Base range" v={`${ctx.q2_base.base_range_pct}%`} />
                  <KV k="Lid / low" v={`${ctx.q2_base.base_high} / ${ctx.q2_base.base_low}`} />
                  <KV k="RSI mean(25)" v={ctx.q2_base.rsi_mean_25} />
                  <KV k="Turnover" v={`₹${ctx.q2_base.turnover_cr} Cr`} />
                  {ctx.q2_base.checklist && (
                    <div className="mt-2">
                      <ChecklistView checks={ctx.q2_base.checklist} />
                    </div>
                  )}
                </>
              ) : (
                <Muted />
              )}
            </Snap>

            <Snap title="Q3 · The breakout">
              {ctx.q3_entry ? (
                <>
                  <KV k="Close vs lid" v={`${ctx.q3_entry.close} vs ${ctx.q3_entry.breakout_level}`} />
                  <KV k="Volume" v={`${ctx.q3_entry.vol_ratio}×`} />
                  <KV k="RSI (5d ago)" v={`${ctx.q3_entry.rsi} (${ctx.q3_entry.rsi_5d_ago})`} />
                  <KV k="Weekly RSI" v={ctx.q3_entry.weekly_rsi} />
                  {ctx.q3_entry.checklist && (
                    <div className="mt-2">
                      <ChecklistView checks={ctx.q3_entry.checklist} />
                    </div>
                  )}
                </>
              ) : (
                <Muted />
              )}
            </Snap>

            <Snap title="Q4 · Sizing">
              {ctx.q4_sizing ? (
                <>
                  <KV k="Quantity" v={ctx.q4_sizing.qty} />
                  <KV k="Stop" v={`₹${ctx.q4_sizing.stop} (${ctx.q4_sizing.stop_source})`} />
                  <KV k="Risk" v={`₹${ctx.q4_sizing.risk_amount} (${ctx.q4_sizing.risk_pct_of_capital}%)`} />
                  <KV k="Capped by" v={ctx.q4_sizing.binding_constraint ?? "nothing"} />
                </>
              ) : (
                <Muted />
              )}
            </Snap>

            <Snap title="Portfolio at entry">
              {ctx.portfolio_at_entry ? (
                <>
                  <KV k="Capital" v={`₹${ctx.settings?.CAPITAL?.toLocaleString?.("en-IN")}`} />
                  <KV k="Open positions" v={ctx.portfolio_at_entry.open_positions} />
                  <KV
                    k="Already deployed"
                    v={`₹${Math.round(ctx.portfolio_at_entry.deployed_value).toLocaleString("en-IN")}`}
                  />
                </>
              ) : (
                <Muted />
              )}
            </Snap>
          </div>
        </div>
      )}
    </Card>
  );
}

function Snap({ title, when, children }: { title: string; when?: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-hairline bg-page p-3">
      <div className="mb-2 flex items-baseline justify-between">
        <div className="text-sm font-semibold text-ink">{title}</div>
        {when && <div className="text-xs text-ink-muted">{when}</div>}
      </div>
      {children}
    </div>
  );
}

function KV({ k, v }: { k: string; v: unknown }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-sm">
      <span className="text-ink-muted">{k}</span>
      <span className="tnum text-ink-2">{v === null || v === undefined ? "—" : String(v)}</span>
    </div>
  );
}

function Muted() {
  return <div className="text-sm text-ink-muted">not captured</div>;
}
