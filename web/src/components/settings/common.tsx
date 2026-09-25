/* Settings / Lessons / Home-wizard building blocks. Area-local; the shared kit stays untouched. */
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Copy, Check as CheckIcon, Download } from "lucide-react";
import { cn } from "@/lib/cn";
import { Button, Field, inputCls } from "@/components/ui";
import { useToast } from "@/components/kit";

export interface ScreenLinkT { slug: string; title: string; section: string }

export function ErrorLine({ error }: { error: unknown }) {
  if (!error) return null;
  return <p className="text-[13px] text-bear" role="alert">{(error as Error).message}</p>;
}

/** Filled dot = working, hollow = not set up (the book's legend). */
export function StatusDot({ on, label }: { on: boolean; label?: string }) {
  return (
    <span aria-label={label ?? (on ? "working" : "not set up")} title={label ?? (on ? "Working" : "Not set up")}
      className={cn("inline-block h-2.5 w-2.5 shrink-0 rounded-full border-2", on ? "border-bull bg-bull" : "border-line-strong bg-transparent")} />
  );
}

export function TextInput({ label, value, onChange, placeholder, type = "text", hint, className, autoComplete }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string; type?: string; hint?: string; className?: string; autoComplete?: string;
}) {
  return (
    <Field label={label} hint={hint}>
      <input type={type} className={cn(inputCls, "font-sans", className)} value={value} placeholder={placeholder}
        autoComplete={autoComplete ?? (type === "password" ? "off" : undefined)} spellCheck={false}
        onChange={(e) => onChange(e.target.value)} />
    </Field>
  );
}

export function Tick({ checked, onChange, children, hint, disabled }: { checked: boolean; onChange: (v: boolean) => void; children: ReactNode; hint?: ReactNode; disabled?: boolean }) {
  return (
    <label className={cn("flex items-start gap-2.5 py-1", disabled ? "opacity-60" : "cursor-pointer")}>
      <input type="checkbox" disabled={disabled} className="mt-[3px] h-4 w-4 shrink-0 accent-[var(--indigo)]" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span><span className="block">{children}</span>{hint && <span className="block text-[13px] text-muted">{hint}</span>}</span>
    </label>
  );
}

/** A link to another screen by slug (react-router). */
export function ScreenLink({ s, className }: { s: ScreenLinkT; className?: string }) {
  return (
    <Link to={`/${s.slug}`} className={cn("inline-flex h-7 items-center rounded-[6px] border border-line-strong bg-panel px-2.5 text-[13px] font-medium hover:border-indigo hover:text-indigo", className)}>
      Open {s.title}
    </Link>
  );
}

/** Copies text; the toast repeats the action. */
export function CopyButton({ text, label = "Copy", done, variant = "outline", size = "sm", disabled }: {
  text: string | (() => Promise<string>); label?: string; done?: string; variant?: "outline" | "primary" | "quiet"; size?: "sm" | "md"; disabled?: boolean;
}) {
  const toast = useToast();
  const [copied, setCopied] = useState(false);
  const run = async () => {
    try {
      const t = typeof text === "string" ? text : await text();
      await navigator.clipboard.writeText(t);
      setCopied(true); setTimeout(() => setCopied(false), 1800);
      toast(done ?? "Copied to the clipboard");
    } catch (e) {
      toast(`Could not copy: ${(e as Error).message.replace(/\.+$/, "")}. Select the text and copy it by hand.`, "danger");
    }
  };
  return (
    <Button variant={variant} size={size} onClick={run} disabled={disabled}>
      {copied ? <CheckIcon size={14} /> : <Copy size={14} />} {label}
    </Button>
  );
}

/** Save text as a file in the browser (Export log, Export workspace). */
export function saveFile(text: string, name: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function fetchText(path: string): Promise<string> {
  const r = await fetch(path);
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.detail ?? `${r.status} ${r.statusText}`);
  }
  return r.text();
}

export function DownloadButton({ path, name, type, label, done }: { path: string; name: string; type: string; label: string; done: string }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  return (
    <Button disabled={busy} onClick={async () => {
      setBusy(true);
      try { saveFile(await fetchText(path), name, type); toast(done); }
      catch (e) { toast((e as Error).message, "danger"); }
      finally { setBusy(false); }
    }}><Download size={14} /> {label}</Button>
  );
}

/* ------------------------------------------------------------ Fit check bar */
export interface Fit { model_gb: number; context_gb: number; used_gb: number; ram_gb: number; total_gb: number; share: number; colour: "green" | "amber" | "red"; facts: string[]; line: string }

