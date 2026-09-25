import { useEffect, useRef } from "react";
import ReactECharts from "echarts-for-react";
import {
  AreaSeries, CandlestickSeries, ColorType, CrosshairMode, LineSeries,
  createChart, type IChartApi, type Time,
} from "lightweight-charts";
import { useTheme } from "./theme";

/** Read the live theme tokens so charts follow Book / Desk. */
function tokens() {
  const s = getComputedStyle(document.documentElement);
  const v = (n: string) => s.getPropertyValue(n).trim();
  return { ink: v("--ink"), muted: v("--muted"), line: v("--line"), panel: v("--panel"),
    indigo: v("--indigo"), bull: v("--bull"), bear: v("--bear") };
}

export function Sparkline({ values, width = 120, height = 32 }: { values: number[]; width?: number; height?: number }) {
  if (values.length < 2) return null;
  const lo = Math.min(...values), hi = Math.max(...values);
  const x = (i: number) => (i / (values.length - 1)) * width;
  const y = (v: number) => height - 2 - ((v - lo) / (hi - lo || 1)) * (height - 4);
  const d = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const up = values[values.length - 1] >= values[0];
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden>
      <path d={d} fill="none" strokeWidth={1.6} stroke={up ? "var(--bull)" : "var(--bear)"} />
    </svg>
  );
}

/* ---------------------------------------------------------------- payoff (ECharts) */
export function PayoffChart({ spot, expiry, now, current, band, breakevens, money }: {
  spot: number[]; expiry: number[]; now: number[]; current: number; band: [number, number];
  breakevens: number[]; money: (x: number) => string;
}) {
  const { theme } = useTheme();
  const t = tokens();
  const pos = spot.map((s, i) => [s, Math.max(expiry[i], 0)]);
  const neg = spot.map((s, i) => [s, Math.min(expiry[i], 0)]);
  const option = {
    animation: false,
    grid: { left: 64, right: 16, top: 16, bottom: 36 },
    textStyle: { fontFamily: "IBM Plex Sans" },
    tooltip: {
      trigger: "axis", backgroundColor: t.panel, borderColor: t.line, textStyle: { color: t.ink },
      valueFormatter: (v: number) => money(v),
    },
    xAxis: { type: "value", min: (v: { min: number }) => Math.floor(v.min / 50) * 50,
      max: (v: { max: number }) => Math.ceil(v.max / 50) * 50, axisLine: { lineStyle: { color: t.line } },
      axisLabel: { color: t.muted, formatter: (v: number) => Math.round(v).toLocaleString() }, splitLine: { show: false } },
    yAxis: { type: "value", axisLabel: { color: t.muted, formatter: (v: number) => money(v) },
      splitLine: { lineStyle: { color: t.line } } },
    series: [
      { type: "line", data: pos, showSymbol: false, lineStyle: { width: 0 }, areaStyle: { color: t.bull, opacity: 0.16 }, silent: true },
      { type: "line", data: neg, showSymbol: false, lineStyle: { width: 0 }, areaStyle: { color: t.bear, opacity: 0.14 }, silent: true },
      { name: "At expiry", type: "line", data: spot.map((s, i) => [s, expiry[i]]), showSymbol: false,
        lineStyle: { width: 2.4, color: t.ink },
        markLine: { symbol: "none", silent: true, label: { show: false },
          data: [
            { xAxis: current, lineStyle: { color: t.muted, type: "dashed" },
              label: { formatter: `Spot ${Math.round(current).toLocaleString()}`, position: "insideStartTop", color: t.muted } },
            ...breakevens.map((b, i) => ({ xAxis: b, lineStyle: { color: t.indigo },
              label: { formatter: `Breakeven ${Math.round(b).toLocaleString()}`, color: t.indigo,
                position: i % 2 ? "insideEndBottom" : "insideEndTop" } })),
          ] },
        markArea: { silent: true, itemStyle: { color: t.indigo, opacity: theme === "desk" ? 0.1 : 0.06 },
          label: { show: false },
          data: [[{ xAxis: band[0] }, { xAxis: band[1] }]] } },
      { name: "Today", type: "line", data: spot.map((s, i) => [s, now[i]]), showSymbol: false,
        lineStyle: { width: 1.5, color: t.indigo, type: "dashed" } },
    ],
  };
  return (
    <div>
      <ReactECharts option={option} notMerge style={{ height: 340, width: "100%" }} key={theme} />
      <div className="mt-1 flex flex-wrap gap-x-5 gap-y-1 pl-16 text-[13px] text-muted">
        <span className="flex items-center gap-1.5"><i className="inline-block h-3 w-0 border-l border-dashed border-muted" /> Spot {Math.round(current).toLocaleString()}</span>
        {breakevens.map((b) => (
          <span key={b} className="flex items-center gap-1.5 text-indigo"><i className="inline-block h-3 w-0.5 bg-indigo" /> Breakeven {Math.round(b).toLocaleString()}</span>
        ))}
        <span className="flex items-center gap-1.5"><i className="inline-block h-3 w-3 rounded-[2px] bg-indigo/15" /> ±1σ expected move</span>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- lightweight-charts */
function useLwChart(build: (chart: IChartApi, t: ReturnType<typeof tokens>) => void, deps: unknown[]) {
  const ref = useRef<HTMLDivElement>(null);
  const { theme } = useTheme();
  useEffect(() => {
    if (!ref.current) return;
    const t = tokens();
    const chart = createChart(ref.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: t.muted,
        fontFamily: "IBM Plex Sans", attributionLogo: false },
      grid: { vertLines: { visible: false }, horzLines: { color: t.line } },
      rightPriceScale: { borderColor: t.line }, timeScale: { borderColor: t.line },
      crosshair: { mode: CrosshairMode.Magnet },
      localization: { priceFormatter: (p: number) => Math.abs(p) >= 100000
        ? `${(p / 100000).toFixed(2)}L`.replace(".00L", "L")
        : p.toLocaleString(undefined, { maximumFractionDigits: 2 }) },
    });
    build(chart, t);
    chart.timeScale().fitContent();
    return () => chart.remove();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme, ...deps]);
  return ref;
}

