/* Paper Desk parts: types, the paper order ticket, pending paper orders and Compare with backtest. */
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, keepPreviousData } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Link2, GitCompare } from "lucide-react";
import { post, type Market } from "@/lib/api";
import { money, num } from "@/lib/format";
import { cn } from "@/lib/cn";
import { Button, Panel, Field, inputCls } from "@/components/ui";
import { Badge, Callout, DataTable, EChart, Hypothetical, Segmented, Select, chartTokens, useToast } from "@/components/kit";
import { FactTile, ExplainPanel } from "@/components/facts";
import { ErrorLine, NumField, useDebounced } from "./common";

/* ------------------------------------------------------------ types */
export interface Order { id: number; symbol: string; side: string; qty: number; kind: string; price: number | null; stop: number | null; target: number | null; status: string; filled_qty: number; avg_fill: number; reason: string; purpose: string; unplanned: boolean; placed_at: string; plan_id: number | null; source: string }
export interface Position { id: number; symbol: string; side: string; qty: number; entry: number; last: number; stop: number | null; target: number | null; open_pnl: number; unplanned: boolean; closing: boolean; funding: number; funding_rate: number | null; opened_at: string; plan_id: number | null; stop_moves: { from: number | null; to: number; reason: string; away_from_entry: boolean }[]; rule_breaks: string[] }
export interface Trade { symbol: string; side: string; qty: number; entry: number; exit: number; entry_ref: number; exit_ref: number; exit_reason: string; slippage: number; costs_total: number; funding: number; net: number; r: number | null; mode: string; exit_time: string }
export interface Pending { id: number; source: string; symbol?: string; side?: string; qty?: number; kind?: string; price?: number | null; stop?: number | null; note?: string; market?: string; multi_leg: boolean; strategy_name?: string | null; legs: { side: string; kind: string; strike: number; qty: number; expiry?: string }[]; link_id?: string; hedge_ratio?: number; exits?: Record<string, number>; events?: string }
export interface Ticket { id: number; source: string; symbol: string; side: string; qty: number; kind: string; price: number | null; stop: number | null; target: number | null; plan_id: number | null }
export interface Drift { bars: number; source: string; start: string; end: string; symbol: string; shadow_r: number; paper_r: number; gap_r: number; cost_gap_r: number; break_gap_r: number; signals: number; taken: number; adherence: number; curve: { signal: string; shadow: number; paper: number }[]; breaks: { signal: string; kind: string; shadow_r: number | null; paper_r: number | null; cost_r: number; break_r: number; trade_id: number | null; note: string; saved_note: string | null }[]; facts: string[] }
export interface DeskState {
  market: Market; symbol: string; mode: string; session: "LIVE" | "Replay"; now: string; cash: number; equity: number; day_pnl: number; realised: number; starting_balance: number; killed: boolean;
  limits: { daily_loss_limit: number; one_r: number; max_trades_per_day: number; trading_window: string };
  guardrails: { trades_left: number | null; cooldown_min: number; day_r: number | null; day_pnl: number; daily_loss_limit: number; next_lockout: string | null; blocked: boolean };
  blocked_now: string | null; live: { ok: boolean; source: string };
  replay: { symbol: string; day: string; interval: string; speed: number; cursor: number; total: number; done: boolean };
  symbols: string[]; instruments: Record<string, { lot: number; kind: string; half_spread: number; slippage: number; cur: string }>;
  orders: Order[]; working: Order[]; positions: Position[]; trades: Trade[]; blocked: Record<string, unknown>[];
  tape: { date: string; time?: string; open: number; high: number; low: number; close: number }[];
  last_prices: Record<string, number>; pending: Pending[]; ticket: Ticket | null; plans: { id: number; name: string }[]; drift: Drift | null;
  handoff: Handoff | null;
}
export interface Fill { time: string; side: string; symbol: string; price: number; kind: string }
export interface Handoff { day: string; source: string; fills: Fill[] }
interface Preview { ready: boolean; reason?: string; price: number; items: Record<string, number>; charges: number; slippage_per_side: number; slippage_money: number; all_in: number; breakeven_pts: number; target_pts: number | null; amber: string | null; table_as_of: string }

