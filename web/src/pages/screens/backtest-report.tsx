import { useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Copy, Info, XCircle } from "lucide-react";
import { get, post, type Market } from "@/lib/api";
import { money, pct } from "@/lib/format";
import { cn } from "@/lib/cn";
import { Button, Panel, Tabs, TabList, Tab, TabPanel, inputCls } from "@/components/ui";
import { FactTile, FactsProvider, ExplainPanel } from "@/components/facts";
import { useMarket } from "@/components/shell";
import { Badge, Callout, DataTable, EChart, EmptyState, Hypothetical, ScreenGrid, Segmented, Select, useToast, type Column } from "@/components/kit";
import {
  ErrorText, ResultChart, SummaryTiles, TradesTable, drawdownSentence, usePalette, withFont, type Frame, type Summary, type Trade,
} from "@/components/strategy/shared";
import { PairTradesTable, ZChart, type PairRule, type PairTrade } from "@/components/strategy/pairs";

interface Check { name: string; status: string; measured: string; why: string; pulls_to: string }
interface Card { grade: string; reason: string; trials: number; sharpe: number; deflated_sharpe: number; dsr_probability: number; warnings: string[]; checks: Check[] }
interface Window { choose_from: string; choose_to: string; score_from: string; score_to: string; chosen: Record<string, number> | string; sharpe_choosing: number; sharpe_unseen: number; return_unseen: number }
interface RuleReport extends Summary {
  kind: "rule"; id: number; card: Card; trades: Trade[]; cost_labels: Record<string, string>; as_of: string;
  walk_forward: { windows: Window[]; in_sample_sharpe: number; oos_sharpe: number; oos_return: number; oos_dates: string[]; oos_equity: number[]; variants: number };
}
interface PairsReport {
  kind: "pairs"; id: number; name: string; rule: PairRule; formation: number; hedge_ratio: number; half_life: number; adf_t: number;
  suspended_at: number | null; trades: PairTrade[]; z: number[]; net_total: number; trials: number; created: string; facts: string[];
}
type Report = RuleReport | PairsReport;
interface Saved { id: number; created: string; tag: string; kind: string; symbol: string; market: string; grade: string | null }
interface Costs { profile: string; slippage_pct: number | null; frame: Frame; items: { item: string; amount: number }[]; total: number; before: number; after: number; as_of: string }

const GRADE_STYLE: Record<string, string> = { Robust: "text-bull", Fragile: "text-saffron", "Likely overfit": "text-bear" };
const STATUS_ICON: Record<string, ReactNode> = {
  pass: <CheckCircle2 size={16} className="text-bull" aria-label="pass" />,
  fail: <XCircle size={16} className="text-bear" aria-label="fail" />,
  warn: <AlertTriangle size={16} className="text-saffron" aria-label="warning" />,
  info: <Info size={16} className="text-muted" aria-label="information" />,
};

