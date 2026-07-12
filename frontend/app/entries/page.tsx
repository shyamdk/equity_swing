"use client";

import CandleChart from "@/components/CandleChart";
import { api, EntryRow } from "@/lib/api";
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
import Link from "next/link";
import { useEffect, useState } from "react";

export default function EntriesPage() {
  const [rows, setRows] = useState<EntryRow[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    api.entries(false).then(setRows).catch((e) => setErr(String(e)));
  }, []);

  if (err) return <ErrorBox error={err} />;
  if (!rows) return <Loading what="breakouts" />;

  const passed = rows.filter((r) => r.passed);
  const rest = rows.filter((r) => !r.passed);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold sm:text-2xl">Q3 · Is it waking up now?</h1>
        <p className="mt-1 max-w-2xl text-sm text-ink-2">
          A watchlist stock becomes a buy only when the spring actually uncoils: the crowd arrives
          (volume), price clears the lid, momentum confirms, and the weekly chart agrees — and we
          haven&apos;t already missed the move.
        </p>
      </div>

      {passed.length === 0 ? (
        <Empty>
          <strong className="text-ink">No breakouts today.</strong> That is a normal, and correct,
          outcome — some weeks there are zero valid setups. Doing nothing <em>is</em> the trade.
          Below you can see how close each watchlist stock came.
        </Empty>
      ) : (
        <div>
          <SectionTitle hint="All checks passed — these are sizeable trades.">
            Ready to buy ({passed.length})
          </SectionTitle>
          <div className="grid gap-4 md:grid-cols-2">
            {passed.map((r) => (
              <EntryCard key={r.symbol} r={r} open={open} setOpen={setOpen} />
            ))}
          </div>
        </div>
      )}

      {rest.length > 0 && (
        <div>
          <SectionTitle hint="Why each one didn't qualify.">
            Not yet ({rest.length})
          </SectionTitle>
          <div className="grid gap-4 md:grid-cols-2">
            {rest.map((r) => (
              <EntryCard key={r.symbol} r={r} open={open} setOpen={setOpen} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function EntryCard({
  r,
  open,
  setOpen,
}: {
  r: EntryRow;
  open: string | null;
  setOpen: (s: string | null) => void;
}) {
  const gap = ((r.close - r.breakout_level) / r.breakout_level) * 100;
  return (
    <Card>
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
          <div className="text-sm text-ink-muted">
            lid ₹{r.breakout_level.toLocaleString("en-IN")}
          </div>
        </div>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 text-sm">
        <Metric
          label="Volume"
          value={`${r.vol_ratio.toFixed(2)}×`}
          good={r.vol_ratio >= 1.5}
        />
        <Metric label="RSI" value={r.rsi.toFixed(1)} good={r.rsi > 50} />
        <Metric
          label="vs lid"
          value={`${gap >= 0 ? "+" : ""}${gap.toFixed(1)}%`}
          good={gap >= 0}
        />
      </div>

      <div className="mt-4">
        <ChecklistView checks={r.checklist} />
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          onClick={() => setOpen(open === r.symbol ? null : r.symbol)}
          className="rounded-lg border border-hairline px-3 py-1.5 text-sm text-ink-2 hover:text-ink"
          aria-expanded={open === r.symbol}
        >
          {open === r.symbol ? "Hide chart" : "Show chart"}
        </button>
        {r.passed && r.atr && (
          <Link
            href={`/sizing?entry=${r.close}&atr=${r.atr}&symbol=${r.symbol}`}
            className="rounded-lg px-3 py-1.5 text-sm font-medium text-white"
            style={{ background: "var(--good)" }}
          >
            Size this trade →
          </Link>
        )}
      </div>

      {open === r.symbol && (
        <div className="mt-3">
          <CandleChart
            symbol={r.symbol}
            height={300}
            priceLines={[
              { price: r.breakout_level, title: "lid", color: "var(--good)", dashed: true },
            ]}
          />
        </div>
      )}
    </Card>
  );
}

function Metric({ label, value, good }: { label: string; value: string; good?: boolean }) {
  return (
    <div className="rounded-lg bg-page px-2.5 py-2">
      <div className="text-xs text-ink-muted">{label}</div>
      <div
        className="tnum mt-0.5 font-medium"
        style={{ color: good === undefined ? "var(--ink)" : good ? "var(--good)" : "var(--ink-2)" }}
      >
        {value}
      </div>
    </div>
  );
}
