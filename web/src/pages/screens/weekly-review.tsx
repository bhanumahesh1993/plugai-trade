import { useState } from "react";
import { useMutation, useQuery, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { Code2, Save, Tag } from "lucide-react";
import { get, post, type Explanation, type Market } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button, Panel, Field, inputCls } from "@/components/ui";
import { Badge, Callout, DataTable, EChart, EmptyState, Segmented, chartTokens, useToast, type Column } from "@/components/kit";
import { useMarket } from "@/components/shell";
import { LocalExplainPanel, LocalFactsProvider, LocalOnly, Tile } from "@/components/journal/local";
import { Disclosure, QueryBlock, hhmm, plain, rStr, toneOf } from "@/components/journal/common";

type Row = Record<string, unknown>;
interface TileT { label: string; value: string; sub: string; last: string; q: string }
interface Finding { label: string; n: number; rows: number[]; total_r: number; query: string; n_label: string; too_few?: boolean; detail?: { row: number; rows: Row[] }[] }
interface Review {
  kind: "journal" | "sample" | "empty"; label: string; saved: boolean; start: string; end: string; latest: string | null; account: string;
  rule_card: string; last_decision: string | null; tiles: TileT[]; rule_breaks: Finding[]; patterns: Finding[];
  bars: { trade_id: number; r: number; broke_rule: boolean }[]; pinned: { label: string; text: string; rows: number[] }[];
  queries: Record<string, string>; facts: string[]; question: string; sample?: string;
}
type Account = "Real" | "Paper" | "Both";

/* Sentence-case tile labels, and the fact each tile answers to (citations light it). */
const TILE: Record<string, { label: string; keys: string[] }> = {
  TRADES: { label: "Trades", keys: ["week 2", "previous week"] },
  RESULT: { label: "Result", keys: ["week 2"] },
  CHARGES: { label: "Charges", keys: ["charges"] },
  NET: { label: "Net", keys: ["net after charges"] },
  ADHERENCE: { label: "Adherence", keys: ["followed every rule card line"] },
  "BREAKS COST": { label: "Breaks cost", keys: ["broke at least one line", "rule break"] },
};
const signTone = (v: string) => (v.startsWith("−") ? "bear" : v.startsWith("+") && v !== "+0.00R" ? "bull" : undefined);

function RBars({ bars }: { bars: Review["bars"] }) {
  const t = chartTokens();
  const option = {
    grid: { left: 40, right: 12, top: 12, bottom: 36 },
    tooltip: { trigger: "axis", valueFormatter: (v: number) => rStr(v) },
    xAxis: { type: "category", data: bars.map((b) => String(b.trade_id)), name: "row", nameLocation: "middle", nameGap: 26,
      axisLine: { lineStyle: { color: t.line } }, axisLabel: { color: t.muted } },
    yAxis: { type: "value", name: "R", splitLine: { lineStyle: { color: t.line } }, axisLabel: { color: t.muted } },
    series: [{ type: "bar", barMaxWidth: 22, data: bars.map((b) => ({ value: b.r,
      itemStyle: { color: b.r >= 0 ? t.bull : t.bear, borderColor: b.broke_rule ? t.ink : "transparent", borderWidth: b.broke_rule ? 2 : 0 } })) }],
  };
  return <EChart option={option} height={260} />;
}

const breakCols: Column<Row>[] = [
  { key: "trade_id", header: "Row", align: "right" },
  { key: "entry_time", header: "In", render: (r) => hhmm(r.entry_time) },
  { key: "exit_time", header: "Out", render: (r) => hhmm(r.exit_time) },
  { key: "side", header: "Side" },
  { key: "r", header: "R", align: "right", render: (r) => <span className={toneOf(r.r)}>{rStr(r.r)}</span> },
  { key: "gap_minutes", header: "Gap (min)", align: "right", render: (r) => plain(r.gap_minutes, 0) },
  { key: "rules_broken", header: "Broke", render: (r) => (r.rules_broken ? String(r.rules_broken) : <span className="text-muted">—</span>) },
];

