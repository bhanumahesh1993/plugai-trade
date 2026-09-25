import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, Save } from "lucide-react";
import { get, post, type Market } from "@/lib/api";
import { money } from "@/lib/format";
import { cn } from "@/lib/cn";
import { Button, Panel, Field, inputCls } from "@/components/ui";
import { Badge, Callout, DataTable, EChart, EmptyState, Hypothetical, Select, Switch, Textarea, chartTokens, useToast, type Column } from "@/components/kit";
import { useMarket } from "@/components/shell";
import { LocalExplainPanel, LocalFactsProvider, LocalOnly, Tile } from "@/components/journal/local";
import { Disclosure, ImportForm, TagChips, hhmm, plain, rStr, splitTags, toneOf, type ImportArgs } from "@/components/journal/common";

type Row = Record<string, unknown> & { trade_id: number };
interface Meta { brokers: string[]; generic_fields: string[]; generic_required: string[]; tags: string[]; sample: string; as_of: string; rule_card: string }
interface Pending { broker: string; fills: number; round_trips: number; unpaired: number; gross: number; charges: number; net: number; unmatched_plans: number[]; rows: Row[]; facts: string[]; as_of: string }
interface Journal {
  kind: "journal" | "sample" | "empty"; label: string; saved?: boolean; round_trips: number; gross: number; charges: number; net: number;
  total_r: number; rows: Row[]; histogram: { bin: number; n: number }[]; beyond_stop: string; avg_winner_r: number | null;
  sessions: string[]; facts: string[]; sample: string;
}
interface Replay { day: string; blocked: number; rows: Row[]; facts: string[]; handoff: { speed: number; tag: string } | null; note: string; question: string }
type Edit = { stop: string; setup: string; tags: string };

const editsOf = (rows: Row[]): Record<number, Edit> =>
  Object.fromEntries(rows.map((r) => [r.trade_id, {
    stop: r.stop_distance == null ? "" : String(r.stop_distance), setup: (r.setup as string) ?? "",
    tags: Array.isArray(r.tags) ? (r.tags as string[]).join(", ") : "",
  }]));
const toEdits = (e: Record<number, Edit>) => Object.entries(e).map(([id, v]) => ({
  trade_id: Number(id), stop_distance: v.stop === "" ? null : Number(v.stop), setup: v.setup || null, tags: splitTags(v.tags),
}));

function EditCell({ value, onChange, label, w = "w-24", numeric }: { value: string; onChange: (v: string) => void; label: string; w?: string; numeric?: boolean }) {
  return <input aria-label={label} className={cn(inputCls, "h-7 px-2 text-[13px]", w, numeric && "text-right")} value={value}
    inputMode={numeric ? "decimal" : undefined} onChange={(e) => onChange(e.target.value)} />;
}

