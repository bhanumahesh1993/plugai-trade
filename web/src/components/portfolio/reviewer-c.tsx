/* Portfolio Reviewer: SIP planner and Thesis tracker tabs. */
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { get, post, type Market } from "@/lib/api";
import { money } from "@/lib/format";
import { Button, Panel, Field, inputCls } from "@/components/ui";
import { Badge, Callout, DataTable, Dialog, EmptyState, Hypothetical, Select, Switch, Textarea, EChart, chartTokens, ScreenGrid, useToast, type Column } from "@/components/kit";
import { LocalExplainPanel, TileGrid, RailTitle, errText, NumInput, type ApiTileT } from "./common";
import { useHoldings } from "./reviewer-a";

/* ------------------------------------------------------------------ SIP planner */
interface SipData { table: Record<string, unknown>[]; facts: string[]; tiles: ApiTileT[]; series: { name: string; values: number[] }[]; invested: number[]; months: number[] }
interface SipIn { monthly: number; years: number; start: string; goal: number; returns_pct: number[]; inflation_pct: number; step_up_pct: number; pause_from: number; pause_months: number }

const SIP_DEFAULT: Record<Market, SipIn> = {
  IN: { monthly: 10000, years: 20, start: new Date().toISOString().slice(0, 10), goal: 5_000_000, returns_pct: [6, 8, 10], inflation_pct: 0, step_up_pct: 0, pause_from: 0, pause_months: 0 },
  US: { monthly: 500, years: 25, start: new Date().toISOString().slice(0, 10), goal: 300_000, returns_pct: [6, 8, 10], inflation_pct: 0, step_up_pct: 0, pause_from: 0, pause_months: 0 },
};

