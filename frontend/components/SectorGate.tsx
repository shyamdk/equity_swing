"use client";

import { api, Settings } from "@/lib/api";
import { Card, SectionTitle } from "@/components/ui";
import { useEffect, useState } from "react";

type Mode = "off" | "skip_lagging" | "leading_only";

const MODES: { key: Mode; label: string; detail: string }[] = [
  {
    key: "off",
    label: "Off — trade every sector",
    detail:
      "Ignore sector rotation entirely. Q3 takes any valid breakout regardless of whether its sector is hot or dead. Use this to test whether the gate is actually helping.",
  },
  {
    key: "skip_lagging",
    label: "Skip lagging (default)",
    detail:
      "Reject breakouts whose sector is in the Lagging quadrant — weak and getting weaker. Everything else is allowed, ranked by sector score.",
  },
  {
    key: "leading_only",
    label: "Strict — leading & improving only",
    detail:
      "Only trade sectors with rising relative strength. Fewest trades, highest sector quality — but a much smaller sample.",
  },
];

function toMode(s: Settings): Mode {
  if (s.SECTOR_AGGRESSIVE) return "leading_only";
  return s.SECTOR_SKIP_LAGGING ? "skip_lagging" : "off";
}

/** Toggle for the Q2.5 gate. Persisted server-side, so a replay honours it. */
export default function SectorGate() {
  const [mode, setMode] = useState<Mode | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.settings().then((s) => setMode(toMode(s))).catch(() => setMode("skip_lagging"));
  }, []);

  const choose = (m: Mode) => {
    setMode(m);
    setSaved(false);
    api
      .saveSettings({
        SECTOR_SKIP_LAGGING: m !== "off",
        SECTOR_AGGRESSIVE: m === "leading_only",
      })
      .then(() => setSaved(true))
      .catch(() => {});
  };

  if (!mode) return null;

  return (
    <Card>
      <div className="flex items-start justify-between gap-3">
        <SectionTitle hint="Changes apply immediately to Q3 and to any replay you run.">
          Sector gate
        </SectionTitle>
        {saved && (
          <span className="text-sm" style={{ color: "var(--good)" }}>
            ✓ Saved
          </span>
        )}
      </div>

      <div className="space-y-2">
        {MODES.map((m) => (
          <label
            key={m.key}
            className={`flex cursor-pointer gap-3 rounded-lg border p-3 transition-colors ${
              mode === m.key ? "border-ink-muted bg-page" : "border-hairline hover:bg-page"
            }`}
          >
            <input
              type="radio"
              name="sector-gate"
              checked={mode === m.key}
              onChange={() => choose(m.key)}
              className="mt-0.5 h-4 w-4 shrink-0"
            />
            <span className="min-w-0">
              <span className="block text-sm font-medium text-ink">{m.label}</span>
              <span className="block text-sm text-ink-2">{m.detail}</span>
            </span>
          </label>
        ))}
      </div>

      <p className="mt-3 text-sm text-ink-muted">
        The gate is a <em>hypothesis</em>, not a fact — it has never been shown to improve the edge
        on your data. Turn it off, re-run the replay on Q5, and compare the expectancy.
      </p>
    </Card>
  );
}
