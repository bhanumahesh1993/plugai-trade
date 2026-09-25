import * as TabsPrimitive from "@radix-ui/react-tabs";
import * as SliderPrimitive from "@radix-ui/react-slider";
import * as ToggleGroup from "@radix-ui/react-toggle-group";
import { forwardRef, type ButtonHTMLAttributes, type HTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import type { Market } from "@/lib/api";

type Variant = "primary" | "quiet" | "outline" | "danger";

export const Button = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" }>(
  ({ className, variant = "outline", size = "md", ...props }, ref) => (
    <button
      ref={ref}
      className={cn(
        "inline-flex items-center justify-center gap-1.5 rounded-[6px] font-medium whitespace-nowrap select-none",
        "disabled:opacity-45 disabled:pointer-events-none",
        size === "sm" ? "h-7 px-2.5 text-[13px]" : "h-9 px-3.5 text-[14px]",
        variant === "primary" && "bg-indigo text-white hover:brightness-110 dark:text-[#0f1a2b]",
        variant === "outline" && "border border-line-strong bg-panel text-ink hover:border-indigo hover:text-indigo",
        variant === "quiet" && "text-muted hover:text-ink hover:bg-panel-2",
        variant === "danger" && "border border-bear/60 text-bear bg-panel hover:bg-bear-soft",
        className,
      )}
      {...props}
    />
  ),
);
Button.displayName = "Button";

/** Panels are the page's structure; tiles (FactTile) are the data. Different radius on purpose. */
export function Panel({ title, action, className, children, ...rest }: Omit<HTMLAttributes<HTMLElement>, "title"> & { title?: ReactNode; action?: ReactNode }) {
  return (
    <section className={cn("rounded-[var(--radius-panel)] border border-line bg-panel", className)} {...rest}>
      {(title || action) && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
          <h2 className="text-[14px] font-semibold text-ink">{title}</h2>
          {action}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function MarketSwitch({ value, onChange }: { value: Market; onChange: (m: Market) => void }) {
  return (
    <ToggleGroup.Root
      type="single"
      value={value}
      onValueChange={(v) => v && onChange(v as Market)}
      className="inline-flex rounded-[6px] border border-line-strong p-0.5 bg-panel"
      aria-label="Market"
    >
      {(["IN", "US"] as Market[]).map((m) => (
        <ToggleGroup.Item
          key={m}
          value={m}
          className={cn(
            "h-7 px-3 rounded-[4px] text-[13px] font-semibold text-muted",
            m === "IN" ? "data-[state=on]:bg-saffron" : "data-[state=on]:bg-navy",
            "data-[state=on]:text-white dark:data-[state=on]:text-[#0f1a2b]",
          )}
        >
          {m === "IN" ? "India" : "US"}
        </ToggleGroup.Item>
      ))}
    </ToggleGroup.Root>
  );
}

export function MarketChip({ m }: { m: Market }) {
  return (
    <span className={cn("inline-flex h-5 items-center rounded-[4px] px-1.5 text-[11px] font-semibold text-white dark:text-[#0f1a2b]",
      m === "IN" ? "bg-saffron" : "bg-navy")}>{m}</span>
  );
}

export const Tabs = TabsPrimitive.Root;
export function TabList({ children }: { children: ReactNode }) {
  return <TabsPrimitive.List className="flex gap-1 border-b border-line">{children}</TabsPrimitive.List>;
}
export function Tab({ value, children }: { value: string; children: ReactNode }) {
  return (
    <TabsPrimitive.Trigger
      value={value}
      className="relative -mb-px h-9 px-3 text-[14px] text-muted hover:text-ink data-[state=active]:text-ink data-[state=active]:font-medium data-[state=active]:border-b-2 data-[state=active]:border-indigo"
    >
      {children}
    </TabsPrimitive.Trigger>
  );
}
export const TabPanel = TabsPrimitive.Content;

export function Slider({ value, min, max, step = 1, onChange, label }: { value: number; min: number; max: number; step?: number; onChange: (v: number) => void; label: string }) {
  return (
    <SliderPrimitive.Root
      className="relative flex h-5 w-full touch-none items-center select-none"
      value={[value]} min={min} max={max} step={step} onValueChange={(v) => onChange(v[0])} aria-label={label}
    >
      <SliderPrimitive.Track className="relative h-1 grow rounded-full bg-line-strong">
        <SliderPrimitive.Range className="absolute h-full rounded-full bg-indigo" />
      </SliderPrimitive.Track>
      <SliderPrimitive.Thumb className="block h-4 w-4 rounded-full border-2 border-indigo bg-panel" />
    </SliderPrimitive.Root>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[12px] text-muted">{label}</span>
      {children}
      {hint && <span className="text-[12px] text-muted">{hint}</span>}
    </label>
  );
}

export const inputCls =
  "h-9 w-full rounded-[6px] border border-line-strong bg-panel px-2.5 text-[14px] text-ink num outline-none focus:border-indigo";
