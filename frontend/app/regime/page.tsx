"use client";

import CandleChart from "@/components/CandleChart";
import { api, Regime } from "@/lib/api";
import { Card, ChecklistView, ErrorBox, Loading, SectionTitle, StatTile } from "@/components/ui";
import { useEffect, useState } from "react";

export default function RegimePage() {
  const [r, setR] = useState<Regime | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.regime().then(setR).catch((e) => setErr(String(e)));
  }, []);

  if (err) return <ErrorBox error={err} />;
  if (!r) return <Loading what="the regime" />;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold sm:text-2xl">Q1 · Is the market healthy?</h1>
        <p className="mt-1 max-w-2xl text-sm text-ink-2">
          The tide lifts or sinks all boats — about 3 in 4 stocks move with the market. If the
          market is unhealthy we take <strong className="text-ink">no new buys at all</strong>, no
          matter how good a chart looks. This is the highest-value rule in the whole strategy.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
        <StatTile
          label="Verdict"
          value={r.healthy ? "🟢 Healthy" : "🔴 Wait"}
          sub={r.healthy ? "Hunt for trades" : "No new buys"}
          accent={r.healthy ? "var(--good)" : "var(--critical)"}
        />
        <StatTile label="Benchmark" value={r.price.toFixed(2)} sub={r.benchmark} />
        <StatTile label="50-DMA" value={r.dma50.toFixed(2)} sub="medium-term mood" />
        <StatTile label="200-DMA" value={r.dma200.toFixed(2)} sub="long-term mood" />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <SectionTitle hint={`${r.benchmark} · daily, with its 50-day average`}>
            The market chart
          </SectionTitle>
          {/* The benchmark is a synthetic composite (open=high=low=close), so a line
              is the honest form here — candles would render as meaningless specks. */}
          <CandleChart
            symbol={r.benchmark}
            interval="1day"
            limit={300}
            chartType="line"
            overlays={[]}
            priceLines={[
              { price: r.dma200, title: "200-DMA", dashed: true },
              { price: r.dma50, title: "50-DMA" },
            ]}
          />
        </Card>

        <Card>
          <SectionTitle hint={`As of ${r.asof}`}>Why this verdict</SectionTitle>
          <ChecklistView checks={r.checklist} />
          <p className="mt-4 text-sm text-ink-muted">
            Both must be true: price above the 200-DMA means the long-term trend is up;
            50-DMA above the 200-DMA means that uptrend is <em>established</em>, not a one-day
            fluke.
          </p>
        </Card>
      </div>
    </div>
  );
}
