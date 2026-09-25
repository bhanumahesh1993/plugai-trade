/* Journal and Tax data are personal: every AI call on these screens goes to
 * /api/journal/explain, which forces the local model (sensitive=True). This is the local
 * twin of facts.tsx (ExplainPanel posts to the shared, non-sensitive /api/explain and its
 * lit-tile context is not exported). Same look, same cited-chip behaviour. */
import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";
import { Sparkles, ShieldCheck, RotateCcw, Lock } from "lucide-react";
import { post, type Explanation } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button } from "@/components/ui";

const LitCtx = createContext<{ lit: string | null; setLit: (k: string | null) => void }>({ lit: null, setLit: () => {} });

export function LocalFactsProvider({ children }: { children: ReactNode }) {
  const [lit, setLit] = useState<string | null>(null);
  const v = useMemo(() => ({ lit, setLit }), [lit]);
  return <LitCtx.Provider value={v}>{children}</LitCtx.Provider>;
}

const norm = (s: string) => s.trim().toLowerCase();

/** A fact tile. It lights when a cited fact starts with its label or any of `keys`. */
export function Tile({ label, value, sub, tone, big, keys, className }: {
  label: string; value: ReactNode; sub?: ReactNode; tone?: "bull" | "bear" | "indigo" | "warn"; big?: boolean;
  keys?: string[]; className?: string;
}) {
  const { lit } = useContext(LitCtx);
  const on = lit !== null && [label, ...(keys ?? [])].some((k) => lit.startsWith(norm(k)));
  return (
    <div className={cn("tile rounded-[var(--radius-tile)] border border-line bg-panel-2 px-3 py-2.5", on && "tile-lit", className)}>
      <div className="text-[12px] text-muted">{label}</div>
      <div className={cn("num mt-0.5 font-semibold leading-tight", big ? "text-[26px]" : "text-[20px]",
        tone === "bull" && "text-bull", tone === "bear" && "text-bear", tone === "indigo" && "text-indigo",
        tone === "warn" && "text-saffron")}>{value}</div>
      {sub && <div className="mt-0.5 text-[12px] text-muted">{sub}</div>}
    </div>
  );
}

export function Cited({ text, sources }: { text: string; sources: string[] }) {
  const { setLit } = useContext(LitCtx);
  const parts = text.split(/(\[\d+\])/g);
  return (
    <p className="whitespace-pre-line font-serif text-[15px] leading-[1.6] text-ink">
      {parts.map((p, i) => {
        const m = p.match(/^\[(\d+)\]$/);
        if (!m) return <span key={i}>{p}</span>;
        const n = Number(m[1]);
        const fact = sources[n - 1];
        return (
          <button key={i} type="button" title={fact}
            onMouseEnter={() => fact && setLit(norm(fact))} onMouseLeave={() => setLit(null)}
            onFocus={() => fact && setLit(norm(fact))} onBlur={() => setLit(null)}
            className="mx-0.5 inline-flex h-[18px] min-w-[18px] -translate-y-px items-center justify-center rounded-[4px] bg-indigo-soft px-1 align-middle font-sans text-[11px] font-semibold text-indigo hover:bg-indigo hover:text-white dark:hover:text-[#0f1a2b]">
            {n}
          </button>
        );
      })}
    </p>
  );
}

export function LocalOnly({ children = "Local only" }: { children?: ReactNode }) {
  return (
    <span className="inline-flex h-5 items-center gap-1 rounded-[4px] border border-line bg-panel-2 px-1.5 text-[12px] font-medium text-muted">
      <Lock size={11} aria-hidden /> {children}
    </span>
  );
}

/** Explain / Show sources / Second opinion (and optional Accept), on the local model only.
 *  `run` replaces the default call (e.g. the Weekly Review's Generate review endpoint). */
export function LocalExplainPanel({ facts, section = "Journal", question, label = "Explain", run, onAccept, acceptLabel = "Accept", acceptDisabled, extra, onResult }: {
  facts: string[]; section?: "Journal" | "Tax"; question?: string; label?: string;
  run?: () => Promise<Explanation>; onAccept?: (text: string) => void; acceptLabel?: string; acceptDisabled?: boolean;
  extra?: ReactNode; onResult?: (e: Explanation) => void;
}) {
  const [showSources, setShowSources] = useState(false);
  const explain = useMutation({
    mutationFn: () => (run ? run() : post<Explanation>("/api/journal/explain", { facts, section, question })),
    onSuccess: (e) => onResult?.(e),
  });
  const out = explain.data;
  const second = useMutation({
    mutationFn: () => post<Explanation>("/api/journal/explain", { facts: out?.sources ?? facts, section, second_of: out?.text ?? "" }),
  });
  const sources = out?.sources?.length ? out.sources : facts;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary" size="sm" onClick={() => explain.mutate()} disabled={explain.isPending || !facts.length}>
          <Sparkles size={14} /> {explain.isPending ? "Working on the local model…" : label}
        </Button>
        <Button size="sm" onClick={() => setShowSources((s) => !s)} aria-pressed={showSources}>Show sources</Button>
        <Button size="sm" onClick={() => second.mutate()} disabled={!out || second.isPending}>
          <RotateCcw size={14} /> Second opinion
        </Button>
        {onAccept && (
          <Button size="sm" disabled={acceptDisabled ?? !out} onClick={() => onAccept(out?.text ?? "")}>{acceptLabel}</Button>
        )}
        {extra}
      </div>
      {explain.error && <p className="text-[13px] text-bear">{(explain.error as Error).message}</p>}
      {out && (
        <div className="drawer-enter rounded-[var(--radius-tile)] border border-line bg-panel p-3.5">
          {out.blocked && <p className="mb-2 text-[13px] text-saffron">Part of this answer was held back by the output filter.</p>}
          <Cited text={out.text} sources={sources} />
          <div className="mt-2 flex items-center gap-1.5 text-[12px] text-muted">
            <ShieldCheck size={13} />
            {out.where === "Fallback" ? "No local model connected: the lab's own numbers, listed" : `${out.where} model ${out.model}, nothing left this computer`}
          </div>
        </div>
      )}
      {second.data && (
        <div className="rounded-[var(--radius-tile)] border border-bear/40 bg-bear-soft/40 p-3.5">
          <div className="mb-1 text-[12px] font-medium text-muted">Second opinion</div>
          <Cited text={second.data.text} sources={second.data.sources} />
        </div>
      )}
      {showSources && (
        <ol className="num rounded-[var(--radius-tile)] border border-line bg-panel-2 p-3 text-[13px]">
          {sources.map((f, i) => <li key={i} className="py-0.5"><span className="mr-2 text-muted">{i + 1}</span>{f}</li>)}
        </ol>
      )}
    </div>
  );
}
