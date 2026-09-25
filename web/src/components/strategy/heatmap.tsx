/* Trend Lab › Parameter heatmap: tuning years and unseen years side by side.
 * Every cell is one trial; the setting chosen before the sweep is outlined. */
import { EChart } from "@/components/kit";
import { usePalette, withFont } from "./shared";

export interface HeatmapData {
  rows: number[]; cols: number[]; tuning: (number | null)[][]; unseen: (number | null)[][]; base: [number, number] | null;
  split_date: string; benchmark_tuning: number; benchmark_unseen: number; trials: number; cells: number;
  row_label: string; col_label: string; text: string; facts: string[];
}

function Grid({ hm, grid, title, span }: { hm: HeatmapData; grid: (number | null)[][]; title: string; span: number }) {
  const t = usePalette();
  const cols = hm.col_label ? hm.cols.map(String) : ["—"];
  const data: Record<string, unknown>[] = [];
  hm.rows.forEach((r, i) => hm.cols.forEach((c, j) => {
    const v = grid[i][j];
    const mine = hm.base !== null && hm.base[0] === r && (!hm.col_label || hm.base[1] === c);
    data.push({ value: [j, i, v ?? "-"],
      itemStyle: mine ? { borderColor: t.ink, borderWidth: 2.5 } : { borderColor: t.panel, borderWidth: 1 } });
  }));
  const option = {
    title: { text: title, left: 64, top: 0, textStyle: { color: t.ink, fontSize: 13, fontWeight: 600 } },
    tooltip: { backgroundColor: t.panel, borderColor: t.line, textStyle: { color: t.ink, fontSize: 12 },
      formatter: (p: { value: [number, number, number | string] }) =>
        `${hm.row_label} ${hm.rows[p.value[1]]}${hm.col_label ? `, ${hm.col_label} ${hm.cols[p.value[0]]}` : ""}<br/>Sharpe ${p.value[2]}` },
    grid: { left: 64, right: 8, top: 30, bottom: 44 },
    xAxis: { type: "category", data: cols, name: hm.col_label, nameLocation: "middle", nameGap: 26,
      nameTextStyle: { color: t.muted }, axisLabel: { color: t.muted }, axisLine: { lineStyle: { color: t.line } }, splitArea: { show: false } },
    yAxis: { type: "category", data: hm.rows.map(String), name: hm.row_label, nameLocation: "middle", nameGap: 40, nameTextStyle: { color: t.muted },
      axisLabel: { color: t.muted }, axisLine: { lineStyle: { color: t.line } } },
    visualMap: { show: false, min: -span, max: span, inRange: { color: [t.bear, t.panel, t.bull] } },
    series: [{ type: "heatmap", data, label: { show: true, color: t.ink, fontSize: 11,
      formatter: (p: { value: [number, number, number | string] }) => (typeof p.value[2] === "number" ? p.value[2].toFixed(2) : "—") } }],
  };
  return <EChart option={withFont(option)} height={Math.max(200, 40 * hm.rows.length + 80)} />;
}

export function HeatmapView({ hm }: { hm: HeatmapData }) {
  const vals = [...hm.tuning.flat(), ...hm.unseen.flat()].filter((v): v is number => v !== null);
  const span = Math.max(0.5, ...vals.map(Math.abs));
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Grid hm={hm} grid={hm.tuning} title={`Tuning years (to ${hm.split_date})`} span={span} />
      <Grid hm={hm} grid={hm.unseen} title={`Unseen years (after ${hm.split_date})`} span={span} />
    </div>
  );
}
