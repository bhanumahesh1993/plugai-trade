import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";
import { Sparkles, ShieldCheck, RotateCcw } from "lucide-react";
import { post, type Explanation } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button } from "./ui";

/* ------------------------------------------------------------------ lit tiles
 * The design's one memorable idea: every AI sentence cites numbered facts, and
 * hovering a citation lights the tile that fact came from.
 */
const LitCtx = createContext<{ lit: string | null; setLit: (k: string | null) => void }>({ lit: null, setLit: () => {} });

export function FactsProvider({ children }: { children: ReactNode }) {
  const [lit, setLit] = useState<string | null>(null);
  const v = useMemo(() => ({ lit, setLit }), [lit]);
  return <LitCtx.Provider value={v}>{children}</LitCtx.Provider>;
}

const keyOf = (fact: string) => fact.split(":")[0].trim().toLowerCase();

export function FactTile({ label, value, sub, tone, big }: {
  label: string; value: ReactNode; sub?: ReactNode; tone?: "bull" | "bear" | "indigo"; big?: boolean;
}) {
  const { lit } = useContext(LitCtx);
  const on = lit !== null && lit === label.toLowerCase();
  return (
    <div className={cn("tile rounded-[var(--radius-tile)] border border-line bg-panel-2 px-3 py-2.5", on && "tile-lit")}>
      <div className="text-[12px] text-muted">{label}</div>
      <div className={cn("num font-semibold leading-tight mt-0.5", big ? "text-[26px]" : "text-[20px]",
        tone === "bull" && "text-bull", tone === "bear" && "text-bear", tone === "indigo" && "text-indigo")}>{value}</div>
      {sub && <div className="text-[12px] text-muted mt-0.5">{sub}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ explain */
function Cited({ text, sources }: { text: string; sources: string[] }) {
  const { setLit } = useContext(LitCtx);
  const parts = text.split(/(\[\d+\])/g);
  return (
    <p className="font-serif text-[15px] leading-[1.6] text-ink whitespace-pre-line">
      {parts.map((p, i) => {
        const m = p.match(/^\[(\d+)\]$/);
        if (!m) return <span key={i}>{p}</span>;
        const n = Number(m[1]);
        const fact = sources[n - 1];
        return (
          <button
            key={i}
            type="button"
            onMouseEnter={() => fact && setLit(keyOf(fact))}
            onMouseLeave={() => setLit(null)}
            onFocus={() => fact && setLit(keyOf(fact))}
            onBlur={() => setLit(null)}
            title={fact}
            className="mx-0.5 inline-flex h-[18px] min-w-[18px] -translate-y-px items-center justify-center rounded-[4px] bg-indigo-soft px-1 font-sans text-[11px] font-semibold text-indigo align-middle hover:bg-indigo hover:text-white dark:hover:text-[#0f1a2b]"
          >
            {n}
          </button>
        );
      })}
    </p>
  );
}

export function ExplainPanel({ facts, section, question, onAccept }: {
  facts: string[]; section: string; question?: string; onAccept?: (text: string) => void;
}) {
  const [showSources, setShowSources] = useState(false);
  const explain = useMutation({ mutationFn: () => post<Explanation>("/api/explain", { facts, section, question }) });
  const second = useMutation({
    mutationFn: () => post<Explanation>("/api/explain", {
      facts, section,
      question: `Assume this answer is wrong and find the error. Check every claim against the facts:\n${explain.data?.text ?? ""}`,
    }),
  });
  const out = explain.data;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" size="sm" onClick={() => explain.mutate()} disabled={explain.isPending}>
          <Sparkles size={14} /> {explain.isPending ? "Explaining…" : "Explain"}
        </Button>
        <Button size="sm" onClick={() => setShowSources((s) => !s)}>Show sources</Button>
        <Button size="sm" onClick={() => second.mutate()} disabled={!out || second.isPending}>
          <RotateCcw size={14} /> Second opinion
        </Button>
        {onAccept && <Button size="sm" disabled={!out} onClick={() => out && onAccept(out.text)}>Accept</Button>}
      </div>
      {out && (
        <div className="drawer-enter rounded-[var(--radius-tile)] border border-line bg-panel p-3.5">
          <Cited text={out.text} sources={out.sources} />
          <div className="mt-2 flex items-center gap-1.5 text-[12px] text-muted">
            <ShieldCheck size={13} /> {out.where === "Fallback" ? "No model connected: the lab's own numbers, listed" : `${out.where} model ${out.model}`}
          </div>
        </div>
      )}
      {second.data && (
        <div className="rounded-[var(--radius-tile)] border border-bear/40 bg-bear-soft/40 p-3.5">
          <Cited text={second.data.text} sources={second.data.sources} />
        </div>
      )}
      {showSources && (
        <ol className="rounded-[var(--radius-tile)] border border-line bg-panel-2 p-3 text-[13px] num">
          {facts.map((f, i) => <li key={i} className="py-0.5"><span className="text-muted mr-2">{i + 1}</span>{f}</li>)}
        </ol>
      )}
    </div>
  );
}
