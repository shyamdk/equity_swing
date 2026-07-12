"use client";

import { api } from "@/lib/api";
import { Card, Empty, ErrorBox, Loading, SectionTitle } from "@/components/ui";
import { useEffect, useState } from "react";

const LADDER = [
  {
    step: "Initial stop (−1R)",
    detail: "Tighter of the swing low or 2×ATR below entry. If hit, you lose exactly 1R.",
    color: "var(--critical)",
  },
  {
    step: "Breakeven at +1R",
    detail: "Stop moves up to your entry. From here the trade can no longer lose money.",
    color: "var(--improving)",
  },
  {
    step: "Book half at +2R",
    detail: "Sell half the position. Real profit is locked in; the rest rides.",
    color: "var(--leading)",
  },
  {
    step: "Chandelier trail",
    detail: "Stop = highest high since entry − 3×ATR. Rises with the stock, never falls.",
    color: "var(--leading)",
  },
  {
    step: "Time stop",
    detail: "Flat (under +5%) after 15 trading days? Exit. Dead money is a cost.",
    color: "var(--weakening)",
  },
];

export default function PositionsPage() {
  const [rows, setRows] = useState<Record<string, unknown>[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.positions("open").then(setRows).catch((e) => setErr(String(e)));
  }, []);

  if (err) return <ErrorBox error={err} />;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold sm:text-2xl">Q5 · When do I get out?</h1>
        <p className="mt-1 max-w-2xl text-sm text-ink-2">
          Every exit is planned <em>before</em> the buy. Losers are capped at 1R; winners are let
          run by a trailing stop. We deliberately do <strong className="text-ink">not</strong> sell
          just because RSI looks &quot;overbought&quot; — that dumps your best trades early.
        </p>
      </div>

      <Card>
        <SectionTitle hint="R = your initial risk per share. Everything is measured in R.">
          The exit ladder
        </SectionTitle>
        <ol className="space-y-3">
          {LADDER.map((l, i) => (
            <li key={l.step} className="flex gap-3">
              <span
                aria-hidden
                className="tnum mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold text-white"
                style={{ background: l.color }}
              >
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

      {!rows ? (
        <Loading what="open positions" />
      ) : rows.length === 0 ? (
        <Empty>
          <strong className="text-ink">No open paper trades.</strong> Once you take a Q3 breakout
          and size it in Q4, it will appear here with its live exit-ladder state — current stop,
          R-multiple, and which rung it has reached.
        </Empty>
      ) : (
        <Card>
          <SectionTitle>Open positions ({rows.length})</SectionTitle>
          <div className="scroll-x">
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="border-b border-hairline text-left text-ink-muted">
                  {["Symbol", "Entry", "Qty", "Stop", "R", "Status"].map((h) => (
                    <th key={h} className="py-2 pr-3 font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i} className="border-b border-hairline last:border-0">
                    <td className="py-2 pr-3 font-medium text-ink">{String(r.symbol)}</td>
                    <td className="tnum py-2 pr-3 text-ink-2">₹{String(r.entry_price)}</td>
                    <td className="tnum py-2 pr-3 text-ink-2">{String(r.qty)}</td>
                    <td className="tnum py-2 pr-3 text-ink-2">₹{String(r.current_stop)}</td>
                    <td className="tnum py-2 pr-3 text-ink-2">{String(r.r_multiple ?? "—")}</td>
                    <td className="py-2 pr-3 text-ink-2">{String(r.status)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
