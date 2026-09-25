/* Strategy Builder › Chart check: the rule's entries and exits drawn on the price,
 * with the averages it reads. Markers sit on the fill session (the open after the
 * signal). Drag the slider under the chart to scroll through the years. */
import { EChart } from "@/components/kit";
import { usePalette, withFont } from "./shared";

export interface ChartCheckData {
  symbol: string; source: string; notice: string | null; dates: string[]; close: number[];
  lines: Record<string, (number | null)[]>; buys: { date: string; price: number }[]; sells: { date: string; price: number }[];
  chip: string; round_trips: number;
}

export function ChartCheckChart({ d }: { d: ChartCheckData }) {
  const t = usePalette();
  const lineColours = [t.indigo, t.muted];
  const start = Math.max(0, 100 - (100 * 504) / Math.max(d.dates.length, 1)); // open on the last ~2 years
  const option = {
    legend: { top: 0, left: 50, textStyle: { color: t.muted, fontSize: 12 } },
    tooltip: { trigger: "axis", backgroundColor: t.panel, borderColor: t.line, textStyle: { color: t.ink, fontSize: 12 },
      valueFormatter: (v: number) => (v == null ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: 2 })) },
    grid: { left: 64, right: 16, top: 30, bottom: 64 },
    xAxis: { type: "category", data: d.dates, boundaryGap: false, axisLine: { lineStyle: { color: t.line } },
      axisTick: { show: false }, axisLabel: { color: t.muted } },
    yAxis: { type: "value", scale: true, axisLabel: { color: t.muted }, splitLine: { lineStyle: { color: t.line } } },
    dataZoom: [
      { type: "inside", start, end: 100 },
      { type: "slider", start, end: 100, height: 22, bottom: 10, borderColor: t.line, textStyle: { color: t.muted },
        fillerColor: "rgba(79,70,229,0.12)", handleStyle: { color: t.indigo }, dataBackground: { lineStyle: { color: t.muted } } },
    ],
    series: [
      { name: "Close", type: "line", data: d.close, showSymbol: false, lineStyle: { width: 1.4, color: t.ink }, itemStyle: { color: t.ink } },
      ...Object.entries(d.lines).map(([name, values], i) => ({
        name, type: "line", data: values, showSymbol: false,
        lineStyle: { width: 1.2, color: lineColours[i % 2], type: i % 2 ? "dashed" : "solid" }, itemStyle: { color: lineColours[i % 2] },
      })),
      { name: "Entry (fill)", type: "scatter", symbol: "triangle", symbolSize: 10, itemStyle: { color: t.bull },
        data: d.buys.map((b) => [b.date, b.price]) },
      { name: "Exit (fill)", type: "scatter", symbol: "triangle", symbolRotate: 180, symbolSize: 10, itemStyle: { color: t.bear },
        data: d.sells.map((b) => [b.date, b.price]) },
    ],
  };
  return <EChart option={withFont(option)} height={340} />;
}
