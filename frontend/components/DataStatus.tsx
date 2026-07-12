"use client";

import { api, Meta } from "@/lib/api";
import { useEffect, useState } from "react";

/**
 * Universe + data-freshness strip, shown on every page.
 *
 * Nothing here refreshes on a schedule — candles only land when the ingest is run.
 * The sector metrics are a STORED snapshot that has to be rebuilt afterwards, so it
 * can silently lag the candles; if it does, we say so loudly rather than quietly
 * serving a stale RRG.
 */
export default function DataStatus() {
  const [m, setM] = useState<Meta | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    api.meta().then(setM).catch(() => {});
  }, []);

  if (!m) return null;

  const stale = m.stale_business_days ?? 0;
  const fresh = stale <= 1;
  const sectorLag = m.sector_lag_days ?? 0;

  return (
    <div className="mb-5 rounded-xl border border-hairline bg-surface">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2.5 text-sm">
        {/* universe */}
        <span className="inline-flex items-center gap-1.5 text-ink-2">
          <span className="text-ink-muted">Universe:</span>
          <strong className="font-medium text-ink">{m.universe.name}</strong>
          <span className="text-ink-muted">({m.universe.symbols} stocks)</span>
        </span>

        {/* freshness */}
        <span className="inline-flex items-center gap-1.5 text-ink-2">
          <span
            aria-hidden
            className="h-2 w-2 rounded-full"
            style={{ background: fresh ? "var(--good)" : "var(--weakening)" }}
          />
          <span className="text-ink-muted">Data as of:</span>
          <strong className="tnum font-medium text-ink">{m.data_asof ?? "—"}</strong>
          <span className="text-ink-muted">
            {stale === 0
              ? "(up to date)"
              : `(${stale} trading day${stale === 1 ? "" : "s"} behind)`}
          </span>
        </span>

        {/* the snapshot that can silently rot */}
        {sectorLag > 0 && (
          <span
            className="inline-flex items-center gap-1.5 font-medium"
            style={{ color: "var(--critical)" }}
          >
            ⚠ Sector rotation is {sectorLag} day{sectorLag === 1 ? "" : "s"} behind the price data —
            rebuild it.
          </span>
        )}

        <button
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="ml-auto shrink-0 rounded-lg border border-hairline px-2.5 py-1 text-sm text-ink-2 hover:text-ink"
        >
          {open ? "Hide" : "How does this refresh?"}
        </button>
      </div>

      {open && (
        <div className="space-y-3 border-t border-hairline px-4 py-3 text-sm">
          <p className="text-ink-2">
            <strong className="text-ink">Nothing refreshes automatically.</strong> There is no
            scheduler — the numbers on every screen change only when you run the ingest by hand.
            Last run: <span className="tnum">{fmt(m.last_ingest_run)}</span>.
          </p>

          <div>
            <div className="font-medium text-ink">To refresh, run these in order:</div>
            <ol className="mt-1 space-y-1">
              {m.refresh.steps.map((s, i) => (
                <li key={s} className="flex gap-2 text-ink-2">
                  <span className="tnum text-ink-muted">{i + 1}.</span>
                  <code className="min-w-0 break-all text-ink-2">{s}</code>
                </li>
              ))}
            </ol>
            <p className="mt-1.5 text-ink-muted">
              Steps 2 and 3 matter: the benchmark and the sector RRG are stored snapshots. Skip them
              and the price data will be current while the regime and rotation quietly are not.
            </p>
          </div>

          <div>
            <div className="font-medium text-ink">Where each screen gets its data</div>
            <ul className="mt-1 space-y-0.5 text-ink-2">
              <li>
                <strong className="font-medium">Q2 base, Q3 entry</strong> — recomputed live from
                stored candles on every page load. Always as fresh as the candles.
              </li>
              <li>
                <strong className="font-medium">Q1 regime, Q2.5 sectors</strong> — stored snapshots
                (benchmark {fmtDate(m.benchmark_asof)}, sectors {fmtDate(m.sectors_asof)}). Rebuilt
                by steps 2–3 above.
              </li>
              <li>
                <strong className="font-medium">Q4 sizing</strong> — pure arithmetic, no data
                dependency.
              </li>
            </ul>
          </div>

          <div>
            <div className="font-medium text-ink">Universe</div>
            <p className="mt-1 text-ink-2">
              {m.universe.name} ({m.universe.symbols} stocks), from{" "}
              <code>{m.universe.source}</code>. {m.universe.note} Intervals held:{" "}
              {m.intervals.map((i) => i.interval).join(", ")}.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function fmt(iso: string | null) {
  if (!iso) return "never";
  const d = new Date(iso);
  return isNaN(+d) ? iso : d.toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}
function fmtDate(s: string | null) {
  return s ?? "—";
}