/* ------------------------------------------------------------ pending import */
function PendingPanel({ p, m, onDone }: { p: Pending; m: Market; onDone: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [edits, setEdits] = useState<Record<number, Edit>>(() => editsOf(p.rows));
  useEffect(() => setEdits(editsOf(p.rows)), [p]);
  const setPending = (d: { pending: Pending | null }) => qc.setQueryData(["journal-pending", m], d);
  const match = useMutation({ mutationFn: () => post<{ pending: Pending }>(`/api/journal/pending/match?market=${m}`), onSuccess: setPending });
  const preview = useMutation({ mutationFn: () => post<{ pending: Pending }>("/api/journal/pending/preview", { market: m, edits: toEdits(edits) }), onSuccess: setPending });
  const accept = useMutation({
    mutationFn: () => post<{ saved: number }>("/api/journal/pending/accept", { market: m, edits: toEdits(edits) }),
    onSuccess: (d) => { toast(`Locked ${d.saved} round trips into the journal`); onDone(); },
  });
  const discard = useMutation({ mutationFn: () => post(`/api/journal/pending/discard?market=${m}`), onSuccess: () => { toast("Import discarded"); onDone(); } });
  const set = (id: number, k: keyof Edit, v: string) => setEdits((e) => ({ ...e, [id]: { ...e[id], [k]: v } }));
  const cols: Column<Row>[] = [
    { key: "trade_id", header: "Row", align: "right" },
    { key: "date", header: "Date", render: (r) => <span className="whitespace-nowrap">{String(r.date ?? "—")}</span> },
    { key: "symbol", header: "Symbol", render: (r) => <span className="whitespace-nowrap">{String(r.symbol ?? "—")}</span> },
    { key: "side", header: "Side" },
    { key: "qty", header: "Qty", align: "right", render: (r) => plain(r.qty) },
    { key: "entry_price", header: "Entry", align: "right", render: (r) => plain(r.entry_price) },
    { key: "exit_price", header: "Exit", align: "right", render: (r) => plain(r.exit_price) },
    { key: "gross", header: "Gross", align: "right", render: (r) => <span className={toneOf(r.gross)}>{money(r.gross as number, m)}</span> },
    { key: "charges", header: "Charges", align: "right", render: (r) => money(r.charges as number, m, 2) },
    { key: "charges_source", header: "Charges from", render: (r) => <span className="whitespace-nowrap text-muted">{String(r.charges_source ?? "—")}</span> },
    { key: "stop_distance", header: "Stop (pts)", render: (r) => edits[r.trade_id] && <EditCell numeric label={`Stop for row ${r.trade_id}`} w="w-20" value={edits[r.trade_id].stop} onChange={(v) => set(r.trade_id, "stop", v)} /> },
    { key: "r_multiple", header: "R", align: "right", render: (r) => <span className={toneOf(r.r_multiple)}>{rStr(r.r_multiple)}</span> },
    { key: "setup", header: "Setup", render: (r) => edits[r.trade_id] && <EditCell label={`Setup for row ${r.trade_id}`} w="w-32" value={edits[r.trade_id].setup} onChange={(v) => set(r.trade_id, "setup", v)} /> },
    { key: "tags", header: "Tags", render: (r) => edits[r.trade_id] && <EditCell label={`Tags for row ${r.trade_id}`} w="w-36" value={edits[r.trade_id].tags} onChange={(v) => set(r.trade_id, "tags", v)} /> },
    { key: "source", header: "Source", render: (r) => <span className="whitespace-nowrap text-[12px] text-muted">{String(r.source ?? "")}</span> },
  ];
  return (
    <Panel title={`Import from ${p.broker}`} action={<span className="text-[13px] text-muted num">{p.fills} fills to {p.round_trips} round trips, {p.unpaired} fills could not be paired (open positions)</span>}>
      <div className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
          <Tile label="Round trips" value={p.round_trips} />
          <Tile label="Gross P&L" value={money(p.gross, m)} tone={p.gross >= 0 ? "bull" : "bear"} />
          <Tile label="Charges" value={money(p.charges, m)} />
          <Tile label="Net" value={money(p.net, m)} tone={p.net >= 0 ? "bull" : "bear"} big />
        </div>
        <p className="text-[13px] text-muted">Compare these totals with your broker's P&L statement for the same dates. Charges marked "cost table" were priced from the dated reference (as of {p.as_of}; live values in Derivatives › Contract Table).</p>
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => match.mutate()} disabled={match.isPending}>Match plans</Button>
          <Button variant="quiet" onClick={() => preview.mutate()} disabled={preview.isPending}>Update R from typed stops</Button>
        </div>
        {p.unmatched_plans.length > 0 && (
          <Callout tone="warn" title={`${p.unmatched_plans.length} trades have no planned stop`}>
            Type the stop (points per unit) in the table to get their R. Rows {p.unmatched_plans.join(", ")}.
          </Callout>
        )}
        <DataTable rows={p.rows} columns={cols} rowKey={(r) => r.trade_id} />
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" onClick={() => accept.mutate()} disabled={accept.isPending}>Accept</Button>
          <Button variant="danger" onClick={() => discard.mutate()}>Discard import</Button>
        </div>
        {(match.error || accept.error || preview.error) && <p className="text-[13px] text-bear">{((match.error || accept.error || preview.error) as Error).message}</p>}
      </div>
    </Panel>
  );
}

