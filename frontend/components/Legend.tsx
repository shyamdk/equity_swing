"use client";

import { QUADRANT_COLOR } from "@/lib/api";
import { ReactNode } from "react";

const QUADRANTS = [
  {
    key: "leading",
    name: "Leading",
    plain: "Strong vs the market, and still getting stronger.",
    what: "The best hunting ground — a breakout here has the wind behind it.",
  },
  {
    key: "improving",
    name: "Improving",
    plain: "Still weak overall, but momentum has turned up.",
    what: "Early-season. Money is starting to flow in — often the best early entries.",
  },
  {
    key: "weakening",
    name: "Weakening",
    plain: "Still strong, but momentum is fading.",
    what: "Fine to trade, but keep the leash short — this sector is rolling over.",
  },
  {
    key: "lagging",
    name: "Lagging",
    plain: "Weak, and getting weaker.",
    what: "Out of season. We SKIP breakouts here — it's rowing against the current.",
  },
];

export interface Term {
  term: string;
  plain: string;
  rule?: string;
}

/** Q2 metric glossary. Every number on a card is defined here in plain English. */
export const Q2_TERMS: Term[] = [
  {
    term: "To lid  ← distance still to travel, NOT a green light",
    plain:
      "How far the price must still RISE to reach the lid. '4.2% to go' means it needs a 4.2% move up — i.e. it has NOT broken out. Smaller = closer to a trigger, so worth watching; it is never an instruction to buy.",
    rule: "Entry happens only in Q3, which also needs volume ≥1.5×, RSI>50 and rising, and the weekly chart to agree. Separately: the sector badge (Leading/Lagging) is about the SECTOR, not this stock — a leading-sector stock can be miles from its lid, and a lagging-sector one can sit right on it. Leading means 'if it breaks out, the wind is behind it', not 'it's about to break out'.",
  },
  {
    term: "Range (e.g. 7.5%)",
    plain:
      "How tightly the stock has traded over the last 20 days: the highest high minus the lowest low, as a % of the low. A small number means the price has gone quiet and sideways — a tightly coiled spring.",
    rule: "Must be under 20%. Tighter is better: a smaller coil means a bigger jump and a closer (cheaper) stop-loss.",
  },
  {
    term: "Turnover (₹ Cr)",
    plain:
      "The average value of shares traded per day over 20 days, in crore rupees. It answers: can I actually buy and sell this without moving the price against myself?",
    rule: "Need ≥ ₹5 Cr/day (or ≥ 2,00,000 shares/day). Thin stocks are easy to manipulate — we avoid them entirely.",
  },
  {
    term: "RSI mean",
    plain:
      "Average RSI over the last 25 days. RSI is a 0–100 momentum meter: 50 is neutral, high means it's been sprinting, low means it's been beaten down.",
    rule: "Want 35–48 — cooled off but not dead — and it must have dipped below 35 at some point, so sellers are exhausted.",
  },
  {
    term: "ATR",
    plain:
      "Average True Range: how many rupees this stock typically moves in a day. A 'bounciness' meter — a calm stock might move ₹5/day, a wild one ₹50.",
    rule: "Sets the stop-loss (2×ATR below entry) and therefore the position size. Bouncier stock → wider stop → smaller quantity.",
  },
  {
    term: "Lid / Base low",
    plain:
      "On the chart: the lid is the ceiling of the base (the highest high of the last 15 days). The base low is the floor.",
    rule: "Q3 needs a close ABOVE the lid to trigger a buy. The base low is the swing low Q4 may use for the stop.",
  },
];

export const Q3_TERMS: Term[] = [
  {
    term: "Volume (e.g. 2.4×)",
    plain:
      "Today's volume compared with the 20-day average. It's the proof behind a price move — a breakout on low volume is a few kids clapping; on high volume it's the whole crowd roaring.",
    rule: "Need ≥ 1.5×. Anything ≥ 2× is a strong signal.",
  },
  {
    term: "Lid",
    plain: "The ceiling of the base — the highest high of the previous 15 days.",
    rule: "Today's close must be ABOVE it. That's the spring uncoiling.",
  },
  {
    term: "vs lid",
    plain: "How far past the lid the price has already run.",
    rule: "If it's already more than 8% past, we SKIP it — chasing means a far-away stop and poor reward for the risk.",
  },
  {
    term: "RSI",
    plain: "Momentum, 0–100. Above 50 means buyers are in control.",
    rule: "Need > 50 AND higher than it was 5 days ago — confirming the push is real and accelerating.",
  },
];

function Row({ children }: { children: ReactNode }) {
  return <div className="border-t border-hairline py-3 first:border-0 first:pt-0">{children}</div>;
}

export default function Legend({ terms, title = "What am I looking at?" }: { terms: Term[]; title?: string }) {
  return (
    <details className="rounded-xl border border-hairline bg-surface" open>
      <summary className="cursor-pointer list-none px-4 py-3 text-sm font-semibold text-ink sm:px-5">
        <span className="mr-1.5 text-ink-muted">ⓘ</span>
        {title}
        <span className="ml-2 font-normal text-ink-muted">(click to collapse)</span>
      </summary>

      <div className="grid gap-6 border-t border-hairline px-4 py-4 sm:px-5 lg:grid-cols-2">
        {/* sector quadrants */}
        <section>
          <h3 className="text-sm font-semibold text-ink">Sector labels</h3>
          <p className="mt-1 text-sm text-ink-2">
            Money rotates between sectors. Roughly half a stock&apos;s move is really its
            sector&apos;s move — so we prefer stocks whose sector is in favour.
          </p>
          <div className="mt-2">
            {QUADRANTS.map((q) => (
              <Row key={q.key}>
                <div className="flex items-start gap-2">
                  <span
                    aria-hidden
                    className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{ background: QUADRANT_COLOR[q.key] }}
                  />
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-ink">{q.name}</div>
                    <div className="text-sm text-ink-2">{q.plain}</div>
                    <div className="mt-0.5 text-sm text-ink-muted">{q.what}</div>
                  </div>
                </div>
              </Row>
            ))}
          </div>
        </section>

        {/* the numbers */}
        <section>
          <h3 className="text-sm font-semibold text-ink">The numbers</h3>
          <p className="mt-1 text-sm text-ink-2">
            Every figure on a card, in plain English — and the rule it has to satisfy.
          </p>
          <div className="mt-2">
            {terms.map((t) => (
              <Row key={t.term}>
                <div className="text-sm font-medium text-ink">{t.term}</div>
                <div className="text-sm text-ink-2">{t.plain}</div>
                {t.rule && (
                  <div className="mt-1 text-sm">
                    <span className="font-medium text-ink-muted">Rule: </span>
                    <span className="text-ink-muted">{t.rule}</span>
                  </div>
                )}
              </Row>
            ))}
          </div>
        </section>
      </div>

      <div className="border-t border-hairline px-4 py-3 text-sm text-ink-muted sm:px-5">
        <span
          aria-hidden
          className="mr-1.5 inline-flex h-4 w-4 items-center justify-center rounded-full text-[10px] font-bold text-white"
          style={{ background: "var(--good)" }}
        >
          ✓
        </span>
        = this check passed
        <span
          aria-hidden
          className="mx-1.5 ml-4 inline-flex h-4 w-4 items-center justify-center rounded-full text-[10px] font-bold text-white"
          style={{ background: "var(--critical)" }}
        >
          ✕
        </span>
        = it failed. A stock is only a candidate when <strong className="text-ink-2">every</strong>{" "}
        check passes.
      </div>
    </details>
  );
}
