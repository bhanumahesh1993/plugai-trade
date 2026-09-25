/* Portfolio Reviewer: Allocation, ETF check, Income tabs. */
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { post, type Market } from "@/lib/api";
import { money, num } from "@/lib/format";
import { cn } from "@/lib/cn";
import { Button, Panel, Field, inputCls } from "@/components/ui";
import { FactTile } from "@/components/facts";
import { Badge, Callout, DataTable, Dialog, Hypothetical, Select, Switch, EChart, chartTokens, ScreenGrid, useToast, type Column } from "@/components/kit";
import { ApiTile, LocalExplainPanel, TileGrid, RailTitle, errText, NumInput, type ApiTileT } from "./common";

/* ------------------------------------------------------------------ Allocation */
interface AllocRow { Sleeve: string; Value: number; "Now %": number; "Target %": number; "Drift (pts)": number; Band: string; Status: string; "To target": number; "Months of new money": number | null }
interface AllocData { target: Record<string, number>; band: number; sleeves: string[]; checklist: string[]; warning: string | null; rows: AllocRow[]; facts: string[]; tiles: ApiTileT[]; total_text?: string }
interface Lot { bought: string; units: number; cost: number }

function TargetDialog({ open, onOpenChange, d, market }: { open: boolean; onOpenChange: (v: boolean) => void; d: AllocData; market: Market }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [tgt, setTgt] = useState<Record<string, number>>(d.target);
  const [band, setBand] = useState(d.band);
  useEffect(() => { if (open) { setTgt(d.target); setBand(d.band); } }, [open, d.target, d.band]);
  const total = Object.values(tgt).reduce((a, b) => a + b, 0);
  const save = useMutation({
    mutationFn: () => post<AllocData>("/api/portfolio/allocation/target", { market, target: tgt, band }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["pf", market, "alloc"] }); toast("Saved target"); onOpenChange(false); },
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Set target"
      footer={<><Button variant="quiet" onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button variant="primary" onClick={() => save.mutate()} disabled={save.isPending}>Save target</Button></>}>
      <div className="grid grid-cols-2 gap-3">
        {d.sleeves.map((s) => (
          <Field key={s} label={`${s} target %`}><NumInput value={tgt[s] ?? 0} min={0} max={100} step={1} onChange={(v) => setTgt({ ...tgt, [s]: v })} /></Field>
        ))}
        <Field label="Band (± points)"><NumInput value={band} min={0.5} max={25} step={0.5} onChange={setBand} /></Field>
      </div>
      <p className={cn("mt-3 text-[13px] num", Math.abs(total - 100) > 0.05 ? "text-bear" : "text-muted")}>Adds up to {total.toFixed(1)}%{Math.abs(total - 100) > 0.05 ? ", not 100%" : ""}</p>
      {save.error && <p className="mt-2 text-[13px] text-bear">{errText(save.error)}</p>}
    </Dialog>
  );
}

