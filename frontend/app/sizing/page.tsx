"use client";

import { api, Sizing } from "@/lib/api";
import { Card, ErrorBox, SectionTitle, StatTile } from "@/components/ui";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

function SizingInner() {
  const qs = useSearchParams();
  const [entry, setEntry] = useState(qs.get("entry") ?? "500");
  const [atr, setAtr] = useState(qs.get("atr") ?? "10");
  const [swingLow, setSwingLow] = useState("");
  const [capital, setCapital] = useState("100000");
  const [riskPct, setRiskPct] = useState("1");
  const [deployed, setDeployed] = useState("0");
  const [openPos, setOpenPos] = useState("0");
  const [out, setOut] = useState<Sizing | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const symbol = qs.get("symbol");

  useEffect(() => {
    const e = parseFloat(entry);
    const a = parseFloat(atr);
    if (!e || !a) return;
    api
      .size({
        entry: e,
        atr: a,
        swing_low: swingLow ? parseFloat(swingLow) : null,
        capital: capital ? parseFloat(capital) : null,
        risk_pct: riskPct ? parseFloat(riskPct) : null,
        deployed_value: parseFloat(deployed) || 0,
        open_positions: parseInt(openPos) || 0,
      })
      .then(setOut)
      .catch((x) => setErr(String(x)));
  }, [entry, atr, swingLow, capital, riskPct, deployed, openPos]);

  if (err) return <ErrorBox error={err} />;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold sm:text-2xl">Q4 · How much do I buy?</h1>
        <p className="mt-1 max-w-2xl text-sm text-ink-2">
          Most people lose money here, not on picking stocks. The{" "}
          <strong className="text-ink">stop decides the size</strong>, never a fixed quantity — so
          every trade risks the same rupees no matter how bouncy the stock.
          {symbol && <> Sizing <strong className="text-ink">{symbol}</strong>.</>}
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-2">
          <SectionTitle>Inputs</SectionTitle>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Entry (₹)" value={entry} onChange={setEntry} />
            <Field label="ATR(14)" value={atr} onChange={setAtr} />
            <Field label="Swing low (₹)" value={swingLow} onChange={setSwingLow} placeholder="optional" />
            <Field label="Capital (₹)" value={capital} onChange={setCapital} />
            <Field label="Risk %" value={riskPct} onChange={setRiskPct} />
            <Field label="Already deployed (₹)" value={deployed} onChange={setDeployed} />
            <Field label="Open positions" value={openPos} onChange={setOpenPos} />
          </div>
        </Card>

        <div className="space-y-4 lg:col-span-3">
          {out && (
            <>
              <div className="grid grid-cols-2 gap-3 sm:gap-4">
                <StatTile
                  label="Buy quantity"
                  value={out.qty}
                  sub={out.qty ? `₹${out.position_value.toLocaleString("en-IN")}` : out.reason}
                  accent={out.qty ? "var(--good)" : "var(--critical)"}
                />
                <StatTile
                  label="Stop-loss"
                  value={`₹${out.stop}`}
                  sub={`from ${out.stop_source === "atr" ? "2×ATR" : "swing low"}`}
                  accent="var(--critical)"
                />
                <StatTile
                  label="Risk if stopped"
                  value={`₹${out.risk_amount.toLocaleString("en-IN")}`}
                  sub={`${out.risk_pct_of_capital}% of capital · 1R = ₹${out.risk_per_share}/share`}
                />
                <StatTile
                  label="Position size"
                  value={`${out.position_pct_of_capital}%`}
                  sub="of capital"
                />
              </div>

              <Card>
                <SectionTitle>What decided the size</SectionTitle>
                {out.binding_constraint ? (
                  <p className="text-sm text-ink-2">
                    The risk rule alone wanted{" "}
                    <strong className="text-ink tnum">{out.qty_uncapped} shares</strong>, but the{" "}
                    <strong className="text-ink">
                      {out.binding_constraint === "max_position_pct"
                        ? "25% per-position cap"
                        : "cash ceiling"}
                    </strong>{" "}
                    cut it to <strong className="text-ink tnum">{out.qty}</strong>. That means you
                    risk {out.risk_pct_of_capital}% instead of the {out.capital ? "1" : "1"}% target
                    — and that is <em>fine</em>. The 1% rule assumes the stop holds; the caps are the
                    second line of defence for when a stock gaps straight through it. Under-risking
                    never hurts you.
                  </p>
                ) : (
                  <p className="text-sm text-ink-2">
                    No cap bound — you get the full risk target. Quantity ={" "}
                    <span className="tnum">
                      ₹{(out.capital * 0.01).toLocaleString("en-IN")} ÷ ₹{out.risk_per_share}
                    </span>{" "}
                    = <strong className="text-ink tnum">{out.qty} shares</strong>.
                  </p>
                )}
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="block">
      <span className="text-xs text-ink-muted">{label}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        inputMode="decimal"
        className="tnum mt-1 w-full rounded-lg border border-hairline bg-page px-2.5 py-2 text-sm text-ink outline-none focus:border-ink-muted"
      />
    </label>
  );
}

export default function SizingPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-ink-muted">Loading…</div>}>
      <SizingInner />
    </Suspense>
  );
}
