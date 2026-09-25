/* Shared pieces for the Strategy screens: result tiles, the HYPOTHETICAL equity and
 * drawdown chart, trades, the data choice. Every number is computed by the engine. */
import { useEffect, useState, type ReactNode } from "react";
import type { Market } from "@/lib/api";
import { money, pct } from "@/lib/format";
import { FactTile } from "@/components/facts";
import { useTheme } from "@/components/theme";
import { DataTable, EChart, Segmented, type Column } from "@/components/kit";

/* ------------------------------------------------------------ types */
export type CardLine = [string, boolean];
export interface RuleCard { title: string; lines: CardLine[] }
export interface Frame {
  dates: string[]; equity: number[]; buy_and_hold: number[]; drawdown: number[]; bh_drawdown: number[];
  before_costs?: number[];
}
export interface DrawdownStory { depth: number | null; start: string | null; trough: string | null; recovered: string | null; months_below: number }
export interface Summary {
  meta: { symbol: string; symbols: string[]; market: Market; source: string; start: string; end: string; profile: string; capital: number; origin: string; slippage_pct: number | null };
  read_back: string; cards: RuleCard[]; digest: string; trials: number;
  stats: Record<string, number>; gross: Record<string, number>;
  frame: Frame; drawdown_story: DrawdownStory; facts: string[]; grade?: string;
}
export type Trade = Record<string, string | number | boolean | null>;

/* ------------------------------------------------------------ theme palette
 * Chart colours follow the theme state directly (the CSS variables change one
 * effect later, so reading them during render would lag a theme switch). */
const PALETTE = {
  book: { ink: "#1B2437", muted: "#5B6780", line: "#DCE3EE", panel: "#FFFFFF", indigo: "#4F46E5", bull: "#15803D", bear: "#DC2626" },
  desk: { ink: "#E7EDF6", muted: "#8FA0BA", line: "#233451", panel: "#152338", indigo: "#8B8FFF", bull: "#34C27A", bear: "#F2626A" },
};
export function usePalette() {
  const { theme } = useTheme();
  return PALETTE[theme];
}

/** ECharts does not inherit the page font into axis labels, legends and labels: set it everywhere. */
const FONT_KEYS = new Set(["textStyle", "axisLabel", "nameTextStyle", "label"]);
export function withFont<T>(o: T): T {
  if (Array.isArray(o)) return o.map(withFont) as T;
  if (o && typeof o === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(o as Record<string, unknown>)) {
      out[k] = FONT_KEYS.has(k) && v && typeof v === "object" && !Array.isArray(v)
        ? withFont({ fontFamily: "IBM Plex Sans", ...(v as object) }) : withFont(v);
    }
    return out as T;
  }
  return o;
}

/* ------------------------------------------------------------ session state
 * Remember a screen's inputs while the reader moves between screens. Optional:
 * works without storage (private windows). */
export function useSessionState<T>(key: string, initial: T): [T, (v: T | ((p: T) => T)) => void] {
  const [v, setV] = useState<T>(() => {
    try {
      const raw = sessionStorage.getItem(`plugai-${key}`);
      if (raw) return JSON.parse(raw) as T;
    } catch { /* ignore */ }
    return initial;
  });
  useEffect(() => {
    try { sessionStorage.setItem(`plugai-${key}`, JSON.stringify(v)); } catch { /* ignore */ }
  }, [key, v]);
  return [v, setV];
}

/* ------------------------------------------------------------ small pieces */
export function DataChoice({ synthetic, onChange }: { synthetic: boolean; onChange: (s: boolean) => void }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[12px] text-muted">Data</span>
      <Segmented label="Data" value={synthetic ? "Synthetic" : "Free source"} options={["Synthetic", "Free source"] as const}
        onChange={(v) => onChange(v === "Synthetic")} />
    </div>
  );
}

export function PaperOnlyNote() {
  return <p className="text-[12px] text-muted">Paper only. PlugAI-Trade never places real orders.</p>;
}

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null;
  return <p className="text-[13px] text-bear" role="alert">{(error as Error).message}</p>;
}

