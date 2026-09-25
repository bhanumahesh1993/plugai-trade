/* Futures & Roll tabs: Contract, Basis, Roll calendar, Margin & MTM (Chapter 24). */
import { useEffect, useState } from "react";
import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { get, post, type Market } from "@/lib/api";
import { money, num } from "@/lib/format";
import { cn } from "@/lib/cn";
import { Button, Field, Panel, Slider } from "@/components/ui";
import { Badge, Callout, DataTable, EmptyState, Hypothetical, Segmented, Select, chartTokens, useToast, type Column } from "@/components/kit";
import { FactTile } from "@/components/facts";
import { Lines, NumberField, SignedBars, signTone } from "./common";

export interface Choices { market: Market; default: string; contracts: string[]; basis: string[]; roll: string[]; margin: string[]; as_of: string }
type OnFacts = (facts: string[]) => void;
const signed = (x: number, d = 2) => `${x >= 0 ? "+" : "−"}${Math.abs(x).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d })}`;
const pctS = (x: number) => `${signed(x)}%`;

/* ================================================================== Contract */
interface SpecRow extends Record<string, unknown> { symbol: string; contract: string; exchange: string; multiplier_text: string; unit: string; settlement: string; expiry: string; source: string; pending: boolean }
interface OIRow extends Record<string, unknown> { contract: string; price_change_pct: number; oi_change_near_pct: number; oi_change_next_pct: number; label: string; roll_check: string }
interface ContractsOut { rows: SpecRow[]; oi: OIRow[]; facts: string[]; mcx: string[] }
interface SplitOut { tiles: Record<string, string>; facts: string[]; units: number }