export function SipTab({ market }: { market: Market }) {
  const toast = useToast();
  const [goalMode, setGoalMode] = useState(false);
  const [byMkt, setByMkt] = useState(SIP_DEFAULT);
  const s = byMkt[market];
  const set = (p: Partial<SipIn>) => setByMkt((x) => ({ ...x, [market]: { ...x[market], ...p } }));
  const body = { market, ...s, goal: goalMode ? s.goal : null };
  const { data: d, error } = useQuery({
    queryKey: ["pf", market, "sip", body],
    queryFn: () => post<SipData>("/api/portfolio/sip", body),
    placeholderData: keepPreviousData,
  });
  const save = useMutation({
    mutationFn: () => post<{ id: number; saved: string }>("/api/portfolio/sip/save", body),
    onSuccess: (r) => toast(`Saved plan, dated ${r.saved}`),
    onError: (e) => toast(errText(e), "danger"),
  });
  const t = chartTokens();
  const cur = market === "IN" ? "₹" : "$";
  const short = (v: number) => market === "IN"
    ? (v >= 1e7 ? `₹${(v / 1e7).toFixed(1)} Cr` : `₹${(v / 1e5).toFixed(0)}L`)
    : (v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : `$${(v / 1e3).toFixed(0)}k`);
  const shades = [0.45, 0.7, 1];
  const option = d && {
    grid: { left: 64, right: 16, top: 30, bottom: 32 },
    legend: { top: 0, left: 0, textStyle: { color: t.muted }, itemWidth: 16 },
    tooltip: { trigger: "axis", backgroundColor: t.panel, borderColor: t.line, textStyle: { color: t.ink }, valueFormatter: (v: number) => money(v, market) },
    xAxis: { type: "category", data: d.months, name: "Month", nameLocation: "middle", nameGap: 24, nameTextStyle: { color: t.muted },
      axisLabel: { color: t.muted, interval: 11, formatter: (v: string) => `${Math.round(Number(v) / 12)}y` }, axisLine: { lineStyle: { color: t.line } } },
    yAxis: { type: "value", axisLabel: { color: t.muted, formatter: short }, splitLine: { lineStyle: { color: t.line } } },
    series: [
      ...d.series.map((sr, i) => ({ name: sr.name, type: "line", data: sr.values, showSymbol: false,
        lineStyle: { color: t.indigo, width: 2, opacity: shades[Math.min(i, 2)] ?? 1 }, itemStyle: { color: t.indigo, opacity: shades[Math.min(i, 2)] ?? 1 } })),
      { name: "Invested", type: "line", data: d.invested, showSymbol: false, lineStyle: { color: t.muted, width: 1.5, type: "dashed" }, itemStyle: { color: t.muted },
        areaStyle: { color: t.muted, opacity: 0.08 } },
    ],
  };
  const tableCols: Column<Record<string, unknown>>[] = Object.keys(d?.table[0] ?? {}).map((k, i) => ({
    key: k, header: k, align: i === 0 ? "left" : "right",
    render: i === 0 ? undefined : (r: Record<string, unknown>) => money(r[k] as number, market),
  }));
  return (
    <ScreenGrid rail={
      <>
        <RailTitle>Projected value</RailTitle>
        <TileGrid tiles={d?.tiles.filter((x) => x.big)} />
        <TileGrid tiles={d?.tiles.filter((x) => !x.big)} />
        {d && <LocalExplainPanel facts={d.facts} />}
        <Button onClick={() => save.mutate()} disabled={!d || save.isPending}>Save plan</Button>
        <p className="text-[13px] text-muted">Stores the assumptions with today's date. Next year's review compares what happened with what you assumed.</p>
      </>
    }>
      <Panel title="Plan" action={<div className="w-[160px]"><Switch checked={goalMode} onChange={setGoalMode} label="Goal mode" /></div>}>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Field label={`Monthly amount (${cur})`}><NumInput value={s.monthly} min={0} step={500} onChange={(v) => set({ monthly: v })} /></Field>
          <Field label="Years"><NumInput value={s.years} min={1} max={50} step={1} onChange={(v) => set({ years: Math.max(1, Math.round(v)) })} /></Field>
          <Field label="Start date"><input type="date" className={inputCls} value={s.start} onChange={(e) => set({ start: e.target.value })} /></Field>
          {goalMode && <Field label={`Target amount (${cur}, at today's prices if Inflation > 0)`}><NumInput value={s.goal} min={0} step={10000} onChange={(v) => set({ goal: v })} /></Field>}
        </div>
        <p className="mt-4 mb-2 text-[13px] text-muted">Assumed return, illustrative: not forecasts. Real returns vary and can be negative for years.</p>
        <div className="grid grid-cols-3 gap-3">
          {s.returns_pct.map((r, i) => (
            <Field key={i} label={`Assumed return ${i + 1} (%)`}>
              <NumInput value={r} min={-20} max={30} step={0.5} onChange={(v) => set({ returns_pct: s.returns_pct.map((x, j) => (j === i ? v : x)) })} />
            </Field>
          ))}
        </div>
        <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
          <Field label="Inflation %"><NumInput value={s.inflation_pct} min={0} max={20} step={0.5} onChange={(v) => set({ inflation_pct: v })} /></Field>
          <Field label="Step-up % a year"><NumInput value={s.step_up_pct} min={0} max={50} step={1} onChange={(v) => set({ step_up_pct: v })} /></Field>
          <Field label="Pause from month"><NumInput value={s.pause_from} min={0} max={600} step={1} onChange={(v) => set({ pause_from: Math.round(v) })} /></Field>
          <Field label="Pause (months)"><NumInput value={s.pause_months} min={0} max={120} step={1} onChange={(v) => set({ pause_months: Math.round(v) })} /></Field>
        </div>
        {error && <p className="mt-2 text-bear">{errText(error)}</p>}
      </Panel>
      <Panel title={`${money(s.monthly, market)} a month: value under each assumption`} action={<Hypothetical />}>
        {option ? <EChart option={option} height={300} /> : <div style={{ height: 300 }} />}
        <div className="mt-3"><DataTable rows={d?.table ?? []} columns={tableCols} /></div>
      </Panel>
    </ScreenGrid>
  );
}

/* ------------------------------------------------------------------ Thesis tracker */
interface CheckRow { "My condition": string; "Last qtr": number | null; "This qtr": number | null; Source: string; Status: string; review: boolean }
interface ThesisT { id: number; holding: string; why: string; conditions: { metric: string; op: string; threshold: number; text: string }[]; check: CheckRow[]; tripped: number; facts: string[]; tiles: ApiTileT[] }
interface ThesesData { theses: ThesisT[]; ops: string[] }