/* ------------------------------------------------------------ tabs */
function CostsTab({ r, market }: { r: RuleReport; market: Market }) {
  const inMarket = r.meta.market === "IN";
  const labels = r.cost_labels;
  const cur = Object.entries(labels).find(([, v]) => v === r.meta.profile)?.[0] ?? "Delivery";
  const [pick, setPick] = useState(cur);
  const [spread, setSpread] = useState<number>(r.meta.slippage_pct ?? 0.02);
  const body = inMarket ? { id: r.id, profile: labels[pick] } : { id: r.id, slippage_pct: spread };
  const q = useQuery({ queryKey: ["bt-costs", body], queryFn: () => post<Costs>("/api/backtest/costs", body),
    placeholderData: keepPreviousData, retry: false });
  const c = q.data;
  const cols: Column<{ item: string; amount: number }>[] = [
    { key: "item", header: "Item", render: (x) => (["stt", "gst", "sebi", "dp"].includes(x.item) ? x.item.toUpperCase() : x.item.charAt(0).toUpperCase() + x.item.slice(1)) },
    { key: "amount", header: "Amount", align: "right", render: (x) => money(x.amount, market) },
  ];
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-4">
        {inMarket ? (
          <div className="flex flex-col gap-1">
            <span className="text-[12px] text-muted">Cost profile</span>
            <Segmented label="Cost profile" value={pick} options={Object.keys(labels)} onChange={setPick} />
          </div>
        ) : (
          <label className="flex w-56 flex-col gap-1">
            <span className="text-[12px] text-muted">Spread + slippage % a side</span>
            <input className={inputCls} type="number" min={0} max={1} step={0.01} value={spread}
              onChange={(e) => setSpread(Math.min(1, Math.max(0, Number(e.target.value) || 0)))} />
          </label>
        )}
        <p className="text-[13px] text-muted">Re-prices the same rule. Not a new trial: the rule did not change.</p>
      </div>
      <ErrorText error={q.error} />
      {c && (
        <>
          <ResultChart frame={c.frame} gross showDrawdown={false} height={300} />
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
            <DataTable rows={[...c.items, { item: "Total", amount: c.total }]} columns={cols} />
            <div className="flex flex-col gap-2.5">
              <div className="grid grid-cols-2 gap-2.5">
                <FactTile label="Before costs" value={pct(c.before, 1)} tone={c.before >= 0 ? "bull" : "bear"} />
                <FactTile label="After costs" value={pct(c.after, 1)} tone={c.after >= 0 ? "bull" : "bear"} big />
              </div>
              <p className="text-[13px] text-muted">{c.profile}: charges from the dated tables ({c.as_of}); slippage is an assumption you can change on the SIZE · COST card.</p>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function chosenText(c: Window["chosen"]) {
  if (typeof c === "string") return c;
  const e = Object.entries(c);
  return e.length ? e.map(([k, v]) => `${k.replace(/^(entry|exit)\.0\.(left|right)\.n$/, "$1 length").replace("time_stop", "time stop")} ${v}`).join(", ") : "as written";
}

function WalkForwardTab({ r }: { r: RuleReport }) {
  const t = usePalette();
  const wf = r.walk_forward;
  if (!wf.windows.length) {
    return <Callout tone="info">Too little history for walk-forward windows (needs 2 years to choose and 6 months to score). Test a longer period.</Callout>;
  }
  const cols: Column<Window & Record<string, unknown>>[] = [
    ...(["choose_from", "choose_to", "score_from", "score_to"] as const).map((k) => ({
      key: k, header: k.replace("_", " ").replace(/^./, (c) => c.toUpperCase()),
      render: (w: Window) => <span className="num whitespace-nowrap">{w[k]}</span> })),
    { key: "chosen", header: "Chosen", render: (w) => chosenText(w.chosen) },
    { key: "sharpe_choosing", header: "Sharpe, choosing", align: "right" },
    { key: "sharpe_unseen", header: "Sharpe, unseen", align: "right" },
    { key: "return_unseen", header: "Return, unseen", align: "right",
      render: (w) => <span className={w.return_unseen >= 0 ? "text-bull" : "text-bear"}>{pct(w.return_unseen, 1)}</span> },
  ];
  const option = {
    grid: { left: 56, right: 16, top: 16, bottom: 32 },
    tooltip: { trigger: "axis", backgroundColor: t.panel, borderColor: t.line, textStyle: { color: t.ink }, valueFormatter: (v: number) => v.toFixed(1) },
    xAxis: { type: "category", data: wf.oos_dates, axisLabel: { color: t.muted }, axisLine: { lineStyle: { color: t.line } } },
    yAxis: { type: "value", scale: true, axisLabel: { color: t.muted }, splitLine: { lineStyle: { color: t.line } } },
    series: [{ name: "Unseen record", type: "line", data: wf.oos_equity, showSymbol: false, lineStyle: { color: t.indigo, width: 2 } }],
  };
  return (
    <div className="flex flex-col gap-4">
      <p className="text-[13px] text-muted">{wf.windows.length} windows: settings chosen on 2 years from {wf.variants} nearby variants, then scored on the next 6 months that the choice never saw.</p>
      <div className="grid grid-cols-3 gap-2.5">
        <FactTile label="Sharpe, choosing windows" value={wf.in_sample_sharpe.toFixed(2)} />
        <FactTile label="Sharpe, unseen windows" value={wf.oos_sharpe.toFixed(2)} big />
        <FactTile label="Result, unseen windows" value={pct(wf.oos_return, 1)} tone={wf.oos_return >= 0 ? "bull" : "bear"} />
      </div>
      <DataTable rows={wf.windows as (Window & Record<string, unknown>)[]} columns={cols} />
      <div>
        <div className="mb-1 flex items-center gap-2 text-[13px] text-muted">Unseen record, stitched (start = 100) <Hypothetical /></div>
        <EChart option={withFont(option)} height={220} />
      </div>
    </div>
  );
}

function ReportCardTab({ card }: { card: Card }) {
  const cols: Column<Check & Record<string, unknown>>[] = [
    { key: "status", header: "", width: "28px", render: (c) => STATUS_ICON[c.status] ?? null },
    { key: "name", header: "Check", render: (c) => <span className="font-medium">{c.name}</span> },
    { key: "measured", header: "What the lab measured" },
    { key: "pulls_to", header: "Pulls the grade to", render: (c) => (c.status === "fail" || c.status === "warn") && c.pulls_to ? c.pulls_to : "" },
  ];
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline gap-3">
        <span className="text-[13px] text-muted">Report Card</span>
        <span className={cn("text-[26px] font-semibold", GRADE_STYLE[card.grade])}>{card.grade}</span>
      </div>
      <p><span className="text-muted">Why: </span>{card.reason}</p>
      <p className="num text-[14px]">Sharpe {card.sharpe.toFixed(2)}, trial-adjusted (deflated) {card.deflated_sharpe.toFixed(2)}, Trials: {card.trials}.
        Probability the true Sharpe beats the best of {card.trials} tries on noise: {(card.dsr_probability * 100).toFixed(0)}%.</p>
      <DataTable rows={card.checks as (Check & Record<string, unknown>)[]} columns={cols} />
      {card.warnings.map((w) => <Callout key={w} tone="warn">{w}</Callout>)}
      <p className="text-[13px] text-muted">The grade is about the test, not the idea. Not a forecast; not a recommendation.</p>
    </div>
  );
}

/* ------------------------------------------------------------ rule report */
function RuleReportView({ r }: { r: RuleReport }) {
  const [market] = useMarket();
  const m = r.meta.market ?? market;
  const toast = useToast();
  const qc = useQueryClient();
  const accept = useMutation({
    mutationFn: (note: string) => post<{ journal_id: number }>("/api/backtest/accept", { id: r.id, ai_note: note }),
    onSuccess: () => { toast("Saved to journal"); qc.invalidateQueries({ queryKey: ["bt-saved"] }); },
    onError: (e) => toast((e as Error).message, "danger"),
  });
  const story = r.drawdown_story;
  const sentence = drawdownSentence(story, r.stats.bh_max_drawdown);
  const copy = async () => {
    const text = sentence ?? "No drawdown in this test.";
    try { await navigator.clipboard.writeText(text); toast("Copied drawdown numbers"); }
    catch { toast("Could not reach the clipboard. Select the sentence and copy it.", "danger"); }
  };
  const card = r.card;
  return (
    <ScreenGrid rail={
      <>
        <section className="rounded-[var(--radius-panel)] border border-line bg-panel p-4">
          <div className="text-[13px] text-muted">Report Card</div>
          <div className={cn("mt-1 text-[34px] font-semibold leading-none", GRADE_STYLE[card.grade])}>{card.grade}</div>
          <p className="mt-2 text-[14px]">{card.reason}</p>
          <div className="mt-3 grid grid-cols-2 gap-2.5">
            <FactTile label="Trials" value={card.trials} sub="Every tested variant counts" />
            <FactTile label="Trial-adjusted (deflated) Sharpe" value={card.deflated_sharpe.toFixed(2)} sub={`Raw Sharpe ${card.sharpe.toFixed(2)}`} />
          </div>
          {card.warnings.length > 0 && <div className="mt-3 flex flex-col gap-2">{card.warnings.map((w) => <Callout key={w} tone="warn">{w}</Callout>)}</div>}
        </section>
        <ExplainPanel facts={r.facts} section="Strategy" onAccept={(t) => accept.mutate(t)} />
        <p className="text-[12px] text-muted">Accept saves the rule cards, this report and the AI note to your journal.</p>
      </>
    }>
      <section className="flex flex-col gap-2 rounded-[var(--radius-panel)] border border-line bg-panel px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[16px] font-semibold">{r.meta.symbol}</span>
          <Badge>{r.meta.source}</Badge>
          <span className="num text-[13px] text-muted">{r.meta.start} to {r.meta.end}</span>
          <Badge>{r.meta.profile}</Badge>
          {r.meta.origin === "agent" && <Badge tone="indigo">PROPOSED by an agent</Badge>}
          <span className="ml-auto"><Hypothetical /></span>
        </div>
        <p className="font-serif text-[14px] leading-[1.55] text-muted">{r.read_back}</p>
      </section>

      <SummaryTiles s={r.stats} g={r.gross} trials={card.trials} market={m} />

      <Tabs defaultValue="equity">
        <TabList>
          <Tab value="equity">Equity &amp; drawdown</Tab>
          <Tab value="costs">Costs</Tab>
          <Tab value="wf">Walk-forward</Tab>
          <Tab value="trades">Trades</Tab>
          <Tab value="card">Report Card</Tab>
        </TabList>
        <Panel className="mt-4">
          <TabPanel value="equity">
            <div className="mb-2 flex items-center gap-2"><Hypothetical /><span className="text-[13px] text-muted">Rule after costs against buy and hold; drawdown beneath. Hover the deepest point for its depth and date.</span></div>
            <ResultChart frame={r.frame} />
            {sentence && (
              <div className="mt-3 flex flex-col gap-3">
                <div className="grid grid-cols-3 gap-2.5">
                  <FactTile label="Deepest drawdown" value={pct(story.depth, 1)} tone="bear" />
                  <FactTile label="Began" value={story.start} sub={`Bottom ${story.trough}`} />
                  <FactTile label="Months below the earlier high" value={story.months_below} sub={story.recovered ? `Recovered ${story.recovered}` : "Not yet recovered"} />
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <p className="text-[13px] text-muted">{sentence}</p>
                  <Button size="sm" onClick={copy}><Copy size={14} /> Copy drawdown numbers</Button>
                </div>
              </div>
            )}
          </TabPanel>
          <TabPanel value="costs"><CostsTab r={r} market={m} /></TabPanel>
          <TabPanel value="wf"><WalkForwardTab r={r} /></TabPanel>
          <TabPanel value="trades"><TradesTable trades={r.trades} market={m} /></TabPanel>
          <TabPanel value="card"><ReportCardTab card={card} /></TabPanel>
        </Panel>
      </Tabs>
      <p className="num text-[14px]">Trials: <b>{card.trials}</b>, Sharpe {card.sharpe.toFixed(2)}, trial-adjusted {card.deflated_sharpe.toFixed(2)}, grade <b>{card.grade}</b></p>
    </ScreenGrid>
  );
}

/* ------------------------------------------------------------ pairs report */
function PairsReportView({ r }: { r: PairsReport }) {
  return (
    <ScreenGrid rail={<ExplainPanel facts={r.facts} section="Strategy" />}>
      <section className="flex flex-wrap items-center gap-2 rounded-[var(--radius-panel)] border border-line bg-panel px-4 py-3">
        <span className="text-[16px] font-semibold">{r.name}</span><Badge>Pairs Lab</Badge>
        <span className="num text-[13px] text-muted">Formation {r.formation} sessions, frozen</span>
        <span className="ml-auto"><Hypothetical /></span>
      </section>
      <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3">
        <FactTile label="Spread P&L (log)" value={r.net_total.toFixed(4)} tone={r.net_total >= 0 ? "bull" : "bear"} big />
        <FactTile label="Round trips" value={r.trades.length} />
        <FactTile label="Trials" value={r.trials} sub="Pairs tested in the Pairs Lab" />
        <FactTile label="Hedge ratio" value={r.hedge_ratio.toFixed(3)} />
        <FactTile label="Half-life" value={`${r.half_life.toFixed(1)} sessions`} />
        <FactTile label="Cointegration t" value={r.adf_t.toFixed(2)} />
      </div>
      {r.suspended_at && <Callout tone="warn">Stopped at session {r.suspended_at}: pair suspended. Only a new formation window after the event is an honest restart.</Callout>}
      <Panel title="Spread z-score" action={<Hypothetical />}>
        <ZChart z={r.z} formation={r.formation} rule={r.rule} trades={r.trades} />
      </Panel>
      <Panel title="Trades"><PairTradesTable trades={r.trades} /></Panel>
      <Callout tone="info">A pairs run is stored as spread trades on log prices, before costs. The Costs tab, walk-forward windows and the Report Card grade rule backtests from the Strategy Builder and Trend Lab.</Callout>
    </ScreenGrid>
  );
}

/* ------------------------------------------------------------ page */
export default function BacktestReport() {
  const [market] = useMarket();
  const [params, setParams] = useSearchParams();
  const qc = useQueryClient();
  const toast = useToast();
  const id = params.get("id");
  const saved = useQuery({ queryKey: ["bt-saved"], queryFn: () => get<Saved[]>("/api/backtest/saved") });
  const report = useQuery({
    queryKey: ["bt-report", id], queryFn: () => get<Report>(`/api/backtest/report${id ? `?id=${id}` : ""}`), retry: false,
  });
  const sample = useMutation({
    mutationFn: () => post<{ id: number }>("/api/backtest/sample", { market }),
    onSuccess: ({ id: nid }) => { qc.invalidateQueries({ queryKey: ["bt-saved"] }); setParams({ id: String(nid) }); toast("Sample rule run"); },
    onError: (e) => toast((e as Error).message, "danger"),
  });
  const empty = Boolean((report.data as { empty?: boolean } | undefined)?.empty);
  const r = empty ? undefined : report.data;
  const none = (report.isError || empty) && !(saved.data?.length);

  return (
    <FactsProvider>
      <div className="flex flex-col gap-5">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex w-[min(460px,100%)] flex-col gap-1">
            <span className="text-[12px] text-muted">Saved reports</span>
            <Select value={id ?? ""} onChange={(e) => setParams(e.target.value ? { id: e.target.value } : {})}>
              <option value="">Current (the newest report sent here)</option>
              {(saved.data ?? []).map((s) => (
                <option key={s.id} value={s.id}>#{s.id} {s.symbol}{s.grade ? `, ${s.grade}` : s.kind === "pairs" ? ", pairs run" : ""}, {s.created.slice(0, 16).replace("T", " ")}</option>
              ))}
            </Select>
          </label>
          <Button onClick={() => sample.mutate()} disabled={sample.isPending}>{sample.isPending ? "Running…" : "Run sample rule"}</Button>
          <span className="text-[13px] text-muted">All results are HYPOTHETICAL.</span>
        </div>

        {none && (
          <EmptyState action={<Button variant="primary" onClick={() => sample.mutate()} disabled={sample.isPending}>Run sample rule</Button>}>
            No backtest yet. Build one in Strategy Builder or Trend Lab, or run the Lesson 11 sample rule on synthetic data.
          </EmptyState>
        )}
        {report.isError && !none && <Callout tone="danger" title="This report could not be opened">{(report.error as Error).message}</Callout>}
        {report.isPending && <div className="h-[480px]" aria-busy="true" />}
        {r?.kind === "rule" && <RuleReportView key={r.id} r={r} />}
        {r?.kind === "pairs" && <PairsReportView key={r.id} r={r} />}
      </div>
    </FactsProvider>
  );
}
