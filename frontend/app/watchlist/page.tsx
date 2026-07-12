"use client";

import CandleChart from "@/components/CandleChart";
import { api, BaseRow } from "@/lib/api";
import {
  Card,
  ChecklistView,
  Empty,
  ErrorBox,
  Loading,
  QuadrantBadge,
  SectionTitle,
  Verdict,
} from "@/components/ui";
import { useEffect, useState } from "react";

export default function WatchlistPage() {
  const [rows, setRows] = useState<BaseRow[] | null>(null);
  const [onlyPassed, setOnlyPassed] = useState(true);
  const [open, setOpen] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setRows(null);
    api.watchlist(onlyPassed).then(setRows).catch((e) => setErr(String(e)));
  }, [onlyPassed]);

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

      {/* filters sit in one row above the content */}
      <div className="flex flex-wrap items-center gap-3">
        <label className="inline-flex items-center gap-2 text-sm text-ink-2">
          <input
            type="checkbox"
            checked={onlyPassed}
            onChange={(e) => setOnlyPassed(e.target.checked)}
            className="h-4 w-4"
          />
          Only show stocks that passed all checks
        </label>
        {rows && <span className="text-sm text-ink-muted">{rows.length} stocks</span>}
      </div>

      {!rows ? (
        <Loading what="the watchlist" />
      ) : rows.length === 0 ? (
        <Empty>
          Nothing is in a valid base right now. That&apos;s normal — patience is part of the edge.
        </Empty>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {rows.map((r) => (
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
                  <div className="text-sm text-ink-muted">{r.base_range_pct.toFixed(1)}% range</div>
                </div>
              </div>

              <div className="mt-3 grid grid-cols-3 gap-2 text-sm">
                <Metric label="Turnover" value={`₹${r.turnover_cr.toFixed(1)} Cr`} />
                <Metric label="RSI mean" value={r.rsi_mean_25.toFixed(1)} />
                <Metric label="ATR" value={r.atr ? r.atr.toFixed(2) : "—"} />
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

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-page px-2.5 py-2">
      <div className="text-xs text-ink-muted">{label}</div>
      <div className="tnum mt-0.5 font-medium text-ink">{value}</div>
    </div>
  );
}