function NewThesisDialog({ open, onOpenChange, names, ops, onSaved }: { open: boolean; onOpenChange: (v: boolean) => void; names: string[]; ops: string[]; onSaved: (id: number) => void }) {
  const toast = useToast();
  const qc = useQueryClient();
  const [holding, setHolding] = useState("");
  const [typed, setTyped] = useState("");
  const [why, setWhy] = useState("");
  const [conds, setConds] = useState([{ metric: "revenue_growth_pct", op: ">=", threshold: 10 }]);
  useEffect(() => { if (open) setHolding(names[0] ?? ""); }, [open, names]);
  const save = useMutation({
    mutationFn: () => post<ThesesData & { id: number }>("/api/portfolio/theses", { holding: holding === "__typed" ? typed : holding, why, conditions: conds }),
    onSuccess: (r) => { qc.setQueryData(["pf", "theses"], r); onSaved(r.id); toast("Saved thesis"); onOpenChange(false); setWhy(""); },
  });
  const setC = (i: number, p: Partial<(typeof conds)[number]>) => setConds(conds.map((c, j) => (j === i ? { ...c, ...p } : c)));
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Add thesis"
      footer={<><Button variant="quiet" onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button variant="primary" onClick={() => save.mutate()} disabled={save.isPending}>Save thesis</Button></>}>
      <div className="flex flex-col gap-3">
        <Field label="Holding">
          <Select value={holding} onChange={(e) => setHolding(e.target.value)}>
            {names.map((n) => <option key={n} value={n}>{n}</option>)}
            <option value="__typed">Type a holding</option>
          </Select>
        </Field>
        {holding === "__typed" && <Field label="Holding name"><input className={inputCls} value={typed} onChange={(e) => setTyped(e.target.value)} /></Field>}
        <Field label="Why I own it"><Textarea value={why} onChange={(e) => setWhy(e.target.value)} /></Field>
        <div>
          <div className="mb-1 text-[12px] text-muted">Conditions that would break it</div>
          {conds.map((c, i) => (
            <div key={i} className="mb-2 grid grid-cols-[1fr_84px_96px_auto] items-center gap-2">
              <input aria-label="Metric" className={inputCls} value={c.metric} onChange={(e) => setC(i, { metric: e.target.value })} />
              <Select aria-label="Comparison" value={c.op} onChange={(e) => setC(i, { op: e.target.value })}>{ops.map((o) => <option key={o}>{o}</option>)}</Select>
              <NumInput value={c.threshold} onChange={(v) => setC(i, { threshold: v })} />
              <button aria-label="Remove condition" className="text-muted hover:text-bear" onClick={() => setConds(conds.filter((_, j) => j !== i))}><X size={15} /></button>
            </div>
          ))}
          <Button size="sm" onClick={() => setConds([...conds, { metric: "", op: "<", threshold: 0 }])}><Plus size={14} /> Add condition</Button>
        </div>
        {save.error && <p className="text-[13px] text-bear">{errText(save.error)}</p>}
      </div>
    </Dialog>
  );
}

