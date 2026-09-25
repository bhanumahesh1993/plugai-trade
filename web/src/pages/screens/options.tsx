import { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post, type Market } from "@/lib/api";
import { money } from "@/lib/format";
import { cn } from "@/lib/cn";
import { Button, Panel, Slider, Field, inputCls } from "@/components/ui";
import { Callout, EmptyState, Hypothetical, Segmented, useToast } from "@/components/kit";
import { FactTile, FactsProvider, ExplainPanel } from "@/components/facts";
import { PayoffChart } from "@/components/charts";
import { useMarket } from "@/components/shell";
import { NumberField, Note, PAPER_NOTE } from "@/components/derivatives/common";
import {
  AddLeg, AddLegButton, AttributionStrip, IVPanel, LegTable, MarginPanel, ScenarioTiles, StressTable,
  type Attribution, type IVData, type LegIn, type LegOut, type MarginInfo, type StressRow,
} from "@/components/derivatives/options-parts";

interface Underlying { symbol: string; market: Market; spot: number; step: number; lot: number; lot_note: string; strike: number; choices: string[]; presets: string[] }
interface Quote {
  symbol: string; spot: number; lot: number; name: string; tiles: Record<string, string>; single: boolean; per: string;
  payoff: { spot: number[]; expiry: number[]; now: number[] }; band: [number, number]; breakevens: number[];
  facts: string[]; leg_lines: string[]; legs: LegOut[]; days_left: number; days_slider_max: number; step: number;
  lot_note: string; chain_label: string; rate: number; margin: MarginInfo;
}
interface ScenarioOut { single: boolean; tiles: Record<string, string>; facts: string[]; days_left: number; attribution: Attribution }
interface StressOut { rows: StressRow[]; max_loss: number | null; worst: number; facts: string[] }
interface PlanRow { id: number; created: string; name: string; version: number; exit_rule: string; has_explanation: boolean; legs: number }

interface Setup { symbol: string; spot: number | null; iv: number | null; legs: LegIn[]; name: string; account: string }
const START: Record<Market, Setup> = {
  IN: { symbol: "NIFTY", spot: null, iv: null, name: "", account: "cash", legs: [{ kind: "call", strike: 25000, side: "buy", qty: 1, expiry: "weekly" }] },
  US: { symbol: "SPY", spot: null, iv: null, name: "", account: "cash", legs: [{ kind: "call", strike: 565, side: "buy", qty: 1, expiry: "weekly" }] },
};

const TONE: Record<string, "bull" | "bear" | "indigo" | undefined> = {
  "Max loss": "bear", "Credit": "bull", "Max profit": "bull", "Required move": "indigo",
};
/** Theta is a cost when it is negative (buyers) and income when positive (sellers). */
const toneOf = (k: string, v: string) =>
  k === "Theta/day" ? (v.trim().startsWith("−") || v.trim().startsWith("-") ? "bear" : "bull") : TONE[k];