export function ContractTab({ market, choices, onFacts }: { market: Market; choices: Choices; onFacts: OnFacts }) {
  const [lists, setLists] = useState<Record<Market, string[]>>({ IN: ["NIFTY"], US: ["MES"] });
  const names = lists[market];
  const avail = choices.contracts.filter((c) => !names.includes(c));
  const [pick, setPick] = useState("");
  const chosen = avail.includes(pick) ? pick : avail[0] ?? "";
  const setNames = (n: string[]) => setLists((l) => ({ ...l, [market]: n }));
  const { data, error } = useQuery({
    queryKey: ["fut-contracts", market, names],
    queryFn: () => post<ContractsOut>("/api/derivatives/contracts", { market, symbols: names }),
    placeholderData: keepPreviousData,
  });
  const [splitOn, setSplitOn] = useState(false);
  const [sp, setSp] = useState({ b0: 70 as number | null, b1: 70 as number | null, f0: 88 as number | null, f1: 88.8 as number | null });
  const mcx = data?.mcx[0];
  const split = useQuery({
    queryKey: ["fut-split", mcx, sp],
    queryFn: () => post<SplitOut>("/api/derivatives/usdinr-split", { symbol: mcx, bench_from: sp.b0 ?? 0, bench_to: sp.b1 ?? 0, fx_from: sp.f0 ?? 0, fx_to: sp.f1 ?? 0 }),
    enabled: market === "IN" && splitOn && !!mcx, placeholderData: keepPreviousData,
  });
  useEffect(() => { onFacts([...(data?.facts ?? []), ...(market === "IN" && splitOn && mcx ? split.data?.facts ?? [] : [])]); },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data, split.data, splitOn, mcx, market]);

  const specCols: Column<SpecRow>[] = [
    { key: "contract", header: "Contract", render: (r) => <span className="font-medium">{r.contract}</span> },
    { key: "exchange", header: "Exchange" },
    { key: "multiplier_text", header: "Lot / multiplier", align: "right" },
    { key: "unit", header: "Unit" },
    { key: "settlement", header: "Settlement", render: (r) => <span className="capitalize">{r.settlement || "—"}</span> },
    { key: "expiry", header: "Expiry" },
    { key: "source", header: "Source", render: (r) => r.pending ? <Badge tone="warn">† pending reference row</Badge> : <span className="text-[13px] text-muted">{r.source}</span> },
    { key: "x", header: "", render: (r) => names.length > 1 ? (
      <button aria-label={`Remove ${r.symbol}`} className="text-muted hover:text-bear" onClick={() => setNames(names.filter((n) => n !== r.symbol))}><X size={14} /></button>) : null },
  ];
  const oiCols: Column<OIRow>[] = [
    { key: "contract", header: "Contract" },
    { key: "price_change_pct", header: "Price change", align: "right", render: (r) => <span className={r.price_change_pct >= 0 ? "text-bull" : "text-bear"}>{pctS(r.price_change_pct)}</span> },
    { key: "oi_change_near_pct", header: "Near OI", align: "right", render: (r) => pctS(r.oi_change_near_pct) },
    { key: "oi_change_next_pct", header: "Next OI", align: "right", render: (r) => pctS(r.oi_change_next_pct) },
    { key: "label", header: "Label", render: (r) => <Badge>{r.label}</Badge> },
    { key: "roll_check", header: "Roll check", render: (r) => <span className="text-[13px]">{r.roll_check}</span> },
  ];
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Contract">
          <Select className="w-48" value={chosen} onChange={(e) => setPick(e.target.value)} disabled={!avail.length}>
            {avail.map((c) => <option key={c} value={c}>{c} FUT</option>)}
          </Select>
        </Field>
        <Button onClick={() => chosen && setNames([...names, chosen])} disabled={!chosen}><Plus size={14} /> Add contract</Button>
        {market === "IN" && (
          <Button variant={splitOn ? "primary" : "outline"} onClick={() => setSplitOn((s) => !s)} disabled={!mcx}
            title={mcx ? undefined : "Add an MCX contract (for example CRUDEOIL) first."}>USDINR split</Button>
        )}
        {market === "IN" && !mcx && <span className="pb-2 text-[13px] text-muted">Add an MCX contract (for example CRUDEOIL) to use the USDINR split.</span>}
      </div>
      {error && <Callout tone="danger" title="Could not load the contract">{(error as Error).message}</Callout>}
      <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
        {data?.rows.map((r, i) => <FactTile key={r.symbol} label={r.symbol} big={i === 0} value={r.multiplier_text} sub={`per ${r.unit}, ${r.settlement}-settled`} />)}
      </div>
      <Panel title="Contract specs">
        <DataTable rows={data?.rows ?? []} columns={specCols} rowKey={(r) => r.symbol} />
      </Panel>
      <Panel title="OI build-up" action={<Hypothetical />}>
        <DataTable rows={data?.oi ?? []} columns={oiCols} rowKey={(r) => r.contract} />
        <p className="mt-3 text-[13px] text-muted">Labels describe one day's activity (synthetic OI); they are not signals. Near month falling while next month rises usually means a roll.</p>
      </Panel>
      {market === "IN" && splitOn && mcx && (
        <Panel title={`USDINR split: ${mcx}`}>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <NumberField label="Benchmark yesterday ($)" value={sp.b0} step={0.5} onChange={(v) => setSp({ ...sp, b0: v })} />
            <NumberField label="Benchmark today ($)" value={sp.b1} step={0.5} onChange={(v) => setSp({ ...sp, b1: v })} />
            <NumberField label="USDINR yesterday" value={sp.f0} step={0.01} onChange={(v) => setSp({ ...sp, f0: v })} />
            <NumberField label="USDINR today" value={sp.f1} step={0.01} onChange={(v) => setSp({ ...sp, f1: v })} />
          </div>
          {split.error && <p className="mt-3 text-[13px] text-bear">{(split.error as Error).message}</p>}
          <div className="mt-4 grid grid-cols-1 gap-2.5 md:grid-cols-3">
            {split.data && Object.entries(split.data.tiles).map(([k, v]) => (
              <FactTile key={k} label={k} value={v} tone={k.includes("part") ? signTone(v) ?? (v === "₹0" ? undefined : "bull") : undefined} />
            ))}
          </div>
          <p className="mt-3 text-[13px] text-muted">Computed in code. Import duty and local premium sit in real MCX prices too.</p>
        </Panel>
      )}
    </div>
  );
}