function RebalanceChecklist({ d, market }: { d: AllocData; market: Market }) {
  const [lots, setLots] = useState<Lot[]>([{ bought: "2024-04-01", units: 100, cost: 50 }]);
  const [units, setUnits] = useState(50);
  const [price, setPrice] = useState(60);
  const valid = lots.filter((l) => l.bought && l.units > 0);
  const { data: sale } = useQuery({
    queryKey: ["pf", "sale", valid, units, price],
    queryFn: () => post<Record<string, unknown>[]>("/api/portfolio/sale-lots", { lots: valid, units, price }),
    enabled: valid.length > 0, placeholderData: keepPreviousData,
  });
  const out = d.rows.filter((r) => r.Status !== "inside");
  const setLot = (i: number, p: Partial<Lot>) => setLots(lots.map((l, j) => (j === i ? { ...l, ...p } : l)));
  return (
    <Panel title="Rebalance checklist">
      <ol className="list-decimal space-y-1.5 pl-5 text-[14px]">{d.checklist.map((c) => <li key={c}>{c}</li>)}</ol>
      <h3 className="mt-5 mb-2 text-[13px] font-semibold">Sleeves outside their bands</h3>
      {out.length ? (
        <DataTable rows={out as unknown as Record<string, unknown>[]} columns={[
          { key: "Sleeve", header: "Sleeve" },
          { key: "Drift (pts)", header: "Drift (pts)", align: "right", render: (r) => `${(r["Drift (pts)"] as number) > 0 ? "+" : ""}${r["Drift (pts)"]}` },
          { key: "To target", header: "To target", align: "right", render: (r) => money(r["To target"] as number, market) },
          { key: "Months of new money", header: "Months of new money", align: "right", render: (r) => r["Months of new money"] == null ? "Set monthly new money" : String(r["Months of new money"]) },
        ]} />
      ) : <p className="text-muted">No sleeve is outside its band.</p>}
      <h3 className="mt-5 mb-1 text-[13px] font-semibold">Lots for a sale (estimate, Draft for your CA / CPA)</h3>
      <div className="flex flex-col gap-2">
        {lots.map((l, i) => (
          <div key={i} className="grid grid-cols-[1fr_1fr_1fr_auto] items-end gap-2">
            <Field label="Bought"><input type="date" className={inputCls} value={l.bought} onChange={(e) => setLot(i, { bought: e.target.value })} /></Field>
            <Field label="Units"><NumInput value={l.units} onChange={(v) => setLot(i, { units: v })} /></Field>
            <Field label="Cost per unit"><NumInput value={l.cost} onChange={(v) => setLot(i, { cost: v })} /></Field>
            <button aria-label="Remove lot" className="mb-2 text-muted hover:text-bear" onClick={() => setLots(lots.filter((_, j) => j !== i))}><X size={15} /></button>
          </div>
        ))}
        <div><Button size="sm" onClick={() => setLots([...lots, { bought: new Date().toISOString().slice(0, 10), units: 10, cost: 50 }])}><Plus size={14} /> Add lot</Button></div>
        <div className="grid grid-cols-2 gap-3 md:max-w-md">
          <Field label="Units to sell"><NumInput value={units} min={0} onChange={setUnits} /></Field>
          <Field label="Price / NAV"><NumInput value={price} min={0} onChange={setPrice} /></Field>
        </div>
        {sale && <DataTable rows={sale} columns={[
          { key: "Bought", header: "Bought" }, { key: "Units", header: "Units", align: "right" },
          { key: "Held (days)", header: "Held (days)", align: "right" }, { key: "Type", header: "Type" },
          { key: "Gain", header: "Gain", align: "right", render: (r) => money(r.Gain as number, market, 2) },
          { key: "Rate", header: "Rate", align: "right", render: (r) => `${((r.Rate as number) * 100).toFixed(1)}%` },
          { key: "Note", header: "Note" },
        ]} />}
      </div>
      <p className="mt-3 text-[13px] text-muted">The lab places no orders; you act in your own broker or fund account.</p>
    </Panel>
  );
}

