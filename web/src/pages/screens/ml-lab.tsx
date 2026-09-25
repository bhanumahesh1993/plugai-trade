import { Fragment, useEffect, useMemo, useState } from "react";
import * as SliderPrimitive from "@radix-ui/react-slider";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Brain, Send, Shuffle } from "lucide-react";
import { get, post, type Market } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button, Field, Panel, Tabs, TabList, Tab, TabPanel, inputCls } from "@/components/ui";
import { Badge, Callout, EChart, EmptyState, Hypothetical, chartTokens, useToast } from "@/components/kit";
import { ExplainPanel, FactTile, FactsProvider } from "@/components/facts";
import { useMarket } from "@/components/shell";
import { Check, ErrorLine, Note, NumField, Radio, TextField } from "@/components/automate/common";

/* ------------------------------------------------------------ types */
interface Meta {
  features: { key: string; known_at: string }[]; noise: { key: string; known_at: string };
  labels: { key: string; name: string; question: string }[]; horizon: number; scenario_engine: string;
  sklearn: boolean; default_symbol: Record<Market, string>;
}
interface Card {
  label: string; label_name: string; question: string; features: string[]; symbol: string; engine: string;
  scores: { train: number; valid: number; test: number }; baselines: { name: string; score: number }[];
  importance: { feature: string; points: number; control: boolean }[];
  overfit: { depth: number; train: number; validation: number }[]; trials: number; grade: string; why: string;
  spans: { train: string; valid: string; test: string }; rows: { train: number; valid: number; test: number };
  purge: number; embargo: number; text: string; facts: string[];
  shuffle: { score: number; folds: number; label: string; text: string } | null;
}
interface Scen {
  as_of: string; horizon: number; low_pct: number; middle_pct: number; high_pct: number; baseline_pct: number;
  engine: string; symbol: string; facts: string[];
}
interface Hist { rows: { date: string; low: number; middle: number; high: number; baseline: number; realised: number; inside: number | boolean }[]; facts: string[] }
interface MlState { market: Market; card: Card | null; accepted: number | null; sent: number | null; scenarios: Scen | null; history: Hist | null }

const GRADE: Record<string, { tone: "ok" | "warn" | "danger"; cls: string }> = {
  Robust: { tone: "ok", cls: "text-bull" }, Fragile: { tone: "warn", cls: "text-saffron" }, "Likely overfit": { tone: "danger", cls: "text-bear" },
};
const p1 = (x: number) => `${x.toFixed(1)}%`;
const p2 = (x: number) => `${x.toFixed(2)}%`;
/** Value of a "Label: value" fact, for tiles that mirror the engine's own words. */
const factVal = (facts: string[], label: string) => facts.find((f) => f.startsWith(label + ":"))?.slice(label.length + 1).trim() ?? "—";

