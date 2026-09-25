/* Plan & Risk / Paper Trading building blocks shared by the planning screens. */
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";
import { Sparkles, ShieldCheck, RotateCcw, Lock } from "lucide-react";
import type { Explanation } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button, Field, inputCls } from "@/components/ui";

/* ------------------------------------------------------------ inputs */
/** A number input that keeps what you type (so "0." and "" work) and reports numbers. */
export function NumField({ label, value, onChange, step = "any", hint, min, max, disabled, className, placeholder }: {
  label: string; value: number | null | undefined; onChange: (v: number | null) => void; step?: number | "any";
  hint?: string; min?: number; max?: number; disabled?: boolean; className?: string; placeholder?: string;
}) {
  const [text, setText] = useState(value === null || value === undefined ? "" : String(value));
  useEffect(() => {
    const cur = text.trim() === "" ? null : Number(text);
    if (cur !== (value ?? null)) setText(value === null || value === undefined ? "" : String(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  return (
    <Field label={label} hint={hint}>
      <input className={cn(inputCls, className)} type="number" inputMode="decimal" step={step} min={min} max={max}
        disabled={disabled} placeholder={placeholder} value={text}
        onChange={(e) => {
          setText(e.target.value);
          const t = e.target.value.trim();
          onChange(t === "" || Number.isNaN(Number(t)) ? null : Number(t));
        }} />
    </Field>
  );
}

export function TextField({ label, value, onChange, hint, placeholder, className }: {
  label: string; value: string; onChange: (v: string) => void; hint?: string; placeholder?: string; className?: string;
}) {
  return (
    <Field label={label} hint={hint}>
      <input className={cn(inputCls, "font-sans", className)} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
    </Field>
  );
}

export function Check({ checked, onChange, children, hint }: { checked: boolean; onChange: (v: boolean) => void; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="flex cursor-pointer items-start gap-2.5 py-1">
      <input type="checkbox" className="mt-[3px] h-4 w-4 shrink-0 accent-[var(--indigo)]" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span><span className="block">{children}</span>{hint && <span className="block text-[13px] text-muted">{hint}</span>}</span>
    </label>
  );
}

export function ErrorLine({ error }: { error: unknown }) {
  if (!error) return null;
  return <p className="text-[13px] text-bear" role="alert">{(error as Error).message}</p>;
}

export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t); }, [value, ms]);
  return v;
}

/** Who fills a plan field: you, code (Position Sizer / Alerts) or the lab calendar. */
export function OwnerChip({ owner }: { owner: string }) {
  const label = owner === "YOU" ? "You" : owner === "CODE" ? "Code" : "Calendar";
  const cls = owner === "YOU" ? "border-ink/30 text-ink" : owner === "CODE" ? "border-indigo/40 text-indigo" : "border-line-strong text-muted";
  const title = owner === "YOU" ? "You write this field in your own words"
    : owner === "CODE" ? "Filled by code (Position Sizer / Alerts); you may edit"
    : "Filled from the lab calendar; add any it missed";
  return <span title={title} className={cn("inline-flex h-5 items-center rounded-[4px] border bg-panel px-1.5 text-[12px] font-medium", cls)}>{label}</span>;
}

/* ------------------------------------------------------------ cited explanations with local routing
 * The shared ExplainPanel always calls /api/explain. The Trade Plan critique is its own call
 * (plans.critique), so this panel takes the call as a prop and keeps its own citation highlight
 * for the plan fields it cites.
 */
const LitCtx = createContext<{ lit: string | null; setLit: (k: string | null) => void }>({ lit: null, setLit: () => {} });
export function LocalFacts({ children }: { children: ReactNode }) {
  const [lit, setLit] = useState<string | null>(null);
  const v = useMemo(() => ({ lit, setLit }), [lit]);
  return <LitCtx.Provider value={v}>{children}</LitCtx.Provider>;
}
const keyOf = (fact: string) => fact.split(":")[0].trim().toLowerCase();
export const useLit = (label: string) => {
  const { lit } = useContext(LitCtx);
  return lit !== null && lit === label.toLowerCase();
};

