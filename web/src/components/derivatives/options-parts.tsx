/* Options Strategy Builder parts: leg table, Add leg, IV panel, scenarios, attribution, margin. */
import { useState } from "react";
import { Plus, X } from "lucide-react";
import type { Market } from "@/lib/api";
import { money } from "@/lib/format";
import { cn } from "@/lib/cn";
import { Button, Field, inputCls } from "@/components/ui";
import { Badge, DataTable, Segmented, chartTokens, type Column } from "@/components/kit";
import { FactTile } from "@/components/facts";
import { Lines, NumberField, SignedBars, signTone } from "./common";

export type Kind = "call" | "put" | "stock";
export interface LegIn { kind: Kind; strike: number; side: "buy" | "sell"; qty: number; expiry: "weekly" | "monthly" }
export interface LegOut extends LegIn { premium: number; days: number; lot: number; iv: number; describe: string }

const KIND_LABEL: Record<Kind, string> = { call: "Call", put: "Put", stock: "Shares" };

function Seg<T extends string>({ value, options, onChange, label, tone }: {
  value: T; options: T[]; onChange: (v: T) => void; label: string; tone?: (v: T) => "bull" | "bear" | "ink";
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex overflow-hidden rounded-[6px] border border-line-strong">
      {options.map((o) => {
        const on = value === o;
        const t = tone ? tone(o) : "ink";
        return (
          <button key={o} role="radio" aria-checked={on} onClick={() => onChange(o)}
            className={cn("h-7 px-2.5 text-[13px] font-medium capitalize",
              on ? (t === "bull" ? "bg-bull text-white dark:text-[#0f1a2b]" : t === "bear" ? "bg-bear text-white dark:text-[#0f1a2b]" : "bg-ink text-panel")
                : "text-muted hover:text-ink")}>
            {KIND_LABEL[o as Kind] ?? o}
          </button>
        );
      })}
    </div>
  );
}
const sideTone = (s: string) => (s === "buy" ? "bull" : "bear") as "bull" | "bear";