/* ------------------------------------------------------------ split slider */
function SplitBar({ a, b, onChange }: { a: number; b: number; onChange: (a: number, b: number) => void }) {
  return (
    <div className="flex flex-col gap-2">
      <SliderPrimitive.Root className="relative flex h-5 w-full touch-none select-none items-center" min={10} max={95} step={5}
        minStepsBetweenThumbs={1} value={[a, b]} onValueChange={(v) => onChange(v[0], v[1])} aria-label="Train, validation and test boundaries">
        <SliderPrimitive.Track className="relative h-2 grow overflow-hidden rounded-full bg-line-strong">
          <div className="absolute inset-y-0 left-0 bg-indigo/70" style={{ width: `${a}%` }} />
          <SliderPrimitive.Range className="absolute h-full bg-indigo/35" />
        </SliderPrimitive.Track>
        <SliderPrimitive.Thumb aria-label="End of training block" className="block h-4 w-4 rounded-full border-2 border-indigo bg-panel" />
        <SliderPrimitive.Thumb aria-label="End of validation block" className="block h-4 w-4 rounded-full border-2 border-indigo bg-panel" />
      </SliderPrimitive.Root>
      <div className="grid grid-cols-3 text-[12px]">
        <span><span className="mr-1 inline-block h-2 w-2 rounded-[2px] bg-indigo/70" />Train {a}%</span>
        <span className="text-center"><span className="mr-1 inline-block h-2 w-2 rounded-[2px] bg-indigo/35" />Validation {b - a}%</span>
        <span className="text-right"><span className="mr-1 inline-block h-2 w-2 rounded-[2px] bg-line-strong" />Sealed test {100 - b}%</span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ charts */
function OverfitChart({ c }: { c: Card }) {
  const option = useMemo(() => {
    const t = chartTokens();
    return {
      grid: { left: 48, right: 16, top: 30, bottom: 40 },
      legend: { top: 0, left: 0, textStyle: { color: t.muted }, itemWidth: 18 },
      tooltip: { trigger: "axis", backgroundColor: t.panel, borderColor: t.line, textStyle: { color: t.ink }, valueFormatter: (v: number) => p1(v) },
      xAxis: { type: "category", data: c.overfit.map((r) => r.depth), name: "Tree depth (yes/no questions)", nameLocation: "middle", nameGap: 26,
        nameTextStyle: { color: t.muted }, axisLabel: { color: t.muted }, axisLine: { lineStyle: { color: t.line } } },
      yAxis: { type: "value", scale: true, name: "Accuracy, %", nameTextStyle: { color: t.muted }, axisLabel: { color: t.muted }, splitLine: { lineStyle: { color: t.line } } },
      series: [
        { name: "Training", type: "line", data: c.overfit.map((r) => r.train), lineStyle: { color: t.muted, type: "dashed", width: 2 }, itemStyle: { color: t.muted } },
        { name: "Validation", type: "line", data: c.overfit.map((r) => r.validation), lineStyle: { color: t.indigo, width: 2.2 }, itemStyle: { color: t.indigo } },
      ],
    };
  }, [c]);
  return <EChart option={option} height={280} />;
}

function ImportanceChart({ c }: { c: Card }) {
  const rows = [...c.importance].sort((x, y) => x.points - y.points);
  const option = useMemo(() => {
    const t = chartTokens();
    return {
      grid: { left: 120, right: 40, top: 8, bottom: 36 },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, backgroundColor: t.panel, borderColor: t.line, textStyle: { color: t.ink },
        valueFormatter: (v: number) => `${v >= 0 ? "+" : ""}${v.toFixed(1)} points` },
      xAxis: { type: "value", name: "Accuracy lost when shuffled (points, test years)", nameLocation: "middle", nameGap: 24,
        nameTextStyle: { color: t.muted }, axisLabel: { color: t.muted }, splitLine: { lineStyle: { color: t.line } } },
      yAxis: { type: "category", data: rows.map((r) => r.feature), axisLabel: { color: t.ink }, axisLine: { lineStyle: { color: t.line } } },
      series: [{ type: "bar", barMaxWidth: 16, data: rows.map((r) => ({ value: r.points, itemStyle: { color: r.control ? t.muted : t.indigo, opacity: r.control ? 0.55 : 1 } })),
        label: { show: true, position: "right", color: t.muted, formatter: (p: { value: number }) => p.value.toFixed(1) } }],
    };
  }, [rows]);
  return <EChart option={option} height={28 * rows.length + 60} />;
}

function HistoryChart({ h }: { h: Hist }) {
  const option = useMemo(() => {
    const t = chartTokens();
    const d = h.rows.map((r) => String(r.date).slice(0, 10));
    return {
      grid: { left: 48, right: 16, top: 30, bottom: 30 },
      legend: { top: 0, left: 0, textStyle: { color: t.muted } },
      tooltip: { trigger: "axis", backgroundColor: t.panel, borderColor: t.line, textStyle: { color: t.ink }, valueFormatter: (v: number) => p2(v) },
      xAxis: { type: "category", data: d, axisLabel: { color: t.muted }, axisLine: { lineStyle: { color: t.line } } },
      yAxis: { type: "value", scale: true, axisLabel: { color: t.muted, formatter: (v: number) => `${v.toFixed(1)}%` }, splitLine: { lineStyle: { color: t.line } } },
      series: [
        { name: "Realised", type: "line", data: h.rows.map((r) => r.realised), showSymbol: false, lineStyle: { color: t.ink, width: 1.8 }, itemStyle: { color: t.ink } },
        { name: "Middle band", type: "line", data: h.rows.map((r) => r.middle), showSymbol: false, lineStyle: { color: t.indigo, width: 1.6 }, itemStyle: { color: t.indigo } },
        { name: "Last 20 sessions continue", type: "line", data: h.rows.map((r) => r.baseline), showSymbol: false, lineStyle: { color: t.muted, width: 1.4, type: "dashed" }, itemStyle: { color: t.muted } },
      ],
    };
  }, [h]);
  return <EChart option={option} height={280} />;
}

/* ------------------------------------------------------------ results */
function Results({ c }: { c: Card }) {
  const rows: { name: string; score: number; kind: "model" | "base" | "leak" }[] = [
    { name: "Training years (flattering)", score: c.scores.train, kind: "model" },
    { name: "Validation years", score: c.scores.valid, kind: "model" },
    { name: "Sealed test years", score: c.scores.test, kind: "model" },
    ...c.baselines.map((b) => ({ name: `${b.name === "majority" ? "Majority guess" : `One-line rule: ${b.name}`}, test years`, score: b.score, kind: "base" as const })),
    ...(c.shuffle ? [{ name: `Shuffled ${c.shuffle.folds}-fold (leaky), for learning only`, score: c.shuffle.score, kind: "leak" as const }] : []),
  ];
  const g = GRADE[c.grade] ?? GRADE.Fragile;
  return (
    <div className="flex flex-col gap-4">
      <table className="w-full text-[14px]">
        <thead><tr className="border-b border-line text-left text-[12px] text-muted"><th className="pb-2 font-normal">Accuracy, %</th><th className="w-[45%] pb-2 font-normal"><span className="sr-only">Bar</span></th><th className="pb-2 text-right font-normal">Score</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.name} className="border-b border-line last:border-0">
              <td className={cn("py-2 pr-3", r.name === "Sealed test years" && "font-semibold")}>
                {r.name}{r.kind === "leak" && <Badge tone="warn" className="ml-2">Not a result</Badge>}
              </td>
              <td className="py-2 pr-3">
                <div className="h-2 rounded-full bg-panel-2">
                  <div className={cn("h-2 rounded-full", r.kind === "model" ? "bg-indigo" : r.kind === "leak" ? "bg-saffron/70" : "bg-line-strong")} style={{ width: `${Math.max(0, Math.min(100, r.score))}%` }} />
                </div>
              </td>
              <td className={cn("num py-2 text-right", r.name === "Sealed test years" && "font-semibold")}>{r.score.toFixed(1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <Callout tone={g.tone} title={`Grade: ${c.grade}`}>{c.why}</Callout>
      <Note>Trials counter (this ML family): {c.trials}. Engine: {c.engine}. Hypothetical.</Note>
      {c.shuffle && <Callout tone="warn" title="Shuffle test, for learning only">Shuffling puts the future into training and overlapping labels across the split; {p1(c.shuffle.score)} is not a result. The time-ordered sealed test scored {p1(c.scores.test)}.</Callout>}
    </div>
  );
}

function ModelCardView({ c }: { c: Card }) {
  const rows: [string, string][] = [
    ["Label", c.question], ["Model", c.engine], ["Features", c.features.join(", ")],
    ["Train", `${c.spans.train} (${c.rows.train.toLocaleString()} rows)`],
    ["Validation", `${c.spans.valid} (${c.rows.valid.toLocaleString()} rows)`],
    ["Sealed test", `${c.spans.test} (${c.rows.test.toLocaleString()} rows)`],
    ["Purge / embargo", `${c.purge} / ${c.embargo} rows`],
    ["Scores (train, validation, test)", `${p1(c.scores.train)}, ${p1(c.scores.valid)}, ${p1(c.scores.test)}`],
    ...c.baselines.map((b): [string, string] => [b.name === "majority" ? "Majority guess, test" : `${b.name}, test`, p1(b.score)]),
    ["Trials in this ML family", String(c.trials)], ["Grade", `${c.grade}: ${c.why}`],
  ];
  return (
    <dl className="grid grid-cols-[minmax(140px,auto)_1fr] gap-x-4 gap-y-1.5 text-[14px]">
      {rows.map(([k, v]) => <Fragment key={k}><dt className="text-muted">{k}</dt><dd className="num">{v}</dd></Fragment>)}
      <dt className="text-muted">Note</dt><dd>Grades the test, not the idea. Not a forecast; not a recommendation.</dd>
    </dl>
  );
}

/* ------------------------------------------------------------ screen */
export default function MlLab() {
  const [market] = useMarket();
  const qc = useQueryClient();
  const toast = useToast();
  const key = ["automate", "ml", market];
  const meta = useQuery({ queryKey: ["automate", "ml-meta"], queryFn: () => get<Meta>("/api/automate/ml/meta") });
  const { data: s, error } = useQuery({ queryKey: key, queryFn: () => get<MlState>(`/api/automate/ml/state?market=${market}`) });
  const set = (d: MlState) => qc.setQueryData(["automate", "ml", d.market], d);
  const M = meta.data;

  const [symbol, setSymbol] = useState(market === "IN" ? "NIFTY" : "SPY");
  const [start, setStart] = useState("2010-01-01");
  const [end, setEnd] = useState("2026-05-29");
  const [feats, setFeats] = useState<string[] | null>(null);
  const [noise, setNoise] = useState(true);
  const [label, setLabel] = useState("high_vol_next_10");
  const [bounds, setBounds] = useState<[number, number]>([60, 80]);
  const [purge, setPurge] = useState<number | null>(10);
  const [embargo, setEmbargo] = useState<number | null>(0);
  const [rule, setRule] = useState("vol_20 > 1");
  const [horizon, setHorizon] = useState<number | null>(10);
  const [pending, setPending] = useState(false);
  const [cfgTab, setCfgTab] = useState("dataset");
  const [resTab, setResTab] = useState("results");
  const [scTab, setScTab] = useState("scenarios");
  useEffect(() => setSymbol(market === "IN" ? "NIFTY" : "SPY"), [market]);
  useEffect(() => { if (M && feats === null) { setFeats(M.features.map((f) => f.key)); setPurge(M.horizon); } }, [M, feats]);

  const train = useMutation({
    mutationFn: () => post<MlState>("/api/automate/ml/train", { market, symbol, start, end, features: feats ?? [], noise, label,
      train_pct: bounds[0], valid_pct: bounds[1] - bounds[0], purge: purge ?? M?.horizon ?? 10, embargo: embargo ?? 0, rule }),
    onSuccess: (d) => { set(d); setResTab("results"); toast(`Trained baseline: grade ${d.card?.grade}, trial ${d.card?.trials}`); },
  });
  const shuffle = useMutation({ mutationFn: () => post<MlState>("/api/automate/ml/shuffle", { market }), onSuccess: (d) => { set(d); setResTab("results"); toast("Ran the Shuffle test (for learning only)"); } });
  const accept = useMutation({ mutationFn: (text: string) => post<MlState>("/api/automate/ml/accept", { market, text }), onSuccess: (d) => { set(d); toast("Saved the model card to your journal"); } });
  const scen = useMutation({
    mutationFn: () => post<MlState>("/api/automate/ml/scenarios", { market, symbol, start, end, horizon: horizon ?? 10 }),
    onSuccess: (d) => { set(d); setPending(false); toast("Computed volatility scenarios"); },
  });
  const send = useMutation({ mutationFn: () => post<MlState>("/api/automate/ml/send-to-sizer", { market }), onSuccess: (d) => { set(d); setPending(false); toast("Sent to Plan & Risk › Position Sizer"); } });

  if (error || meta.error) return <Callout tone="danger" title="The ML Lab could not load">{((error ?? meta.error) as Error).message} Restart the lab, then open this screen again.</Callout>;
  const c = s?.card ?? null;
  const sc = s?.scenarios ?? null;
  const h = s?.history ?? null;
  const minPurge = M?.horizon ?? 10;
  const purgeLow = purge !== null && purge < minPurge;

  return (
    <FactsProvider>
      <div className="flex flex-col gap-5">
        <p className="text-[14px] text-muted">Honest tests: a time-ordered split, a purge at least as long as the label, baselines, and every trial counted. The ML Lab never produces a trade signal.</p>

        <div className="flex flex-wrap items-end gap-3 rounded-[var(--radius-panel)] border border-line bg-panel px-4 py-3">
          <div className="w-32"><TextField label="Symbol" value={symbol} onChange={(v) => setSymbol(v.toUpperCase())} /></div>
          <Field label="From"><input type="date" className={cn(inputCls, "w-40")} value={start} onChange={(e) => setStart(e.target.value)} /></Field>
          <Field label="To"><input type="date" className={cn(inputCls, "w-40")} value={end} onChange={(e) => setEnd(e.target.value)} /></Field>
          <div className="w-48"><TextField label="One-line rule baseline" value={rule} onChange={setRule} placeholder="vol_20 > 1" /></div>
          <Button variant="primary" onClick={() => train.mutate()} disabled={train.isPending || !M || !feats?.length || purgeLow}>
            <Brain size={14} /> {train.isPending ? "Training…" : "Train baseline"}
          </Button>
          <Button onClick={() => shuffle.mutate()} disabled={!c || shuffle.isPending} title="The leaky shuffled k-fold score, for learning only"><Shuffle size={14} /> Shuffle test</Button>
          <span className="ml-auto self-center text-[13px] text-muted">Rule looks like feature &gt; value, for example vol_20 &gt; 1</span>
        </div>
        <ErrorLine error={train.error ?? shuffle.error} />

        <div className="grid gap-5 xl:grid-cols-[340px_minmax(0,1fr)]">
          <Panel className="self-start">
            <Tabs value={cfgTab} onValueChange={setCfgTab}>
              <TabList><Tab value="dataset">Dataset</Tab><Tab value="label">Label</Tab><Tab value="split">Split in time</Tab></TabList>
              <div className="pt-3">
                <TabPanel value="dataset">
                  <Note className="mb-2">Tick features. Each is computed only from data up to the row's close.</Note>
                  {M?.features.map((f) => (
                    <Check key={f.key} checked={feats?.includes(f.key) ?? true} onChange={(v) => setFeats((p) => (v ? [...(p ?? []), f.key] : (p ?? []).filter((x) => x !== f.key)))}
                      hint={`Known at: ${f.known_at}`}>{f.key}</Check>
                  ))}
                  {M && <div className="mt-2 border-t border-line pt-2">
                    <Check checked={noise} onChange={setNoise} hint={`Known at: ${M.noise.known_at}. Any feature ranked at or below it is not earning its place.`}>Noise (control)</Check>
                  </div>}
                </TabPanel>
                <TabPanel value="label">
                  <div role="radiogroup" aria-label="Label">
                    {M?.labels.map((l) => <Radio key={l.key} name="ml-label" checked={label === l.key} onChange={() => setLabel(l.key)} hint={l.question}>{l.name}</Radio>)}
                  </div>
                </TabPanel>
                <TabPanel value="split">
                  <div className="flex flex-col gap-4">
                    <div>
                      <div className="mb-2 text-[12px] text-muted">Train, validation and test boundaries (% of history, in time order)</div>
                      <SplitBar a={bounds[0]} b={bounds[1]} onChange={(a, b) => setBounds([a, b])} />
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <NumField label="Purge (rows)" value={purge} min={minPurge} step={1} onChange={setPurge} hint={`Set to the label length (${minPurge}); it cannot be set lower.`} />
                      <NumField label="Embargo (rows)" value={embargo} min={0} step={1} onChange={setEmbargo} hint="Applies to walk-forward runs; here it drops rows at the start of the validation and test blocks." />
                    </div>
                    {purgeLow && <p className="text-[13px] text-bear" role="alert">Purge must be at least {minPurge} rows, the label's length.</p>}
                    <Note>No shuffle option. The sealed test block is opened once, when you click Train baseline.</Note>
                  </div>
                </TabPanel>
              </div>
            </Tabs>
          </Panel>

          <div className="flex min-w-0 flex-col gap-5">
            <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-5">
              <div className="col-span-2"><FactTile big label="Accuracy on sealed test years" value={c ? p1(c.scores.test) : "—"} sub={c ? c.label_name : "Click Train baseline"} /></div>
              <FactTile label="Accuracy on validation years" value={c ? p1(c.scores.valid) : "—"} />
              <FactTile label="Accuracy on training years" value={c ? p1(c.scores.train) : "—"} sub="Flattering" />
              <FactTile label="Trials in this ML family" value={c ? c.trials : "—"} sub="Trials counter" tone="indigo" />
            </div>
            {c && (
              <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-4">
                {c.baselines.map((b) => (
                  <FactTile key={b.name} label={`Baseline '${b.name}' on test years`} value={p1(b.score)} sub={b.name === "majority" ? "Majority guess" : "One-line rule"} />
                ))}
                <div className="col-span-2"><FactTile label="Grade" value={<span className={GRADE[c.grade]?.cls}>{c.grade}</span>} sub={c.why} /></div>
              </div>
            )}
            <Panel title={c ? `${c.symbol}, ${c.label_name}` : "Results"} action={c ? <Hypothetical /> : undefined}>
              {!c ? (
                <EmptyState>Click Train baseline to fill Results vs baselines, the Overfit curve and Feature importance. Gradient boosting with library defaults; every model you train adds one trial.</EmptyState>
              ) : (
                <Tabs value={resTab} onValueChange={setResTab}>
                  <TabList><Tab value="results">Results vs baselines</Tab><Tab value="overfit">Overfit curve</Tab><Tab value="importance">Feature importance</Tab><Tab value="card">Model card</Tab></TabList>
                  <div className="pt-4">
                    <TabPanel value="results"><Results c={c} /></TabPanel>
                    <TabPanel value="overfit">
                      <OverfitChart c={c} />
                      <Note>One decision tree allowed to go deeper: training keeps rising, validation does not.</Note>
                    </TabPanel>
                    <TabPanel value="importance">
                      <ImportanceChart c={c} />
                      <Note>Importance describes the model, not the market. Anything at or below the Noise (control) bar (grey) has not shown it helps.</Note>
                    </TabPanel>
                    <TabPanel value="card"><ModelCardView c={c} /></TabPanel>
                  </div>
                </Tabs>
              )}
            </Panel>
            {c && (
              <Panel title="Explain this model">
                <ExplainPanel facts={c.facts} section="Automate" onAccept={(text) => accept.mutate(text)} />
                <Note className="mt-2">{s?.accepted ? `Saved: model card #${s.accepted} is in your journal.` : "Accept saves the model card (features, label, split, scores, trial count) to your journal."}</Note>
                <ErrorLine error={accept.error} />
              </Panel>
            )}
          </div>
        </div>

        <Panel title="Volatility scenarios">
          <Tabs value={scTab} onValueChange={setScTab}>
            <TabList><Tab value="scenarios">Scenarios</Tab><Tab value="history">Scored history</Tab></TabList>
            <div className="pt-4">
              <TabPanel value="scenarios">
                <div className="flex flex-wrap items-end gap-3">
                  <div className="w-40"><NumField label="Horizon (sessions)" value={horizon} min={5} max={30} step={1} onChange={setHorizon} /></div>
                  <Button variant="primary" onClick={() => scen.mutate()} disabled={scen.isPending}>{scen.isPending ? "Computing…" : "Volatility scenarios"}</Button>
                  <Note className="max-w-[560px] pb-1">A time-series foundation model (Chronos, TimesFM) is optional and runs locally when installed; otherwise: {M?.scenario_engine ?? "…"}.</Note>
                </div>
                <ErrorLine error={scen.error} />
                {sc ? (
                  <div className="mt-4 grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
                    <div className="flex min-w-0 flex-col gap-4">
                      <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
                        <FactTile label="Low (calm) band" value={p2(sc.low_pct)} />
                        <FactTile big label="Middle band" value={p2(sc.middle_pct)} />
                        <FactTile label="High (stormy) band" value={p2(sc.high_pct)} />
                        <FactTile label="Baseline 'last 20 sessions continue'" value={p2(sc.baseline_pct)} />
                      </div>
                      <Note>Average daily high–low range over the next {sc.horizon} sessions for {sc.symbol}, as of {sc.as_of}. Not a forecast of direction. Engine: {sc.engine}.</Note>
                      <div className="flex flex-wrap items-center gap-3">
                        <Button onClick={() => setPending(true)} disabled={pending || !!s?.sent}><Send size={14} /> Send to Position Sizer</Button>
                        {s?.sent && <span className="text-[13px] text-muted">Sent to Plan &amp; Risk › Position Sizer (note #{s.sent}).</span>}
                      </div>
                      {pending && (
                        <Callout tone="info" title="Size a paper position for the calm and the stormy band">
                          <span className="block">Nothing is applied until you click Accept.</span>
                          <span className="mt-2 flex gap-2">
                            <Button size="sm" variant="primary" onClick={() => send.mutate()} disabled={send.isPending}>Accept</Button>
                            <Button size="sm" onClick={() => setPending(false)}>Cancel</Button>
                          </span>
                        </Callout>
                      )}
                      <ErrorLine error={send.error} />
                    </div>
                    <ExplainPanel facts={sc.facts} section="Automate" />
                  </div>
                ) : <div className="mt-4"><EmptyState>Pick a horizon and click Volatility scenarios. The lab shows low, middle and high bands for the daily range, beside the "last 20 sessions continue" baseline.</EmptyState></div>}
              </TabPanel>
              <TabPanel value="history">
                {!h || h.rows.length === 0 ? <EmptyState>Click Volatility scenarios first. Scored history needs more than a year of data.</EmptyState> : (
                  <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
                    <div className="flex min-w-0 flex-col gap-4">
                      <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
                        <FactTile label="Month-ends scored" value={factVal(h.facts, "Month-ends scored")} />
                        <FactTile big label="Realised range inside the low–high band" value={factVal(h.facts, "Realised range inside the low–high band").replace(" of months", "")} sub="Of months" />
                        <FactTile label="Average error, middle band" value={factVal(h.facts, "Average error, middle band")} />
                        <FactTile label="Average error, 'last 20 sessions continue'" value={factVal(h.facts, "Average error, 'last 20 sessions continue'")} />
                      </div>
                      <div>
                        <div className="mb-1 flex items-center justify-between"><span className="text-[14px] font-medium">Scored at each past month-end</span><Hypothetical /></div>
                        <HistoryChart h={h} />
                      </div>
                      <Note>Each forecast used only data up to its own month-end. A foundation model is scored only after its published training cutoff.</Note>
                    </div>
                    <ExplainPanel facts={h.facts} section="Automate" />
                  </div>
                )}
              </TabPanel>
            </div>
          </Tabs>
        </Panel>
        <Note>Hypothetical. A model's output can go to the Position Sizer as a volatility estimate or to your journal as a note, never to an order.</Note>
      </div>
    </FactsProvider>
  );
}