export function AllocationTab({ market }: { market: Market }) {
  const [monthly, setMonthly] = useState(0);
  const [editing, setEditing] = useState(false);
  const [showRebal, setShowRebal] = useState(false);
  const { data: d } = useQuery({
    queryKey: ["pf", market, "alloc", monthly],
    queryFn: () => post<AllocData>("/api/portfolio/allocation", { market, monthly }),
    placeholderData: keepPreviousData,
  });
  const t = chartTokens();
  const rows = d?.rows ?? [];
  const option = {
    grid: { left: 44, right: 12, top: 28, bottom: 28 },
    legend: { top: 0, right: 0, textStyle: { color: t.muted }, itemWidth: 12, itemHeight: 10 },
    tooltip: { trigger: "axis", backgroundColor: t.panel, borderColor: t.line, textStyle: { color: t.ink }, valueFormatter: (v: number) => `${v}%` },
    xAxis: { type: "category", data: rows.map((r) => r.Sleeve), axisLabel: { color: t.ink }, axisLine: { lineStyle: { color: t.line } } },
    yAxis: { type: "value", axisLabel: { color: t.muted, formatter: "{value}%" }, splitLine: { lineStyle: { color: t.line } } },
    series: [
      { name: "Target %", type: "bar", data: rows.map((r) => r["Target %"]), itemStyle: { color: t.line, borderRadius: [3, 3, 0, 0] }, barGap: "10%", barWidth: 28 },
      { name: "Now %", type: "bar", barWidth: 28, data: rows.map((r) => ({ value: r["Now %"],
        itemStyle: { color: t.indigo, borderRadius: [3, 3, 0, 0], ...(r.Status !== "inside" ? { borderColor: t.ink, borderWidth: 2, borderType: "dashed" } : {}) },
        label: { show: r.Status !== "inside", position: "top", color: t.ink, formatter: "Outside band" } })) },
    ],
  };
  const cols: Column<Record<string, unknown>>[] = [
    { key: "Sleeve", header: "Sleeve" },
    { key: "Value", header: "Value", align: "right", render: (r) => money(r.Value as number, market) },
    { key: "Now %", header: "Now %", align: "right" }, { key: "Target %", header: "Target %", align: "right" },
    { key: "Drift (pts)", header: "Drift (pts)", align: "right", render: (r) => `${(r["Drift (pts)"] as number) > 0 ? "+" : ""}${r["Drift (pts)"]}` },
    { key: "Band", header: "Band", align: "right" },
    { key: "Status", header: "Status", render: (r) => r.Status === "inside" ? <Badge>Inside</Badge> : <Badge tone="warn">Outside band</Badge> },
    { key: "To target", header: "To target", align: "right", render: (r) => money(r["To target"] as number, market) },
    { key: "Months of new money", header: "Months of new money", align: "right", render: (r) => r["Months of new money"] == null ? "—" : String(r["Months of new money"]) },
  ];
  return (
    <ScreenGrid rail={
      <>
        <RailTitle>Drift</RailTitle>
        <TileGrid tiles={d?.tiles.slice(0, 1)} />
        <TileGrid tiles={d?.tiles.slice(1)} />
        {d && d.facts.length > 0 && <LocalExplainPanel facts={d.facts} />}
      </>
    }>
      <Panel title={`Target mix and band${d ? `, ±${d.band} points` : ""}`} action={
        <div className="flex gap-2">
          <Button size="sm" onClick={() => setEditing(true)} disabled={!d}>Set target</Button>
          <Button size="sm" onClick={() => setShowRebal((s) => !s)} disabled={!d || !!d.warning}>Rebalance checklist</Button>
        </div>}>
        {d?.warning ? <Callout tone="warn">{d.warning}</Callout> : (
          <>
            <div className="mb-3 max-w-xs">
              <Field label={`Monthly new money (${market === "IN" ? "₹" : "$"})`} hint="Shows how many months of new money would close each gap.">
                <NumInput value={monthly} min={0} step={1000} onChange={setMonthly} />
              </Field>
            </div>
            <EChart option={option} height={240} />
            <div className="mt-3"><DataTable rows={rows as unknown as Record<string, unknown>[]} columns={cols} /></div>
          </>
        )}
      </Panel>
      {showRebal && d && !d.warning && <RebalanceChecklist d={d} market={market} />}
      {d && <TargetDialog open={editing} onOpenChange={setEditing} d={d} market={market} />}
    </ScreenGrid>
  );
}

/* ------------------------------------------------------------------ ETF check */
interface EtfData {
  funds: { name: string; tiles: ApiTileT[] }[];
  gap: { amount: number; years: number; index_return_pct: number; a_text: string; b_text: string; gap_text: string };
  premium: { name: string; times: string[]; values: number[]; threshold: number; peak: number; now: number; inav: number; flagged: boolean; buy_text: string; peak_cost_text: string };
  facts: string[];
}

