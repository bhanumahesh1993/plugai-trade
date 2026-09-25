/* Shared pieces for the Portfolio area (Portfolio Reviewer, Crypto Monitor, Forecast Journal).
 *
 * LocalExplainPanel mirrors the shared ExplainPanel but posts to /api/portfolio/explain, which
 * always runs on the local model (holdings, positions and forecasts are private). The shared
 * panel has no "sensitive" switch yet, so citation chips light tiles here through the DOM:
 * every tile carries data-fact="<text before the colon>" (see ApiTile).
 */
import { useRef, useState, type ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";
import { Sparkles, ShieldCheck, RotateCcw, Lock, Upload } from "lucide-react";
import { post, type Explanation } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button } from "@/components/ui";
import { FactTile } from "@/components/facts";

export interface ApiTileT { label: string; value: string | number; fact: string; sub?: string; tone?: "bull" | "bear" | "indigo" | null; big?: boolean }

const norm = (s: string) => s.split(":")[0].trim().toLowerCase();

/** Light the tiles a citation points at, within the nearest [data-facts-scope] (else the page). */
function light(fact: string | null, from?: HTMLElement) {
  document.querySelectorAll(".tile-lit").forEach((el) => el.classList.remove("tile-lit"));
  if (!fact) return;
  const key = norm(fact);
  const root: ParentNode = from?.closest("[data-facts-scope]") ?? document;
  root.querySelectorAll<HTMLElement>("[data-fact]").forEach((el) => {
    if ((el.dataset.fact ?? "").toLowerCase() === key) (el.querySelector(".tile") ?? el).classList.add("tile-lit");
  });
}

/** A FactTile from the API, tagged with the fact it answers for. */
export function ApiTile({ t, big }: { t: ApiTileT; big?: boolean }) {
  return (
    <div data-fact={t.fact.toLowerCase()} className="min-w-0">
      <FactTile label={t.label} value={t.value} sub={t.sub} tone={t.tone ?? undefined} big={big ?? t.big} />
    </div>
  );
}

export function TileGrid({ tiles, cols = 2 }: { tiles?: ApiTileT[]; cols?: 2 | 3 | 4 }) {
  if (!tiles?.length) return null;
  return (
    <div className={cn("grid gap-2.5", tiles.length === 1 ? "grid-cols-1" : {
      2: "grid-cols-2", 3: "grid-cols-2 md:grid-cols-3", 4: "grid-cols-2 md:grid-cols-4" }[cols])}>
      {tiles.map((t) => <ApiTile key={t.label} t={t} />)}
    </div>
  );
}

function Cited({ text, sources }: { text: string; sources: string[] }) {
  const parts = text.split(/(\[\d+\])/g);
  return (
    <p className="font-serif text-[15px] leading-[1.6] text-ink whitespace-pre-line">
      {parts.map((p, i) => {
        const m = p.match(/^\[(\d+)\]$/);
        if (!m) return <span key={i}>{p}</span>;
        const n = Number(m[1]);
        const fact = sources[n - 1];
        return (
          <button key={i} type="button" title={fact}
            onMouseEnter={(e) => fact && light(fact, e.currentTarget)} onMouseLeave={() => light(null)}
            onFocus={(e) => fact && light(fact, e.currentTarget)} onBlur={() => light(null)}
            className="mx-0.5 inline-flex h-[18px] min-w-[18px] -translate-y-px items-center justify-center rounded-[4px] bg-indigo-soft px-1 font-sans text-[11px] font-semibold text-indigo align-middle hover:bg-indigo hover:text-white dark:hover:text-[#0f1a2b]">
            {n}
          </button>
        );
      })}
    </p>
  );
}

/** Explain / Show sources / Second opinion (/ Accept), on the local model only. */
export function LocalExplainPanel({ facts, section = "Portfolio", question, onAccept, acceptLabel = "Accept" }: {
  facts: string[]; section?: string; question?: string; onAccept?: (text: string) => void; acceptLabel?: string;
}) {
  const [showSources, setShowSources] = useState(false);
  const explain = useMutation({ mutationFn: () => post<Explanation>("/api/portfolio/explain", { facts, section, question }) });
  const second = useMutation({
    mutationFn: () => post<Explanation>("/api/portfolio/explain", {
      facts, section,
      question: `Assume this answer is wrong and find the error. Check every claim against the facts:\n${explain.data?.text ?? ""}`,
    }),
  });
  const out = explain.data;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" size="sm" onClick={() => explain.mutate()} disabled={explain.isPending || !facts.length}>
          <Sparkles size={14} /> {explain.isPending ? "Explaining…" : "Explain"}
        </Button>
        <Button size="sm" onClick={() => setShowSources((s) => !s)} disabled={!facts.length}>Show sources</Button>
        <Button size="sm" onClick={() => second.mutate()} disabled={!out || second.isPending}>
          <RotateCcw size={14} /> Second opinion
        </Button>
        {onAccept && <Button size="sm" disabled={!out} onClick={() => out && onAccept(out.text)}>{acceptLabel}</Button>}
      </div>
      <p className="flex items-center gap-1.5 text-[12px] text-muted"><Lock size={12} /> Local model only: this data never goes to a cloud AI.</p>
      {explain.error && <p className="text-[13px] text-bear">{(explain.error as Error).message}</p>}
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
          {facts.map((f, i) => <li key={i} className="py-0.5"><span className="mr-2 text-muted">{i + 1}</span>{f}</li>)}
        </ol>
      )}
    </div>
  );
}

/** Read a chosen file in the browser as base64 (sent inside JSON; parsed on this computer). */
export function fileToB64(f: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",", 2)[1] ?? "");
    r.onerror = () => reject(new Error("The file could not be read. Choose it again."));
    r.readAsDataURL(f);
  });
}

/** A file picker that looks like the rest of the kit. */
export function FilePick({ accept, file, onFile, label = "Choose file" }: {
  accept: string; file: File | null; onFile: (f: File | null) => void; label?: string;
}) {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <div className="flex min-w-0 items-center gap-2">
      <input ref={ref} type="file" accept={accept} className="sr-only" aria-label={label}
        onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
      <Button size="sm" type="button" onClick={() => ref.current?.click()}><Upload size={14} /> {label}</Button>
      <span className="truncate text-[13px] text-muted">{file ? file.name : "No file chosen"}</span>
    </div>
  );
}

/** Download text as a file (Export CSV). */
export function download(name: string, text: string, type = "text/csv") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Right rail heading, same weight as the Options builder's. */
export function RailTitle({ children }: { children: ReactNode }) {
  return <h2 className="text-[14px] font-semibold">{children}</h2>;
}

export const errText = (e: unknown) => (e instanceof Error ? e.message : String(e ?? ""));

export function NumInput({ value, onChange, step, min, max, id, className }: {
  value: number | ""; onChange: (v: number) => void; step?: number; min?: number; max?: number; id?: string; className?: string;
}) {
  return (
    <input id={id} type="number" value={value} step={step} min={min} max={max}
      onChange={(e) => onChange(e.target.value === "" ? 0 : Number(e.target.value))}
      className={cn("h-9 w-full rounded-[6px] border border-line-strong bg-panel px-2.5 text-[14px] text-ink num outline-none focus:border-indigo", className)} />
  );
}