/* ------------------------------------------------------------ charts */
function RHistogram({ bins }: { bins: { bin: number; n: number }[] }) {
  const t = chartTokens();
  const option = {
    grid: { left: 36, right: 12, top: 12, bottom: 36 },
    tooltip: { trigger: "axis", valueFormatter: (v: number) => `${v} trades` },
    xAxis: { type: "category", data: bins.map((b) => (b.bin === 0 ? "0" : b.bin.toFixed(1).replace("-", "−"))), name: "R", nameLocation: "middle", nameGap: 26,
      axisLine: { lineStyle: { color: t.line } }, axisLabel: { color: t.muted } },
    yAxis: { type: "value", minInterval: 1, splitLine: { lineStyle: { color: t.line } }, axisLabel: { color: t.muted } },
    series: [{ type: "bar", barMaxWidth: 28, data: bins.map((b) => ({ value: b.n, itemStyle: { color: b.bin < 0 ? t.bear : t.bull, borderRadius: [3, 3, 0, 0] } })) }],
  };
  return <EChart option={option} height={220} />;
}

function ReplayChart({ rows }: { rows: Row[] }) {
  const t = chartTokens();
  const ts = (s: unknown) => new Date(String(s)).getTime();
  const option = {
    grid: { left: 64, right: 16, top: 28, bottom: 28 },
    legend: { data: ["Entry", "Exit"], top: 0, right: 0, textStyle: { color: t.muted } },
    tooltip: { trigger: "item" },
    xAxis: { type: "time", axisLine: { lineStyle: { color: t.line } }, axisLabel: { color: t.muted, formatter: "{HH}:{mm}" } },
    yAxis: { type: "value", scale: true, splitLine: { lineStyle: { color: t.line } }, axisLabel: { color: t.muted } },
    series: [
      ...rows.map((r) => ({ type: "line", silent: true, symbol: "none", data: [[ts(r.entry_time), r.entry_price], [ts(r.exit_time), r.exit_price]],
        lineStyle: { color: (r.r as number) >= 0 ? t.bull : t.bear, width: 1.5, type: "dashed" } })),
      { name: "Entry", type: "scatter", symbolSize: 11, itemStyle: { color: t.indigo },
        data: rows.map((r) => ({ value: [ts(r.entry_time), r.entry_price], name: `Row ${r.trade_id} entry ${r.side}` })) },
      { name: "Exit", type: "scatter", symbol: "diamond", symbolSize: 12, itemStyle: { color: t.ink },
        data: rows.map((r) => ({ value: [ts(r.exit_time), r.exit_price], name: `Row ${r.trade_id} exit, ${rStr(r.r)}` })) },
    ],
  };
  return <EChart option={option} height={240} />;
}

