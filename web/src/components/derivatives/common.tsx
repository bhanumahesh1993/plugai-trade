/* Small building blocks shared by the three Derivatives screens. */
import type { ReactNode } from "react";
import { Info } from "lucide-react";
import { cn } from "@/lib/cn";
import { Field, inputCls } from "@/components/ui";
import { EChart, chartTokens } from "@/components/kit";

/** Numeric input with a label; blank stays blank (null) so "blank = default" inputs work. */
export function NumberField({ label, value, onChange, step, min, max, hint, placeholder, className }: {
  label: string; value: number | null; onChange: (v: number | null) => void; step?: number; min?: number; max?: number;
  hint?: string; placeholder?: string; className?: string;
}) {
  return (
    <div className={className}>
      <Field label={label} hint={hint}>
        <input className={inputCls} type="number" step={step} min={min} max={max} placeholder={placeholder}
          value={value ?? ""} aria-label={label}
          onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} />
      </Field>
    </div>
  );
}

/** A quiet footnote: the page's dated / paper-only reminders. */
export function Note({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <p className={cn("flex items-start gap-1.5 text-[13px] text-muted", className)}>
      <Info size={14} className="mt-[3px] shrink-0" />
      <span>{children}</span>
    </p>
  );
}

/** Dated reference note, as on every classic Derivatives page. */
export function DatedNote({ asOf, children }: { asOf?: string; children?: ReactNode }) {
  return <Note>{children ?? "Values come from the dated reference tables."}{asOf && <> As of {asOf}. Run <code className="text-ink">plugai-trade update</code> for the latest table.</>}</Note>;
}

export const PAPER_NOTE = "Paper only. PlugAI-Trade never places real orders; anything sent to the Paper Desk waits for your Accept there.";

type Series = { name: string; data: [string | number, number | null][]; color?: string; dashed?: boolean; area?: boolean };

/** Themed time or value line chart with an optional legend (ECharts). */
export function Lines({ series, height = 220, xType = "time", yFormat, legend = true, marks }: {
  series: Series[]; height?: number; xType?: "time" | "value" | "category"; yFormat?: (v: number) => string; legend?: boolean;
  marks?: { x: string | number; label: string }[];
}) {
  const t = chartTokens();
  const option = {
    grid: { left: 64, right: 16, top: legend ? 30 : 12, bottom: 28 },
    legend: legend ? { top: 0, left: 0, textStyle: { color: t.muted }, itemWidth: 14, itemHeight: 2, icon: "rect" } : undefined,
    tooltip: { trigger: "axis", backgroundColor: t.panel, borderColor: t.line, textStyle: { color: t.ink },
      valueFormatter: (v: number) => (v == null ? "—" : yFormat ? yFormat(v) : v.toLocaleString(undefined, { maximumFractionDigits: 2 })) },
    xAxis: { type: xType, axisLine: { lineStyle: { color: t.line } }, axisLabel: { color: t.muted, hideOverlap: true }, splitLine: { show: false } },
    yAxis: { type: "value", scale: true, axisLabel: { color: t.muted, formatter: yFormat }, splitLine: { lineStyle: { color: t.line } } },
    series: series.map((s, i) => ({
      name: s.name, type: "line", data: s.data, showSymbol: false,
      lineStyle: { width: s.dashed ? 1.5 : 2, color: s.color, type: s.dashed ? "dashed" : "solid" },
      itemStyle: { color: s.color }, areaStyle: s.area ? { color: s.color, opacity: 0.08 } : undefined,
      markLine: i === 0 && marks?.length ? { symbol: "none", silent: true,
        data: marks.map((m) => ({ xAxis: m.x, lineStyle: { color: t.muted, type: "dotted" },
          label: { formatter: m.label, color: t.muted, fontSize: 11, position: "insideEndTop" } })) } : undefined,
    })),
  };
  return <EChart option={option} height={height} />;
}

/** Signed bars (bull above zero, bear below): MTM by day, P&L attribution. */
export function SignedBars({ labels, values, height = 180, yFormat }: {
  labels: (string | number)[]; values: number[]; height?: number; yFormat?: (v: number) => string;
}) {
  const t = chartTokens();
  const option = {
    grid: { left: 64, right: 12, top: 12, bottom: 28 },
    tooltip: { trigger: "axis", backgroundColor: t.panel, borderColor: t.line, textStyle: { color: t.ink },
      valueFormatter: (v: number) => (yFormat ? yFormat(v) : String(v)) },
    xAxis: { type: "category", data: labels, axisLine: { lineStyle: { color: t.line } }, axisLabel: { color: t.muted, interval: 0 } },
    yAxis: { type: "value", axisLabel: { color: t.muted, formatter: yFormat }, splitLine: { lineStyle: { color: t.line } } },
    series: [{ type: "bar", barMaxWidth: 36, data: values.map((v) => ({ value: v, itemStyle: { color: v >= 0 ? t.bull : t.bear, borderRadius: 2 } })) }],
  };
  return <EChart option={option} height={height} />;
}

/** Tone for a tile: bull/bear only for P&L or direction. */
export function signTone(text: string): "bull" | "bear" | undefined {
  const s = text.trim().replace(/^≈\s*/, "");
  if (s.startsWith("−") || s.startsWith("-")) return "bear";
  return undefined;
}
