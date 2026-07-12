"use client";

import { api, Candles } from "@/lib/api";
import {
  CandlestickSeries,
  createChart,
  HistogramSeries,
  IChartApi,
  LineSeries,
  createSeriesMarkers,
  Time,
} from "lightweight-charts";
import { useEffect, useRef, useState } from "react";

function cssVar(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export interface PriceLine {
  price: number;
  title: string;
  color?: string;
  dashed?: boolean;
}

export interface Marker {
  time: string;          // YYYY-MM-DD
  kind: "entry" | "exit" | "partial";
  text: string;
}

const MARKER_STYLE: Record<Marker["kind"], { color: string; pos: "aboveBar" | "belowBar"; shape: "arrowUp" | "arrowDown" | "circle" }> = {
  entry: { color: "var(--good)", pos: "belowBar", shape: "arrowUp" },
  exit: { color: "var(--critical)", pos: "aboveBar", shape: "arrowDown" },
  partial: { color: "var(--improving)", pos: "aboveBar", shape: "circle" },
};

/**
 * Candlestick + volume + EMA overlays.
 * Up/down use the validated green/red pair (CVD ΔE 12.4 — passes, and matches the
 * universal trading convention). Direction is also legible from the wick/open-close
 * geometry, so colour is not the sole channel.
 */
export default function CandleChart({
  symbol,
  interval = "1day",
  limit = 250,
  height = 380,
  overlays = ["ema50"],
  priceLines = [],
  chartType = "candles",
  markers = [],
  focus,
}: {
  symbol: string;
  interval?: string;
  limit?: number;
  height?: number;
  overlays?: string[];
  priceLines?: PriceLine[];
  /** Use "line" for synthetic indices, where open=high=low=close makes candles
   *  degenerate into specks. A single continuous value wants a line. */
  chartType?: "candles" | "line";
  /** Entry / partial / exit arrows — where the trade actually happened. */
  markers?: Marker[];
  /** Zoom to a window (YYYY-MM-DD). Without it a trade gets squeezed into the
   *  right-hand edge of a multi-year chart and you can't see anything. */
  focus?: { from: string; to: string };
}) {
  const box = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [data, setData] = useState<Candles | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .candles(symbol, interval, limit)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setErr(String(e)));
    return () => {
      alive = false;
    };
  }, [symbol, interval, limit]);

  useEffect(() => {
    if (!box.current || !data) return;

    const chart = createChart(box.current, {
      height,
      layout: {
        background: { color: "transparent" },
        textColor: cssVar("--ink-2"),
        fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: cssVar("--grid") },
        horzLines: { color: cssVar("--grid") },
      },
      rightPriceScale: { borderColor: cssVar("--grid") },
      timeScale: { borderColor: cssVar("--grid"), timeVisible: interval.includes("min") },
      crosshair: { mode: 1 }, // magnet — the hover layer, on by default
      autoSize: false,
    });
    chartRef.current = chart;

    const price =
      chartType === "line"
        ? chart.addSeries(LineSeries, {
            color: cssVar("--improving"),
            lineWidth: 2,
            priceLineVisible: false,
          })
        : chart.addSeries(CandlestickSeries, {
            upColor: cssVar("--up"),
            downColor: cssVar("--down"),
            borderUpColor: cssVar("--up"),
            borderDownColor: cssVar("--down"),
            wickUpColor: cssVar("--up"),
            wickDownColor: cssVar("--down"),
          });

    if (chartType === "line") {
      price.setData(
        data.candles.map((c) => ({ time: c.time as Time, value: c.close }))
      );
    } else {
      price.setData(data.candles.map((c) => ({ ...c, time: c.time as Time })));
    }

    // Volume in its own bottom band (never a second y-axis on price).
    // Synthetic indices carry no volume — an all-zero histogram is noise, so skip it.
    const hasVolume = data.volume.some((v) => v.value > 0);
    if (hasVolume) {
      const vol = chart.addSeries(HistogramSeries, {
        priceFormat: { type: "volume" },
        priceScaleId: "vol",
        color: cssVar("--ink-muted"),
      });
      vol.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
      vol.setData(data.volume.map((v) => ({ time: v.time as Time, value: v.value })));
    }

    // Recessive EMA overlays — thin 2px lines, no markers.
    overlays.forEach((name) => {
      const pts = data.indicators?.[name];
      if (!pts?.length) return;
      const line = chart.addSeries(LineSeries, {
        color: cssVar("--improving"),
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      line.setData(pts.map((p) => ({ time: p.time as Time, value: p.value })));
    });

    if (markers.length) {
      createSeriesMarkers(
        price,
        markers
          .slice()
          .sort((a, b) => a.time.localeCompare(b.time))
          .map((m) => ({
            time: m.time as Time,
            position: MARKER_STYLE[m.kind].pos,
            color: cssVar(MARKER_STYLE[m.kind].color.replace(/var\(|\)/g, "")),
            shape: MARKER_STYLE[m.kind].shape,
            text: m.text,
          }))
      );
    }

    priceLines.forEach((pl) =>
      price.createPriceLine({
        price: pl.price,
        color: pl.color ?? cssVar("--ink-muted"),
        lineWidth: 1,
        lineStyle: pl.dashed ? 2 : 0,
        axisLabelVisible: true,
        title: pl.title,
      })
    );

    if (focus) {
      try {
        chart.timeScale().setVisibleRange({
          from: focus.from as Time,
          to: focus.to as Time,
        });
      } catch {
        chart.timeScale().fitContent();
      }
    } else {
      chart.timeScale().fitContent();
    }

    // Responsive: follow the container, not the window.
    const ro = new ResizeObserver(([e]) =>
      chart.applyOptions({ width: e.contentRect.width })
    );
    ro.observe(box.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [data, height, interval, overlays, priceLines, chartType, markers, focus]);

  if (err) return <div className="p-4 text-sm text-ink-muted">Chart unavailable: {err}</div>;
  if (!data) return <div className="p-4 text-sm text-ink-muted">Loading chart…</div>;
  return <div ref={box} className="w-full" />;
}
