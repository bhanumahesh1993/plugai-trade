/* Shared building blocks for every screen. Use these before writing a new one. */
import * as SwitchPrimitive from "@radix-ui/react-switch";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { createContext, useCallback, useContext, useState, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { AlertTriangle, Info, X, CheckCircle2 } from "lucide-react";
import ReactEChartsCore from "echarts-for-react/esm/core";
import { echarts } from "@/lib/echarts";
import { cn } from "@/lib/cn";
import { inputCls } from "./ui";
import { useTheme } from "./theme";

/* ------------------------------------------------------------ badge */
type Tone = "neutral" | "indigo" | "bull" | "bear" | "warn" | "in" | "us";
const toneCls: Record<Tone, string> = {
  neutral: "bg-panel-2 text-muted border border-line",
  indigo: "bg-indigo-soft text-indigo",
  bull: "bg-bull-soft text-bull",
  bear: "bg-bear-soft text-bear",
  warn: "bg-saffron/15 text-saffron",
  in: "bg-saffron text-white dark:text-[#0f1a2b]",
  us: "bg-navy text-white dark:text-[#0f1a2b]",
};
export function Badge({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return <span className={cn("inline-flex h-5 items-center rounded-[4px] px-1.5 text-[12px] font-medium", toneCls[tone], className)}>{children}</span>;
}

/* ------------------------------------------------------------ table */
export interface Column<T> { key: string; header: ReactNode; render?: (row: T) => ReactNode; align?: "left" | "right"; width?: string }
export function DataTable<T extends Record<string, unknown>>({ rows, columns, empty, onRowClick, rowKey }: {
  rows: T[]; columns: Column<T>[]; empty?: ReactNode; onRowClick?: (r: T) => void; rowKey?: (r: T, i: number) => string | number;
}) {
  if (!rows.length) return <EmptyState>{empty ?? "Nothing here yet."}</EmptyState>;
  return (
    <div className="scroll-thin overflow-x-auto">
      <table className="w-full text-[14px]">
        <thead>
          <tr className="border-b border-line text-left text-[12px] text-muted">
            {columns.map((c) => (
              <th key={c.key} style={{ width: c.width }} className={cn("pb-2 pr-3 font-normal", c.align === "right" && "text-right")}>{c.header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={rowKey ? rowKey(r, i) : i} onClick={onRowClick && (() => onRowClick(r))}
              className={cn("border-b border-line last:border-0", onRowClick && "cursor-pointer hover:bg-panel-2")}>
              {columns.map((c) => (
                <td key={c.key} className={cn("py-2 pr-3 align-top", c.align === "right" && "num text-right")}>
                  {c.render ? c.render(r) : String(r[c.key] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ------------------------------------------------------------ empty / callouts */
export function EmptyState({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-[var(--radius-tile)] border border-dashed border-line-strong px-4 py-6 text-muted">
      <div>{children}</div>
      {action}
    </div>
  );
}

export function Callout({ tone = "info", title, children }: { tone?: "info" | "warn" | "danger" | "ok"; title?: ReactNode; children: ReactNode }) {
  const Icon = tone === "ok" ? CheckCircle2 : tone === "info" ? Info : AlertTriangle;
  return (
    <div className={cn("flex gap-2.5 rounded-[var(--radius-tile)] border px-3.5 py-3 text-[14px]",
      tone === "info" && "border-indigo/30 bg-indigo-soft/60",
      tone === "warn" && "border-saffron/40 bg-saffron/10",
      tone === "danger" && "border-bear/40 bg-bear-soft",
      tone === "ok" && "border-bull/40 bg-bull-soft")}>
      <Icon size={17} className={cn("mt-0.5 shrink-0", tone === "info" && "text-indigo", tone === "warn" && "text-saffron",
        tone === "danger" && "text-bear", tone === "ok" && "text-bull")} />
      <div>{title && <div className="font-medium">{title}</div>}<div className={cn(title && "text-muted")}>{children}</div></div>
    </div>
  );
}

/** Mandatory on every backtest / paper / simulated result. */
export function Hypothetical() {
  return <Badge tone="neutral">Hypothetical</Badge>;
}

/* ------------------------------------------------------------ form controls */
export function Textarea({ className, ...p }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn("min-h-[72px] w-full resize-y rounded-[6px] border border-line-strong bg-panel p-2.5 text-[14px] outline-none focus:border-indigo", className)} {...p} />;
}

export function Select({ className, children, ...p }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={cn(inputCls, className)} {...p}>{children}</select>;
}

export function Switch({ checked, onChange, label, hint }: { checked: boolean; onChange: (v: boolean) => void; label: ReactNode; hint?: ReactNode }) {
  return (
    <label className="flex items-start justify-between gap-4 py-1.5">
      <span><span className="block">{label}</span>{hint && <span className="block text-[13px] text-muted">{hint}</span>}</span>
      <SwitchPrimitive.Root checked={checked} onCheckedChange={onChange}
        className="relative mt-0.5 h-5 w-9 shrink-0 rounded-full bg-line-strong data-[state=checked]:bg-indigo">
        <SwitchPrimitive.Thumb className="block h-4 w-4 translate-x-0.5 rounded-full bg-white transition-transform data-[state=checked]:translate-x-[18px]" />
      </SwitchPrimitive.Root>
    </label>
  );
}

export function Segmented<T extends string>({ value, options, onChange, label }: { value: T; options: readonly T[] | { value: T; label: ReactNode }[]; onChange: (v: T) => void; label: string }) {
  const opts = (options as readonly unknown[]).map((o) => (typeof o === "string" ? { value: o as T, label: o as string } : (o as { value: T; label: ReactNode })));
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-[6px] border border-line-strong bg-panel p-0.5">
      {opts.map((o) => (
        <button key={o.value} role="radio" aria-checked={value === o.value} onClick={() => onChange(o.value)}
          className={cn("h-7 rounded-[4px] px-2.5 text-[13px] text-muted", value === o.value && "bg-indigo-soft font-medium text-indigo")}>{o.label}</button>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------ dialog */
export function Dialog({ open, onOpenChange, title, children, footer }: {
  open: boolean; onOpenChange: (v: boolean) => void; title: ReactNode; children: ReactNode; footer?: ReactNode;
}) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/40" />
        <DialogPrimitive.Content className="drawer-enter fixed left-1/2 top-1/2 z-50 w-[min(560px,92vw)] -translate-x-1/2 -translate-y-1/2 rounded-[var(--radius-panel)] border border-line bg-panel shadow-2xl">
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <DialogPrimitive.Title className="text-[15px] font-semibold">{title}</DialogPrimitive.Title>
            <DialogPrimitive.Close aria-label="Close" className="text-muted hover:text-ink"><X size={16} /></DialogPrimitive.Close>
          </div>
          <div className="max-h-[70vh] overflow-y-auto p-4">{children}</div>
          {footer && <div className="flex justify-end gap-2 border-t border-line px-4 py-3">{footer}</div>}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

/* ------------------------------------------------------------ toast */
const ToastCtx = createContext<(msg: string, tone?: "ok" | "danger") => void>(() => {});
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<{ id: number; msg: string; tone: "ok" | "danger" }[]>([]);
  const push = useCallback((msg: string, tone: "ok" | "danger" = "ok") => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { id, msg, tone }]);
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), 3200);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={cn("drawer-enter rounded-[var(--radius-tile)] border px-3.5 py-2.5 text-[14px] shadow-lg",
            t.tone === "ok" ? "border-bull/40 bg-panel" : "border-bear/40 bg-panel text-bear")}>{t.msg}</div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
/** `const toast = useToast(); toast("Saved to journal")` — name the action that happened. */
export const useToast = () => useContext(ToastCtx);

/* ------------------------------------------------------------ generic chart */
/** Any ECharts option, themed. Colours: read CSS vars via chartTokens(). */
const FONT = "IBM Plex Sans";
/** Put the UI font on every text element ECharts would otherwise render in its default serif. */
function withFont(o: unknown): unknown {
  if (Array.isArray(o)) return o.map(withFont);
  if (!o || typeof o !== "object") return o;
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(o as Record<string, unknown>)) {
    out[k] = withFont(v);
    if (/^(textStyle|axisLabel|nameTextStyle|label)$/.test(k) && v && typeof v === "object" && !Array.isArray(v)) {
      out[k] = { fontFamily: FONT, ...(withFont(v) as object) };
    }
  }
  return out;
}

export function EChart({ option, height = 280 }: { option: Record<string, unknown>; height?: number }) {
  const { theme } = useTheme();
  const opt = withFont({ animation: false, ...option, textStyle: { fontFamily: FONT, ...(option.textStyle as object ?? {}) } }) as Record<string, unknown>;
  return <ReactEChartsCore echarts={echarts} option={opt} notMerge style={{ height, width: "100%" }} key={theme} />;
}
export function chartTokens() {
  const s = getComputedStyle(document.documentElement);
  const v = (n: string) => s.getPropertyValue(n).trim();
  return { ink: v("--ink"), muted: v("--muted"), line: v("--line"), panel: v("--panel"), indigo: v("--indigo"),
    bull: v("--bull"), bear: v("--bear"), saffron: v("--saffron"), navy: v("--navy") };
}

/* ------------------------------------------------------------ layout */
/** Standard screen grid: main column + optional right rail (tiles / explain). */
export function ScreenGrid({ children, rail }: { children: ReactNode; rail?: ReactNode }) {
  return (
    <div className={cn("grid gap-5", rail && "xl:grid-cols-[minmax(0,1fr)_340px]")}>
      <div className="flex min-w-0 flex-col gap-5">{children}</div>
      {rail && <div className="flex flex-col gap-4">{rail}</div>}
    </div>
  );
}