/* ------------------------------------------------------------ replay */
function ReplayPanel({ j, m, showSim, tag }: { j: Journal; m: Market; showSim: boolean; tag: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [day, setDay] = useState(j.sessions[0] ?? "");
  useEffect(() => { if (!j.sessions.includes(day)) setDay(j.sessions[0] ?? ""); }, [j.sessions, day]);
  const { data } = useQuery({ queryKey: ["journal-replay", m], queryFn: () => get<{ replay: Replay | null }>(`/api/journal/replay?market=${m}`) });
  const rep = data?.replay;
  const run = useMutation({
    mutationFn: () => post<{ replay: Replay }>("/api/journal/replay", { market: m, day, show_simulated: showSim, tag }),
    onSuccess: (d) => { qc.setQueryData(["journal-replay", m], d); toast(`Session ${d.replay.day} sent to the Paper Desk`); },
  });
  const [note, setNote] = useState("");
  const saveNote = useMutation({
    mutationFn: () => post("/api/journal/replay/note", { market: m, day: rep?.day, note }),
    onSuccess: () => toast("Note saved to the session"),
  });
  const cols: Column<Row>[] = [
    { key: "trade_id", header: "Row", align: "right" },
    { key: "entry_time", header: "Entry", render: (r) => hhmm(r.entry_time) },
    { key: "exit_time", header: "Exit", render: (r) => hhmm(r.exit_time) },
    { key: "side", header: "Side" },
    { key: "entry_price", header: "Entry price", align: "right", render: (r) => plain(r.entry_price) },
    { key: "exit_price", header: "Exit price", align: "right", render: (r) => plain(r.exit_price) },
    { key: "r", header: "R", align: "right", render: (r) => <span className={toneOf(r.r)}>{rStr(r.r)}</span> },
    { key: "hold_minutes", header: "Held (min)", align: "right", render: (r) => plain(r.hold_minutes, 0) },
    { key: "gap_minutes", header: "Gap after previous exit (min)", align: "right", render: (r) => plain(r.gap_minutes, 0) },
    { key: "charges", header: "Charges", align: "right", render: (r) => money(r.charges as number, m, 2) },
    { key: "rules_broken", header: "Broke", render: (r) => (r.rules_broken ? <Badge tone="bear">{String(r.rules_broken)}</Badge> : <span className="text-muted">—</span>) },
  ];
  return (
    <Panel title="Replay a session" action={rep && <Hypothetical />}>
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Session">
            <Select value={day} onChange={(e) => setDay(e.target.value)} className="w-44">
              {j.sessions.map((d) => <option key={d}>{d}</option>)}
            </Select>
          </Field>
          <Button variant="primary" onClick={() => run.mutate()} disabled={!day || run.isPending}><Play size={14} /> Replay</Button>
          <span className="pb-2 text-[13px] text-muted">Uses the tag filter above: pick PAPER to replay a paper session.</span>
        </div>
        {run.error && <p className="text-[13px] text-bear">{(run.error as Error).message}</p>}
        {rep && (
          <>
            <Callout tone="info" title={`Session ${rep.day} sent to Paper Trading › Paper Desk`}>
              Replay mode at {rep.handoff?.speed ?? 5}× (tag {rep.handoff?.tag ?? "REPLAY"}), with each entry and exit marked.{" "}
              <Link to="/paper-desk" className="font-medium text-indigo underline-offset-2 hover:underline">Open Paper Desk</Link>
            </Callout>
            {rep.rows.length > 0 ? <ReplayChart rows={rep.rows} /> : <EmptyState>No filled trades in this session{rep.blocked ? `; ${rep.blocked} blocked tickets` : ""}.</EmptyState>}
            {rep.rows.length > 0 && <DataTable rows={rep.rows} columns={cols} rowKey={(r) => r.trade_id} />}
            <LocalExplainPanel facts={rep.facts} section="Journal" question={rep.question} label="Generate review" />
            <div className="flex flex-col gap-2">
              <Field label="Notes: one sentence on what you will do differently (a Rule Card change to consider, not a trade idea)">
                <Textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder={rep.note || "Wait 30 minutes after a losing exit before the next entry."} />
              </Field>
              <div><Button size="sm" onClick={() => saveNote.mutate()} disabled={!note.trim() || saveNote.isPending}><Save size={14} /> Save note</Button></div>
            </div>
          </>
        )}
      </div>
    </Panel>
  );
}

/* ------------------------------------------------------------ journal */
function JournalPanel({ m, meta }: { m: Market; meta?: Meta }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [showSim, setShowSim] = useState(true);
  const [tag, setTag] = useState("All");
  const key = ["journal-trades", m, showSim, tag];
  const { data: j, isLoading } = useQuery({ queryKey: key, queryFn: () => get<Journal>(`/api/journal/trades?market=${m}&show_simulated=${showSim}&tag=${tag}`) });
  const [edits, setEdits] = useState<Record<number, Edit>>({});
  useEffect(() => { if (j?.rows) setEdits(editsOf(j.rows)); }, [j]);
  const sample = useMutation({ mutationFn: () => post(`/api/journal/sample?market=${m}`), onSuccess: () => { qc.invalidateQueries({ queryKey: ["journal-trades", m] }); toast("Lesson 14 sample loaded"); } });
  const save = useMutation({
    mutationFn: () => post("/api/journal/tags", { market: m, edits: toEdits(edits) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["journal-trades", m] }); toast("Tags saved"); },
  });
  const set = (id: number, k: keyof Edit, v: string) => setEdits((e) => ({ ...e, [id]: { ...e[id], [k]: v } }));
  const editable = !!j?.saved;
  const cols = useMemo<Column<Row>[]>(() => [
    { key: "trade_id", header: "Row", align: "right" },
    { key: "date", header: "Date", render: (r) => <span className="whitespace-nowrap">{String(r.date ?? "—")}</span> },
    { key: "entry_time", header: "In", render: (r) => hhmm(r.entry_time) },
    { key: "exit_time", header: "Out", render: (r) => hhmm(r.exit_time) },
    { key: "symbol", header: "Symbol", render: (r) => <span className="whitespace-nowrap">{String(r.symbol ?? "—")}</span> },
    { key: "side", header: "Side" },
    { key: "qty", header: "Qty", align: "right", render: (r) => plain(r.qty) },
    { key: "entry_price", header: "Entry", align: "right", render: (r) => plain(r.entry_price) },
    { key: "exit_price", header: "Exit", align: "right", render: (r) => plain(r.exit_price) },
    { key: "gross", header: "Gross", align: "right", render: (r) => <span className={toneOf(r.gross)}>{money(r.gross as number, m)}</span> },
    { key: "charges", header: "Charges", align: "right", render: (r) => money(r.charges as number, m, 2) },
    { key: "net", header: "Net", align: "right", render: (r) => <span className={toneOf(r.net)}>{money(r.net as number, m)}</span> },
    { key: "stop_distance", header: "Stop (pts)", align: editable ? "left" : "right", render: (r) => editable && edits[r.trade_id]
      ? <EditCell numeric label={`Stop for row ${r.trade_id}`} w="w-20" value={edits[r.trade_id].stop} onChange={(v) => set(r.trade_id, "stop", v)} /> : plain(r.stop_distance) },
    { key: "r_multiple", header: "R", align: "right", render: (r) => <span className={cn("font-medium", toneOf(r.r_multiple))}>{rStr(r.r_multiple)}</span> },
    { key: "setup", header: "Setup", render: (r) => editable && edits[r.trade_id]
      ? <EditCell label={`Setup for row ${r.trade_id}`} w="w-32" value={edits[r.trade_id].setup} onChange={(v) => set(r.trade_id, "setup", v)} /> : String(r.setup ?? "—") },
    { key: "tags", header: "Tags", render: (r) => editable && edits[r.trade_id]
      ? <EditCell label={`Tags for row ${r.trade_id}`} w="w-36" value={edits[r.trade_id].tags} onChange={(v) => set(r.trade_id, "tags", v)} /> : <TagChips tags={r.tags} /> },
    { key: "account", header: "Account" },
  ], [editable, edits, m]);

  if (isLoading || !j) return <Panel title="Journal"><div className="h-40" /></Panel>;
  if (j.kind === "empty") {
    return (
      <Panel title="Journal">
        <EmptyState action={<Button onClick={() => sample.mutate()} disabled={sample.isPending}>Load lesson 14 sample ({meta?.sample ?? j.sample}, synthetic)</Button>}>
          No trades yet. Import a tradebook above, or load the lesson sample to follow Chapter 14.
        </EmptyState>
      </Panel>
    );
  }
  return (
    <>
      <Panel title="Journal" action={<span className="flex items-center gap-2 text-[13px] text-muted">Showing {j.label}{j.kind === "sample" && <Badge>Synthetic</Badge>}</span>}>
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
            <div className="w-[300px]"><Switch checked={showSim} onChange={setShowSim} label="Show PAPER / REPLAY / BLOCKED rows" /></div>
            <Field label="Tag">
              <Select value={tag} onChange={(e) => setTag(e.target.value)} className="w-36">
                {["All", ...(meta?.tags ?? ["REAL", "PAPER", "REPLAY", "PILOT", "BLOCKED"])].map((t) => <option key={t}>{t}</option>)}
              </Select>
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-2.5 md:grid-cols-5">
            <Tile label="Total R" value={rStr(j.total_r)} tone={j.total_r > 0 ? "bull" : j.total_r < 0 ? "bear" : undefined} big sub="before charges" />
            <Tile label="Round trips" value={j.round_trips} keys={["trades"]} />
            <Tile label="Gross" value={money(j.gross, m)} tone={j.gross > 0 ? "bull" : j.gross < 0 ? "bear" : undefined} />
            <Tile label="Charges" value={money(j.charges, m)} keys={["charges", "average charges per trade"]} />
            <Tile label="Net" value={money(j.net, m)} tone={j.net > 0 ? "bull" : j.net < 0 ? "bear" : undefined} />
          </div>
          {j.rows.length ? (
            <div className="max-h-[440px] overflow-y-auto scroll-thin">
              <DataTable rows={j.rows} columns={cols} rowKey={(r) => r.trade_id} />
            </div>
          ) : <EmptyState>No rows match this filter. Switch the tag to All or show PAPER / REPLAY / BLOCKED rows.</EmptyState>}
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={() => save.mutate()} disabled={!editable || save.isPending} title="Tags: setup, mistake, market mood, PAPER / PILOT">
              <Save size={14} /> Save tags
            </Button>
            <span className="text-[13px] text-muted">
              {editable ? "Tags: setup, mistake, market mood, PAPER / PILOT. Separate them with commas." : "The lesson sample is read-only. Import and Accept your own tradebook to tag rows."}
            </span>
          </div>
          {save.error && <p className="text-[13px] text-bear">{(save.error as Error).message}</p>}
        </div>
      </Panel>

      {j.histogram.length > 0 && (
        <Panel title="R-multiples" action={<span className="text-[12px] text-muted">bins of 0.5R, before charges</span>}>
          <RHistogram bins={j.histogram} />
          <p className="mt-1 text-[13px] text-muted">{j.beyond_stop}; average winner {j.avg_winner_r ?? "—"}R.</p>
        </Panel>
      )}
      {j.sessions.length > 0 && <ReplayPanel j={j} m={m} showSim={showSim} tag={tag} />}
    </>
  );
}