/** Same look as FactTile; lit by citations in a CitedPanel inside the same LocalFacts. */
export function LocalTile({ label, value, sub, tone, big }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "bull" | "bear" | "indigo"; big?: boolean }) {
  const on = useLit(label);
  return (
    <div className={cn("tile rounded-[var(--radius-tile)] border border-line bg-panel-2 px-3 py-2.5", on && "tile-lit")}>
      <div className="text-[12px] text-muted">{label}</div>
      <div className={cn("num mt-0.5 font-semibold leading-tight", big ? "text-[26px]" : "text-[20px]",
        tone === "bull" && "text-bull", tone === "bear" && "text-bear", tone === "indigo" && "text-indigo")}>{value}</div>
      {sub && <div className="mt-0.5 text-[12px] text-muted">{sub}</div>}
    </div>
  );
}

function Cited({ text, sources }: { text: string; sources: string[] }) {
  const { setLit } = useContext(LitCtx);
  return (
    <p className="whitespace-pre-line font-serif text-[15px] leading-[1.6] text-ink">
      {text.split(/(\[\d+\])/g).map((p, i) => {
        const m = p.match(/^\[(\d+)\]$/);
        if (!m) return <span key={i}>{p.split(/(\*[^*\n]+\*)/g).map((q, j) => (/^\*[^*]+\*$/.test(q) ? <b key={j} className="font-semibold">{q.slice(1, -1)}</b> : q.replace(/\*/g, "")))}</span>;
        const n = Number(m[1]);
        const fact = sources[n - 1];
        return (
          <button key={i} type="button" title={fact}
            onMouseEnter={() => fact && setLit(keyOf(fact))} onMouseLeave={() => setLit(null)}
            onFocus={() => fact && setLit(keyOf(fact))} onBlur={() => setLit(null)}
            className="mx-0.5 inline-flex h-[18px] min-w-[18px] -translate-y-px items-center justify-center rounded-[4px] bg-indigo-soft px-1 align-middle font-sans text-[11px] font-semibold text-indigo hover:bg-indigo hover:text-white dark:hover:text-[#0f1a2b]">
            {n}
          </button>
        );
      })}
    </p>
  );
}

export function CitedPanel({ facts, run, second, label = "Explain", pendingLabel = "Explaining…", localOnly, note }: {
  facts: string[]; run: () => Promise<Explanation>; second: (text: string) => Promise<Explanation>;
  label?: string; pendingLabel?: string; localOnly?: boolean; note?: ReactNode;
}) {
  const [showSources, setShowSources] = useState(false);
  const first = useMutation({ mutationFn: run });
  const sec = useMutation({ mutationFn: () => second(first.data?.text ?? "") });
  const out = first.data;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" size="sm" onClick={() => first.mutate()} disabled={first.isPending}>
          <Sparkles size={14} /> {first.isPending ? pendingLabel : label}
        </Button>
        <Button size="sm" onClick={() => setShowSources((s) => !s)}>Show sources</Button>
        <Button size="sm" onClick={() => sec.mutate()} disabled={!out || sec.isPending}><RotateCcw size={14} /> Second opinion</Button>
      </div>
      {localOnly && <p className="flex items-center gap-1.5 text-[12px] text-muted"><Lock size={12} /> Sensitive: explained by your local model only.</p>}
      <ErrorLine error={first.error ?? sec.error} />
      {out && (
        <div className="drawer-enter rounded-[var(--radius-tile)] border border-line bg-panel p-3.5">
          <Cited text={out.text} sources={out.sources} />
          <div className="mt-2 flex items-start gap-1.5 text-[12px] text-muted">
            <ShieldCheck size={13} className="mt-px shrink-0" />
            <span>{out.where === "Fallback" ? "No model connected: the lab's own checks, listed" : `${out.where} model ${out.model}`}{note ? `. ${note}.` : ""}</span>
          </div>
        </div>
      )}
      {sec.data && (
        <div className="rounded-[var(--radius-tile)] border border-bear/40 bg-bear-soft/40 p-3.5">
          <Cited text={sec.data.text} sources={sec.data.sources} />
        </div>
      )}
      {showSources && (
        <ol className="num rounded-[var(--radius-tile)] border border-line bg-panel-2 p-3 text-[13px]">
          {facts.map((f, i) => <li key={i} className="py-0.5"><span className="mr-2 text-muted">{i + 1}</span>{f}</li>)}
        </ol>
      )}
    </div>
  );
}
