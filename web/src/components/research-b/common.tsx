/* Small pieces shared by Chart Helper, Earnings Desk and IPO Dashboard. */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { ChevronRight, FileUp, X } from "lucide-react";
import { cn } from "@/lib/cn";

/** A collapsible section (the classic page's expanders). */
export function Disclosure({ title, children, defaultOpen = false, hint }: {
  title: ReactNode; children: ReactNode; defaultOpen?: boolean; hint?: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="rounded-[var(--radius-panel)] border border-line bg-panel">
      <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-4 py-2.5 text-left">
        <ChevronRight size={15} className={cn("shrink-0 text-muted transition-transform", open && "rotate-90")} />
        <span className="text-[14px] font-semibold">{title}</span>
        {hint && <span className="ml-auto text-[12px] text-muted">{hint}</span>}
      </button>
      {open && <div className="border-t border-line p-4">{children}</div>}
    </section>
  );
}

/** Toggle chips for picking several items (multiselect). */
export function ChipPicker({ options, value, onChange, label }: {
  options: string[]; value: string[]; onChange: (v: string[]) => void; label: string;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-1.5">
      {options.map((o) => {
        const on = value.includes(o);
        return (
          <button key={o} type="button" aria-pressed={on}
            onClick={() => onChange(on ? value.filter((x) => x !== o) : [...value, o])}
            className={cn("h-7 rounded-[4px] border px-2.5 text-[13px]",
              on ? "border-indigo bg-indigo-soft font-medium text-indigo" : "border-line-strong text-muted hover:text-ink")}>
            {o}
          </button>
        );
      })}
    </div>
  );
}

/** A page citation such as "[p. 4]", shown as a chip. */
export function PageChip({ cite }: { cite: string }) {
  if (!cite) return <span className="text-muted">—</span>;
  return (
    <span className="num inline-flex h-5 items-center whitespace-nowrap rounded-[4px] border border-line-strong bg-panel-2 px-1.5 text-[12px] text-muted">
      {cite.replace(/^\[|\]$/g, "")}
    </span>
  );
}

/** Drop or pick a PDF; returns its bytes as base64. */
export function FileDrop({ file, onFile, label = "Drop the results PDF" }: {
  file: { name: string } | null; onFile: (f: { name: string; base64: string } | null) => void; label?: string;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const read = (f: File | undefined) => {
    if (!f) return;
    const r = new FileReader();
    r.onload = () => onFile({ name: f.name, base64: String(r.result).split(",")[1] ?? "" });
    r.readAsDataURL(f);
  };
  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); read(e.dataTransfer.files[0]); }}
      className={cn("flex min-h-[64px] items-center gap-3 rounded-[var(--radius-tile)] border border-dashed px-3.5 py-2.5",
        over ? "border-indigo bg-indigo-soft/50" : "border-line-strong")}
    >
      <FileUp size={18} className="shrink-0 text-muted" />
      {file ? (
        <>
          <span className="min-w-0 flex-1 truncate text-[14px]">{file.name}</span>
          <button type="button" aria-label="Remove file" className="text-muted hover:text-bear" onClick={() => onFile(null)}><X size={15} /></button>
        </>
      ) : (
        <span className="flex-1 text-[13px] text-muted">
          {label}, or{" "}
          <button type="button" className="font-medium text-indigo hover:underline" onClick={() => ref.current?.click()}>choose a file</button>
        </span>
      )}
      <input ref={ref} type="file" accept="application/pdf,.pdf" className="hidden" onChange={(e) => read(e.target.files?.[0])} />
    </div>
  );
}

/** Delay a fast-changing value (typing) before it drives a query. */
export function useDebounced<T>(value: T, ms = 350): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** Small label/value pairs for provenance and meta lines (instead of dotted strings). */
export function MetaList({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="flex flex-wrap gap-x-5 gap-y-1 text-[13px]">
      {items.map(([k, v]) => (
        <div key={k} className="flex gap-1.5"><dt className="text-muted">{k}</dt><dd className="num">{v}</dd></div>
      ))}
    </dl>
  );
}

export const errText = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** Reserve room while a query loads, so the page does not jump. */
export function Placeholder({ height = 120, children }: { height?: number; children?: ReactNode }) {
  return (
    <div style={{ minHeight: height }} className="flex items-center justify-center rounded-[var(--radius-tile)] bg-panel-2 text-[13px] text-muted">
      {children ?? "Loading…"}
    </div>
  );
}