function BreakRow({ f, m, saved }: { f: Finding; m: Market; saved: boolean }) {
  const toast = useToast();
  const qc = useQueryClient();
  const [tag, setTag] = useState("");
  const add = useMutation({
    mutationFn: () => post<{ tagged: number }>("/api/journal/tags/add", { market: m, rows: f.rows, tag }),
    onSuccess: (d) => { toast(`Tag added to ${d.tagged} rows`); setTag(""); qc.invalidateQueries({ queryKey: ["journal-trades", m] }); },
  });
  return (
    <Disclosure summary={
      <span className="flex flex-wrap items-baseline gap-x-2">
        <span className="font-medium">{f.label}</span>
        <span className="num text-muted">rows {f.rows.join(", ")}</span>
        <span className={cn("num ml-auto font-medium", toneOf(f.total_r))}>{rStr(f.total_r)}</span>
      </span>}>
      <div className="flex flex-col gap-3">
        <p className="text-[13px] text-muted">Each break with the row before it: time of day, the previous result, the gap in minutes.</p>
        {f.detail?.map((d) => <DataTable key={d.row} rows={d.rows} columns={breakCols} />)}
        <p className="num text-[12px] text-muted">{f.query}</p>
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Add a mistake tag to these rows">
            <input className={cn(inputCls, "w-52")} value={tag} onChange={(e) => setTag(e.target.value)} placeholder="revenge trade" disabled={!saved} />
          </Field>
          <Button size="md" onClick={() => add.mutate()} disabled={!saved || !tag.trim() || add.isPending}><Tag size={14} /> Add tag</Button>
          {!saved && <span className="pb-2 text-[12px] text-muted">The lesson sample is read-only.</span>}
        </div>
        {add.error && <p className="text-[13px] text-bear">{(add.error as Error).message}</p>}
      </div>
    </Disclosure>
  );
}

