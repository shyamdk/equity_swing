"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

const LINKS = [
  { href: "/", label: "Dashboard", tag: "" },
  { href: "/regime", label: "Market Regime", tag: "Q1" },
  { href: "/watchlist", label: "Base / Watchlist", tag: "Q2" },
  { href: "/sectors", label: "Sector Rotation", tag: "Q2.5" },
  { href: "/entries", label: "Entry Trigger", tag: "Q3" },
  { href: "/sizing", label: "Position Sizing", tag: "Q4" },
  { href: "/positions", label: "Exit Ladder", tag: "Q5" },
];

export default function Nav() {
  const path = usePathname();
  const [open, setOpen] = useState(false);

  const items = (
    <ul className="space-y-0.5">
      {LINKS.map((l) => {
        const active = path === l.href;
        return (
          <li key={l.href}>
            <Link
              href={l.href}
              onClick={() => setOpen(false)}
              aria-current={active ? "page" : undefined}
              className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors ${
                active
                  ? "bg-page font-semibold text-ink"
                  : "text-ink-2 hover:bg-page hover:text-ink"
              }`}
            >
              {l.tag && (
                <span className="tnum w-8 shrink-0 rounded border border-hairline px-1 py-0.5 text-center text-[10px] font-semibold text-ink-muted">
                  {l.tag}
                </span>
              )}
              {!l.tag && <span className="w-8 shrink-0" />}
              <span className="truncate">{l.label}</span>
            </Link>
          </li>
        );
      })}
    </ul>
  );

  return (
    <>
      {/* mobile top bar */}
      <header className="sticky top-0 z-30 flex items-center justify-between border-b border-hairline bg-surface px-4 py-3 md:hidden">
        <span className="font-semibold">Robust Swing</span>
        <button
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-label="Toggle navigation"
          className="rounded-lg border border-hairline px-3 py-1.5 text-sm text-ink-2"
        >
          {open ? "✕" : "☰"}
        </button>
      </header>

      {open && (
        <nav className="border-b border-hairline bg-surface px-3 py-2 md:hidden">{items}</nav>
      )}

      {/* desktop sidebar */}
      <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 border-r border-hairline bg-surface p-3 md:block">
        <div className="px-3 py-3">
          <div className="font-semibold">Robust Swing</div>
          <div className="text-xs text-ink-muted">v1 · Nifty 500</div>
        </div>
        <nav>{items}</nav>
      </aside>
    </>
  );
}