export function EtfTab({ market }: { market: Market }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [inp, setInp] = useState<Record<Market, { amount?: number; years?: number; index_return_pct?: number; threshold_pct?: number }>>({ IN: {}, US: {} });
  const [name, setName] = useState("");
  const [standIn, setStandIn] = useState(false);
  const p = inp[market];
  const key = ["pf", market, "etf", p];
  const { data: d } = useQuery({ queryKey: key, queryFn: () => post<EtfData>("/api/portfolio/etf", { market, ...p }), placeholderData: keepPreviousData });
  const set = (k: keyof typeof p) => (v: number) => setInp((s) => ({ ...s, [market]: { ...s[market], [k]: v } }));
  const add = useMutation({
    mutationFn: () => post<{ added: string }>("/api/portfolio/etf/add", { market, name }),
    onSuccess: (r) => { setStandIn(true); setName(""); qc.invalidateQueries({ queryKey: ["pf", market, "etf"] }); toast(`Added ${r.added}`); },
  });
  const save = useMutation({
    mutationFn: () => post<{ id: number }>("/api/portfolio/etf/save", { market, ...p }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["pf", "theses"] }); toast("Saved to thesis"); },
    onError: (e) => toast(errText(e), "danger"),
  });
  const t = chartTokens();
  const pr = d?.premium;
  const thr = pr?.threshold ?? 0.5;
  const option = pr && {
    grid: { left: 48, right: 16, top: 16, bottom: 28 },
    tooltip: { trigger: "axis", backgroundColor: t.panel, borderColor: t.line, textStyle: { color: t.ink }, valueFormatter: (v: number) => `${v.toFixed(2)}%` },
    xAxis: { type: "category", data: pr.times, axisLabel: { color: t.muted, interval: 11 }, axisLine: { lineStyle: { color: t.line } } },
    yAxis: { type: "value", axisLabel: { color: t.muted, formatter: "{value}%" }, splitLine: { lineStyle: { color: t.line } } },
    series: [
      { name: "Premium", type: "line", data: pr.values, showSymbol: false, lineStyle: { color: t.indigo, width: 2 },
        markLine: { symbol: "none", silent: true, data: [{ yAxis: thr, lineStyle: { color: t.muted, type: "dashed" }, label: { formatter: `Flag above ${thr}%`, color: t.muted, position: "insideEndTop" } }] } },
      { name: "Above your flag", type: "scatter", symbolSize: 7, itemStyle: { color: t.ink },
        data: pr.values.map((v, i) => (v > thr ? [pr.times[i], v] : null)).filter(Boolean) },
    ],
  };
  const lastFund = d?.funds.length ? d.funds[d.funds.length - 1].name : "";
  return (
    <ScreenGrid rail={
      <>
        <RailTitle>Cost of the gap</RailTitle>
        <ApiTile t={{ label: "Cost of the gap", value: d?.gap.gap_text ?? "…", fact: "Cost of the gap", sub: `${d?.gap.years ?? ""} years, returns held constant` }} big />
        {d && <LocalExplainPanel facts={d.facts} />}
        <Button onClick={() => save.mutate()} disabled={!d || save.isPending}>Save to thesis</Button>
        <p className="text-[13px] text-muted">Saved to the Thesis tracker; next month's review can check whether the gap held.</p>
      </>
    }>
      <Panel title="Compare two ETFs on the same index">
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-[240px] flex-1"><Field label="ETF name or ticker"><input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} /></Field></div>
          <Button onClick={() => add.mutate()} disabled={!name.trim() || add.isPending}>Add ETF</Button>
        </div>
        {standIn && <div className="mt-3"><Callout tone="info">No free NAV / iNAV source is connected for this fund, so a synthetic stand-in is shown. Connect AMFI NAV / NSE bhavcopy (IN) or yfinance (US) in Data Sources.</Callout></div>}
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          {d?.funds.map((f) => (
            <div key={f.name} className="flex min-w-0 flex-col gap-2">
              <div className="text-[14px] font-semibold">{f.name}</div>
              {f.tiles.map((x) => <ApiTile key={x.label} t={{ ...x, big: false }} />)}
            </div>
          ))}
        </div>
      </Panel>
      <Panel title="Cost of the gap" action={<Hypothetical />}>
        <div className="grid grid-cols-3 gap-3">
          <Field label={`Investment (${market === "IN" ? "₹" : "$"})`}><NumInput value={d?.gap.amount ?? ""} step={10000} onChange={set("amount")} /></Field>
          <Field label="Horizon (years)"><NumInput value={d?.gap.years ?? ""} step={1} onChange={set("years")} /></Field>
          <Field label="Index total return % a year (assumed)"><NumInput value={d?.gap.index_return_pct ?? ""} step={0.1} onChange={set("index_return_pct")} /></Field>
        </div>
        <div className="mt-4 grid grid-cols-3 gap-2.5">
          <FactTile label={d?.funds[0]?.name ?? "ETF A"} value={d?.gap.a_text ?? "…"} />
          <FactTile label={d?.funds[1]?.name ?? "ETF B"} value={d?.gap.b_text ?? "…"} />
          <FactTile label="Difference, returns held constant" value={d?.gap.gap_text ?? "…"} tone="bear" />
        </div>
      </Panel>
      <Panel title={`Premium today: ${lastFund}`} action={<span className="text-[12px] text-muted">Market price against iNAV, 5-minute points</span>}>
        <div className="mb-2 max-w-[180px]"><Field label="Flag above (%)"><NumInput value={thr} min={0.1} max={5} step={0.1} onChange={set("threshold_pct")} /></Field></div>
        {option ? <EChart option={option} height={240} /> : <div style={{ height: 240 }} />}
        {pr?.flagged && <div className="mt-2"><Callout tone="warn">Premium reached {(pr.peak * 100).toFixed(2)}% today, above your {thr.toFixed(1)}% threshold. Reference limit price = iNAV {market === "IN" ? "₹" : "$"}{pr.inav.toFixed(2)} (synthetic). Nothing is placed.</Callout></div>}
        {pr && <p className="mt-2 text-[13px] text-muted">Latest premium {pr.now >= 0 ? "+" : "−"}{Math.abs(pr.now * 100).toFixed(2)}%. Buying {pr.buy_text} at the peak premium pays about {pr.peak_cost_text} above fair value.</p>}
      </Panel>
    </ScreenGrid>
  );
}

