"use client";

import { CHECK_LABELS, Checklist, QUADRANT_COLOR } from "@/lib/api";
import { ReactNode } from "react";

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-xl border border-hairline bg-surface p-4 sm:p-5 ${className}`}
    >
      {children}
    </div>
  );
}

export function SectionTitle({ children, hint }: { children: ReactNode; hint?: string }) {
  return (
    <div className="mb-3">
      <h2 className="text-base font-semibold text-ink sm:text-lg">{children}</h2>
      {hint && <p className="mt-0.5 text-sm text-ink-2">{hint}</p>}
    </div>
  );
}

/** A single headline number. No plot — so no hover layer needed. */
export function StatTile({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: ReactNode;
  sub?: string;
  accent?: string;
}) {
  return (
    <Card>
      <div className="text-sm text-ink-2">{label}</div>
      <div
        className="mt-1 text-2xl font-semibold sm:text-3xl"
        style={accent ? { color: accent } : undefined}
      >
        {value}
      </div>
      {sub && <div className="mt-1 text-sm text-ink-muted">{sub}</div>}
    </Card>
  );
}

/**
 * Pass/fail list. Identity is carried by an ICON + LABEL, never by colour alone —
 * so it survives colourblindness, greyscale printing and forced-colors mode.
 */
export function ChecklistView({ checks }: { checks: Checklist }) {
  return (
    <ul className="space-y-1.5">
      {Object.entries(checks).map(([key, ok]) => (
        <li key={key} className="flex items-start gap-2 text-sm">
          <span
            aria-hidden
            className="mt-px inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] font-bold text-white"
            style={{ background: ok ? "var(--good)" : "var(--critical)" }}
          >
            {ok ? "✓" : "✕"}
          </span>
          <span className="text-ink-2">
            {CHECK_LABELS[key] ?? key.replace(/_/g, " ")}
            <span className="sr-only">: {ok ? "pass" : "fail"}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Compact ✓/✕ strip for dense table rows. Tooltip carries the label. */
export function ChecklistStrip({ checks }: { checks: Checklist }) {
  return (
    <span className="inline-flex gap-1">
      {Object.entries(checks).map(([key, ok]) => (
        <span
          key={key}
          title={`${CHECK_LABELS[key] ?? key}: ${ok ? "pass" : "fail"}`}
          className="inline-flex h-4 w-4 items-center justify-center rounded-full text-[9px] font-bold text-white"
          style={{ background: ok ? "var(--good)" : "var(--critical)" }}
        >
          {ok ? "✓" : "✕"}
        </span>
      ))}
    </span>
  );
}

export function QuadrantBadge({ quadrant }: { quadrant: string | null }) {
  if (!quadrant) return <span className="text-ink-muted">—</span>;
  const color = QUADRANT_COLOR[quadrant] ?? "var(--ink-muted)";
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-sm text-ink-2">
      <span
        aria-hidden
        className="h-2.5 w-2.5 shrink-0 rounded-full"
        style={{ background: color }}
      />
      {quadrant}
    </span>
  );
}

export function Verdict({ passed }: { passed: boolean }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold text-white"
      style={{ background: passed ? "var(--good)" : "var(--critical)" }}
    >
      {passed ? "✓ PASS" : "✕ FAIL"}
    </span>
  );
}

export function Loading({ what = "data" }: { what?: string }) {
  return <div className="p-6 text-sm text-ink-muted">Loading {what}…</div>;
}

export function ErrorBox({ error }: { error: string }) {
  return (
    <Card className="border-l-4" >
      <div className="text-sm font-semibold text-ink">Couldn&apos;t load data</div>
      <p className="mt-1 text-sm text-ink-2">{error}</p>
      <p className="mt-2 text-sm text-ink-muted">
        Is the backend running? <code>uvicorn backend.api.main:app --port 8001</code>
      </p>
    </Card>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <Card>
      <p className="text-sm text-ink-2">{children}</p>
    </Card>
  );
}