const KINDS = [{ value: "market", label: "Market" }, { value: "limit", label: "Limit" }, { value: "stop", label: "Stop-entry" }];

/* ------------------------------------------------------------ ticket */
export function PaperTicket({ s, onState }: { s: DeskState; onState: (d: DeskState) => void }) {
  const m = s.market;
  const toast = useToast();
  const t = s.ticket;
  const syms = useMemo(() => (t && !s.symbols.includes(t.symbol) ? [t.symbol, ...s.symbols] : s.symbols), [s.symbols, t]);
  const [symbol, setSymbol] = useState(t?.symbol ?? s.replay.symbol ?? syms[0]);
  const inst = s.instruments[symbol] ?? { lot: 1, half_spread: 0, slippage: 0, kind: "equity", cur: m === "IN" ? "₹" : "$" };
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [lots, setLots] = useState<number | null>(1);
  const [kind, setKind] = useState("market");
  const [price, setPrice] = useState<number | null>(null);
  const [stop, setStop] = useState<number | null>(null);
  const [target, setTarget] = useState<number | null>(null);
  const [planId, setPlanId] = useState<number | null>(null);
  const [slipOpen, setSlipOpen] = useState(false);
  const [showCost, setShowCost] = useState(false);
  const [hs, setHs] = useState<number | null>(inst.half_spread);
  const [sl, setSl] = useState<number | null>(inst.slippage);

  // A ticket handed over by Trade Plan › Send to Paper Desk fills the form once.
  useEffect(() => {
    if (!t) return;
    const lot = s.instruments[t.symbol]?.lot ?? 1;
    setSymbol(t.symbol); setSide(t.side === "sell" ? "sell" : "buy"); setLots(Math.max(1, Math.floor((t.qty || lot) / lot)));
    setKind(t.kind || "market"); setPrice(t.price); setStop(t.stop); setTarget(t.target); setPlanId(t.plan_id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [t?.id]);
  useEffect(() => { setHs(inst.half_spread); setSl(inst.slippage); }, [symbol, inst.half_spread, inst.slippage]);
  const last = s.last_prices[symbol];
  useEffect(() => { if (kind !== "market" && price === null && last) setPrice(Math.round(last * 100) / 100); }, [kind]); // eslint-disable-line react-hooks/exhaustive-deps

  const assume = useMutation({ mutationFn: () => post<DeskState>("/api/paper/assumptions", { market: m, symbol, half_spread: hs ?? 0, slippage: sl ?? 0 }), onSuccess: onState });
  const dAssume = useDebounced(`${hs}|${sl}`, 400);
  useEffect(() => {
    if (hs === null || sl === null) return;
    if (hs !== inst.half_spread || sl !== inst.slippage) assume.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dAssume]);

  const qty = (lots ?? 0) * inst.lot;
  const pv = useDebounced({ market: m, symbol, side, qty, price: kind === "market" ? null : price, target, hs: inst.half_spread, sl: inst.slippage, last }, 200);
  const { data: cp } = useQuery({ queryKey: ["paper-preview", pv], placeholderData: keepPreviousData, queryFn: () => post<Preview>("/api/paper/preview", pv) });
  const place = useMutation({
    mutationFn: () => post<DeskState & { placed: Order }>("/api/paper/order", {
      market: m, symbol, side, qty, kind, price: kind === "market" ? null : price, stop, target, plan_id: planId, ticket_id: t?.id ?? null,
    }),
    onSuccess: (d) => {
      onState(d);
      const o = d.placed;
      if (o.status === "BLOCKED") toast(`Blocked: ${o.reason}. Logged in Journal › Trades`, "danger");
      else toast(`Placed paper order #${o.id}: working, it fills on a later bar`);
    },
  });

  return (
    <Panel title="Paper order ticket" className="self-start">
      <div className="-mx-4 -mt-4 mb-4 border-b border-line bg-indigo-soft px-4 py-2 text-[13px] text-indigo">Paper. Simulated fills only; nothing is sent to a broker.</div>
      <div className="flex flex-col gap-3">
        {t && <Callout tone="info">Filled in from {t.source}. Check it, then Place paper order.</Callout>}
        <Field label="Contract">
          <Select className="font-sans" value={symbol} onChange={(e) => setSymbol(e.target.value)}>{syms.map((x) => <option key={x}>{x}</option>)}</Select>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Side"><Segmented label="Side" value={side} options={[{ value: "buy", label: "Buy" }, { value: "sell", label: "Sell" }]} onChange={setSide} /></Field>
          <NumField label={inst.lot > 1 ? `Lots (1 lot = ${inst.lot})` : "Quantity"} value={lots} step={1} min={1} onChange={setLots} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Type"><Select className="font-sans" value={kind} onChange={(e) => setKind(e.target.value)}>{KINDS.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}</Select></Field>
          <NumField label="Limit / trigger price" value={kind === "market" ? null : price} disabled={kind === "market"} placeholder={kind === "market" ? "next bar's open" : ""} onChange={setPrice} />
          <NumField label="Stop" value={stop} onChange={setStop} />
          <NumField label="Planned target (optional)" value={target} onChange={setTarget} />
        </div>
        <Field label="Plan">
          <Select className="font-sans" value={planId ?? ""} onChange={(e) => setPlanId(e.target.value ? Number(e.target.value) : null)}>
            <option value="">(no plan: unplanned)</option>
            {s.plans.map((p) => <option key={p.id} value={p.id}>#{p.id} {p.name}</option>)}
          </Select>
        </Field>

        <div className="rounded-[var(--radius-tile)] border border-line">
          <button type="button" onClick={() => setSlipOpen((o) => !o)} aria-expanded={slipOpen} className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-[13px]">
            {slipOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />} Slippage setting
          </button>
          {slipOpen && (
            <div className="grid grid-cols-2 gap-3 border-t border-line p-3">
              <p className="col-span-2 text-[12px] text-muted">Same meaning as the backtester's.</p>
              <NumField label="Half spread (price units)" value={hs} step={0.01} min={0} onChange={setHs} />
              <NumField label="Slippage (price units)" value={sl} step={0.01} min={0} onChange={setSl} />
            </div>
          )}
        </div>

        <div className="grid grid-cols-[minmax(0,1fr)_auto] items-end gap-3">
          <FactTile big label="Breakeven (pts)" value={cp?.ready ? num(cp.breakeven_pts, m, 2) : "—"}
            sub={cp?.ready ? `All-in ${money(cp.all_in, m, 2)} ÷ ${qty} units` : cp?.reason ?? "Needs a price: type one or feed a bar"} />
          <Button size="sm" onClick={() => setShowCost((x) => !x)} disabled={!cp?.ready} aria-expanded={showCost}>Cost preview</Button>
        </div>
        {showCost && cp?.ready && (
          <div className="rounded-[var(--radius-tile)] border border-line bg-panel-2 p-3">
            <table className="w-full text-[13px]">
              <tbody>
                {Object.entries(cp.items).filter(([k]) => k !== "total").map(([k, v]) => (
                  <tr key={k}><td className="py-0.5 pr-2 text-muted">{["stt", "gst", "sebi", "dp"].includes(k) ? k.toUpperCase() : k.replace(/^./, (c) => c.toUpperCase())}</td><td className="num text-right">{money(v, m, 2)}</td></tr>
                ))}
                <tr className="border-t border-line"><td className="py-0.5">Charges</td><td className="num text-right">{money(cp.charges, m, 2)}</td></tr>
                <tr><td className="py-0.5">Slippage {cp.slippage_per_side} a side</td><td className="num text-right">{money(cp.slippage_money, m, 2)}</td></tr>
                <tr className="border-t border-line font-medium"><td className="py-0.5">All-in</td><td className="num text-right">{money(cp.all_in, m, 2)}</td></tr>
              </tbody>
            </table>
            <p className="mt-2 text-[12px] text-muted">Charges from the dated cost table, as of {cp.table_as_of}; live values in Derivatives › Contract Table.</p>
          </div>
        )}
        {cp?.amber && <Callout tone="warn">{cp.amber}</Callout>}
        {planId === null && <p className="text-[13px] text-muted">Unplanned: this paper order is not linked to a saved Trade Plan; the journal counts it.</p>}
        <Button variant="primary" onClick={() => place.mutate()} disabled={s.killed || place.isPending || !qty}>Place paper order</Button>
        <ErrorLine error={place.error ?? assume.error} />
        {s.killed && <p className="text-[13px] text-bear">Kill switch is on for this session. New paper orders are blocked.</p>}
      </div>
    </Panel>
  );
}

/* ------------------------------------------------------------ pending paper orders */
export function PendingOrders({ s, onState }: { s: DeskState; onState: (d: DeskState) => void }) {
  const toast = useToast();
  const act = useMutation({
    mutationFn: ({ id, action }: { id: number; action: "accept" | "reject" }) => post<DeskState & { accepted?: Order | null }>(`/api/paper/pending/${id}/${action}?market=${s.market}`),
    onSuccess: (d, v) => {
      onState(d);
      if (v.action === "reject") return toast(`Rejected pending paper order #${v.id}`);
      if (!d.accepted) return toast("Accepted for tracking. Multi-leg strategies are not filled by the bar model");
      toast(d.accepted.status === "BLOCKED" ? `Blocked: ${d.accepted.reason}` : `Accepted: paper order #${d.accepted.id} working`, d.accepted.status === "BLOCKED" ? "danger" : "ok");
    },
  });
  if (!s.pending.length) return null;
  const groups: { link?: string; rows: Pending[] }[] = [];
  for (const r of s.pending) {
    const g = r.link_id ? groups.find((x) => x.link === r.link_id) : undefined;
    if (g) g.rows.push(r); else groups.push({ link: r.link_id, rows: [r] });
  }
  const row = (r: Pending) => (
    <li key={r.id} className="flex flex-wrap items-center gap-3 py-2">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="num text-muted">#{r.id}</span>
          {r.multi_leg ? <span className="font-medium">{r.strategy_name ?? r.kind ?? "Strategy"}</span>
            : <span className="font-medium"><span className="capitalize">{r.side}</span> {r.qty} {r.symbol}, {r.kind === "stop" ? "stop-entry" : r.kind}{r.price ? ` at ${r.price}` : ""}{r.stop ? `, stop ${r.stop}` : ""}</span>}
          <Badge>{r.source}</Badge>
          {r.multi_leg && <Badge tone="indigo">{r.legs.length}-leg</Badge>}
        </div>
        {r.multi_leg && r.legs.length > 0 && (
          <div className="mt-1 text-[13px] text-muted">{r.legs.map((l, i) => <span key={i} className="mr-3 capitalize">{l.side} {l.qty} {l.kind} {l.strike}</span>)}</div>
        )}
        {r.note && <div className="mt-0.5 text-[13px] text-muted">{r.note}</div>}
      </div>
      <Button size="sm" variant="primary" onClick={() => act.mutate({ id: r.id, action: "accept" })} disabled={act.isPending}>Accept</Button>
      <Button size="sm" variant="quiet" onClick={() => act.mutate({ id: r.id, action: "reject" })} disabled={act.isPending}>Reject</Button>
    </li>
  );
  return (
    <Panel title="Pending paper orders" action={<span className="text-[13px] text-muted">Drafted elsewhere; nothing happens until you click</span>}>
      <div className="flex flex-col gap-3">
        {groups.map((g, i) => g.link ? (
          <div key={g.link} className="rounded-[var(--radius-tile)] border border-indigo/30 px-3">
            <div className="flex flex-wrap items-center gap-2 pt-2 text-[13px] text-indigo"><Link2 size={14} /> Linked legs {g.link}
              {g.rows[0].hedge_ratio != null && <span className="text-muted">, hedge ratio {g.rows[0].hedge_ratio}</span>}
              {g.rows[0].events && <span className="text-muted">, events {g.rows[0].events}</span>}</div>
            <ul className="divide-y divide-line">{g.rows.map(row)}</ul>
          </div>
        ) : <ul key={i} className="divide-y divide-line">{g.rows.map(row)}</ul>)}
      </div>
      <ErrorLine error={act.error} />
    </Panel>
  );
}

/* ------------------------------------------------------------ Compare with backtest */
const RULE = "Buy at the next open on the first close above the 20-day average; sell at the next open when the close is below the 20-day average";
const iso = (d: Date) => d.toISOString().slice(0, 10);

function BreakNote({ market, b }: { market: Market; b: Drift["breaks"][number] }) {
  const toast = useToast();
  const [text, setText] = useState(b.saved_note ?? "");
  const save = useMutation({ mutationFn: () => post("/api/paper/compare/note", { market, signal: b.signal, trade_id: b.trade_id, text }), onSuccess: () => toast("Saved note for the weekly review") });
  return (
    <div className="flex min-w-[240px] gap-1.5">
      <input aria-label={`Why the ${b.kind} on ${b.signal} happened`} className={cn(inputCls, "h-7 font-sans text-[13px]")} placeholder="Why it happened (one line)" value={text} onChange={(e) => setText(e.target.value)} />
      <Button size="sm" onClick={() => save.mutate()} disabled={!text.trim() || save.isPending}>Save note</Button>
    </div>
  );
}

export function CompareWithBacktest({ s, onDrift }: { s: DeskState; onDrift: () => void }) {
  const m = s.market;
  const [open, setOpen] = useState(!!s.drift);
  const [rule, setRule] = useState(RULE);
  const [from, setFrom] = useState(iso(new Date(new Date().getFullYear(), new Date().getMonth(), 1)));
  const [to, setTo] = useState(iso(new Date()));
  const [sym, setSym] = useState(s.symbols[0]);
  useEffect(() => setSym(s.symbols[0]), [m]); // eslint-disable-line react-hooks/exhaustive-deps
  const run = useMutation({ mutationFn: () => post<Drift>("/api/paper/compare", { market: m, rule, symbol: sym, start: from, end: to }), onSuccess: onDrift });
  const r = run.data ?? s.drift;
  const t = chartTokens();
  const R = (x: number | null | undefined) => (x == null ? "—" : `${x >= 0 ? "+" : "−"}${Math.abs(x).toFixed(2)}R`);
  return (
    <section className="rounded-[var(--radius-panel)] border border-line bg-panel">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-[14px] font-semibold">
        <GitCompare size={16} /> Compare with backtest
        <span className="ml-auto text-[13px] font-normal text-muted">Same rule, same bars, same fills</span>
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
      </button>
      {open && (
          <div className="flex flex-col gap-4 border-t border-line p-4">
            <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_160px_160px_180px]">
              <Field label="Rule (read-back text)"><input className={cn(inputCls, "font-sans")} value={rule} onChange={(e) => setRule(e.target.value)} /></Field>
              <Field label="From"><input type="date" className={inputCls} value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
              <Field label="To"><input type="date" className={inputCls} value={to} onChange={(e) => setTo(e.target.value)} /></Field>
              <Field label="Contract"><Select className="font-sans" value={sym} onChange={(e) => setSym(e.target.value)}>{s.symbols.map((x) => <option key={x}>{x}</option>)}</Select></Field>
            </div>
            <div className="flex items-center gap-3">
              <Button variant="primary" onClick={() => run.mutate()} disabled={run.isPending}>{run.isPending ? "Running…" : "Run shadow backtest"}</Button>
              {r && <span className="text-[13px] text-muted">{r.bars} bars recorded for {r.symbol}, {r.start} to {r.end}; source {r.source}</span>}
            </div>
            <ErrorLine error={run.error} />
            {r && (
              <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
                <div className="flex min-w-0 flex-col gap-4">
                  <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
                    <FactTile big label="Gap" value={R(r.gap_r)} sub="Shadow minus paper" />
                    <FactTile label="Shadow backtest" value={R(r.shadow_r)} tone={r.shadow_r >= 0 ? "bull" : "bear"} />
                    <FactTile label="Paper" value={R(r.paper_r)} tone={r.paper_r >= 0 ? "bull" : "bear"} />
                    <FactTile label="Rule adherence" value={`${(r.adherence * 100).toFixed(1)}%`} sub={`${r.taken} of ${r.signals} signals taken`} />
                    <FactTile label="Cost gap" value={R(r.cost_gap_r)} sub="Costs" />
                    <FactTile label="Rule-break gap" value={R(r.break_gap_r)} sub="Rule breaks" />
                  </div>
                  <div>
                    <div className="mb-1 flex items-center justify-between text-[13px] text-muted"><span>Cumulative R by signal: shadow backtest and paper</span><Hypothetical /></div>
                    {r.curve.length ? (
                      <EChart height={220} option={{
                        grid: { left: 48, right: 16, top: 24, bottom: 32 },
                        legend: { data: ["Shadow backtest", "Paper"], textStyle: { color: t.muted }, top: 0, right: 0 },
                        tooltip: { trigger: "axis", backgroundColor: t.panel, borderColor: t.line, textStyle: { color: t.ink } },
                        xAxis: { type: "category", data: r.curve.map((c) => c.signal), axisLabel: { color: t.muted }, axisLine: { lineStyle: { color: t.line } } },
                        yAxis: { type: "value", axisLabel: { color: t.muted, formatter: "{value}R" }, splitLine: { lineStyle: { color: t.line } } },
                        series: [
                          { name: "Shadow backtest", type: "line", data: r.curve.map((c) => c.shadow), lineStyle: { color: t.muted, type: "dashed" }, itemStyle: { color: t.muted } },
                          { name: "Paper", type: "line", data: r.curve.map((c) => c.paper), lineStyle: { color: t.indigo, width: 2 }, itemStyle: { color: t.indigo } },
                        ],
                      }} />
                    ) : <p className="text-[13px] text-muted">No signals in this period.</p>}
                  </div>
                  <DataTable rows={r.breaks as unknown as Record<string, unknown>[]} empty="No rule breaks: every gap in this period is costs."
                    columns={[
                      { key: "signal", header: "Signal" },
                      { key: "kind", header: "Break", render: (b) => <span className="capitalize">{b.kind as string}</span> },
                      { key: "shadow_r", header: "Shadow R", align: "right", render: (b) => R(b.shadow_r as number | null) },
                      { key: "paper_r", header: "Paper R", align: "right", render: (b) => R(b.paper_r as number | null) },
                      { key: "break_r", header: "Gap R", align: "right", render: (b) => R(b.break_r as number) },
                      { key: "trade_id", header: "Trade", render: (b) => (b.trade_id ? `#${b.trade_id}` : "—") },
                      { key: "note", header: "Note", render: (b) => <BreakNote market={m} b={b as unknown as Drift["breaks"][number]} /> },
                    ]} />
                  <p className="text-[13px] text-muted">If the cost gap is consistently larger than your assumption, update the slippage setting in the rule cards and note that this is a new version of the rule.</p>
                </div>
                <Panel title="Explain the gap"><ExplainPanel facts={r.facts} section="Paper Trading" sensitive /></Panel>
              </div>
            )}
          </div>
      )}
    </section>
  );
}
