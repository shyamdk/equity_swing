"use client";

import { QUADRANT_COLOR, RRGSeries } from "@/lib/api";
import { useMemo, useState } from "react";

/** Short labels — 20 full sector names would collide. */
const ABBR: Record<string, string> = {
  "Financial Services": "Financials",
  "Capital Goods": "Cap Goods",
  "Automobile and Auto Components": "Auto",
  "Fast Moving Consumer Goods": "FMCG",
  "Information Technology": "IT",
  "Consumer Services": "Cons Svcs",
  "Oil Gas & Consumable Fuels": "Oil & Gas",
  "Consumer Durables": "Cons Dur",
  "Metals & Mining": "Metals",
  "Construction Materials": "Constr Mat",
  "Media Entertainment & Publication": "Media",
  Telecommunication: "Telecom",
};
const short = (s: string) => ABBR[s] ?? s;

const QUADRANTS = [
  { key: "improving", label: "IMPROVING", sub: "weak, gaining" },
  { key: "leading", label: "LEADING", sub: "strong, gaining" },
  { key: "lagging", label: "LAGGING", sub: "weak, fading" },
  { key: "weakening", label: "WEAKENING", sub: "strong, fading" },
];

const W = 150; // plot width in viewBox units
const H = 100; // plot height
const PAD = 3; // domain padding, % of span
const GAP = 3.6; // minimum vertical gap between labels

/**
 * Relative Rotation Graph.
 *
 * Position encodes the quadrant (x = RS-Ratio, y = RS-Momentum, axes crossing at
 * 100), so quadrant colour is reinforcement rather than the only channel. Identity
 * is carried by DIRECT LABELS — with 20 sectors we are far past the 8 categorical
 * slots, so we never colour by sector.
 *
 * Axes are scaled independently (RS-Ratio and RS-Momentum are different units), which
 * spreads the cluster across the plot. Labels are de-collided vertically and joined to
 * their dot with a leader line when they have to move.
 */