const FIT_WORD = { green: "Fits", amber: "Tight", red: "Too big" } as const;
/** Model file + context scratchpad + already in use, against total RAM. An estimate. */
export function FitBar({ fit, label }: { fit: Fit; label?: ReactNode }) {
  const pct = (x: number) => `${Math.min(100, (x / Math.max(fit.ram_gb, fit.total_gb)) * 100)}%`;
  const tone = fit.colour === "green" ? "text-bull" : fit.colour === "amber" ? "text-saffron" : "text-bear";
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-baseline justify-between gap-2 text-[13px]">
        <span>{label}</span>
        <span className="num">
          <span className="font-semibold">{fit.total_gb.toFixed(1)} GB</span>
          <span className="text-muted"> of {fit.ram_gb.toFixed(0)} GB RAM, {Math.round(fit.share * 100)}%</span>
          <span className={cn("ml-2 font-medium", tone)}>{FIT_WORD[fit.colour]}</span>
        </span>
      </div>
      <div className="relative flex h-2.5 overflow-hidden rounded-full bg-panel-2 ring-1 ring-line" role="img"
        aria-label={`Fit check: ${fit.line}`}>
        <span className="h-full bg-indigo" style={{ width: pct(fit.model_gb) }} title={`Model file ${fit.model_gb.toFixed(1)} GB`} />
        <span className="h-full bg-indigo/55" style={{ width: pct(fit.context_gb) }} title={`Context scratchpad ${fit.context_gb.toFixed(2)} GB`} />
        <span className="h-full bg-muted/40" style={{ width: pct(fit.used_gb) }} title={`Already in use ${fit.used_gb.toFixed(1)} GB`} />
        <span className="absolute top-0 h-full w-px bg-ink/60" style={{ left: pct(0.8 * fit.ram_gb) }} title="80% of RAM" aria-hidden />
      </div>
      <div className="flex flex-wrap gap-x-4 text-[12px] text-muted num">
        <span><i className="mr-1 inline-block h-2 w-2 rounded-sm bg-indigo align-middle" />Model file {fit.model_gb.toFixed(1)} GB</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded-sm bg-indigo/55 align-middle" />Context scratchpad {fit.context_gb.toFixed(2)} GB</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded-sm bg-muted/40 align-middle" />Already in use {fit.used_gb.toFixed(1)} GB</span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ Pull model (server-sent events) */
export interface PullState { running: boolean; fraction: number; status: string; done?: string; error?: string }

/** Streams Ollama's pull progress from /api/wizard/pull. */
export function usePull(onDone?: (msg: string) => void) {
  const [st, setSt] = useState<PullState>({ running: false, fraction: 0, status: "" });
  const es = useRef<EventSource | null>(null);
  const doneRef = useRef(onDone);
  doneRef.current = onDone;
  useEffect(() => () => es.current?.close(), []);
  const start = useCallback((tag: string, setDefault = true) => {
    es.current?.close();
    setSt({ running: true, fraction: 0, status: `Pulling ${tag}…` });
    const src = new EventSource(`/api/wizard/pull?tag=${encodeURIComponent(tag)}&set_default=${setDefault}`);
    es.current = src;
    src.onmessage = (e) => {
      const p = JSON.parse(e.data) as { status: string; fraction: number };
      setSt((s) => ({ ...s, status: `${tag}: ${p.status}`, fraction: p.fraction || s.fraction }));
    };
    src.addEventListener("done", (e) => {
      const m = JSON.parse((e as MessageEvent).data).message as string;
      setSt({ running: false, fraction: 1, status: "", done: m }); src.close(); doneRef.current?.(m);
    });
    src.addEventListener("fail", (e) => {
      const m = JSON.parse((e as MessageEvent).data).message as string;
      setSt((s) => ({ ...s, running: false, error: m })); src.close();
    });
    src.onerror = () => {
      if (src.readyState === EventSource.CLOSED) return;
      src.close();
      setSt((s) => (s.running ? { ...s, running: false, error: "The connection to the lab dropped. Click Pull model again; it resumes." } : s));
    };
  }, []);
  return { ...st, start };
}

export function PullProgress({ st }: { st: PullState }) {
  if (!st.running && !st.error && !st.done) return null;
  return (
    <div className="flex flex-col gap-1.5" aria-live="polite">
      {(st.running || st.fraction > 0) && !st.error && (
        <>
          <div className="h-2 overflow-hidden rounded-full bg-panel-2 ring-1 ring-line">
            <div className="h-full bg-indigo transition-[width]" style={{ width: `${Math.round(st.fraction * 100)}%` }} />
          </div>
          <div className="num text-[13px] text-muted">{st.running ? `${st.status} ${Math.round(st.fraction * 100)}%` : ""}</div>
        </>
      )}
      {st.done && <p className="text-[13px] text-bull">{st.done}</p>}
      {st.error && <p className="text-[13px] text-bear" role="alert">{st.error}</p>}
    </div>
  );
}

/** Small "label: value" meta line without middle dots. */
export function Meta({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="flex flex-wrap gap-x-5 gap-y-1 text-[13px]">
      {items.map(([k, v]) => <div key={k} className="flex gap-1.5"><dt className="text-muted">{k}</dt><dd>{v}</dd></div>)}
    </dl>
  );
}
