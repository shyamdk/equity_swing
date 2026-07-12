"use client";

import RRGChart from "@/components/RRGChart";
import SectorGate from "@/components/SectorGate";
import { api, RRGSeries, Sector } from "@/lib/api";
import { Card, ErrorBox, Loading, QuadrantBadge, SectionTitle } from "@/components/ui";
import { useEffect, useState } from "react";

export default function SectorsPage() {
  const [rows, setRows] = useState<Sector[]>([]);
  const [rrg, setRrg] = useState<RRGSeries[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.sectors(), api.rrg(8)])
      .then(([s, g]) => {
        setRows(s);
        setRrg(g);
      })
      .catch((e) => setErr(String(e)));
  }, []);

  if (err) return <ErrorBox error={err} />;
  if (!rows.length) return <Loading what="sectors" />;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold sm:text-2xl">Q2.5 · Is the sector in season?</h1>
        <p className="mt-1 max-w-2xl text-sm text-ink-2">
          Q1 asked about the tide; this asks about the <strong className="text-ink">currents</strong>.
          Money rotates between sectors, and roughly half a stock&apos;s move is really its
          sector&apos;s move. A perfect breakout in a leading sector has the wind behind it; the same
          chart in a dead sector is rowing against the stream. This is a{" "}
          <em>preference</em>, not a hard gate — except that we skip the clearly-lagging quadrant.
        </p>
      </div>

      <SectorGate />

      <Card>
        <SectionTitle hint="Each dot is a sector; the tail is where it has been.">
          Relative Rotation Graph
        </SectionTitle>
        <RRGChart series={rrg} />
      </Card>

      <Card>
        <SectionTitle hint="Ranked by Sector Score — the number we sort by.">
          Sector ranking
        </SectionTitle>
        {/* table view = the accessible fallback for the scatter above */}
        <div className="scroll-x">
          <table className="w-full min-w-[520px] text-sm">
            <thead>
              <tr className="border-b border-hairline text-left text-ink-muted">
                <th className="py-2 pr-3 font-medium">#</th>
                <th className="py-2 pr-3 font-medium">Sector</th>
                <th className="py-2 pr-3 font-medium">Quadrant</th>
                <th className="py-2 pr-3 text-right font-medium">RS-Ratio</th>
                <th className="py-2 pr-3 text-right font-medium">RS-Mom</th>
                <th className="py-2 text-right font-medium">Score</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s, i) => (
                <tr key={s.sector} className="border-b border-hairline last:border-0">
                  <td className="tnum py-2 pr-3 text-ink-muted">{i + 1}</td>
                  <td className="py-2 pr-3 text-ink">{s.sector}</td>
                  <td className="py-2 pr-3">
                    <QuadrantBadge quadrant={s.quadrant} />
                  </td>
                  <td className="tnum py-2 pr-3 text-right text-ink-2">
                    {s.rs_ratio.toFixed(1)}
                  </td>
                  <td className="tnum py-2 pr-3 text-right text-ink-2">
                    {s.rs_momentum.toFixed(1)}
                  </td>
                  <td
                    className="tnum py-2 text-right font-medium"
                    style={{ color: s.score >= 0 ? "var(--good)" : "var(--critical)" }}
                  >
                    {s.score > 0 ? "+" : ""}
                    {s.score.toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
