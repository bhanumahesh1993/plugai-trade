import { useEffect, useState } from "react";
import { useMutation, useQuery, keepPreviousData } from "@tanstack/react-query";
import { useSearchParams, Link } from "react-router-dom";
import { ClipboardCheck, Dices } from "lucide-react";
import { get, post, type Market } from "@/lib/api";
import { money, num } from "@/lib/format";
import { Button, Panel, Field, Tabs, TabList, Tab, TabPanel, Slider } from "@/components/ui";
import { Callout, DataTable, EChart, Hypothetical, Segmented, Select, chartTokens, useToast } from "@/components/kit";
import { FactTile, FactsProvider, ExplainPanel } from "@/components/facts";
import { useMarket } from "@/components/shell";
import { Check, ErrorLine, NumField, TextField, useDebounced } from "@/components/planning/common";

const SECTION = "Plan & Risk";
interface PlanLite { id: number; name: string; symbol: string; entry: number | null; stop: number | null; side: string; qty: number | null }
interface Ctx {
  symbol: string; market: Market; lot: number; table_as_of: string; last: number; atr: number; daily_vol: number;
  asof: string; source: string; data_error: string | null; plans: PlanLite[];
  defaults: { account: number; risk_pct: number; cap_pct: number; total_cap_r: number; group_cap_r: number };
}
interface Tile { label: string; value: string; sub?: string | null; big?: boolean; warn?: boolean }
interface SizeOut {
  method: string; unit: string; size: number; quantity: number; tiles: Tile[]; facts: string[];
  notional_warning: string | null; cap_message: string | null; cap_binding: boolean; choices: string[]; notes: string[];
  cost_allowance: number | null; stop: number | null; suggested_stop: number | null; size_text: string; lot: number;
  cap_check: null | { ok: boolean; total_open_r: number; total_cap_r: number; group: string; group_effective_r: number; group_cap_r: number; messages: string[]; facts: string[] };
}