export function CandleChart({ bars, height = 300 }: { bars: { date?: string; time?: string; open: number; high: number; low: number; close: number }[]; height?: number }) {
  const ref = useLwChart((chart, t) => {
    const s = chart.addSeries(CandlestickSeries, { upColor: t.bull, downColor: t.bear, borderVisible: false,
      wickUpColor: t.bull, wickDownColor: t.bear });
    const intraday = bars.some((b) => b.time);
    // Session times are exchange-local; stamp them as UTC so the axis shows them unchanged.
    if (intraday) chart.applyOptions({ timeScale: { timeVisible: true, secondsVisible: false } });
    s.setData(bars.map((b) => ({
      time: (b.time ? Math.floor(Date.parse(b.time + "Z") / 1000) : b.date) as Time,
      open: b.open, high: b.high, low: b.low, close: b.close })));
  }, [bars]);
  return <div ref={ref} style={{ height }} className="w-full" />;
}

export function EquityChart({ dates, equity, benchmark, drawdown }: { dates: string[]; equity: number[]; benchmark: number[]; drawdown: number[] }) {
  const ref = useLwChart((chart, t) => {
    const eq = chart.addSeries(AreaSeries, { lineColor: t.indigo, topColor: t.indigo + "33", bottomColor: t.indigo + "00", lineWidth: 2, title: "Strategy" });
    eq.setData(dates.map((d, i) => ({ time: d as Time, value: equity[i] })));
    const bh = chart.addSeries(LineSeries, { color: t.muted, lineWidth: 1, lineStyle: 2, title: "Buy and hold" });
    bh.setData(dates.map((d, i) => ({ time: d as Time, value: benchmark[i] })));
    const dd = chart.addSeries(AreaSeries, { lineColor: t.bear, topColor: t.bear + "22", bottomColor: t.bear + "55",
      lineWidth: 1, invertFilledArea: true, priceFormat: { type: "custom", formatter: (v: number) => `${v.toFixed(0)}%` } } as never, 1);
    dd.setData(dates.map((d, i) => ({ time: d as Time, value: drawdown[i] * 100 })));
    chart.panes()[1]?.setHeight(90);
  }, [dates, equity]);
  return <div ref={ref} style={{ height: 380 }} className="w-full" />;
}
