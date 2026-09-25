/* Pairs Lab pieces shared with the Backtest Report: the spread z-score chart and the
 * trades table. The formation window is frozen; everything after it is trading. */
import type { Market } from "@/lib/api";
import { DataTable, EChart, type Column } from "@/components/kit";
import { usePalette, withFont } from "./shared";

export interface PairTrade {
  number: number; side: number; entry_session: number; entry_z: number; exit_session: number; exit_z: number;
  exit_type: string; spread_pnl: number; sessions?: number;
}
export interface PairRule { entry: number; exit: number; stop: number; time_stop: number }

const EXIT_SYMBOL: Record<string, string> = { exit: "circle", "time stop": "rect", stop: "diamond", open: "emptyCircle" };

export function ZChart({ z, formation, rule, trades }: { z: number[]; formation: number; rule: PairRule; trades: PairTrade[] }) {
  const t = usePalette();
  const sessions = z.map((_, i) => i + 1);
  const level = (y: number, name: string, color: string) => ({ yAxis: y, name, lineStyle: { color, type: "dashed", width: 1 },
    label: { formatter: `${name} ${y > 0 ? "+" : ""}${y}`, color, fontSize: 11, position: "insideEndTop" } });
  const option = {
    legend: { top: 0, right: 64, textStyle: { color: t.muted, fontSize: 12 } },
    tooltip: { trigger: "axis", backgroundColor: t.panel, borderColor: t.line, textStyle: { color: t.ink, fontSize: 12 },
      valueFormatter: (v: number) => (v == null ? "—" : Number(v).toFixed(2)) },
    grid: { left: 48, right: 64, top: 48, bottom: 40 },
    xAxis: { type: "category", data: sessions, name: "Session", nameLocation: "middle", nameGap: 26, nameTextStyle: { color: t.muted },
      axisLine: { lineStyle: { color: t.line } }, axisTick: { show: false }, axisLabel: { color: t.muted, interval: 49 } },
    yAxis: { type: "value", name: "z-score", nameTextStyle: { color: t.muted }, axisLabel: { color: t.muted }, splitLine: { lineStyle: { color: t.line } } },
    series: [
      { name: "Spread z-score", type: "line", data: z, showSymbol: false, lineStyle: { width: 1.2, color: t.indigo }, itemStyle: { color: t.indigo },
        markLine: { symbol: "none", silent: true, data: [
          level(rule.entry, "Entry", t.indigo), level(-rule.entry, "Entry", t.indigo),
          level(rule.exit, "Exit", t.muted), level(-rule.exit, "Exit", t.muted),
          level(rule.stop, "Stop", t.bear), level(-rule.stop, "Stop", t.bear),
          { xAxis: formation - 1, lineStyle: { color: t.ink, type: "solid", width: 1.2 },
            label: { formatter: `Formation ends, session ${formation}`, color: t.ink, fontSize: 11, position: "end" } },
        ] },
        markArea: { silent: true, itemStyle: { color: t.muted, opacity: 0.06 }, data: [[{ xAxis: 0 }, { xAxis: formation - 1 }]] } },
      ...Object.keys(EXIT_SYMBOL).map((kind) => ({
        name: `Exit: ${kind}`, type: "scatter", symbol: EXIT_SYMBOL[kind], symbolSize: 8,
        itemStyle: { color: kind === "stop" ? t.bear : t.ink },
        data: trades.filter((x) => x.exit_type === kind).map((x) => [x.exit_session - 1, x.exit_z]),
      })).filter((s) => s.data.length),
    ],
  };
  return <EChart option={withFont(option)} height={300} />;
}

export function PairTradesTable({ trades }: { trades: PairTrade[]; market?: Market }) {
  const cols: Column<PairTrade & Record<string, unknown>>[] = [
    { key: "number", header: "Trade", align: "right" },
    { key: "side", header: "Side", render: (r) => (r.side > 0 ? "Long A, short B" : "Short A, long B") },
    { key: "entry_session", header: "Entry session", align: "right" },
    { key: "entry_z", header: "Entry z", align: "right", render: (r) => r.entry_z.toFixed(2) },
    { key: "exit_session", header: "Exit session", align: "right" },
    { key: "exit_z", header: "Exit z", align: "right", render: (r) => r.exit_z.toFixed(2) },
    { key: "exit_type", header: "Exit" },
    { key: "sessions", header: "Sessions", align: "right", render: (r) => r.sessions ?? r.exit_session - r.entry_session },
    { key: "spread_pnl", header: "Spread P&L (log)", align: "right",
      render: (r) => <span className={r.spread_pnl >= 0 ? "text-bull" : "text-bear"}>{r.spread_pnl.toFixed(4)}</span> },
  ];
  return <DataTable rows={trades as (PairTrade & Record<string, unknown>)[]} columns={cols} empty="No round trips in the trading window." />;
}