/* ------------------------------------------------------------------ Income */
interface IncomeData { rows: Record<string, unknown>[]; trap: { month: number; price: number; yield_pct: number; price_driven: boolean }[]; trap_cut_month: number; tiles: ApiTileT[]; facts: string[]; profile: string; cess_pct: number; cess_in_table: boolean; qualified_rates: number[] }

export function IncomeTab({ market }: { market: Market }) {
  const [p, setP] = useState({ holding_period: false, slab_pct: 30, cess_pct: undefined as number | undefined, bracket_pct: 22, qualified: true, qualified_rate: 0.15, niit: false });
  const { data: d, error } = useQuery({
    queryKey: ["pf", market, "income", p],
    queryFn: () => post<IncomeData>("/api/portfolio/income", { market, ...p }),
    placeholderData: keepPreviousData,
  });
  const t = chartTokens();
  const cur = market === "IN" ? "₹" : "$";
  const trap = d?.trap ?? [];
  // Segment i-1 -> i is "price-driven" when trap[i].price_driven: dashed there, solid elsewhere.
  const into = (i: number) => !!trap[i]?.price_driven;
  const dashed = trap.map((r, i) => (into(i) || into(i + 1) ? r.yield_pct : null));
  const solid = trap.map((r, i) => ((i > 0 && !into(i)) || (i + 1 < trap.length && !into(i + 1)) ? r.yield_pct : null));
  const option = {
    grid: [{ left: 56, right: 16, top: 24, height: 120 }, { left: 56, right: 16, top: 190, height: 120 }],
    legend: { bottom: 0, left: 0, textStyle: { color: t.muted }, itemWidth: 16 },
    tooltip: { trigger: "axis", backgroundColor: t.panel, borderColor: t.line, textStyle: { color: t.ink } },
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    xAxis: [{ type: "category", data: trap.map((r) => r.month), gridIndex: 0, axisLabel: { show: false }, axisLine: { lineStyle: { color: t.line } } },
      { type: "category", data: trap.map((r) => r.month), gridIndex: 1, name: "Month", nameLocation: "middle", nameGap: 26, nameTextStyle: { color: t.muted }, axisLabel: { color: t.muted }, axisLine: { lineStyle: { color: t.line } } }],
    yAxis: [{ type: "value", gridIndex: 0, name: `Price ${cur}`, nameTextStyle: { color: t.muted, align: "left" }, scale: true, axisLabel: { color: t.muted }, splitLine: { lineStyle: { color: t.line } } },
      { type: "value", gridIndex: 1, name: "Trailing yield %", nameTextStyle: { color: t.muted, align: "left" }, scale: true, axisLabel: { color: t.muted }, splitLine: { lineStyle: { color: t.line } } }],
    series: [
      { name: "Price", type: "line", data: trap.map((r) => r.price), showSymbol: false, lineStyle: { color: t.ink, width: 2 }, itemStyle: { color: t.ink },
        markLine: { symbol: "none", silent: true, data: [{ xAxis: String(d?.trap_cut_month ?? 30), lineStyle: { color: t.muted, type: "dotted" }, label: { formatter: "Dividend cut", color: t.muted } }] } },
      { name: "Trailing yield", type: "line", xAxisIndex: 1, yAxisIndex: 1, data: solid, showSymbol: false, connectNulls: false, lineStyle: { color: t.indigo, width: 2 }, itemStyle: { color: t.indigo } },
      { name: "Yield up only because price fell", type: "line", xAxisIndex: 1, yAxisIndex: 1, data: dashed, showSymbol: false, connectNulls: false,
        lineStyle: { color: t.bear, width: 2.5, type: "dashed" }, itemStyle: { color: t.bear } },
    ],
  };
  const cols: Column<Record<string, unknown>>[] = [
    { key: "Holding", header: "Holding" }, { key: "Shares", header: "Shares", align: "right" },
    { key: "Price", header: "Price", align: "right", render: (r) => num(r.Price as number, market) },
    { key: "Dividend (12m)", header: "Dividend (12m)", align: "right", render: (r) => num(r["Dividend (12m)"] as number, market) },
    { key: "Yield %", header: "Yield %", align: "right" },
    { key: "Ex-date", header: "Ex-date", render: (r) => <span className="num whitespace-nowrap">{String(r["Ex-date"])}</span> },
    { key: "Gross income", header: "Gross income", align: "right", render: (r) => money(r["Gross income"] as number, market) },
    { key: "Payout %", header: "Payout %", align: "right" }, { key: "Cash cover", header: "Cash cover", align: "right" },
    { key: "Safety", header: "Safety", render: (r) => r.flag
      ? <div className="flex flex-col items-start gap-0.5"><Badge tone="warn">Flag</Badge><span className="text-[12px] text-muted">{String(r.Safety)}</span></div>
      : <Badge>ok</Badge> },
    ...(market === "US" && p.holding_period ? [{ key: "Treated as", header: "Treated as" }] : []),
  ];
  return (
    <ScreenGrid rail={
      <>
        <RailTitle>Income after tax</RailTitle>
        <TileGrid tiles={d?.tiles.slice(0, 1)} />
        <TileGrid tiles={d?.tiles.slice(1)} />
        {d && <LocalExplainPanel facts={d.facts} />}
      </>
    }>
      <Panel title="Last 12 months of dividends" action={market === "US" && (
        <div className="w-[240px]"><Switch checked={p.holding_period} onChange={(v) => setP({ ...p, holding_period: v })} label="Holding-period check" /></div>)}>
        <p className="mb-3 text-[13px] text-muted">Synthetic sample until a free dividend source is connected. Payout and cash cover are computed in code; a flag appears when payout passes 100% or cover falls below 1.</p>
        {error && <p className="text-bear">{errText(error)}</p>}
        <DataTable rows={d?.rows ?? []} columns={cols} />
      </Panel>
      <Panel title="Yield vs price" action={<span className="text-[12px] text-muted">Synthetic dividend payer</span>}>
        <p className="mb-2 text-[13px] text-muted">Dashed red: the yield rose only because the price fell.</p>
        <EChart option={option} height={370} />
      </Panel>
      <Panel title="Tax profile">
        {market === "IN" ? (
          <div className="grid max-w-lg grid-cols-2 gap-3">
            <Field label="Your slab rate %"><NumInput value={p.slab_pct} min={0} max={45} onChange={(v) => setP({ ...p, slab_pct: v })} /></Field>
            <Field label="Cess %" hint={d && !d.cess_in_table ? "Cess is not in the dated table yet; confirm the rate (Appendix A)." : undefined}>
              <NumInput value={p.cess_pct ?? d?.cess_pct ?? 4} min={0} max={10} onChange={(v) => setP({ ...p, cess_pct: v })} />
            </Field>
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-3 md:items-end">
            <Field label="Your bracket %"><NumInput value={p.bracket_pct} min={0} max={40} onChange={(v) => setP({ ...p, bracket_pct: v })} /></Field>
            <Field label="Qualified rate">
              <Select value={p.qualified_rate} onChange={(e) => setP({ ...p, qualified_rate: Number(e.target.value) })} disabled={!p.qualified}>
                {(d?.qualified_rates ?? [0, 0.15, 0.2]).map((r) => <option key={r} value={r}>{Math.round(r * 100)}%</option>)}
              </Select>
            </Field>
            <div />
            <Switch checked={p.qualified} onChange={(v) => setP({ ...p, qualified: v })} label="Expect qualified dividends" />
            <Switch checked={p.niit} onChange={(v) => setP({ ...p, niit: v })} label="Add NIIT (3.8%, top brackets)" />
          </div>
        )}
        <p className="mt-3 text-[13px] text-muted">Rates come from the dated tax table or from your own profile, never from the AI.</p>
      </Panel>
    </ScreenGrid>
  );
}