export function Labelled({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex min-w-0 flex-col gap-1">
      <span className="text-[12px] text-muted">{label}</span>
      {children}
    </label>
  );
}

/* ------------------------------------------------------------ tiles */
/** The first table a Backtest Report shows (Chapter 11), as tiles. */
export function SummaryTiles({ s, g, trials, market, bigFirst = true }: {
  s: Record<string, number>; g: Record<string, number>; trials: number; market: Market; bigFirst?: boolean;
}) {
  const winRate = s.round_trips ? ` (${((s.winners / s.round_trips) * 100).toFixed(1)}%)` : "";
  return (
    <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
      <FactTile label="After costs" value={pct(s.total_return, 1)} tone={s.total_return >= 0 ? "bull" : "bear"} big={bigFirst}
        sub={`Before costs ${pct(g.total_return, 1)}`} />
      <FactTile label="Round trips" value={s.round_trips} sub={`Winning: ${s.winners}${winRate}`} />
      <FactTile label="Worst drawdown" value={pct(s.max_drawdown, 1)} tone="bear" />
      <FactTile label="Buy and hold" value={pct(s.bh_return, 1)} sub="Same period" />
      <FactTile label="Charges / fees" value={money(s.charges, market)} />
      <FactTile label="Assumed slippage" value={money(s.slippage, market)} />
      <FactTile label="Sharpe (after costs)" value={s.sharpe?.toFixed(2)} />
      <FactTile label="Trials" value={trials} sub="Distinct variants in this family" />
    </div>
  );
}

/* ------------------------------------------------------------ equity + drawdown */
export interface ExtraLine { name: string; values: number[] }

/** Equity scaled to 100 with the buy-and-hold line, and the drawdown pane beneath.
 *  The deepest drawdown is marked; hovering shows its depth and date. */
export function ResultChart({ frame, extra = [], gross = false, height = 380, showDrawdown = true }: {
  frame: Frame; extra?: ExtraLine[]; gross?: boolean; height?: number; showDrawdown?: boolean;
}) {
  const t = usePalette();
  const dates = frame.dates;
  let deepest = 0;
  frame.drawdown.forEach((v, i) => { if (v < frame.drawdown[deepest]) deepest = i; });
  const eqGrid = showDrawdown ? { left: 56, right: 16, top: 50, height: "50%" } : { left: 56, right: 16, top: 50, bottom: 32 };
  const series: Record<string, unknown>[] = [
    { name: "Rule, after costs", type: "line", data: frame.equity, showSymbol: false, lineStyle: { width: 2, color: t.indigo }, itemStyle: { color: t.indigo } },
    { name: "Buy and hold", type: "line", data: frame.buy_and_hold, showSymbol: false, lineStyle: { width: 1.4, color: t.muted, type: "dashed" }, itemStyle: { color: t.muted } },
  ];
  if (gross && frame.before_costs) {
    series.push({ name: "Rule, before costs", type: "line", data: frame.before_costs, showSymbol: false, lineStyle: { width: 1.4, color: t.ink, type: "dotted" }, itemStyle: { color: t.ink } });
  }
  extra.forEach((x) => series.push({ name: x.name, type: "line", data: x.values, showSymbol: false, lineStyle: { width: 1.6, color: t.ink }, itemStyle: { color: t.ink } }));
  if (showDrawdown) {
    series.push(
      { name: "Drawdown", type: "line", xAxisIndex: 1, yAxisIndex: 1, data: frame.drawdown, showSymbol: false,
        lineStyle: { width: 1, color: t.bear }, itemStyle: { color: t.bear }, areaStyle: { color: t.bear, opacity: 0.28 },
        markPoint: { symbol: "circle", symbolSize: 8, itemStyle: { color: t.bear },
          label: { show: true, position: "right", color: t.bear, fontSize: 11, formatter: `Deepest ${frame.drawdown[deepest]?.toFixed(1)}%` },
          data: [{ coord: [deepest, frame.drawdown[deepest]] }] } },
      { name: "Buy and hold drawdown", type: "line", xAxisIndex: 1, yAxisIndex: 1, data: frame.bh_drawdown, showSymbol: false,
        lineStyle: { width: 1, color: t.muted, type: "dashed" }, itemStyle: { color: t.muted } },
    );
  }
  const axisX = (idx: number, show: boolean) => ({ type: "category", data: dates, gridIndex: idx, boundaryGap: false,
    axisLine: { lineStyle: { color: t.line } }, axisTick: { show: false },
    axisLabel: { show, color: t.muted, formatter: (v: string) => v.slice(0, 7) } });
  const option = {
    legend: { top: 0, left: 50, itemGap: 18, textStyle: { color: t.muted, fontSize: 12 }, itemWidth: 16, itemHeight: 2, icon: "rect",
      data: series.filter((s) => !String(s.name).includes("drawdown") && s.name !== "Drawdown").map((s) => s.name) },
    tooltip: { trigger: "axis", backgroundColor: t.panel, borderColor: t.line, textStyle: { color: t.ink, fontSize: 12 },
      valueFormatter: (v: number) => (v == null ? "—" : v.toFixed(1)) },
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    grid: showDrawdown ? [eqGrid, { left: 56, right: 16, top: "68%", bottom: 36 }] : [eqGrid],
    xAxis: showDrawdown ? [axisX(0, false), axisX(1, true)] : [axisX(0, true)],
    yAxis: [
      { type: "value", scale: true, gridIndex: 0, name: "Start = 100", nameGap: 12, nameTextStyle: { color: t.muted, fontSize: 11, align: "right" },
        axisLabel: { color: t.muted }, splitLine: { lineStyle: { color: t.line } } },
      ...(showDrawdown ? [{ type: "value", gridIndex: 1, max: 0, splitNumber: 2, axisLabel: { color: t.muted, formatter: "{value}%" },
        splitLine: { lineStyle: { color: t.line } } }] : []),
    ],
    dataZoom: [{ type: "inside", xAxisIndex: showDrawdown ? [0, 1] : [0] }],
    series,
  };
  return <EChart option={withFont(option)} height={height} />;
}