/* ------------------------------------------------------------ result block (tiles, warnings, Explain, Use in plan) */
function SizeResult({ q, planId, body }: { q: { data?: SizeOut; error: unknown }; planId: number | null; body: Record<string, unknown> }) {
  const toast = useToast();
  const use = useMutation({
    mutationFn: () => post<{ plan_id: number; version: number; size_text: string }>("/api/planning/sizer/use-in-plan", { ...body, plan_id: planId }),
    onSuccess: (r) => toast(`Plan #${r.plan_id} updated to version ${r.version}: ${r.size_text}`),
  });
  const r = q.data;
  if (q.error && !r) return <Callout tone="info">{(q.error as Error).message}</Callout>;
  if (!r) return <div className="h-[92px]" />;
  const facts = [...r.facts, ...(r.cap_check?.facts ?? [])];
  return (
    <div className="flex flex-col gap-3">
      {q.error ? <Callout tone="info">{(q.error as Error).message}</Callout> : null}
      <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3 2xl:grid-cols-6">
        {r.tiles.map((t) => (
          <FactTile key={t.label} label={t.label} value={t.value} sub={t.sub ?? undefined} big={t.big}
            tone={t.big && r.size > 0 ? "indigo" : undefined} />
        ))}
      </div>
      {r.notional_warning && <Callout tone="warn">{r.notional_warning}</Callout>}
      {r.cap_message && <Callout tone={r.cap_binding ? "warn" : "info"} title={r.cap_binding ? "Position cap binds" : undefined}>{r.cap_message}</Callout>}
      {r.choices.length > 0 && (
        <Callout tone="danger" title="Size 0. The sizer never rounds up. Your choices:">
          <ul className="list-disc pl-4">{r.choices.map((c) => <li key={c}>{c}</li>)}</ul>
        </Callout>
      )}
      {r.cap_check && (
        <Callout tone={r.cap_check.ok ? "info" : "warn"}>
          Open risk including this trade {num(r.cap_check.total_open_r, "US", 2)}R (cap {r.cap_check.total_cap_r}R). Group “{r.cap_check.group}” behaves
          like {num(r.cap_check.group_effective_r, "US", 2)}R (cap {r.cap_check.group_cap_r}R){r.cap_check.ok ? "." : `: ${r.cap_check.messages.join("; ")}.`}
        </Callout>
      )}
      {r.notes.length > 0 && <ul className="text-[13px] text-muted">{r.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
      <div className="grid gap-4 border-t border-line pt-4 lg:grid-cols-[minmax(0,1fr)_auto]">
        <ExplainPanel facts={facts} section={SECTION} />
        <div className="flex flex-col items-start gap-1.5">
          <Button variant="primary" onClick={() => use.mutate()} disabled={planId === null || r.size === 0 || use.isPending}>
            <ClipboardCheck size={15} /> Use in plan
          </Button>
          <span className="max-w-[240px] text-[12px] text-muted">
            {planId === null ? "Pick a plan above to write this size into it." : "Writes the size (and an ATR stop) into the plan's Size field, as a new version."}
          </span>
          {use.isSuccess && <Link to={`/trade-plan?plan=${planId}`} className="text-[13px] text-indigo underline">Open the plan</Link>}
          <ErrorLine error={use.error} />
        </div>
      </div>
    </div>
  );
}

function useSize(body: Record<string, unknown>, enabled = true) {
  const d = useDebounced(body, 250);
  // Judge the debounced body, so a stale first value never reaches the server.
  const b = d as { method?: string; entry?: number; stop?: number | null; atr?: number | null; daily_vol?: number; account?: number };
  const valid = !!b.entry && !!b.account && (b.method !== "fixed" || b.stop != null) && (b.method !== "atr" || !!b.atr) && (b.method !== "vol" || !!b.daily_vol);
  return useQuery({
    queryKey: ["size", d], enabled: enabled && valid, placeholderData: keepPreviousData, retry: false,
    queryFn: () => post<SizeOut>("/api/planning/sizer/size", d),
  });
}

/* ------------------------------------------------------------ Simulate streaks */
interface StreakRow { risk_pct: number; typical_fall: number; bad_luck_fall: number; share_dd_30: number; share_touch_50: number; median_final: number; streak_median: number; streak_p10: number; streak_p90: number }
interface StreakOut { note: string | null; rows: StreakRow[]; fan: Record<string, number[]>; facts: string[] }

function Streaks({ riskDefault }: { riskDefault: number }) {
  const [s, setS] = useState({ win_rate: 40, win_r: 1.6, loss_r: -1, risk_pct: riskDefault, sequences: 2000, trades: 100, seed: 12, use_journal: false });
  useEffect(() => setS((x) => ({ ...x, risk_pct: riskDefault })), [riskDefault]);
  const run = useMutation({ mutationFn: () => post<StreakOut>("/api/planning/sizer/streaks", s) });
  const r = run.data;
  const p = (x: number) => `${(x * 100).toFixed(1)}%`;
  const t = chartTokens();
  const fan = r?.fan;
  const option = fan && {
    grid: { left: 52, right: 16, top: 16, bottom: 36 },
    tooltip: { trigger: "axis", backgroundColor: t.panel, borderColor: t.line, textStyle: { color: t.ink } },
    xAxis: { type: "category", data: fan.trade, name: "Trade", nameLocation: "middle", nameGap: 24, nameTextStyle: { color: t.muted }, axisLabel: { color: t.muted }, axisLine: { lineStyle: { color: t.line } } },
    yAxis: { type: "value", scale: true, name: "% of start", nameTextStyle: { color: t.muted }, axisLabel: { color: t.muted, formatter: "{value}%" }, splitLine: { lineStyle: { color: t.line } } },
    series: [
      { name: "5th", type: "line", data: fan.p5, stack: "b", lineStyle: { opacity: 0 }, showSymbol: false, silent: true },
      { name: "5th–95th", type: "line", data: fan.p95.map((v, i) => v - fan.p5[i]), stack: "b", lineStyle: { opacity: 0 }, showSymbol: false, areaStyle: { color: t.indigo, opacity: 0.12 }, silent: true },
      { name: "25th", type: "line", data: fan.p25, stack: "m", lineStyle: { opacity: 0 }, showSymbol: false, silent: true },
      { name: "25th–75th", type: "line", data: fan.p75.map((v, i) => v - fan.p25[i]), stack: "m", lineStyle: { opacity: 0 }, showSymbol: false, areaStyle: { color: t.indigo, opacity: 0.22 }, silent: true },
      { name: "Median", type: "line", data: fan.p50, showSymbol: false, lineStyle: { color: t.indigo, width: 2 } },
    ],
  };
  return (
    <Panel title="Simulate streaks" action={<Hypothetical />}>
      <p className="mb-3 text-[13px] text-muted">Monte Carlo of made-up trade sequences with a fixed seed. It shows how deep a normal run of losses goes at your risk per trade, and at half of it.</p>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <NumField label="Win rate (%)" value={s.win_rate} min={1} max={99} onChange={(v) => setS({ ...s, win_rate: v ?? 0 })} />
        <NumField label="Average win (R)" value={s.win_r} step={0.1} onChange={(v) => setS({ ...s, win_r: v ?? 0 })} />
        <NumField label="Average loss (R)" value={s.loss_r} step={0.1} onChange={(v) => setS({ ...s, loss_r: v ?? 0 })} />
        <NumField label="Risk per trade (%)" value={s.risk_pct} step={0.1} onChange={(v) => setS({ ...s, risk_pct: v ?? 0 })} />
        <NumField label="Sequences" value={s.sequences} step={100} min={100} max={20000} onChange={(v) => setS({ ...s, sequences: v ?? 100 })} />
        <NumField label="Trades each" value={s.trades} step={10} min={10} max={1000} onChange={(v) => setS({ ...s, trades: v ?? 10 })} />
        <NumField label="Seed" value={s.seed} step={1} onChange={(v) => setS({ ...s, seed: v ?? 0 })} />
        <div className="flex items-end pb-1"><Check checked={s.use_journal} onChange={(v) => setS({ ...s, use_journal: v })}>Use my journal's R-multiples</Check></div>
      </div>
      <div className="mt-3"><Button variant="primary" onClick={() => run.mutate()} disabled={run.isPending}><Dices size={15} /> {run.isPending ? "Simulating…" : "Simulate streaks"}</Button></div>
      <ErrorLine error={run.error} />
      {r && (
        <div className="mt-4 flex flex-col gap-4">
          {r.note && <Callout tone="info">{r.note}</Callout>}
          <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
            <FactTile big label="Bad-luck fall (95th percentile)" value={p(r.rows[0].bad_luck_fall)} tone="bear" />
            <FactTile label="Typical fall (median max drawdown)" value={p(r.rows[0].typical_fall)} />
            <FactTile label="Paths with a ≥30% fall" value={p(r.rows[0].share_dd_30)} />
            <FactTile label="Longest losing streak" value={r.rows[0].streak_median} sub={`10th–90th ${r.rows[0].streak_p10}–${r.rows[0].streak_p90}`} />
          </div>
          <DataTable rows={r.rows as unknown as Record<string, unknown>[]} columns={[
            { key: "risk_pct", header: "Risk", align: "right", render: (x) => `${((x.risk_pct as number) * 100).toFixed(2)}%` },
            { key: "typical_fall", header: "Typical fall", align: "right", render: (x) => p(x.typical_fall as number) },
            { key: "bad_luck_fall", header: "Bad-luck fall (95th)", align: "right", render: (x) => p(x.bad_luck_fall as number) },
            { key: "share_dd_30", header: "≥ 30% fall", align: "right", render: (x) => p(x.share_dd_30 as number) },
            { key: "share_touch_50", header: "Touch 50%", align: "right", render: (x) => p(x.share_touch_50 as number) },
            { key: "median_final", header: "Median end", align: "right", render: (x) => p(x.median_final as number) },
            { key: "streak_median", header: "Longest losing streak (median, 10th–90th)", align: "right", render: (x) => `${x.streak_median}, ${x.streak_p10}–${x.streak_p90}` },
          ]} />
          <div>
            <div className="mb-1 flex items-center justify-between text-[13px] text-muted"><span>Equity paths at {r.rows[0].risk_pct * 100}% risk: median, 25th–75th and 5th–95th percentile bands</span><Hypothetical /></div>
            {option && <EChart option={option} height={260} />}
          </div>
          <ExplainPanel facts={r.facts} section={SECTION} />
        </div>
      )}
    </Panel>
  );
}

/* ------------------------------------------------------------ Hedge */
function Hedge({ market, ctx }: { market: Market; ctx?: Ctx }) {
  const [h, setH] = useState({ exposure: 20000, side: "receivable", futures_price: 88.4, ratio: 1 });
  const dh = useDebounced(h, 250);
  const inQ = useQuery({ queryKey: ["hedge", dh], enabled: market === "IN", placeholderData: keepPreviousData, retry: false,
    queryFn: () => post<{ lots: number; futures_side: string; lot_usd: number; locked_inr: number; scenarios: Record<string, number>[]; facts: string[]; table_as_of: string }>("/api/planning/sizer/hedge", dh) });
  const risk0 = ctx ? ctx.defaults.account * ctx.defaults.risk_pct / 100 : 400;
  const [u, setU] = useState<{ risk: number; distance: number; contract_size: number | null }>({ risk: risk0, distance: 0.0055, contract_size: null });
  useEffect(() => setU((x) => ({ ...x, risk: risk0 })), [risk0]);
  const du = useDebounced(u, 250);
  const usQ = useQuery({ queryKey: ["hedge-us", du], enabled: market === "US", placeholderData: keepPreviousData, retry: false,
    queryFn: () => post<{ contracts: number; per_contract: number; contract_size: number; table_contract_size: number; facts: string[]; table_as_of: string }>("/api/planning/sizer/hedge-us", du) });

  if (market === "IN") {
    const r = inQ.data;
    return (
      <div className="flex flex-col gap-4">
        <Callout tone="info">Currency derivatives only to hedge a genuine exposure (RBI directions).</Callout>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <NumField label="Exposure ($)" value={h.exposure} step={1000} onChange={(v) => setH({ ...h, exposure: v ?? 0 })} />
          <Field label="Exposure is a">
            <Select value={h.side} onChange={(e) => setH({ ...h, side: e.target.value })} className="font-sans"><option value="receivable">Receivable</option><option value="payable">Payable</option></Select>
          </Field>
          <NumField label="USDINR futures price" value={h.futures_price} step={0.01} onChange={(v) => setH({ ...h, futures_price: v ?? 0 })} />
          <Field label={`Hedge ratio ${h.ratio.toFixed(2)}`}><div className="pt-2"><Slider label="Hedge ratio" min={0} max={1} step={0.25} value={h.ratio} onChange={(v) => setH({ ...h, ratio: v })} /></div></Field>
        </div>
        <ErrorLine error={inQ.error} />
        {r && (
          <>
            <div className="grid grid-cols-3 gap-2.5">
              <FactTile big label="Hedge" value={`${r.futures_side === "sell" ? "Sell" : "Buy"} ${r.lots} lots`} tone="indigo" />
              <FactTile label="Lot" value={`$${r.lot_usd.toLocaleString("en-US")}`} sub={`Dated table, as of ${r.table_as_of}`} />
              <FactTile label="Rupee value locked" value={money(r.locked_inr, "IN")} />
            </div>
            <DataTable rows={r.scenarios} columns={[
              { key: "rate", header: "USDINR at expiry", align: "right", render: (x) => num(x.rate as number, "IN", 2) },
              { key: "invoice_inr", header: "Invoice (₹)", align: "right", render: (x) => money(x.invoice_inr as number, "IN") },
              { key: "futures_pnl", header: "Futures (₹)", align: "right", render: (x) => <span className={(x.futures_pnl as number) >= 0 ? "text-bull" : "text-bear"}>{money(x.futures_pnl as number, "IN")}</span> },
              { key: "total", header: "Total (₹)", align: "right", render: (x) => money(x.total as number, "IN") },
            ]} />
            <p className="text-[12px] text-muted">Illustrative; brokerage, taxes and the bank's conversion spread are left out.</p>
            <ExplainPanel facts={r.facts} section={SECTION} />
          </>
        )}
      </div>
    );
  }
  const r = usQ.data;
  return (
    <div className="flex flex-col gap-4">
      <Callout tone="info">US: size a currency-futures view from the stop, never from the deposit.</Callout>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <NumField label="Risk per trade ($)" value={u.risk} step={10} onChange={(v) => setU({ ...u, risk: v ?? 0 })} />
        <NumField label="Stop distance (price)" value={u.distance} step={0.0005} onChange={(v) => setU({ ...u, distance: v ?? 0 })} />
        <NumField label="Contract size (units)" value={u.contract_size ?? r?.table_contract_size ?? null} step={500}
          hint="From Derivatives › Contract Table" onChange={(v) => setU({ ...u, contract_size: v })} />
      </div>
      {r && !r.table_contract_size && <p className="text-[13px] text-muted">The dated table has no row for this contract yet: type its size from the exchange's contract specifications.</p>}
      <ErrorLine error={usQ.error} />
      {r && (
        <>
          <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3">
            <FactTile big label="Whole contracts (rounded down)" value={r.contracts} tone={r.contracts ? "indigo" : "bear"} />
            <FactTile label="Risk per contract" value={`$${r.per_contract.toFixed(2)}`} />
          </div>
          {r.contracts === 0 && <Callout tone="danger">Size 0: one contract risks more than your budget. Choices: a nearer stop that the market supports, a smaller instrument, or pass.</Callout>}
          <ExplainPanel facts={r.facts} section={SECTION} />
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------ screen */
export default function PositionSizer() {
  const [market] = useMarket();
  const [params, setParams] = useSearchParams();
  const planId = params.get("plan") ? Number(params.get("plan")) : null;
  const [symbolBy, setSymbolBy] = useState<Record<Market, string>>({ IN: "NIFTY FUT", US: "SPY" });
  const [tab, setTab] = useState("fixed");
  const symbolIn = useDebounced(symbolBy[market], 400);

  const { data: base } = useQuery({ queryKey: ["sizer-ctx-plans", market], queryFn: () => get<Ctx>(`/api/planning/sizer/context?market=${market}&symbol=${encodeURIComponent(symbolBy[market])}`) });
  const plan = base?.plans.find((p) => p.id === planId) ?? null;
  useEffect(() => { if (plan?.symbol) setSymbolBy((s) => ({ ...s, [market]: plan.symbol })); /* eslint-disable-next-line */ }, [plan?.id]);
  const { data: ctx } = useQuery({
    queryKey: ["sizer-ctx", market, symbolIn], placeholderData: keepPreviousData,
    queryFn: () => get<Ctx>(`/api/planning/sizer/context?market=${market}&symbol=${encodeURIComponent(symbolIn)}`),
  });

  // Inputs, reset when the market, symbol or plan changes (like the classic page's keyed widgets).
  const d = ctx?.defaults;
  const entry0 = plan?.entry ?? (ctx ? Math.round(ctx.last * 100) / 100 : 0);
  const [c, setC] = useState({ account: 0, risk_pct: 1, cap_pct: 25 });
  const [fx, setFx] = useState<{ entry: number | null; stop: number | null; cost: number | null }>({ entry: null, stop: null, cost: null });
  const [at, setAt] = useState<{ entry: number | null; atr: number | null; multiple: number; side: string; stop: number | null; cost: number | null }>({ entry: null, atr: null, multiple: 1.5, side: "long", stop: null, cost: null });
  const [vt, setVt] = useState<{ target: number; price: number | null; dv: number | null }>({ target: 12, price: null, dv: null });
  const { data: mlBands } = useQuery({ queryKey: ["ml-bands", market], queryFn: () => get<{ symbol?: string; horizon?: number; low_pct: number; middle_pct: number; high_pct: number }>(`/api/planning/sizer/vol-scenarios?market=${market}`) });
  const resetKey = `${market}|${ctx?.symbol}|${planId}|${ctx?.last}`;
  useEffect(() => {
    if (!ctx || !d) return;
    setC({ account: d.account, risk_pct: d.risk_pct, cap_pct: d.cap_pct });
    setFx({ entry: entry0, stop: plan?.stop ?? Math.round(entry0 * 0.99 * 100) / 100, cost: null });
    setAt({ entry: entry0, atr: Math.round(ctx.atr * 100) / 100, multiple: market === "IN" ? 1.5 : 2, side: plan?.side === "short" ? "short" : "long", stop: null, cost: null });
    setVt({ target: 12, price: entry0, dv: Math.max(Math.round(ctx.daily_vol * 10000) / 100, 0.01) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetKey]);
  // A typed cost or stop belongs to the prices it was typed for.
  useEffect(() => setFx((x) => ({ ...x, cost: null })), [fx.entry, fx.stop]);
  useEffect(() => setAt((x) => ({ ...x, stop: null })), [at.entry, at.atr, at.multiple, at.side]);

  const sym = ctx?.symbol ?? symbolBy[market];
  const common = { market, symbol: sym, account: c.account, risk_pct: c.risk_pct, cap_pct: c.cap_pct || null };
  const fixedBody = { ...common, method: "fixed", entry: fx.entry ?? 0, stop: fx.stop, cost_per_lot: fx.cost };
  const atrBody = { ...common, method: "atr", entry: at.entry ?? 0, atr: at.atr, multiple: at.multiple, side: at.side, stop_typed: at.stop, cost_per_lot: at.cost };
  const volBody = { ...common, method: "vol", cap_pct: null, entry: vt.price ?? 0, target_vol: vt.target, daily_vol: vt.dv ?? 0 };
  const ready = !!ctx && c.account > 0;
  const fixedQ = useSize(fixedBody, ready && tab === "fixed" && !!fx.entry && fx.stop !== null);
  const atrQ = useSize(atrBody, ready && tab === "atr" && !!at.entry && !!at.atr);
  const volQ = useSize(volBody, ready && tab === "vol" && !!vt.price && !!vt.dv);
  const unitWord = (ctx?.lot ?? 1) > 1 ? "lot" : "share";

  const commonInputs = (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
      <NumField label="Account" value={c.account} step={1000} onChange={(v) => setC((x) => ({ ...x, account: v ?? 0 }))} />
      <NumField label="Risk per trade (%)" value={c.risk_pct} step={0.05} min={0} max={10} onChange={(v) => setC((x) => ({ ...x, risk_pct: v ?? 0 }))} />
      <NumField label="Position cap (% of account)" value={c.cap_pct} step={1} onChange={(v) => setC((x) => ({ ...x, cap_pct: v ?? 0 }))} />
    </div>
  );

  return (
    <FactsProvider>
      <div className="flex flex-col gap-5">
        <Panel>
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Plan">
              <Select className="w-72 font-sans" value={planId ?? ""} onChange={(e) => setParams(e.target.value ? { plan: e.target.value } : {}, { replace: true })}>
                <option value="">(no plan)</option>
                {base?.plans.map((p) => <option key={p.id} value={p.id}>#{p.id} {p.name} ({p.symbol})</option>)}
              </Select>
            </Field>
            <TextField label="Symbol" className="w-40" value={symbolBy[market]} onChange={(v) => setSymbolBy((s) => ({ ...s, [market]: v.toUpperCase() }))} />
            <div className="flex flex-wrap gap-x-6 gap-y-1 pb-2 text-[13px] text-muted">
              <span>Last <b className="num font-medium text-ink">{ctx ? num(ctx.last, market) : "…"}</b></span>
              <span>ATR (14) <b className="num font-medium text-ink">{ctx ? num(ctx.atr, market) : "…"}</b></span>
              <span>Daily move <b className="num font-medium text-ink">{ctx ? `${(ctx.daily_vol * 100).toFixed(2)}%` : "…"}</b></span>
              <span>Data {ctx?.source}, as of {ctx?.asof}</span>
              {ctx && ctx.lot > 1 && <span>Lot size <b className="num font-medium text-ink">{ctx.lot}</b>, dated table as of {ctx.table_as_of} (Derivatives › Contract Table)</span>}
            </div>
          </div>
          {ctx?.data_error && <p className="mt-2 text-[13px] text-muted">{ctx.data_error}</p>}
          <p className="mt-3 text-[13px] text-muted">Size = risk budget ÷ risk per unit, rounded down. Every tile is computed in code; lot sizes and costs come from the dated tables.</p>
        </Panel>

        <Panel>
          <Tabs value={tab} onValueChange={setTab}>
            <TabList>
              <Tab value="fixed">Fixed risk %</Tab>
              <Tab value="atr">ATR stop</Tab>
              <Tab value="vol">Vol target</Tab>
              <Tab value="hedge">Hedge</Tab>
            </TabList>
            <TabPanel value="fixed" className="flex flex-col gap-4 pt-4">
              {commonInputs}
              <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
                <NumField label="Entry" value={fx.entry} onChange={(v) => setFx((x) => ({ ...x, entry: v }))} />
                <NumField label="Stop" value={fx.stop} onChange={(v) => setFx((x) => ({ ...x, stop: v }))} />
                <NumField label={`Costs / ${unitWord} (allowance)`} value={fx.cost ?? fixedQ.data?.cost_allowance ?? null}
                  hint={`Dated cost table (as of ${ctx?.table_as_of ?? "…"}) plus slippage; edit to yours`} onChange={(v) => setFx((x) => ({ ...x, cost: v }))} />
              </div>
              <SizeResult q={fixedQ} planId={planId} body={fixedBody} />
            </TabPanel>
            <TabPanel value="atr" className="flex flex-col gap-4 pt-4">
              {commonInputs}
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <NumField label="Trigger / entry" value={at.entry} onChange={(v) => setAt((x) => ({ ...x, entry: v }))} />
                <NumField label="ATR (14)" value={at.atr} hint={`From the lab's data, as of ${ctx?.asof ?? "…"}`} onChange={(v) => setAt((x) => ({ ...x, atr: v }))} />
                <NumField label="ATR multiple" value={at.multiple} step={0.1} onChange={(v) => setAt((x) => ({ ...x, multiple: v ?? 0 }))} />
                <Field label="Side"><Segmented label="Side" value={at.side} options={[{ value: "long", label: "Long" }, { value: "short", label: "Short" }]} onChange={(v) => setAt((x) => ({ ...x, side: v }))} /></Field>
              </div>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <FactTile label="Stop" value={atrQ.data?.suggested_stop != null ? num(atrQ.data.suggested_stop, market) : "—"}
                  sub={at.entry && at.atr ? `${num(at.entry, market)} ${at.side === "long" ? "−" : "+"} ${at.multiple} × ${at.atr}` : undefined} />
                <NumField label="Stop (tile suggests; type to round to your tick)" value={at.stop ?? atrQ.data?.suggested_stop ?? null}
                  onChange={(v) => setAt((x) => ({ ...x, stop: v, cost: null }))} />
                <NumField label={`Costs / ${unitWord}`} value={at.cost ?? atrQ.data?.cost_allowance ?? null} onChange={(v) => setAt((x) => ({ ...x, cost: v }))} />
              </div>
              <SizeResult q={atrQ} planId={planId} body={atrBody} />
            </TabPanel>
            <TabPanel value="vol" className="flex flex-col gap-4 pt-4">
              {mlBands?.middle_pct != null && (
                <Callout title={`Volatility scenarios from ML Lab (${mlBands.symbol ?? ""}, next ${mlBands.horizon} sessions)`}>
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    <span className="text-[13px]">Use as the daily move:</span>
                    {([["Low (calm)", mlBands.low_pct], ["Middle", mlBands.middle_pct], ["High (stressed)", mlBands.high_pct]] as [string, number][]).map(([lbl, v]) => (
                      <Button key={lbl} size="sm" onClick={() => setVt((x) => ({ ...x, dv: Math.round(v * 100) / 100 }))}>
                        {lbl} {v.toFixed(2)}%
                      </Button>
                    ))}
                  </div>
                </Callout>
              )}
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <NumField label="Account" value={c.account} step={1000} onChange={(v) => setC((x) => ({ ...x, account: v ?? 0 }))} />
                <NumField label="Target volatility (% a year)" value={vt.target} step={0.5} onChange={(v) => setVt((x) => ({ ...x, target: v ?? 0 }))} />
                <NumField label="Price" value={vt.price} onChange={(v) => setVt((x) => ({ ...x, price: v }))} />
                <NumField label="Instrument's daily move (%)" value={vt.dv} step={0.05} hint={`From the lab's data, as of ${ctx?.asof ?? "…"}`} onChange={(v) => setVt((x) => ({ ...x, dv: v }))} />
              </div>
              <SizeResult q={volQ} planId={planId} body={volBody} />
              <p className="text-[13px] text-muted">The sizer shows the choices side by side and applies none of them until you click Use in plan.</p>
            </TabPanel>
            <TabPanel value="hedge" className="pt-4">
              <Hedge market={market} ctx={ctx} />
            </TabPanel>
          </Tabs>
        </Panel>

        <Streaks riskDefault={d?.risk_pct ?? 1} />
      </div>
    </FactsProvider>
  );
}