export default function RRGChart({ series }: { series: RRGSeries[] }) {
  const [hover, setHover] = useState<string | null>(null);

  const { nodes, midX, midY } = useMemo(() => {
    const all = series.flatMap((s) => s.points);
    if (!all.length) return { nodes: [], midX: W / 2, midY: H / 2 };

    // Independent domains, each kept symmetric about 100 so the crosshair is honest.
    const spread = (vals: number[]) =>
      Math.max(...vals.map((v) => Math.abs(v - 100)), 0.5) * (1 + PAD / 10);
    const rx = spread(all.map((p) => p.rs_ratio));
    const ry = spread(all.map((p) => p.rs_momentum));

    const sx = (v: number) => ((v - (100 - rx)) / (2 * rx)) * W;
    const sy = (v: number) => H - ((v - (100 - ry)) / (2 * ry)) * H;

    const ns = series
      .map((s) => {
        const last = s.points[s.points.length - 1];
        if (!last) return null;
        return {
          sector: s.sector,
          quadrant: last.quadrant,
          x: sx(last.rs_ratio),
          y: sy(last.rs_momentum),
          labelY: sy(last.rs_momentum),
          trail: s.points.map((p) => `${sx(p.rs_ratio)},${sy(p.rs_momentum)}`).join(" "),
          rs: last.rs_ratio,
          mom: last.rs_momentum,
        };
      })
      .filter((n): n is NonNullable<typeof n> => n !== null);

    // De-collide labels: greedy top-down pass, then relax back upward so the block
    // stays centred rather than drifting off the bottom.
    ns.sort((a, b) => a.y - b.y);
    let prev = -Infinity;
    for (const n of ns) {
      n.labelY = Math.max(n.y, prev + GAP);
      prev = n.labelY;
    }
    let next = Infinity;
    for (let i = ns.length - 1; i >= 0; i--) {
      ns[i].labelY = Math.min(ns[i].labelY, next - GAP);
      next = ns[i].labelY;
    }

    return { nodes: ns, midX: sx(100), midY: sy(100) };
  }, [series]);

  if (!nodes.length) return null;

  return (
    <div className="w-full">
      <div className="w-full">
        <svg
          viewBox={`-14 -6 ${W + 34} ${H + 12}`}
          className="h-auto w-full"
          role="img"
          aria-label="Relative rotation graph of sectors"
        >
          {/* quadrant washes — low alpha, purely orienting */}
          <rect x={0} y={0} width={midX} height={midY} fill="var(--improving)" opacity={0.05} />
          <rect x={midX} y={0} width={W - midX} height={midY} fill="var(--leading)" opacity={0.05} />
          <rect x={0} y={midY} width={midX} height={H - midY} fill="var(--lagging)" opacity={0.05} />
          <rect
            x={midX}
            y={midY}
            width={W - midX}
            height={H - midY}
            fill="var(--weakening)"
            opacity={0.05}
          />

          {/* axes cross at 100 */}
          <line x1={midX} y1={0} x2={midX} y2={H} stroke="var(--grid)" strokeWidth={0.35} />
          <line x1={0} y1={midY} x2={W} y2={midY} stroke="var(--grid)" strokeWidth={0.35} />

          {QUADRANTS.map((q) => {
            const right = q.key === "leading" || q.key === "weakening";
            const top = q.key === "improving" || q.key === "leading";
            return (
              <text
                key={q.key}
                x={right ? W - 1 : 1}
                y={top ? 3.5 : H - 1.2}
                textAnchor={right ? "end" : "start"}
                className="fill-ink-muted"
                style={{ fontSize: 2.6, letterSpacing: 0.25 }}
              >
                {q.label}
              </text>
            );
          })}

          {nodes.map((n) => {
            const color = QUADRANT_COLOR[n.quadrant] ?? "var(--ink-muted)";
            const dim = hover !== null && hover !== n.sector;
            // Flip the label inward near the right edge so it can't clip.
            const flip = n.x > W * 0.8;
            const lx = flip ? n.x - 2.6 : n.x + 2.6;
            const moved = Math.abs(n.labelY - n.y) > 0.8;

            return (
              <g
                key={n.sector}
                opacity={dim ? 0.15 : 1}
                onMouseEnter={() => setHover(n.sector)}
                onMouseLeave={() => setHover(null)}
                style={{ cursor: "pointer" }}
              >
                <polyline
                  points={n.trail}
                  fill="none"
                  stroke={color}
                  strokeWidth={0.45}
                  opacity={0.45}
                  strokeLinecap="round"
                />
                {/* leader line — only when the label had to move off its dot */}
                {moved && (
                  <line
                    x1={n.x + (flip ? -1.4 : 1.4)}
                    y1={n.y}
                    x2={lx}
                    y2={n.labelY - 0.7}
                    stroke="var(--ink-muted)"
                    strokeWidth={0.2}
                    opacity={0.6}
                  />
                )}
                {/* head — surface ring separates overlapping marks */}
                <circle
                  cx={n.x}
                  cy={n.y}
                  r={1.5}
                  fill={color}
                  stroke="var(--surface)"
                  strokeWidth={0.55}
                />
                {/* direct label = identity; halo keeps it legible over trails */}
                <text
                  x={lx}
                  y={n.labelY}
                  textAnchor={flip ? "end" : "start"}
                  className="fill-ink-2"
                  stroke="var(--surface)"
                  strokeWidth={0.5}
                  paintOrder="stroke"
                  style={{ fontSize: 2.5, fontWeight: hover === n.sector ? 700 : 400 }}
                >
                  {short(n.sector)}
                </text>
                <title>
                  {n.sector} — {n.quadrant} · RS-Ratio {n.rs.toFixed(1)} · RS-Momentum{" "}
                  {n.mom.toFixed(1)}
                </title>
                <circle cx={n.x} cy={n.y} r={3.5} fill="transparent" />
              </g>
            );
          })}
        </svg>
      </div>

      {/* legend — always present for ≥2 categories */}
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
        {QUADRANTS.map((q) => (
          <span key={q.key} className="inline-flex items-center gap-1.5 text-sm text-ink-2">
            <span
              aria-hidden
              className="h-2.5 w-2.5 rounded-full"
              style={{ background: QUADRANT_COLOR[q.key] }}
            />
            {q.label.charAt(0) + q.label.slice(1).toLowerCase()}
            <span className="text-ink-muted">({q.sub})</span>
          </span>
        ))}
      </div>
      <p className="mt-2 text-sm text-ink-muted">
        x = RS-Ratio (is it strong?) · y = RS-Momentum (is that strength rising?) · axes cross at
        100 · trails show the last few weeks. Sectors rotate clockwise.
      </p>
    </div>
  );
}
