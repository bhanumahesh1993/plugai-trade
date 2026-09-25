/* Small building blocks shared by the Research screens (Briefing, Document Desk, Screener, Score-Tester). */
import { useState, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/cn";

/** Error text from a failed query or mutation, in plain English. */
export function ErrorLine({ error }: { error: unknown }) {
  if (!error) return null;
  return <p role="alert" className="text-[14px] text-bear">{(error as Error).message}</p>;
}

/** A quiet disclosure (the classic page's expanders). */
export function Disclosure({ title, children, defaultOpen = false, className }: {
  title: ReactNode; children: ReactNode; defaultOpen?: boolean; className?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={cn("rounded-[var(--radius-tile)] border border-line", className)}>
      <button type="button" aria-expanded={open} onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-[14px] font-medium hover:bg-panel-2">
        <ChevronRight size={15} className={cn("shrink-0 text-muted transition-transform", open && "rotate-90")} />
        {title}
      </button>
      {open && <div className="border-t border-line p-3">{children}</div>}
    </div>
  );
}

/** Multi-select as toggle chips (delivery channels, triage filter). */
export function ChipToggle<T extends string>({ options, value, onChange, label }: {
  options: readonly T[]; value: T[]; onChange: (v: T[]) => void; label: string;
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

/** Read a dropped or chosen file. */
export function readFile(f: File, as: "text" | "dataurl"): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result));
    r.onerror = () => reject(new Error(`Could not read ${f.name}.`));
    if (as === "text") r.readAsText(f); else r.readAsDataURL(f);
  });
}

/** Save text as a file (Export CSV). */
export function download(text: string, filename: string, type = "text/csv") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** A caption under a control group. */
export function Hint({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cn("text-[13px] text-muted", className)}>{children}</p>;
}