export default function WeeklyReview() {
  const [m] = useMarket();
  const qc = useQueryClient();
  const toast = useToast();
  const [weekOf, setWeekOf] = useState("");
  const [account, setAccount] = useState<Account>("Both");
  const [showQ, setShowQ] = useState(false);
  const [change, setChange] = useState("");
  const [narration, setNarration] = useState("");
  const [decision, setDecision] = useState("");
  const key = ["journal-weekly", m, weekOf, account];
  const { data: r, isLoading, error } = useQuery({
    queryKey: key, placeholderData: keepPreviousData,
    queryFn: () => get<Review>(`/api/journal/weekly?market=${m}&account=${account}${weekOf ? `&week_of=${weekOf}` : ""}`),
  });
  const body = { market: m, week_of: weekOf || null, account };
  const sample = useMutation({ mutationFn: () => post(`/api/journal/sample?market=${m}`), onSuccess: () => { qc.invalidateQueries({ queryKey: ["journal-weekly", m] }); toast("Lesson 14 sample loaded"); } });
  const accept = useMutation({
    mutationFn: () => post<{ version: number; change: string; changed_on: string }>("/api/journal/weekly/accept", { ...body, change }),
    onSuccess: (d) => { setDecision(d.change); toast(`Added to the Rule Card as version ${d.version}`); },
  });
  const save = useMutation({
    mutationFn: () => post("/api/journal/weekly/save", { ...body, narration, decision: decision || change }),
    onSuccess: () => { toast("Review saved with its tiles, narration and decision"); qc.invalidateQueries({ queryKey: ["journal-weekly", m] }); },
  });

  if (isLoading) return <div className="h-40" />;
  if (error) return <Callout tone="danger" title="The review could not be built">{(error as Error).message}</Callout>;
  if (!r || r.kind === "empty") {
    return (
      <Panel title="Weekly Review" className="max-w-[720px]">
        <EmptyState action={<Button onClick={() => sample.mutate()} disabled={sample.isPending}>Load lesson 14 sample ({r?.sample ?? (m === "IN" ? "Kavita" : "Marcus")}, synthetic)</Button>}>
          No journal rows yet. Import a tradebook in Journal › Trades, or load the lesson sample.
        </EmptyState>
      </Panel>
    );
  }
  const breaks = r.rule_breaks.filter((f) => f.n);
  const patterns = r.patterns.filter((f) => f.n);
  const bars = r.bars;
  return (
    <LocalFactsProvider>
      <div className="flex flex-col gap-5">
        <div className="flex flex-wrap items-end gap-4 rounded-[var(--radius-panel)] border border-line bg-panel px-4 py-3">
          <Field label="Week of">
            <input type="date" className={cn(inputCls, "w-44")} value={weekOf || r.latest || ""} onChange={(e) => setWeekOf(e.target.value)} />
          </Field>
          <div className="flex flex-col gap-1">
            <span className="text-[12px] text-muted">Account</span>
            <Segmented label="Account" value={account} options={["Real", "Paper", "Both"] as const} onChange={setAccount} />
          </div>
          <div className="ml-auto flex flex-wrap items-center gap-2 pb-1 text-[13px] text-muted">
            <span className="num">Week {r.start} to {r.end}</span>
            <span>Rule Card {r.rule_card}</span>
            {r.kind === "sample" && <Badge>Synthetic sample</Badge>}
            <LocalOnly />
          </div>
        </div>

        {r.last_decision && <Callout tone="info" title="Last week you decided">{r.last_decision}</Callout>}
        <p className="text-[13px] text-muted">If the trade count or gross total does not match your broker, stop here and fix the import in Journal › Trades.</p>

        <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3 xl:grid-cols-6">
          {r.tiles.map((t) => {
            const meta = TILE[t.label] ?? { label: t.label, keys: [] };
            return (
              <Tile key={t.label} label={meta.label} keys={meta.keys} value={t.value} big={t.label === "RESULT"}
                tone={t.label === "RESULT" || t.label === "BREAKS COST" || t.label === "NET" ? signTone(t.value) : undefined}
                sub={<span className="flex flex-col"><span>{t.sub}</span><span className="num">{t.last}</span></span>} />
            );
          })}
        </div>

        <div className="grid gap-5 xl:grid-cols-2">
          <div className="flex min-w-0 flex-col gap-5">
            <Panel title="Rule breaks" action={<span className="text-[12px] text-muted">vs Rule Card {r.rule_card}</span>}>
              {breaks.length ? <div className="flex flex-col gap-2">{breaks.map((f) => <BreakRow key={f.label} f={f} m={m} saved={r.saved} />)}</div>
                : <p className="text-muted">No Rule Card line broken this week.</p>}
            </Panel>
            <Panel title="Detector: not yet a rule">
              {patterns.length ? (
                <ul className="flex flex-col divide-y divide-line">
                  {patterns.map((f) => (
                    <li key={f.label} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2">
                      <span className="font-medium">{f.label}</span>
                      <span className="num text-[13px] text-muted">rows {f.rows.join(", ")}</span>
                      <span className={cn("num text-[13px] font-medium", toneOf(f.total_r))}>{rStr(f.total_r)}</span>
                      {f.too_few ? <Badge tone="warn" className="ml-auto">{f.n_label}</Badge> : <Badge className="ml-auto">{f.n_label}</Badge>}
                    </li>
                  ))}
                </ul>
              ) : <p className="text-muted">No pattern to watch this week.</p>}
              <p className="mt-2 text-[12px] text-muted">Patterns with fewer than 30 trades are marked too few to conclude: watch them, do not write a rule yet.</p>
            </Panel>
          </div>
          <Panel title="R per trade" action={bars.length > 0 && <span className="num text-[12px] text-muted">rows {bars[0].trade_id} to {bars[bars.length - 1].trade_id}; outlined bars broke a line</span>}>
            {bars.length ? <RBars bars={bars} /> : <EmptyState>No trades in this week. Pick another week.</EmptyState>}
          </Panel>
        </div>

        {r.pinned.length > 0 && (
          <Panel title="Pinned questions">
            <ul className="flex flex-col gap-2">{r.pinned.map((p) => <li key={p.label}><span className="font-medium">{p.label}: </span><span className="font-serif">{p.text}</span></li>)}</ul>
          </Panel>
        )}

        <Panel title="Review and one change">
          <div className="flex flex-col gap-4">
            <LocalExplainPanel facts={r.facts} section="Journal" label="Generate review"
              run={() => post<Explanation>("/api/journal/weekly/generate", body)}
              onResult={(e) => setNarration(e.text)}
              extra={<Button size="sm" variant="quiet" onClick={() => setShowQ((s) => !s)} aria-pressed={showQ}><Code2 size={14} /> Show query</Button>} />
            {showQ && <QueryBlock sql={Object.entries(r.queries).map(([k, v]) => `-- ${k}\n${v}`).join("\n\n")} />}
            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-[280px] flex-1">
                <Field label="One change for next week (a Rule Card line or checklist item)">
                  <input className={inputCls} value={change} onChange={(e) => setChange(e.target.value)} placeholder="No new trade within 30 minutes of a losing exit" />
                </Field>
              </div>
              <Button variant="primary" onClick={() => accept.mutate()} disabled={!change.trim() || accept.isPending}>Accept</Button>
              <Button onClick={() => save.mutate()} disabled={save.isPending}><Save size={14} /> Save review</Button>
            </div>
            {decision && <p className="text-[13px] text-bull">On the Rule Card as the next version: {decision}</p>}
            {(accept.error || save.error) && <p className="text-[13px] text-bear">{((accept.error || save.error) as Error).message}</p>}
          </div>
        </Panel>
      </div>
    </LocalFactsProvider>
  );
}