/* ================================================================== Basis */
interface BasisRow { date: string; days_left: number; spot: number; futures: number; basis: number; fair_basis: number }
interface FairRow extends Record<string, unknown> { expiry: string; days: number; spot: number; fair_value: number; fair_basis: number }
interface BasisOut { series: BasisRow[]; label: string; yesterday: BasisRow; fair: FairRow[]; facts: string[] }

export function BasisTab({ market, choices, onFacts }: { market: Market; choices: Choices; onFacts: OnFacts }) {
  const [sym, setSym] = useState<Record<Market, string>>({ IN: "NIFTY", US: "SPY" });
  const [rate, setRate] = useState<Record<Market, number | null>>({ IN: 6.5, US: 4.0 });
  const [div, setDiv] = useState<number | null>(1.3);
  const symbol = choices.basis.includes(sym[market]) ? sym[market] : choices.basis[0];
  const { data, error } = useQuery({
    queryKey: ["fut-basis", market, symbol, rate[market], div],
    queryFn: () => post<BasisOut>("/api/derivatives/basis", { symbol, market, rate_pct: rate[market] ?? 0, dividend_pct: div ?? 0 }),
    placeholderData: keepPreviousData,
  });
  useEffect(() => { onFacts(data?.facts ?? []); }, [data, onFacts]);
  const t = chartTokens();
  const cols: Column<FairRow>[] = [
    { key: "expiry", header: "Expiry" }, { key: "days", header: "Days", align: "right" },
    { key: "spot", header: "Spot", align: "right", render: (r) => num(r.spot, market) },
    { key: "fair_value", header: "Fair value", align: "right", render: (r) => num(r.fair_value, market) },
    { key: "fair_basis", header: "Fair basis", align: "right", render: (r) => signed(r.fair_basis) },
  ];
  const y = data?.yesterday;
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Index">
          <Select className="w-40" value={symbol} onChange={(e) => setSym({ ...sym, [market]: e.target.value })}>
            {choices.basis.map((c) => <option key={c}>{c}</option>)}
          </Select>
        </Field>
        <NumberField className="w-36" label="Interest rate %" value={rate[market]} step={0.1} onChange={(v) => setRate({ ...rate, [market]: v })} />
        <NumberField className="w-36" label="Dividend yield %" value={div} step={0.1} onChange={setDiv} />
      </div>
      {error && <Callout tone="danger" title="Could not build the basis series">{(error as Error).message}</Callout>}
      <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
        <FactTile big label="Basis yesterday" value={y ? `${signed(y.basis, 1)} pts` : "…"} />
        <FactTile label="Fair basis yesterday" value={y ? `${signed(y.fair_basis, 1)} pts` : "…"} />
        <FactTile label="Latest basis reading" value={<span className="text-[17px]">{data ? data.label[0].toUpperCase() + data.label.slice(1) : "…"}</span>} sub="a description, not a signal" />
        {data?.fair[0] && <FactTile label={data.fair[0].expiry} value={num(data.fair[0].fair_value, market)} sub={`fair value, ${data.fair[0].days} days`} />}
      </div>
      <Panel title="Spot and futures" action={<Hypothetical />}>
        {data && <Lines height={220} series={[
          { name: "Spot", data: data.series.map((r) => [r.date, r.spot]), color: t.muted },
          { name: "Futures", data: data.series.map((r) => [r.date, r.futures]), color: t.indigo },
        ]} />}
        {data && <Lines height={170} yFormat={(v) => `${v.toFixed(0)}`} series={[
          { name: "Basis (pts)", data: data.series.map((r) => [r.date, r.basis]), color: t.indigo },
          { name: "Fair basis", data: data.series.map((r) => [r.date, r.fair_basis]), color: t.muted, dashed: true },
        ]} />}
        {data && y && <p className="mt-2 text-[13px] text-muted">Synthetic convergence; fair basis = spot × ({(rate[market] ?? 0).toFixed(1)}% − {(div ?? 0).toFixed(1)}%) × days left ÷ 365. Yesterday: basis {y.basis.toFixed(1)} vs fair {y.fair_basis.toFixed(1)}, {data.label} (a description, not a signal).</p>}
      </Panel>
      <Panel title="Fair value by expiry">
        <DataTable rows={data?.fair ?? []} columns={cols} rowKey={(r) => r.expiry} />
      </Panel>
    </div>
  );
}

