"use client";

import { api, BaseRow, EntryRow, Regime, Sector } from "@/lib/api";
import { Card, ErrorBox, Loading, QuadrantBadge, SectionTitle, StatTile } from "@/components/ui";
import Link from "next/link";
import { useEffect, useState } from "react";

export default function Dashboard() {
  const [regime, setRegime] = useState<Regime | null>(null);
  const [sectors, setSectors] = useState<Sector[]>([]);
  const [wl, setWl] = useState<BaseRow[]>([]);
  const [entries, setEntries] = useState<EntryRow[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.regime(), api.sectors(), api.watchlist(true), api.entries(true)])
      .then(([r, s, w, e]) => {
        setRegime(r);
        setSectors(s);
        setWl(w);
        setEntries(e);
      })
      .catch((e) => setErr(String(e)));
  }, []);

  if (err) return <ErrorBox error={err} />;
  if (!regime) return <Loading what="the funnel" />;

  const green = regime.healthy;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold sm:text-2xl">Dashboard</h1>
        <p className="mt-1 text-sm text-ink-2">
          The Q1→Q5 funnel, as of {regime.asof}. Every stage says <em>no</em>{" "}
          until it can&apos;t.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
        <StatTile
          label="Q1 · Market regime"
          value={green ? "🟢 Healthy" : "🔴 Wait"}
          sub={green ? "Green light to hunt" : "No new buys today"}
          accent={green ? "var(--good)" : "var(--critical)"}
        />
        <StatTile label="Q2 · In a base" value={wl.length} sub="watchlist candidates" />
        <StatTile
          label="Q2.5 · Leading sectors"
          value={sectors.filter((s) => s.quadrant === "leading").length}
          sub={`of ${sectors.length} sectors`}
        />
        <StatTile
          label="Q3 · Breaking out"
          value={entries.length}
          sub={entries.length ? "ready to size" : "nothing today — that's fine"}
          accent={entries.length ? "var(--good)" : undefined}
        />
      </div>

      {!green && (
        <Card>
          <p className="text-sm text-ink-2">
            <strong className="text-ink">The market is below its 200-DMA.</strong> The regime
            filter blocks new buys — roughly 3 in 4 stocks follow the market, so a breakout into a
            falling tide is a bad bet. Doing nothing is the correct trade.{" "}
            <Link href="/regime" className="underline">
              See Q1 →
            </Link>
          </p>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <SectionTitle hint="Prefer breakouts here; skip the laggards.">
            Hottest sectors
          </SectionTitle>
          <ul className="space-y-2">
            {sectors.slice(0, 5).map((s) => (
              <li key={s.sector} className="flex items-center justify-between gap-3 text-sm">
                <span className="truncate text-ink">{s.sector}</span>
                <span className="flex shrink-0 items-center gap-3">
                  <QuadrantBadge quadrant={s.quadrant} />
                  <span className="tnum w-14 text-right text-ink-2">{s.score.toFixed(2)}</span>
                </span>
              </li>
            ))}
          </ul>
          <Link href="/sectors" className="mt-3 inline-block text-sm underline">
            Full RRG →
          </Link>
        </Card>

        <Card>
          <SectionTitle hint="Passed the base test — waiting to wake up.">Watchlist</SectionTitle>
          {wl.length === 0 ? (
            <p className="text-sm text-ink-2">No stocks in a valid base right now.</p>
          ) : (
            <ul className="space-y-2">
              {wl.slice(0, 5).map((r) => (
                <li key={r.symbol} className="flex items-center justify-between gap-3 text-sm">
                  <span className="truncate font-medium text-ink">{r.symbol}</span>
                  <span className="flex shrink-0 items-center gap-3">
                    <QuadrantBadge quadrant={r.quadrant} />
                    <span className="tnum w-24 text-right text-ink-2">
                      {r.base_range_pct.toFixed(1)}% range
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          )}
          <Link href="/watchlist" className="mt-3 inline-block text-sm underline">
            All {wl.length} candidates →
          </Link>
        </Card>
      </div>
    </div>
  );
}