export default function OptionsBuilder() {
  const [market] = useMarket();
  const toast = useToast();
  const qc = useQueryClient();
  const [setups, setSetups] = useState<Record<Market, Setup>>(START);
  const s = setups[market];
  const patch = (p: Partial<Setup>) => setSetups((x) => ({ ...x, [market]: { ...x[market], ...p } }));
  const [symbolDraft, setSymbolDraft] = useState(s.symbol);
  useEffect(() => setSymbolDraft(s.symbol), [s.symbol, market]);
  const [days, setDays] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  const [gap, setGap] = useState<number | null>(0);
  const [ivChg, setIvChg] = useState<number | null>(0);
  const [scnOn, setScnOn] = useState(false);
  const [tableOn, setTableOn] = useState(false);
  const [extra, setExtra] = useState<{ label: string; gap_pct: number; iv_pts: number | null }[]>([]);
  const [own, setOwn] = useState<{ label: string; gap: number | null; iv: number | null }>({ label: "", gap: -12, iv: 20 });
  const [exitRule, setExitRule] = useState("");
  const [accepted, setAccepted] = useState("");

  const setLegs = (legs: LegIn[], name = s.name) => { patch({ legs, name }); setDays(null); };
  const spec = { symbol: s.symbol, market, legs: s.legs, spot: s.spot, iv_pct: s.iv, name: s.name, account: s.account };

  const und = useQuery({
    queryKey: ["opt-und", market, s.symbol],
    queryFn: () => get<Underlying>(`/api/options/underlying?symbol=${encodeURIComponent(s.symbol)}&market=${market}`),
  });
  const spot = s.spot ?? und.data?.spot ?? 0;
  const step = und.data?.step ?? 1;

  const { data: q, error, isFetching } = useQuery({
    queryKey: ["opt", spec, days],
    queryFn: () => post<Quote>("/api/options/quote", { ...spec, days_left: days }),
    placeholderData: keepPreviousData,
    enabled: s.legs.length > 0,
  });
  const iv = useQuery({ queryKey: ["opt-iv", s.symbol], queryFn: () => get<IVData>(`/api/options/iv?symbol=${encodeURIComponent(s.symbol)}`) });
  const scn = useQuery({
    queryKey: ["opt-scn", spec, days, gap, ivChg],
    queryFn: () => post<ScenarioOut>("/api/options/scenario", { ...spec, days_left: days, gap: gap ?? 0, iv_change: ivChg ?? 0 }),
    enabled: scnOn && s.legs.length > 0, placeholderData: keepPreviousData,
  });
  const stress = useQuery({
    queryKey: ["opt-stress", spec, extra],
    queryFn: () => post<StressOut>("/api/options/stress", { ...spec, extra }),
    enabled: tableOn && s.legs.length > 0, placeholderData: keepPreviousData,
  });
  const planName = q?.name ?? "";
  const history = useQuery({
    queryKey: ["opt-plans", planName],
    queryFn: () => get<{ plans: PlanRow[] }>(`/api/options/plans?name=${encodeURIComponent(planName)}`),
    enabled: !!planName,
  });

  const loadSymbol = async (sym: string) => {
    const clean = sym.trim().toUpperCase();
    if (!clean || clean === s.symbol) return;
    try {
      const u = await get<Underlying>(`/api/options/underlying?symbol=${encodeURIComponent(clean)}&market=${market}`);
      patch({ symbol: u.symbol, spot: null, name: "", legs: [{ kind: "call", strike: u.strike, side: "buy", qty: 1, expiry: "weekly" }] });
      setDays(null);
    } catch (e) {
      toast((e as Error).message, "danger");
      setSymbolDraft(s.symbol);
    }
  };
  const loadPreset = useMutation({
    mutationFn: (name: string) => post<{ name: string; legs: LegIn[] }>("/api/options/preset", { name, symbol: s.symbol, market, spot: s.spot }),
    onSuccess: (r) => { setLegs(r.legs, r.name); toast(`Loaded ${r.name}`); },
    onError: (e) => toast((e as Error).message, "danger"),
  });

  const allFacts = useMemo(() => [
    ...(q?.facts ?? []), ...(iv.data?.facts ?? []),
    ...(scnOn ? scn.data?.facts ?? [] : []), ...(tableOn ? stress.data?.facts ?? [] : []),
    ...(scnOn ? scn.data?.attribution.facts ?? [] : []), ...(q?.leg_lines ?? []), ...(q?.margin.facts ?? []),
  ], [q, iv.data, scn.data, stress.data, scnOn, tableOn]);

  const save = useMutation({
    mutationFn: () => post<{ version: number }>("/api/options/plan", { ...spec, facts: q?.facts ?? [], ai_explanation: accepted, exit_rule: exitRule }),
    onSuccess: (r) => { toast(`Saved to plan, version ${r.version}. Earlier versions are kept as history.`); qc.invalidateQueries({ queryKey: ["opt-plans"] }); },
    onError: (e) => toast((e as Error).message, "danger"),
  });
  const send = useMutation({
    mutationFn: () => post<{ id: number }>("/api/options/paper", spec),
    onSuccess: () => { toast("Sent to Paper Desk as a pending paper order. Nothing fills until you Accept."); qc.invalidateQueries({ queryKey: ["paper"] }); },
    onError: (e) => toast((e as Error).message, "danger"),
  });

  const fmt = (x: number) => money(x, market);
  const maxDays = q?.days_slider_max ?? 5;
  const shownDays = days ?? maxDays;
  const unit = market === "IN" ? "points" : "$";
  const tiles = q ? Object.entries(q.tiles) : [];

  return (
    <FactsProvider>
      <div className="flex flex-col gap-5">
        {/* ------------------------------------------------ setup bar */}
        <section className="flex flex-wrap items-end gap-3 rounded-[var(--radius-panel)] border border-line bg-panel px-4 py-3">
          <div className="flex flex-col gap-1">
            <span className="text-[12px] text-muted">Underlying</span>
            <div className="flex items-center gap-2">
              <Segmented label="Underlying" value={und.data?.choices.includes(s.symbol) ? s.symbol : ""}
                options={(und.data?.choices ?? [s.symbol]).map((c) => ({ value: c, label: c }))} onChange={(v) => loadSymbol(v)} />
              <input aria-label="Underlying symbol" className={cn(inputCls, "h-8 w-28 uppercase")} value={symbolDraft}
                onChange={(e) => setSymbolDraft(e.target.value)} onBlur={() => loadSymbol(symbolDraft)}
                onKeyDown={(e) => e.key === "Enter" && loadSymbol(symbolDraft)} />
            </div>
          </div>
          <NumberField className="w-32" label="Spot" value={s.spot} step={step} placeholder={und.data ? String(und.data.spot) : ""}
            onChange={(v) => patch({ spot: v })} />
          <NumberField className="w-36" label="IV % (blank = chain)" value={s.iv} min={1} max={200} placeholder="chain"
            onChange={(v) => patch({ iv: v })} />
          <div className="min-w-[220px] flex-1 pb-1 text-[12px] text-muted">
            {q ? <>{q.lot_note}<br />{q.chain_label}, rate {(q.rate * 100).toFixed(2)}%</> : und.data?.lot_note}
          </div>
          <Button variant="quiet" onClick={() => { setLegs([], ""); setScnOn(false); setTableOn(false); setAccepted(""); }}>New strategy</Button>
        </section>

        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_300px] xl:grid-cols-[340px_minmax(0,1fr)_330px]">
          {/* ------------------------------------------------ left: legs (below the payoff on narrow screens) */}
          <div className="order-3 flex flex-col gap-5 lg:col-span-2 xl:order-none xl:col-span-1">
            <Panel title={`${s.symbol} legs`} action={<span className="num text-[13px] text-muted">Spot {spot ? spot.toLocaleString(market === "IN" ? "en-IN" : "en-US") : "…"}</span>}>
              {s.legs.length ? (
                <LegTable legs={s.legs} priced={q?.legs.length === s.legs.length ? q.legs : undefined} market={market} step={step}
                  onChange={(l) => setLegs(l, l.length === s.legs.length ? s.name : "")} />
              ) : (
                <EmptyState>New strategy: click Add leg, then Buy or Sell, then Call or Put. Or pick an Income preset below.</EmptyState>
              )}
              <div className="mt-3"><AddLegButton open={adding} onClick={() => setAdding((a) => !a)} /></div>
              {adding && spot > 0 && <AddLeg spot={spot} step={step} market={market} onClose={() => setAdding(false)}
                onAdd={(l) => setLegs([...s.legs, l], "")} />}
            </Panel>
            <Panel title="Income presets">
              <div className="flex flex-wrap gap-2">
                {(und.data?.presets ?? []).map((name) => (
                  <Button key={name} size="sm" variant={s.name === name ? "primary" : "outline"} onClick={() => loadPreset.mutate(name)}
                    disabled={loadPreset.isPending}>{name}</Button>
                ))}
              </div>
              <p className="mt-3 text-[13px] text-muted">Adds the legs with Sell and Buy already set, on the monthly lesson chain. Change any strike in the leg rows.</p>
            </Panel>
            <Panel title="Save and send">
              <div className="flex flex-col gap-3">
                <Field label="Exit rule (time and price, in words)">
                  <input className={cn(inputCls, "font-sans")} value={exitRule} onChange={(e) => setExitRule(e.target.value)}
                    placeholder="Close at 50% of credit or 3 days before expiry" />
                </Field>
                {accepted && <p className="text-[13px] text-muted">The accepted explanation will be saved with the plan.</p>}
                <div className="flex flex-wrap gap-2">
                  <Button variant="primary" onClick={() => save.mutate()} disabled={!q || save.isPending}>Save to plan</Button>
                  <Button onClick={() => send.mutate()} disabled={!q || send.isPending}>Send to Paper Desk</Button>
                </div>
                {history.data && history.data.plans.length > 0 && (
                  <div>
                    <div className="text-[12px] text-muted">Version history: {planName}</div>
                    <ul className="mt-1 flex flex-col text-[13px]">
                      {history.data.plans.slice(0, 6).map((p) => (
                        <li key={p.id} className="num flex justify-between gap-2 border-b border-line py-1 last:border-0">
                          <span>Version {p.version}</span>
                          <span className="truncate text-muted">{p.exit_rule || "no exit rule"}</span>
                          <span className="shrink-0 text-muted">{p.created?.slice(0, 16).replace("T", " ")}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                <Note>{PAPER_NOTE}</Note>
              </div>
            </Panel>
          </div>

          {/* ------------------------------------------------ middle: payoff, scenarios */}
          <div className="order-1 flex min-w-0 flex-col gap-5 xl:order-none">
            <Panel title={q?.name ?? "Payoff"} action={isFetching ? <span className="text-[12px] text-muted">Repricing…</span> : <Hypothetical />}>
              {error && <Callout tone="danger" title="Could not price this strategy">{(error as Error).message}</Callout>}
              {!s.legs.length && <EmptyState>Add a leg or pick an Income preset to draw the payoff.</EmptyState>}
              {q && s.legs.length > 0 && <PayoffChart spot={q.payoff.spot} expiry={q.payoff.expiry} now={q.payoff.now} current={q.spot}
                band={q.band} breakevens={q.breakevens} money={fmt} />}
              <div className="mt-4 flex items-center gap-4">
                <span className="w-24 text-[13px] text-muted">Days left</span>
                <Slider label="Days left" min={0} max={maxDays} value={shownDays} onChange={setDays} />
                <span className="num w-10 text-right font-medium">{shownDays}</span>
              </div>
              <p className="mt-2 text-[13px] text-muted">Solid line: profit or loss at expiry. Dashed: today, repriced with {shownDays} days left. Shaded band: the market's own ±1σ expected move. Black–Scholes on the lesson chain; illustrative.</p>
            </Panel>

            <Panel title="Scenarios" action={<Hypothetical />}>
              <div className="flex flex-wrap items-end gap-3">
                <NumberField className="w-36" label={`Gap (${unit})`} value={gap} step={market === "IN" ? 10 : 1} onChange={setGap} />
                <NumberField className="w-40" label="IV change (points)" value={ivChg} step={1} onChange={setIvChg} />
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button onClick={() => setScnOn(true)} disabled={!s.legs.length}>Gap</Button>
                <Button onClick={() => setScnOn(true)} disabled={!s.legs.length}>IV spike</Button>
                <Button variant={tableOn ? "primary" : "outline"} onClick={() => setTableOn((t) => !t)} disabled={!s.legs.length}>Scenarios</Button>
              </div>
              {scnOn && scn.data && (
                <div className="mt-4 flex flex-col gap-2">
                  <ScenarioTiles tiles={scn.data.tiles} />
                  <p className="text-[13px] text-muted">Repriced with {scn.data.days_left} days left (tomorrow's open at the earliest). Set Days left to choose when.</p>
                </div>
              )}
              {!scnOn && <p className="mt-3 text-[13px] text-muted">Enter a gap and an IV change, then click Gap or IV spike to reprice. Scenarios shows the chapter's default set.</p>}
              {tableOn && stress.data && (
                <div className="mt-5 flex flex-col gap-3">
                  <StressTable rows={stress.data.rows} market={market} />
                  <p className="text-[13px] text-muted">Repriced one day after entry, everything else fixed. Maximum loss at expiry: {stress.data.max_loss == null ? "unlimited" : money(stress.data.max_loss, market, 2)}. Illustrative; not a forecast.</p>
                  <div className="grid grid-cols-[minmax(0,1fr)_88px_96px] items-end gap-3 rounded-[var(--radius-tile)] border border-line bg-panel-2 p-3">
                    <Field label="Your scenario (name)">
                      <input className={cn(inputCls, "font-sans")} placeholder="Crash" value={own.label} onChange={(e) => setOwn({ ...own, label: e.target.value })} />
                    </Field>
                    <NumberField label="Gap %" value={own.gap} step={1} onChange={(v) => setOwn({ ...own, gap: v })} />
                    <NumberField label="IV points" value={own.iv} step={1} onChange={(v) => setOwn({ ...own, iv: v })} />
                    <Button className="justify-self-start" onClick={() => { setExtra([...extra, { label: own.label || "My scenario", gap_pct: own.gap ?? 0, iv_pts: own.iv }]); toast("Added scenario to the table"); }}>Add scenario</Button>
                    {extra.length > 0 && <Button variant="quiet" className="justify-self-start" onClick={() => setExtra([])}>Clear my scenarios</Button>}
                  </div>
                </div>
              )}
            </Panel>

            <Panel title="P&L attribution" action={<span className="text-[12px] text-muted">Direction (delta, gamma), time (theta), volatility (vega)</span>}>
              {scnOn && scn.data ? <AttributionStrip a={scn.data.attribution} market={market} />
                : <EmptyState>Run a scenario (Gap or IV spike) to split its P&L into direction, time and volatility.</EmptyState>}
            </Panel>
          </div>

          {/* ------------------------------------------------ right: tiles, explain, margin, IV */}
          <div className="order-2 flex flex-col gap-4 xl:order-none">
            <div>
              <h2 className="text-[14px] font-semibold">{q?.single ?? true ? "What you're paying for" : "Position tiles"} <span className="font-normal text-muted">{q?.per}</span></h2>
              <div className="mt-2 grid min-h-[210px] grid-cols-2 gap-2.5">
                {tiles.map(([k, v], i) => <FactTile key={k} label={k} value={v} tone={toneOf(k, v)} big={i === 0} />)}
              </div>
            </div>
            {q && <ExplainPanel facts={allFacts} section="Derivatives" onAccept={(t) => { setAccepted(t); toast("Accepted the explanation for the plan"); }}
              question="Narrate these tiles and scenarios in plain words, citing each number. Do not say whether to trade." />}
            <Panel title="Margin estimate">
              {q ? <MarginPanel m={q.margin} single={q.single} market={market} tiles={q.tiles} account={s.account} onAccount={(a) => patch({ account: a })} />
                : <p className="text-muted">Add a leg to estimate margin.</p>}
            </Panel>
            <Panel title="IV panel">
              {iv.data ? <IVPanel d={iv.data} /> : <div className="h-[380px]" />}
            </Panel>
            <Note>Margin figures are estimates; your broker's calculator is the real figure.</Note>
          </div>
        </div>
      </div>
    </FactsProvider>
  );
}