/* ------------------------------------------------------------ screen */
export default function Trades() {
  const [m] = useMarket();
  const qc = useQueryClient();
  const toast = useToast();
  const { data: meta } = useQuery({ queryKey: ["journal-meta", m], queryFn: () => get<Meta>(`/api/journal/meta?market=${m}`) });
  const { data: pend } = useQuery({ queryKey: ["journal-pending", m], queryFn: () => get<{ pending: Pending | null }>(`/api/journal/pending?market=${m}`) });
  const [paper, setPaper] = useState(false);
  const imp = useMutation({
    mutationFn: (a: ImportArgs) => post<{ pending: Pending }>("/api/journal/import", { market: m, paper, ...a }),
    onSuccess: (d) => { qc.setQueryData(["journal-pending", m], d); toast(`Imported ${d.pending.round_trips} round trips from ${d.pending.broker}; check them, then Accept`); },
  });
  const refresh = () => {
    qc.setQueryData(["journal-pending", m], { pending: null });
    qc.invalidateQueries({ queryKey: ["journal-trades", m] });
    qc.invalidateQueries({ queryKey: ["journal-meta", m] });
  };
  const pending = pend?.pending;
  return (
    <LocalFactsProvider>
      <div className="flex flex-col gap-5">
        <div className="flex flex-wrap items-center gap-2 text-[13px] text-muted">
          <LocalOnly /> Journal data stays local: AI calls here use the local model only.
        </div>
        <Disclosure key={pending ? "p" : "n"} defaultOpen={!pending} summary={<span className="font-semibold">Import tradebook</span>}>
          {meta && (
            <ImportForm brokers={meta.brokers} accountDefault="Main" fileLabel="Tradebook CSV (strip client ID, PAN / SSN first)"
              fields={meta.generic_fields} required={meta.generic_required} pending={imp.isPending} templateLink
              onImport={(a) => imp.mutate(a)}>
              <div className="max-w-[520px]"><Switch checked={paper} onChange={setPaper} label="These are PAPER trades" hint="Rows arrive tagged PAPER and can be shown or hidden." /></div>
            </ImportForm>
          )}
          {imp.error && <p className="mt-3 text-[13px] text-bear">{(imp.error as Error).message}</p>}
        </Disclosure>
        {pending && <PendingPanel p={pending} m={m} onDone={refresh} />}
        <JournalPanel m={m} meta={meta} />
      </div>
    </LocalFactsProvider>
  );
}