/** The leg editor: one row per leg; Premium and Lot size come from the chain and the Contract Table. */
export function LegTable({ legs, priced, onChange, market, step }: {
  legs: LegIn[]; priced?: LegOut[]; onChange: (legs: LegIn[]) => void; market: Market; step: number;
}) {
  const set = (i: number, l: LegIn) => onChange(legs.map((x, j) => (j === i ? l : x)));
  return (
    <div className="flex flex-col">
      {legs.map((l, i) => {
        const p = priced?.[i];
        return (
          <div key={i} className="border-b border-line py-2.5 last:border-0">
            <div className="flex flex-wrap items-center gap-2">
              <Seg label="Side" value={l.side} options={["buy", "sell"]} tone={sideTone} onChange={(side) => set(i, { ...l, side })} />
              <Seg label="Type" value={l.kind} options={["call", "put", "stock"]} onChange={(kind) => set(i, { ...l, kind })} />
              <button onClick={() => onChange(legs.filter((_, j) => j !== i))} className="ml-auto rounded-[4px] p-1 text-muted hover:text-bear" aria-label={`Remove leg ${i + 1}`}><X size={15} /></button>
            </div>
            <div className="mt-2 grid grid-cols-[1fr_1fr_64px] gap-2">
              <label className="flex flex-col gap-0.5"><span className="text-[12px] text-muted">{l.kind === "stock" ? "Price" : "Strike"}</span>
                <input aria-label={`Strike leg ${i + 1}`} className={cn(inputCls, "h-8")} type="number" step={step} value={l.strike}
                  onChange={(e) => set(i, { ...l, strike: Number(e.target.value) })} /></label>
              <label className="flex flex-col gap-0.5"><span className="text-[12px] text-muted">Expiry</span>
                <select aria-label={`Expiry leg ${i + 1}`} className={cn(inputCls, "h-8")} value={l.expiry} disabled={l.kind === "stock"}
                  onChange={(e) => set(i, { ...l, expiry: e.target.value as LegIn["expiry"] })}>
                  <option value="weekly">Weekly</option><option value="monthly">Monthly</option>
                </select></label>
              <label className="flex flex-col gap-0.5"><span className="text-[12px] text-muted">{market === "IN" ? "Lots" : "Contracts"}</span>
                <input aria-label={`Lots leg ${i + 1}`} className={cn(inputCls, "h-8")} type="number" min={1} value={l.qty}
                  onChange={(e) => set(i, { ...l, qty: Math.max(1, Number(e.target.value) || 1) })} /></label>
            </div>
            <div className="num mt-1.5 flex gap-4 text-[12px] text-muted">
              <span>Premium <span className="text-ink">{p ? money(p.premium, market, 2) : "…"}</span></span>
              <span>{market === "IN" ? "Lot size" : "Multiplier"} <span className="text-ink">{p?.lot ?? "…"}</span></span>
              {p && l.kind !== "stock" && <span>IV <span className="text-ink">{(p.iv * 100).toFixed(1)}%</span></span>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** Add leg: strike, expiry, lots, then Buy / Sell, then Call / Put (or Shares) adds it. */
export function AddLeg({ spot, step, market, onAdd, onClose }: {
  spot: number; step: number; market: Market; onAdd: (l: LegIn) => void; onClose: () => void;
}) {
  const [strike, setStrike] = useState<number | null>(Math.round(spot / step) * step);
  const [expiry, setExpiry] = useState<LegIn["expiry"]>("weekly");
  const [qty, setQty] = useState<number | null>(1);
  const [side, setSide] = useState<LegIn["side"]>("buy");
  const add = (kind: Kind) => {
    onAdd({ kind, side, expiry, qty: Math.max(1, qty ?? 1), strike: kind === "stock" ? spot : strike ?? spot });
    onClose();
  };
  return (
    <div className="drawer-enter mt-3 rounded-[var(--radius-tile)] border border-line bg-panel-2 p-3">
      <div className="grid grid-cols-3 gap-2">
        <NumberField label="Strike" value={strike} step={step} onChange={setStrike} />
        <Field label="Expiry">
          <select className={inputCls} value={expiry} onChange={(e) => setExpiry(e.target.value as LegIn["expiry"])}>
            <option value="weekly">Weekly</option><option value="monthly">Monthly</option>
          </select>
        </Field>
        <NumberField label={market === "IN" ? "Lots" : "Contracts"} value={qty} min={1} onChange={setQty} />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Seg label="Side" value={side} options={["buy", "sell"]} tone={sideTone} onChange={setSide} />
        <span className="text-[13px] text-muted">then add a</span>
        <Button size="sm" onClick={() => add("call")}>Call</Button>
        <Button size="sm" onClick={() => add("put")}>Put</Button>
        <Button size="sm" variant="quiet" onClick={() => add("stock")}>Shares</Button>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- IV panel */
export interface IVData { symbol: string; iv: number; rank: number; percentile: number; low: number; high: number; window: number;
  below_days: number; source: string; dates: string[]; series: number[]; events: { date: string; text: string }[]; facts: string[] }

export function IVPanel({ d }: { d: IVData }) {
  const fmtDate = (s: string) => new Date(s + "T00:00:00").toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-3 gap-2">
        <FactTile label="IV today" value={`${d.iv.toFixed(1)}%`} />
        <FactTile label="IV rank" value={d.rank.toFixed(0)} />
        <FactTile label="IV percentile" value={d.percentile.toFixed(0)} />
      </div>
      <div>
        <div className="mb-1 flex justify-between text-[12px] text-muted"><span>IV rank gauge</span><span className="num">{d.rank.toFixed(0)} of 100</span></div>
        <div className="relative h-2 rounded-full bg-line" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={d.rank} aria-label="IV rank gauge">
          <div className="absolute inset-y-0 left-0 rounded-full bg-indigo" style={{ width: `${Math.min(100, Math.max(0, d.rank))}%` }} />
        </div>
        <div className="num mt-1 flex justify-between text-[12px] text-muted"><span>Low {d.low.toFixed(1)}%</span><span>High {d.high.toFixed(1)}%</span></div>
      </div>
      <Lines height={150} legend={false} yFormat={(v) => `${v.toFixed(0)}%`}
        series={[{ name: "IV %", data: d.dates.map((t, i) => [t, d.series[i]]), color: chartTokens().indigo }]}
        marks={d.events.map((e) => ({ x: e.date, label: "Event" }))} />
      <p className="text-[12px] text-muted">Series: {d.source}; window {d.window} sessions. Rank = (today − low) ÷ (high − low); percentile = share of earlier sessions below today.</p>
      <div>
        <div className="text-[13px] font-medium">Events</div>
        <ul className="mt-1 flex flex-col gap-0.5 text-[13px]">
          {d.events.map((e) => <li key={e.date} className="num"><span className="text-muted">{fmtDate(e.date)}</span> {e.text}</li>)}
        </ul>
        <p className="mt-1 text-[12px] text-muted">Check RBI or Fed, budget and heavyweight results dates before expiry in the Earnings Desk calendar.</p>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- attribution */
export interface Attribution { parts: Record<string, number>; actual: number; facts: string[] }

export function AttributionStrip({ a, market }: { a: Attribution; market: Market }) {
  const labels = [...Object.keys(a.parts), "Actual"];
  const values = [...Object.values(a.parts), a.actual];
  return (
    <div className="flex flex-col gap-3">
      <p className="text-[13px] text-muted">{a.facts[0]}</p>
      <SignedBars labels={labels} values={values} height={170} yFormat={(v) => money(v, market)} />
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
        {Object.entries(a.parts).map(([k, v]) => (
          <FactTile key={k} label={`${k} (from entry Greeks)`} value={money(v, market)} tone={v < 0 ? "bear" : v > 0 ? "bull" : undefined} />
        ))}
        <FactTile label="Actual (full repricing)" value={money(a.actual, market)} tone={a.actual < 0 ? "bear" : "bull"} />
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- stress table */
export interface StressRow extends Record<string, unknown> { label: string; spot: number; iv: number; days_left: number; pnl: number }

export function StressTable({ rows, market }: { rows: StressRow[]; market: Market }) {
  const cols: Column<StressRow>[] = [
    { key: "label", header: "Scenario" },
    { key: "spot", header: "Spot", align: "right", render: (r) => r.spot.toLocaleString(market === "IN" ? "en-IN" : "en-US", { maximumFractionDigits: 2 }) },
    { key: "iv", header: "IV", align: "right", render: (r) => `${(r.iv * 100).toFixed(0)}%` },
    { key: "days_left", header: "Days left", align: "right", render: (r) => String(r.days_left) },
    { key: "pnl", header: "P&L", align: "right", render: (r) => <span className={cn("whitespace-nowrap font-medium", r.pnl < 0 ? "text-bear" : "text-bull")}>{money(r.pnl, market)}</span> },
  ];
  return <DataTable rows={rows} columns={cols} rowKey={(r) => r.label} />;
}

/* ---------------------------------------------------------------- margin */
export interface MarginInfo { estimate: number | null; expiry_day: number | null; model: string; parts: Record<string, number>; facts: string[]; account: string }

const PART_LABEL: Record<string, string> = {
  span: "Scan loss (SPAN-style)", exposure: "Exposure add-on", premium_paid: "Premium paid", stock: "Shares",
  expiry_day_extra: "Expiry-day extra",
  spreads: "Spreads (max loss)", naked: "Naked short options",
};

export function MarginPanel({ m, single, market, tiles, account, onAccount }: {
  m: MarginInfo; single: boolean; market: Market; tiles: Record<string, string>; account: string; onAccount: (a: string) => void;
}) {
  if (m.estimate == null) return <p className="text-muted">No margin estimate for this position.</p>;
  const mainKey = Object.keys(tiles).find((k) => k.startsWith("Margin estimate"));
  const rows = Object.entries(m.parts).filter(([k, v]) => PART_LABEL[k] && v);
  return (
    <div className="flex flex-col gap-3">
      {market === "US" && (
        <Segmented label="Account type" value={account} onChange={onAccount}
          options={[{ value: "cash", label: "Cash account" }, { value: "margin", label: "Margin account" }]} />
      )}
      <div className="grid grid-cols-2 gap-2">
        {single && m.facts[0] && <FactTile label={m.facts[0].split(":")[0]} value={m.facts[0].split(": ").slice(1).join(": ")} />}
        {!single && mainKey && <div className="rounded-[var(--radius-tile)] border border-dashed border-line px-3 py-2.5 text-[12px] text-muted">{mainKey}<div className="num mt-0.5 text-[16px] font-semibold text-ink">{tiles[mainKey]}</div></div>}
        <FactTile label="Margin on expiry day" value={`≈ ${money(m.expiry_day, market)}`} />
      </div>
      <table className="w-full text-[13px]">
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k} className="border-b border-line last:border-0">
              <td className="py-1.5 text-muted">{PART_LABEL[k]}</td>
              <td className="num py-1.5 text-right">{money(v, market)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-[12px] text-muted">{m.model}. An estimate, not your broker's figure; drag Days left to 0 for the expiry-day figure.</p>
    </div>
  );
}

/* ---------------------------------------------------------------- scenario tiles */
export function ScenarioTiles({ tiles }: { tiles: Record<string, string> }) {
  return (
    <div className="grid grid-cols-2 gap-2">
      {Object.entries(tiles).map(([k, v]) => <FactTile key={k} label={k} value={v} tone={k.includes("P&L") || k === "Your scenario" ? (signTone(v) ?? "bull") : undefined} />)}
    </div>
  );
}

export function AddLegButton({ open, onClick }: { open: boolean; onClick: () => void }) {
  return <Button size="sm" variant={open ? "primary" : "outline"} onClick={onClick} aria-expanded={open}><Plus size={14} /> Add leg</Button>;
}

export function PendingBadge() { return <Badge tone="indigo">Pending</Badge>; }