export function ThesisTab({ market }: { market: Market }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { data } = useQuery({ queryKey: ["pf", "theses"], queryFn: () => get<ThesesData>("/api/portfolio/theses") });
  const { data: h } = useHoldings(market);
  const [sel, setSel] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const [checked, setChecked] = useState<number | null>(null);
  const [fig, setFig] = useState({ quarter: "2026-Q3", metric: "", value: 0, source: "" });
  const [note, setNote] = useState("");
  const theses = data?.theses ?? [];
  const t = theses.find((x) => x.id === sel) ?? theses[0];
  const metric = fig.metric || t?.conditions[0]?.metric || "";
  const addFig = useMutation({
    mutationFn: () => post<ThesisT>(`/api/portfolio/theses/${t!.id}/figure`, { ...fig, metric }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["pf", "theses"] }); toast("Added figure"); },
    onError: (e) => toast(errText(e), "danger"),
  });
  const addNote = useMutation({
    mutationFn: () => post(`/api/portfolio/theses/${t!.id}/note`, { text: note }),
    onSuccess: () => { toast("Added note to journal"); setNote(""); },
    onError: (e) => toast(errText(e), "danger"),
  });
  if (!data) return <div style={{ height: 320 }} />;
  if (!t) return <EmptyState action={<Button onClick={() => setAdding(true)}>Add thesis</Button>}>No thesis yet. Write why you own a holding and what would break it.</EmptyState>;
  const isChecked = checked === t.id;
  const cols: Column<Record<string, unknown>>[] = [
    { key: "My condition", header: "My condition" },
    { key: "Last qtr", header: "Last qtr", align: "right", render: (r) => r["Last qtr"] == null ? "—" : String(r["Last qtr"]) },
    { key: "This qtr", header: "This qtr", align: "right", render: (r) => r["This qtr"] == null ? "—" : String(r["This qtr"]) },
    { key: "Source", header: "Source", render: (r) => String(r.Source || "—") },
    { key: "Status", header: "Status", render: (r) => r.review ? <Badge tone="warn">Review</Badge> : r.Status === "holds" ? <Badge tone="indigo">Holds</Badge> : <Badge>No figure yet</Badge> },
  ];
  return (
    <ScreenGrid rail={
      <>
        <RailTitle>Thesis check</RailTitle>
        <TileGrid tiles={t.tiles.slice(0, 1)} />
        <TileGrid tiles={t.tiles.slice(1)} />
        <LocalExplainPanel facts={t.facts} />
        <Panel title="Your decision (for the journal)">
          <Textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="What you decided, and why" />
          <Button className="mt-2" onClick={() => addNote.mutate()} disabled={!note.trim() || addNote.isPending}>Add note to journal</Button>
          <p className="mt-2 text-[13px] text-muted">The lab places no orders; you act in your own broker or fund account.</p>
        </Panel>
      </>
    }>
      <Panel title="Thesis" action={<Button size="sm" onClick={() => setAdding(true)}><Plus size={14} /> Add thesis</Button>}>
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[280px] flex-1">
            <Field label="Thesis">
              <Select value={t.id} onChange={(e) => { setSel(Number(e.target.value)); setFig({ ...fig, metric: "" }); }}>
                {theses.map((x) => <option key={x.id} value={x.id}>{x.holding}</option>)}
              </Select>
            </Field>
          </div>
          <Button variant="primary" onClick={() => setChecked(t.id)}>Check thesis</Button>
        </div>
        <p className="mt-3 font-serif text-[15px]"><span className="font-sans font-semibold">{t.holding}.</span> <span className="text-muted font-sans text-[13px]">Why I own it:</span> {t.why}</p>
        {isChecked ? (
          <div className="mt-3 flex flex-col gap-3">
            <DataTable rows={t.check as unknown as Record<string, unknown>[]} columns={cols} />
            {t.tripped > 0 && <Callout tone="warn">{t.tripped} condition tripped: a prompt to look, not a sale.</Callout>}
          </div>
        ) : <p className="mt-3 text-[13px] text-muted">Click Check thesis to compare each condition with the latest figures.</p>}
      </Panel>
      <Panel title="Add figures (or Accept them from the Document Desk)">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-[120px_minmax(0,1fr)_120px_minmax(0,1fr)_auto] md:items-end">
          <Field label="Quarter"><input className={inputCls} value={fig.quarter} onChange={(e) => setFig({ ...fig, quarter: e.target.value })} /></Field>
          <Field label="Metric">
            <Select value={metric} onChange={(e) => setFig({ ...fig, metric: e.target.value })}>
              {t.conditions.map((c) => <option key={c.metric} value={c.metric}>{c.metric}</option>)}
            </Select>
          </Field>
          <Field label="Value"><NumInput value={fig.value} onChange={(v) => setFig({ ...fig, value: v })} /></Field>
          <Field label="Source (page / table)"><input className={inputCls} value={fig.source} onChange={(e) => setFig({ ...fig, source: e.target.value })} /></Field>
          <Button onClick={() => addFig.mutate()} disabled={addFig.isPending || !metric}>Add figure</Button>
        </div>
      </Panel>
      <NewThesisDialog open={adding} onOpenChange={setAdding} names={h?.rows.map((r) => r.name) ?? []} ops={data.ops}
        onSaved={(id) => { setSel(id); setChecked(null); }} />
    </ScreenGrid>
  );
}
