/* Candles with named, computed level lines (Chart Helper). */
import { useEffect, useRef } from "react";
import {
  CandlestickSeries, ColorType, CrosshairMode, LineStyle, createChart, type Time,
} from "lightweight-charts";
import { useTheme } from "@/components/theme";

export interface Bar { date?: string; time?: string; open: number; high: number; low: number; close: number }
export interface LevelLine { price: number; label: string; kind: string }

function tokens() {
  const s = getComputedStyle(document.documentElement);
  const v = (n: string) => s.getPropertyValue(n).trim();
  return { ink: v("--ink"), muted: v("--muted"), line: v("--line"), indigo: v("--indigo"),
    bull: v("--bull"), bear: v("--bear") };
}

/** Levels are not direction, so they never use bull/bear: VWAP in ink, pivots/POC dotted. */
function style(kind: string, t: ReturnType<typeof tokens>) {
  if (kind === "VWAP") return { color: t.ink, lineStyle: LineStyle.Solid, lineWidth: 2 as const };
  if (kind.startsWith("OR ")) return { color: t.indigo, lineStyle: LineStyle.Dashed, lineWidth: 1 as const };
  if (kind.startsWith("Pivot") || kind === "POC") return { color: t.muted, lineStyle: LineStyle.Dotted, lineWidth: 1 as const };
  return { color: t.muted, lineStyle: LineStyle.Dashed, lineWidth: 1 as const };
}

export function LevelChart({ bars, levels = [], height = 340 }: { bars: Bar[]; levels?: LevelLine[]; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const { theme } = useTheme();
  useEffect(() => {
    if (!ref.current || !bars.length) return;
    const t = tokens();
    const intraday = bars.some((b) => b.time);
    const chart = createChart(ref.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: t.muted,
        fontFamily: "IBM Plex Sans", attributionLogo: false },
      grid: { vertLines: { visible: false }, horzLines: { color: t.line } },
      rightPriceScale: { borderColor: t.line, scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: { borderColor: t.line, timeVisible: intraday, secondsVisible: false },
      crosshair: { mode: CrosshairMode.Magnet },
      localization: { priceFormatter: (p: number) => p.toLocaleString(undefined, { maximumFractionDigits: 2 }) },
    });
    const s = chart.addSeries(CandlestickSeries, { upColor: t.bull, downColor: t.bear, borderVisible: false,
      wickUpColor: t.bull, wickDownColor: t.bear, priceLineVisible: false });
    // Session times are exchange-local; stamp them as UTC so the axis shows them unchanged.
    s.setData(bars.map((b) => ({
      time: (b.time ? Math.floor(Date.parse(b.time + "Z") / 1000) : b.date) as Time,
      open: b.open, high: b.high, low: b.low, close: b.close })));
    for (const l of levels) {
      s.createPriceLine({ price: l.price, title: l.label, axisLabelVisible: true, ...style(l.kind, t) });
    }
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [theme, bars, levels]);
  return <div ref={ref} style={{ height }} className="w-full" aria-label="Candle chart with computed levels" role="img" />;
}
