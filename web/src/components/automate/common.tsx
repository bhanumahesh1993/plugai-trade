/* Automate-area building blocks (Scheduler, News Pipeline, ML Lab, Agents, Plugins). */
import { useEffect, useState, type ReactNode } from "react";
import { Check as CheckIcon, X as XIcon } from "lucide-react";
import { cn } from "@/lib/cn";
import { Field, inputCls } from "@/components/ui";

/** A number input that keeps what you type (so "0." and "" work) and reports numbers. */
export function NumField({ label, value, onChange, step = "any", hint, min, max, className }: {
  label: string; value: number | null; onChange: (v: number | null) => void; step?: number | "any";
  hint?: string; min?: number; max?: number; className?: string;
}) {
  const [text, setText] = useState(value === null ? "" : String(value));
  useEffect(() => {
    const cur = text.trim() === "" ? null : Number(text);
    if (cur !== value) setText(value === null ? "" : String(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  return (
    <Field label={label} hint={hint}>
      <input className={cn(inputCls, className)} type="number" inputMode="decimal" step={step} min={min} max={max} value={text}
        onChange={(e) => {
          setText(e.target.value);
          const t = e.target.value.trim();
          onChange(t === "" || Number.isNaN(Number(t)) ? null : Number(t));
        }} />
    </Field>
  );
}

export function TextField({ label, value, onChange, hint, placeholder, className, type = "text" }: {
  label: string; value: string; onChange: (v: string) => void; hint?: string; placeholder?: string; className?: string; type?: string;
}) {
  return (
    <Field label={label} hint={hint}>
      <input type={type} className={cn(inputCls, "font-sans", className)} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
    </Field>
  );
}

export function Check({ checked, onChange, children, hint, disabled }: { checked: boolean; onChange: (v: boolean) => void; children: ReactNode; hint?: ReactNode; disabled?: boolean }) {
  return (
    <label className={cn("flex cursor-pointer items-start gap-2.5 py-1", disabled && "cursor-not-allowed opacity-60")}>
      <input type="checkbox" disabled={disabled} className="mt-[3px] h-4 w-4 shrink-0 accent-[var(--indigo)]" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="min-w-0"><span className="block">{children}</span>{hint && <span className="block text-[13px] text-muted">{hint}</span>}</span>
    </label>
  );
}

export function Radio({ name, checked, onChange, children, hint }: { name: string; checked: boolean; onChange: () => void; children: ReactNode; hint?: ReactNode }) {
  return (
    <label className="flex cursor-pointer items-start gap-2.5 py-1">
      <input type="radio" name={name} className="mt-[3px] h-4 w-4 shrink-0 accent-[var(--indigo)]" checked={checked} onChange={onChange} />
      <span className="min-w-0"><span className="block">{children}</span>{hint && <span className="block text-[13px] text-muted">{hint}</span>}</span>
    </label>
  );
}

export function ErrorLine({ error }: { error: unknown }) {
  if (!error) return null;
  return <p className="text-[13px] text-bear" role="alert">{(error as Error).message}</p>;
}

/** Small muted line under a control group. */
export function Note({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cn("text-[13px] leading-snug text-muted", className)}>{children}</p>;
}

/** A pass / fail mark for check lists (never used for P&L). */
export function OkMark({ ok }: { ok: boolean }) {
  return ok
    ? <CheckIcon size={15} className="shrink-0 text-bull" aria-label="passed" />
    : <XIcon size={15} className="shrink-0 text-bear" aria-label="failed" />;
}

/** "2026-09-25T18:26:39+00:00" → "2026-09-25 18:26". */
export const stamp = (s?: string | null) => (s ? s.slice(0, 16).replace("T", " ") : "");

/** Literal text from the engine: shell commands, file contents. Code, so monospace. */
export function Plain({ text, className }: { text: string; className?: string }) {
  return <pre className={cn("scroll-thin max-h-[360px] overflow-auto whitespace-pre-wrap break-all rounded-[var(--radius-tile)] border border-line bg-panel-2 p-3 font-mono text-[12px] leading-[1.55]", className)}>{text}</pre>;
}
