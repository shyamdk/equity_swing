"use client";

import CandleChart from "@/components/CandleChart";
import Legend, { Q2_TERMS } from "@/components/Legend";
import Link from "next/link";
import { api, BaseRow } from "@/lib/api";
import {
  Card,
  ChecklistView,
  Empty,
  ErrorBox,
  Loading,
  QuadrantBadge,
  Verdict,
} from "@/components/ui";
import { useEffect, useState } from "react";

type Sort = "closest" | "sector" | "tightest";

/** How far the price still has to travel to clear the lid and trigger Q3. */
const toLid = (r: BaseRow) => ((r.base_high - r.close) / r.close) * 100;

export default function WatchlistPage() {
  const [rows, setRows] = useState<BaseRow[] | null>(null);
  const [onlyPassed, setOnlyPassed] = useState(true);
  const [quadrant, setQuadrant] = useState<string>("all");
  const [sort, setSort] = useState<Sort>("closest");
  const [open, setOpen] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setRows(null);
    api.watchlist(onlyPassed).then(setRows).catch((e) => setErr(String(e)));
  }, [onlyPassed]);

  const view = (rows ?? [])
    .filter((r) => quadrant === "all" || r.quadrant === quadrant)
    .sort((a, b) => {
      if (sort === "closest") return toLid(a) - toLid(b);
      if (sort === "tightest") return a.base_range_pct - b.base_range_pct;
      return (b.sector_score ?? -Infinity) - (a.sector_score ?? -Infinity);
    });

  if (err) return <ErrorBox error={err} />;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold sm:text-2xl">Q2 · Is this a good stock?</h1>
        <p className="mt-1 max-w-2xl text-sm text-ink-2">
          We hunt for the <strong className="text-ink">crouch before the jump</strong>: a liquid
          stock that fell, went quiet sideways in a tight range, with volume drying up. These are
          candidates — <em>not</em> buys. Q3 decides when they actually wake up.
        </p>
      </div>

      {/* The single most dangerous misreading of this screen. Say it up front. */}
      <div
        className="rounded-xl border-l-4 border border-hairline bg-surface px-4 py-3 text-sm"
        style={{ borderLeftColor: "var(--weakening)" }}
      >
        <strong className="text-ink">Nothing on this page is a buy.</strong>{" "}
        <span className="text-ink-2">
          These are <em>candidates</em>. A positive “to lid” means the price still has to{" "}
          <strong className="text-ink">rise</strong> that much to reach its breakout level — it has{" "}
          <strong className="text-ink">not</strong> broken out. Entry only happens in{" "}
          <Link href="/entries" className="underline">
            Q3
          </Link>
          , which additionally requires volume ≥1.5×, RSI above 50 and rising, and the weekly chart
          to agree.
        </span>
      </div>

      <Legend terms={Q2_TERMS} />

      {/* filters sit in one row above the content */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <label className="inline-flex items-center gap-2 text-sm text-ink-2">
          <input
            type="checkbox"
            checked={onlyPassed}
            onChange={(e) => setOnlyPassed(e.target.checked)}
            className="h-4 w-4"
          />
          Only stocks that passed all checks
        </label>

        <label className="inline-flex items-center gap-2 text-sm text-ink-2">
          Sector:
          <select
            value={quadrant}
            onChange={(e) => setQuadrant(e.target.value)}
            className="rounded-lg border border-hairline bg-surface px-2 py-1 text-sm text-ink"
          >
            <option value="all">All sectors</option>
            <option value="leading">🟢 Leading — wind behind it</option>
            <option value="improving">🔵 Improving — turning up</option>
            <option value="weakening">🟠 Weakening — fading</option>
            <option value="lagging">🔴 Lagging — we skip these</option>
          </select>
        </label>

        <label className="inline-flex items-center gap-2 text-sm text-ink-2">
          Sort by:
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as Sort)}
            className="rounded-lg border border-hairline bg-surface px-2 py-1 text-sm text-ink"
          >
            <option value="closest">Closest to breakout</option>
            <option value="sector">Hottest sector</option>
            <option value="tightest">Tightest base</option>
          </select>
        </label>

        <span className="text-sm text-ink-muted">
          {view.length} of {rows?.length ?? 0} stocks
        </span>
      </div>

      {!rows ? (
        <Loading what="the watchlist" />
      ) : view.length === 0 ? (
        <Empty>
          {rows.length === 0
            ? "Nothing is in a valid base right now. That's normal — patience is part of the edge."
            : "No stocks in a base match this sector filter. Try 'All sectors'."}
        </Empty>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {view.map((r) => (
            <Card key={r.symbol}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="truncate font-semibold text-ink">{r.symbol}</h3>
                    <Verdict passed={r.passed} />
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink-2">
                    <span className="truncate">{r.sector ?? "—"}</span>
                    <QuadrantBadge quadrant={r.quadrant} />
                  </div>
                </div>
                <div className="tnum shrink-0 text-right">
                  <div className="font-semibold text-ink">₹{r.close.toLocaleString("en-IN")}</div>
                  <div
                    className="text-sm text-ink-muted"
                    title="20-day price range (high−low ÷ low). Under 20% = a tight, coiled base."
                  >
                    {r.base_range_pct.toFixed(1)}% range
                  </div>
                </div>
              </div>

              <div className="mt-3 grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
                <Metric
                  label="To lid"
                  value={toLid(r) <= 0 ? "at lid" : `${toLid(r).toFixed(1)}% to go`}
                  hint={`Distance the price must still RISE to reach the lid (₹${r.base_high}). A positive number means it has NOT broken out — this is not an entry, it's a "watch closely". Entry only happens in Q3, which also needs volume ≥1.5×, RSI>50 and rising, and the weekly chart to agree.`}
                />
                <Metric
                  label="Turnover"
                  value={`₹${r.turnover_cr.toFixed(1)} Cr`}
                  hint="Avg daily traded value over 20 days. Need ≥ ₹5 Cr so you can get in and out easily."
                />
                <Metric
                  label="RSI mean"
                  value={r.rsi_mean_25.toFixed(1)}
                  hint="Avg 25-day momentum (0–100). Want 35–48: cooled off, sellers exhausted — not dead."
                />
                <Metric
                  label="ATR"
                  value={r.atr ? r.atr.toFixed(2) : "—"}
                  hint="Avg daily move in ₹ ('bounciness'). Sets the stop (2×ATR) and so the position size."
                />
              </div>

              <div className="mt-4">
                <ChecklistView checks={r.checklist} />
              </div>

              <button
                onClick={() => setOpen(open === r.symbol ? null : r.symbol)}
                className="mt-4 rounded-lg border border-hairline px-3 py-1.5 text-sm text-ink-2 hover:text-ink"
                aria-expanded={open === r.symbol}
              >
                {open === r.symbol ? "Hide chart" : "Show chart"}
              </button>

              {open === r.symbol && (
                <div className="mt-3">
                  <CandleChart
                    symbol={r.symbol}
                    height={300}
                    priceLines={[
                      { price: r.base_high, title: "lid", color: "var(--good)", dashed: true },
                      { price: r.base_low, title: "base low", color: "var(--critical)", dashed: true },
                    ]}
                  />
                  <p className="mt-2 text-sm text-ink-muted">
                    The <strong>lid</strong> is what Q3 needs a close above. The{" "}
                    <strong>base low</strong> is the swing low Q4 may use for the stop.
                  </p>
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function Metric({
  label,
  value,
  hint,
  good,
}: {
  label: string;
  value: string;
  hint?: string;
  good?: boolean;
}) {
  return (
    <div className="rounded-lg bg-page px-2.5 py-2" title={hint}>
      <div className="flex items-center gap-1 text-xs text-ink-muted">
        {label}
        {hint && <span aria-hidden>ⓘ</span>}
      </div>
      <div
        className="tnum mt-0.5 font-medium"
        style={{ color: good ? "var(--good)" : "var(--ink)" }}
      >
        {value}
      </div>
    </div>
  );
}