/* ================================================================== Roll calendar */
const COST_LABEL: Record<string, string> = {
  stt: "STT", gst: "GST", sebi: "SEBI fee", dp: "DP charge", exchange: "Exchange charges", stamp: "Stamp duty",
  brokerage: "Brokerage", slippage: "Slippage", total: "Total", commission: "Commission", regulatory: "Regulatory fees",
  exchange_fees: "Exchange fees", nfa: "NFA fee",
};
interface CalRow extends Record<string, unknown> { contract: string; expiry: string; window: string; window_from: string; window_to: string }
interface RollOut {
  calendar: CalRow[]; defaults: { spot: number; near: number; next: number }; inputs: { spot: number; near: number; next: number; slippage: number };
  spread: number; fair_spread: number; costs: Record<string, number>; series: { date: string; contract: string; joined: number; adjusted: number; roll: boolean }[];
  roll_dates: string[]; facts: string[];
}

export function RollTab({ market, choices, onFacts }: { market: Market; choices: Choices; onFacts: OnFacts }) {
  const toast = useToast();
  const [sym, setSym] = useState<Record<Market, string>>({ IN: "NIFTY", US: "MES" });
  const symbol = choices.roll.includes(sym[market]) ? sym[market] : choices.roll[0];
  const [before, setBefore] = useState(5);
  const [px, setPx] = useState<{ spot: number | null; near: number | null; next: number | null }>({ spot: null, near: null, next: null });
  const [slip, setSlip] = useState<number | null>(0);
  useEffect(() => setPx({ spot: null, near: null, next: null }), [symbol, before, market]);
  const { data, error } = useQuery({
    queryKey: ["fut-roll", market, symbol, before, px, slip],
    queryFn: () => post<RollOut>("/api/derivatives/roll", { symbol, market, before, ...px, slippage: slip ?? 0 }),
    placeholderData: keepPreviousData,
  });
  useEffect(() => { onFacts(data?.facts ?? []); }, [data, onFacts]);
  const alert = useMutation({
    mutationFn: () => post<{ date: string; contract: string }>("/api/derivatives/roll/alert", { symbol, market, before }),
    onSuccess: (r) => toast(`Roll alert set for ${r.date} in Paper Trading, Alerts (SIMULATED)`),
    onError: (e) => toast((e as Error).message, "danger"),
  });
  const trend = useMutation({
    mutationFn: () => post<{ rows: number; roll_dates: string[] }>("/api/derivatives/roll/trend-lab", { symbol, market, before }),
    onSuccess: (r) => toast(`Sent to Trend Lab: back-adjusted series (${r.rows} sessions) and ${r.roll_dates.length} roll dates`),
    onError: (e) => toast((e as Error).message, "danger"),
  });
  const t = chartTokens();
  const calCols: Column<CalRow>[] = [
    { key: "contract", header: "Contract" }, { key: "expiry", header: "Expiry / last trading day" }, { key: "window", header: "Roll window" },
  ];
  const costRows = data ? Object.entries(data.costs).map(([k, v]) => ({ item: k, amount: v })) : [];
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end gap-5">
        <Field label="Contract">
          <Select className="w-40" value={symbol} onChange={(e) => setSym({ ...sym, [market]: e.target.value })}>
            {choices.roll.map((c) => <option key={c} value={c}>{c} FUT</option>)}
          </Select>
        </Field>
        <div className="min-w-[280px] flex-1">
          <div className="mb-1 flex justify-between text-[12px] text-muted"><span>Roll window opens (sessions before expiry)</span><span className="num font-medium text-ink">{before}</span></div>
          <Slider label="Roll window opens (sessions before expiry)" min={1} max={10} value={before} onChange={setBefore} />
        </div>
      </div>
      {error && <Callout tone="danger" title="Could not build the roll calendar">{(error as Error).message}</Callout>}
      <Panel title="Roll calendar">
        <DataTable rows={data?.calendar ?? []} columns={calCols} rowKey={(r) => r.expiry} />
        <p className="mt-3 text-[13px] text-muted">India: last Tuesday of the month; US micros: third Friday of Mar, Jun, Sep and Dec. Holiday shifts apply when the reference tables carry a holiday list.</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button variant="primary" onClick={() => alert.mutate()} disabled={alert.isPending}>Set roll alert</Button>
          <Button onClick={() => trend.mutate()} disabled={trend.isPending}>Send to Trend Lab</Button>
        </div>
      </Panel>
      <Panel title="Roll cost">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <NumberField label="Spot" value={px.spot} placeholder={data ? String(data.defaults.spot) : ""} onChange={(v) => setPx({ ...px, spot: v })} />
          <NumberField label="Near price" value={px.near} placeholder={data ? String(data.defaults.near) : ""} onChange={(v) => setPx({ ...px, near: v })} />
          <NumberField label="Next price" value={px.next} placeholder={data ? String(data.defaults.next) : ""} onChange={(v) => setPx({ ...px, next: v })} />
          <NumberField label="Slippage (pts per leg)" value={slip} step={0.25} onChange={setSlip} />
        </div>
        <div className="mt-4 grid grid-cols-1 gap-2.5 md:grid-cols-3">
          <FactTile big label="Roll round-trip cost" value={data ? money(data.costs.total, market, 2) : "…"} tone="bear" />
          <FactTile label="Calendar spread" value={data ? `${signed(data.spread)} pts` : "…"} sub="not a fee" />
          <FactTile label="Fair spread from carry" value={data ? `${signed(data.fair_spread)} pts` : "…"} />
        </div>
        <table className="mt-4 w-full text-[14px]">
          <tbody>
            {costRows.map((r) => (
              <tr key={r.item} className={cn("border-b border-line last:border-0", r.item === "total" && "font-semibold")}>
                <td className="py-1.5">{COST_LABEL[r.item] ?? r.item[0].toUpperCase() + r.item.slice(1).replace(/_/g, " ")}</td>
                <td className="num py-1.5 text-right">{money(r.amount, market, 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
      <Panel title="Joined and back-adjusted series" action={<Hypothetical />}>
        {data && <Lines height={240} series={[
          { name: "Joined end to end", data: data.series.map((r) => [r.date, r.joined]), color: t.muted },
          { name: "Back-adjusted", data: data.series.map((r) => [r.date, r.adjusted]), color: t.indigo },
        ]} marks={data.roll_dates.map((d) => ({ x: d, label: "Roll" }))} />}
        <p className="mt-2 text-[13px] text-muted">Joined end to end vs back-adjusted (difference method): the adjusted line has no roll-day jump for a trend rule to mistake for a move.</p>
      </Panel>
    </div>
  );
}

/* ================================================================== Margin & MTM */
interface Defaults { symbol: string; entry: number; cash: number; initial: number; maintenance: number; margin_pct: number; has_book: boolean; multiplier: number; unit: string; source: string; pending: boolean; as_of: string }
interface LedgerRow extends Record<string, unknown> { day: number; settle: number; change: number; mtm: number; cash: number; margin_required: number; free_cash: number; status: string }
interface MarginOut {
  symbol: string; position_tiles: Record<string, string>; facts: string[]; replayed: boolean; path?: string; sessions?: number; day?: number;
  rows?: LedgerRow[]; tiles?: Record<string, string>; free_cash?: number; mtm_today?: number; call_price?: number; call_price_text?: string;
  shock?: { label: string; value: string; shortfall: number; price: number; tiles: Record<string, string>; facts: string[] };
}
interface Form { entry: number | null; cash: number | null; qty: number | null; side: "long" | "short"; pct: number | null; initial: number | null; maint: number | null; path: "book" | "synthetic" }

export function MarginTab({ market, choices, onFacts, onPlan }: { market: Market; choices: Choices; onFacts: OnFacts; onPlan: (p: { symbol: string; entry: number; qty: number; side: string; call_price?: number }) => void }) {
  const [sym, setSym] = useState<Record<Market, string>>({ IN: "NIFTY", US: "MES" });
  const symbol = choices.margin.includes(sym[market]) ? sym[market] : choices.margin[0];
  const defs = useQuery({
    queryKey: ["fut-mdef", market, symbol],
    queryFn: () => get<Defaults>(`/api/derivatives/margin/defaults?symbol=${symbol}&market=${market}`),
  });
  const [f, setF] = useState<Form | null>(null);
  const [replay, setReplay] = useState(false);
  const [day, setDay] = useState<number | null>(null);
  const [shockIn, setShockIn] = useState<number | null>(-3);
  const [shock, setShock] = useState<number | null>(null);
  useEffect(() => {
    const d = defs.data;
    if (!d) return;
    setF({ entry: d.entry, cash: d.cash, qty: 1, side: "long", pct: d.margin_pct, initial: d.initial, maint: d.maintenance, path: d.has_book ? "book" : "synthetic" });
    setReplay(false); setDay(null); setShock(null);
  }, [defs.data]);
  const us = market === "US";
  const body = f && {
    symbol, market, entry: f.entry ?? 0, cash: f.cash ?? 0, qty: f.qty ?? 1, side: f.side,
    margin_pct: us ? null : f.pct, initial: us ? f.initial : null, maintenance: us ? f.maint : null,
    path: f.path, replay, day, shock_pct: shock,
  };
  const { data, error } = useQuery({
    queryKey: ["fut-margin", body],
    queryFn: () => post<MarginOut>("/api/derivatives/margin", body),
    enabled: !!body && (body.entry ?? 0) > 0, placeholderData: keepPreviousData,
  });
  useEffect(() => { onFacts(data?.facts ?? []); }, [data, onFacts]);
  const set = (p: Partial<Form>) => f && setF({ ...f, ...p });
  const ledgerCols: Column<LedgerRow>[] = [
    { key: "day", header: "Day", align: "right" },
    { key: "settle", header: "Settle", align: "right", render: (r) => num(r.settle, market) },
    { key: "change", header: "Change", align: "right", render: (r) => <span className={r.change >= 0 ? "text-bull" : "text-bear"}>{signed(r.change)}</span> },
    { key: "mtm", header: "MTM cash flow", align: "right", render: (r) => <span className={r.mtm >= 0 ? "text-bull" : "text-bear"}>{money(r.mtm, market)}</span> },
    { key: "cash", header: "Cash", align: "right", render: (r) => money(r.cash, market) },
    { key: "margin_required", header: "Margin required", align: "right", render: (r) => money(r.margin_required, market) },
    { key: "free_cash", header: "Free cash", align: "right", render: (r) => <span className={r.free_cash < 0 ? "font-medium text-bear" : ""}>{money(r.free_cash, market)}</span> },
    { key: "status", header: "Status", render: (r) => r.status.startsWith("call") ? <Badge tone="bear">{r.status}</Badge> : <span className="text-[13px] text-muted">{r.status}</span> },
  ];
  const d = defs.data;
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Contract">
          <Select className="w-40" value={symbol} onChange={(e) => setSym({ ...sym, [market]: e.target.value })}>
            {choices.margin.map((c) => <option key={c} value={c}>{c} FUT</option>)}
          </Select>
        </Field>
        {d && <span className="pb-2 text-[13px] text-muted">{us ? "Multiplier" : "Lot"} {d.multiplier.toLocaleString()} per {d.unit} ({d.pending ? "† pending reference row" : `Contract Table, as of ${d.as_of}`})</span>}
      </div>
      {f && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <NumberField label="Entry price" value={f.entry} onChange={(v) => set({ entry: v })} />
          <NumberField label="Account cash" value={f.cash} onChange={(v) => set({ cash: v })} />
          <NumberField label="Contracts" value={f.qty} min={1} max={50} onChange={(v) => set({ qty: v })} />
          <Field label="Side">
            <Select value={f.side} onChange={(e) => set({ side: e.target.value as Form["side"] })}>
              <option value="long">Long</option><option value="short">Short</option>
            </Select>
          </Field>
          {us ? (<>
            <NumberField label="Initial margin / contract" value={f.initial} onChange={(v) => set({ initial: v })} />
            <NumberField label="Maintenance / contract" value={f.maint} onChange={(v) => set({ maint: v })} />
          </>) : <NumberField label="Margin % of notional (illustrative)" value={f.pct} step={0.5} onChange={(v) => set({ pct: v })} />}
        </div>
      )}
      {error && <Callout tone="danger" title="Could not run the position">{(error as Error).message}</Callout>}
      <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
        {data && Object.entries(data.position_tiles).map(([k, v]) => <FactTile key={k} label={k} value={v} tone={k === "Leverage" ? "indigo" : undefined} />)}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        {f && <Segmented label="Path" value={f.path} onChange={(p) => set({ path: p })}
          options={d?.has_book ? [{ value: "book", label: "Book sample (Ch 24)" }, { value: "synthetic", label: "Synthetic" }] : [{ value: "synthetic", label: "Synthetic" }]} />}
        <Button variant="primary" onClick={() => { setReplay(true); setDay(null); }}>Replay path</Button>
        {data?.replayed && <Hypothetical />}
      </div>
      {!data?.replayed ? (
        <EmptyState>Click Replay path to run the position over the settlement prices, day by day.</EmptyState>
      ) : (<>
        <div className="flex items-center gap-4">
          <span className="w-28 text-[13px] text-muted">After session</span>
          <Slider label="After session" min={1} max={data.sessions ?? 1} value={data.day ?? 1} onChange={setDay} />
          <span className="num w-10 text-right font-medium">{data.day}</span>
        </div>
        <div className="grid grid-cols-1 gap-2.5 md:grid-cols-3">
          <FactTile big label="Move to margin call" value={data.tiles?.["Move to margin call"]} tone="bear"
            sub={`Price where free cash reaches zero: ${data.call_price_text}`} />
          <FactTile label="MTM today" value={data.tiles?.["MTM today"]} tone={(data.mtm_today ?? 0) < 0 ? "bear" : "bull"} />
          <FactTile label="Free cash" value={data.tiles?.["Free cash"]} tone={(data.free_cash ?? 0) < 0 ? "bear" : undefined} />
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => onPlan({ symbol, entry: f?.entry ?? 0, qty: f?.qty ?? 1, side: f?.side ?? "long", call_price: data.call_price })}>Save to plan</Button>
          <span className="text-[13px] text-muted">Copies the Move to margin call price into a trade plan, as a line you will act on before it arrives.</span>
        </div>
        <Panel title="MTM ledger" action={<Hypothetical />}>
          <DataTable rows={data.rows ?? []} columns={ledgerCols} rowKey={(r) => r.day} />
          <div className="mt-4">
            <SignedBars labels={(data.rows ?? []).map((r) => r.day)} values={(data.rows ?? []).map((r) => r.mtm)} height={170} yFormat={(v) => money(v, market)} />
          </div>
        </Panel>
        <Panel title="Shock">
          <div className="flex flex-wrap items-end gap-3">
            <NumberField className="w-32" label="Shock (%)" value={shockIn} step={0.5} onChange={setShockIn} />
            <Button onClick={() => setShock(shockIn ?? 0)}>Add shock</Button>
          </div>
          {data.shock ? (
            <div className="mt-4 grid grid-cols-2 gap-2.5 md:grid-cols-4">
              <FactTile label={data.shock.label} value={data.shock.value} tone={data.shock.shortfall > 0 ? "bear" : "bull"} />
              {Object.entries(data.shock.tiles).map(([k, v]) => <FactTile key={k} label={k} value={v} tone={k === "MTM hit" ? signTone(v) : undefined} />)}
              <p className="col-span-full text-[13px] text-muted">Shock: price {num(data.shock.price, market)}. {data.shock.facts[data.shock.facts.length - 1]}.</p>
            </div>
          ) : <p className="mt-3 text-[13px] text-muted">Type a gap, say −3%, and click Add shock to see the MTM hit and whether the account would be short.</p>}
        </Panel>
      </>)}
    </div>
  );
}