export function drawdownSentence(story: DrawdownStory, bhWorst: number): string | null {
  if (!story.start || story.depth == null) return null;
  const rec = story.recovered ? `recovered ${story.recovered}` : "not yet recovered";
  return `Deepest drawdown ${(story.depth * 100).toFixed(1)}%, began ${story.start}, bottom ${story.trough}, ` +
    `${story.months_below} months below the earlier high (${rec}). Buy-and-hold worst: ${(bhWorst * 100).toFixed(1)}%.`;
}

/* ------------------------------------------------------------ trades */
export function TradesTable({ trades, market }: { trades: Trade[]; market: Market }) {
  const m = (k: string) => (r: Trade) => money(r[k] as number, market);
  const cols: Column<Trade>[] = [
    { key: "symbol", header: "Symbol" },
    { key: "entry_date", header: "Entry" },
    { key: "exit_date", header: "Exit", render: (r) => (r.open ? "Open" : String(r.exit_date ?? "—")) },
    { key: "bars", header: "Sessions", align: "right" },
    { key: "units", header: "Units", align: "right" },
    { key: "buy_value", header: "Buy value", align: "right", render: m("buy_value") },
    { key: "sell_value", header: "Sell value", align: "right", render: m("sell_value") },
    { key: "gross_pnl", header: "Gross P&L", align: "right", render: m("gross_pnl") },
    { key: "charges", header: "Charges", align: "right", render: m("charges") },
    { key: "slippage", header: "Slippage", align: "right", render: m("slippage") },
    { key: "net_pnl", header: "Net P&L", align: "right",
      render: (r) => <span className={(r.net_pnl as number) >= 0 ? "text-bull" : "text-bear"}>{money(r.net_pnl as number, market)}</span> },
    { key: "return_pct", header: "Return", align: "right", render: (r) => `${(r.return_pct as number)?.toFixed(2)}%` },
  ];
  return <DataTable rows={trades} columns={cols} empty="No trades in this period." />;
}
