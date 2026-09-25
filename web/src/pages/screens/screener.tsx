import { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDownUp, CalendarClock } from "lucide-react";
import { get, post, type Market } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button, Field, Panel, inputCls } from "@/components/ui";
import { Badge, Callout, DataTable, Dialog, EmptyState, Select, Textarea, useToast, type Column } from "@/components/kit";
import { ExplainPanel, FactTile, FactsProvider } from "@/components/facts";
import { useMarket } from "@/components/shell";
import { ChipToggle, ErrorLine, Hint } from "@/components/research/common";

interface Setup {
  universes: string[]; universe: string; asof: string; presets: string[]; triage: string[]; schedule_time: string;
  watchlists: { name: string; symbols: string[]; review_by?: string }[];
}
interface RuleCard { metric: string; op: string; value: number; original: number; text: string; interpreted: string; editable: boolean }
interface Parsed { rules: RuleCard[]; exclude_events: number; unparsed: string[]; read_back: string; facts: string[] }
type ResultRow = Record<string, unknown> & { Symbol: string; Triage: string; "Next event": string; _sessions: number | null; _near: string[] };
interface Result {
  market: Market; universe: string; asof: string; source: string; tested: number; passed: number;
  columns: string[]; rows: ResultRow[]; excluded: { symbol: string; reason: string }[]; triage: string[]; facts: string[];
}

const RULES_Q = "Read every rule back in plain English, one line each. Do not add rules.";
const TRIAGE_Q = "Group these names into the four triage bins (Watch closely, Wait for the setup, Research first, Drop), quoting the columns. No recommendations.";

const isoWeek = (d: Date) => {
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const day = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - day);
  return Math.ceil(((t.getTime() - Date.UTC(t.getUTCFullYear(), 0, 1)) / 86400000 + 1) / 7);
};
const plusDays = (n: number) => new Date(Date.now() + n * 86400000).toISOString().slice(0, 10);

function fmtVal(v: unknown) {
  if (typeof v === "number") return Math.abs(v) >= 1000 ? v.toLocaleString("en-US", { maximumFractionDigits: 0 }) : v.toFixed(2);
  if (v === null || v === undefined) return "—";
  return String(v);
}

function ScheduleDialog({ open, onOpenChange, market, text, universe, defaultTime }: {
  open: boolean; onOpenChange: (v: boolean) => void; market: Market; text: string; universe: string; defaultTime: string;
}) {
  const toast = useToast();
  const [run, setRun] = useState(defaultTime);
  const [name, setName] = useState("");
  useEffect(() => { setRun(defaultTime); setName(/gap/i.test(text) ? "Gap scan" : "My screen"); }, [open, defaultTime, text]);
  const save = useMutation({
    mutationFn: () => post("/api/research/screener/schedule", { name, market, run_time: run, text, universe }),
    onSuccess: () => { toast("Scheduled on market days. It appears in Automate › Scheduler."); onOpenChange(false); },
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Schedule"
      footer={<><Button variant="quiet" onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button variant="primary" onClick={() => save.mutate()} disabled={!name.trim() || !run || save.isPending}>Accept</Button></>}>
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Run time" hint="A gap scan runs on the indicated or pre-market price, not last night's close.">
            <input type="time" className={inputCls} value={run} onChange={(e) => setRun(e.target.value)} />
          </Field>
          <Field label="Name"><input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} /></Field>
        </div>
        <Hint>Runs on market days over {universe}, on the local model.</Hint>
        <ErrorLine error={save.error} />
      </div>
    </Dialog>
  );
}

function SaveWatchlist({ res, market, text, tags, triage }: { res: Result; market: Market; text: string; tags: Record<string, string>; triage: string[] }) {
  const toast = useToast();
  const qc = useQueryClient();
  const [keep, setKeep] = useState<string[]>(["Watch closely"]);
  const [name, setName] = useState(`Screen week ${isoWeek(new Date())}`);
  const [review, setReview] = useState(plusDays(7));
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const names = res.rows.map((r) => r.Symbol).filter((s) => keep.includes(tags[s]));
  const save = useMutation({
    mutationFn: () => post<{ saved: number }>("/api/research/screener/watchlist", {
      name, market, symbols: names, reasons: Object.fromEntries(names.map((s) => [s, reasons[s] ?? ""])),
      review_by: review, rules_text: text, triage: Object.fromEntries(names.map((s) => [s, tags[s] ?? ""])) }),
    onSuccess: (r) => { toast(`Saved ${r.saved} names. The Daily Briefing picks it up tomorrow.`); qc.invalidateQueries({ queryKey: ["scr-setup"] }); qc.invalidateQueries({ queryKey: ["briefing-setup"] }); },
  });
  return (
    <Panel title="Save as watchlist">
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <span className="text-[12px] text-muted">Filter: Triage =</span>
          <ChipToggle label="Triage filter" options={triage} value={keep} onChange={setKeep} />
        </div>
        {names.length ? (
          <table className="w-full text-[14px]">
            <thead><tr className="border-b border-line text-left text-[12px] text-muted"><th className="w-[140px] pb-2 font-normal">Symbol</th><th className="pb-2 font-normal">Reason</th></tr></thead>
            <tbody>
              {names.map((s) => (
                <tr key={s} className="border-b border-line last:border-0">
                  <td className="py-1.5 font-medium">{s}</td>
                  <td className="py-1.5"><input aria-label={`Reason for ${s}`} className={cn(inputCls, "h-8 font-sans")} placeholder="One line: why this name is on the list"
                    value={reasons[s] ?? ""} onChange={(e) => setReasons((r) => ({ ...r, [s]: e.target.value }))} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <Hint>No names carry the chosen triage tags. Change the filter or the Triage column.</Hint>}
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_180px_auto] md:items-end">
          <Field label="Watchlist name"><input className={cn(inputCls, "font-sans")} value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Review by"><input type="date" className={inputCls} value={review} onChange={(e) => setReview(e.target.value)} /></Field>
          <Button variant="primary" onClick={() => save.mutate()} disabled={save.isPending}>Save as watchlist</Button>
        </div>
        <Hint>Every name needs a Reason; the lab refuses to save a name without one.</Hint>
        <ErrorLine error={save.error} />
      </div>
    </Panel>
  );
}

export default function Screener() {
  const [market] = useMarket();
  const toast = useToast();
  const { data: setup, error: setupError } = useQuery({ queryKey: ["scr-setup", market], queryFn: () => get<Setup>(`/api/research/screener/setup?market=${market}`) });
  const [universe, setUniverse] = useState("");
  const [asof, setAsof] = useState("");
  const [text, setText] = useState("");
  const [debounced, setDebounced] = useState("");
  const [edits, setEdits] = useState<Record<number, number>>({});
  const [excl, setExcl] = useState<number | null>(null);
  const [accepted, setAccepted] = useState(false);
  const [scheduling, setScheduling] = useState(false);
  const [sortEvent, setSortEvent] = useState(false);
  const [tags, setTags] = useState<Record<string, string>>({});

  useEffect(() => { if (setup) { setUniverse(setup.universe); setAsof(setup.asof); } }, [setup]);
  useEffect(() => { const t = setTimeout(() => setDebounced(text), 300); return () => clearTimeout(t); }, [text]);
  useEffect(() => { setEdits({}); setExcl(null); setAccepted(false); }, [debounced, market]);

  const { data: parsed } = useQuery({
    queryKey: ["scr-parse", market, debounced, edits, excl],
    queryFn: () => post<Parsed>("/api/research/screener/parse", { text: debounced, market, edits, exclude_events: excl }),
    enabled: !!debounced.trim(), placeholderData: keepPreviousData,
  });
  const p = debounced.trim() ? parsed : undefined;
  const exclude = excl ?? p?.exclude_events ?? 0;

  const loadPreset = async (name: string) => {
    const r = await get<{ text: string }>(`/api/research/screener/preset?name=${encodeURIComponent(name)}&market=${market}`);
    setText(r.text); setDebounced(r.text);
  };

  const run = useMutation({
    mutationFn: () => post<Result>("/api/research/screener/run", { text: debounced, market, edits, exclude_events: exclude, universe, asof }),
    onSuccess: (r) => { setTags(Object.fromEntries(r.rows.map((x) => [x.Symbol, x.Triage]))); setSortEvent(false); },
  });
  const res = run.data && run.data.market === market ? run.data : undefined;
  const rows = useMemo(() => {
    if (!res) return [];
    const r = res.rows.map((x) => ({ ...x, Triage: tags[x.Symbol] ?? x.Triage }));
    return sortEvent ? [...r].sort((a, b) => (a._sessions ?? 999) - (b._sessions ?? 999)) : r;
  }, [res, tags, sortEvent]);

  const columns: Column<ResultRow>[] = res ? res.columns.map((c) => {
    if (c === "Symbol") return { key: c, header: c, render: (r) => (
      <span className="whitespace-nowrap font-medium" title={r._near.length ? `Only just passes: ${r._near.join("; ")}` : undefined}>{r.Symbol}</span>) };
    if (c === "Next event") return { key: c, width: "210px", header: (
      <button type="button" onClick={() => setSortEvent(true)} className={cn("inline-flex items-center gap-1 hover:text-ink", sortEvent && "font-medium text-indigo")}
        title="Sort by the next event, nearest first">Next event <ArrowDownUp size={12} /></button>), render: (r) => <span className="text-[13px]">{r["Next event"]}</span> };
    if (c === "Triage") return { key: c, header: c, width: "180px", render: (r) => (
      <Select aria-label={`Triage for ${r.Symbol}`} className="h-8" value={r.Triage} onChange={(e) => setTags((t) => ({ ...t, [r.Symbol]: e.target.value }))}>
        {res.triage.map((t) => <option key={t}>{t}</option>)}
      </Select>) };
    if (c === "Latest item") return { key: c, header: c, render: (r) => <span className="text-[13px] text-muted">{String(r[c] ?? "")}</span> };
    return { key: c, header: c, align: "right" as const, render: (r: ResultRow) => <span className="whitespace-nowrap">{fmtVal(r[c])}</span> };
  }) : [];

  const rail = (
    <>
      <Panel title="Watchlists">
        {setup?.watchlists.length ? (
          <ul className="flex flex-col">
            {setup.watchlists.slice(0, 8).map((w, i) => (
              <li key={i} className="border-b border-line py-2 last:border-0">
                <div className="font-medium">{w.name}</div>
                <div className="num text-[12px] text-muted">{w.symbols.length} names, review by {w.review_by}</div>
              </li>
            ))}
          </ul>
        ) : <p className="text-[13px] text-muted">No saved watchlists yet. Run a screen, tag the results, then Save as watchlist.</p>}
      </Panel>
      {res && (
        <Panel title="Triage with the AI">
          <Hint className="mb-3">The AI groups the passing names into the four bins, quoting the lab's columns. Nothing is saved until you Accept; your tag always wins.</Hint>
          <ExplainPanel facts={res.facts} section="Research" question={TRIAGE_Q} onAccept={() => toast("Tags kept. Save as watchlist when ready.")} />
        </Panel>
      )}
    </>
  );

  return (
    <FactsProvider>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="flex min-w-0 flex-col gap-5">
          <Panel title="Describe your screen" action={<span className="text-[13px] text-muted">The AI drafts rules; the lab computes. No stock is picked by a model.</span>}>
            <div className="flex flex-col gap-3">
              <div className="grid gap-3 md:grid-cols-[200px_170px_minmax(0,1fr)] md:items-end">
                <Field label="Universe">
                  <Select value={universe} onChange={(e) => setUniverse(e.target.value)}>
                    {setup?.universes.map((u) => <option key={u}>{u}</option>)}
                  </Select>
                </Field>
                <Field label="As of"><input type="date" className={inputCls} value={asof} onChange={(e) => setAsof(e.target.value)} /></Field>
                <div className="flex flex-col gap-1">
                  <span className="text-[12px] text-muted">Presets</span>
                  <div className="flex flex-wrap gap-1.5">
                    {setup?.presets.map((n) => <Button key={n} size="sm" onClick={() => loadPreset(n)}>{n}</Button>)}
                  </div>
                </div>
              </div>
              <Hint>Offline universe: synthetic SYN-{market}-### names (no real market information).</Hint>
              <Textarea aria-label="Describe your screen" rows={3} className="font-serif text-[15px]" value={text} onChange={(e) => setText(e.target.value)}
                placeholder="Stocks near their 52-week high with volume picking up, liquid" />
              <ErrorLine error={setupError} />
            </div>
          </Panel>

          {p && (
            <Panel title="Rules preview" action={accepted ? <Badge tone="indigo">Accepted</Badge> : <span className="text-[12px] text-muted">Not accepted yet</span>}>
              <div className="flex flex-col gap-2">
                {p.rules.length === 0 && <Hint>No rule understood yet. Try words such as “within 10% of the 52-week high” or pick a preset.</Hint>}
                {p.rules.map((r, i) => (
                  <div key={`${r.metric}-${i}`} className="flex items-center gap-3 rounded-[var(--radius-tile)] border border-line bg-panel-2 px-3 py-2">
                    <span className="num w-5 text-muted">{i + 1}</span>
                    <div className="min-w-0 flex-1">
                      <span>{r.text}</span>
                      {r.interpreted && (
                        <span title={r.interpreted} tabIndex={0} aria-label={`Interpreted: ${r.interpreted}`}
                          className="ml-1.5 inline-flex h-5 w-5 cursor-help items-center justify-center rounded-[4px] bg-saffron/15 text-[12px] font-semibold text-saffron">?</span>)}
                      {r.interpreted && <div className="text-[12px] text-muted">Interpreted: {r.interpreted}</div>}
                    </div>
                    {r.editable && (
                      <input aria-label={`Value for rule ${i + 1}`} type="number" step="any" className={cn(inputCls, "h-8 w-24 text-right")}
                        value={edits[i] ?? r.original} onChange={(e) => e.target.value !== "" && setEdits((x) => ({ ...x, [i]: Number(e.target.value) }))} />
                    )}
                  </div>
                ))}
                {p.unparsed.map((u) => <Callout key={u} tone="warn">Not understood: “{u}”. Reword it or remove it.</Callout>)}
                <div className="mt-1 flex flex-wrap items-end gap-3">
                  <Field label="Exclude events within N sessions (0 = off)">
                    <input type="number" min={0} max={60} className={cn(inputCls, "w-28")} value={exclude}
                      onChange={(e) => setExcl(Math.max(0, Math.min(60, Number(e.target.value) || 0)))} />
                  </Field>
                  <Button variant="primary" onClick={() => run.mutate()} disabled={!p.rules.length || run.isPending || !universe}>
                    {run.isPending ? "Computing every rule on every name…" : "Run"}
                  </Button>
                  <Button onClick={() => setScheduling(true)} disabled={!p.rules.length}><CalendarClock size={15} /> Schedule</Button>
                </div>
                {p.rules.length > 0 && (
                  <div className="mt-2 border-t border-line pt-3">
                    <ExplainPanel facts={p.facts} section="Research" question={RULES_Q} onAccept={() => { setAccepted(true); toast("Rules accepted"); }} />
                    {!accepted && <Hint className="mt-2">Rules not accepted yet: Explain, compare with your sentence, then Accept.</Hint>}
                  </div>
                )}
                <ErrorLine error={run.error} />
              </div>
            </Panel>
          )}

          {!p && !res && (
            <EmptyState>Describe your screen in your own words, or pick a preset. Each rule becomes a card you can check and edit before you Run.</EmptyState>
          )}

          {res && (
            <>
              <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
                <FactTile label="Passed" value={res.passed} sub={`of ${res.tested} names tested`} big />
                <FactTile label="Excluded" value={res.excluded.length} sub="by the event rule" />
                <FactTile label="Universe" value={res.universe} sub={`as of ${res.asof}, source ${res.source}`} />
                <FactTile label="Watch closely" value={rows.filter((r) => r.Triage === "Watch closely").length} sub="with your tags" />
              </div>
              <Panel title="Results" action={<span className="text-[12px] text-muted">Hover a symbol for rules it only just passes</span>}>
                <DataTable rows={rows} columns={columns} rowKey={(r) => r.Symbol}
                  empty="No name passed every rule on this date. Loosen a number on a rule card, or try a wider universe." />
                {res.excluded.length > 0 && (
                  <div className="mt-3 flex flex-col gap-0.5 text-[13px] text-muted">
                    <span>Removed by the event rule:</span>
                    {res.excluded.map((x) => <span key={x.symbol}>{x.symbol}, excluded: {x.reason}</span>)}
                  </div>
                )}
              </Panel>
              {res.rows.length > 0 && (
                <SaveWatchlist res={res} market={market} text={debounced} tags={tags} triage={res.triage} />
              )}
            </>
          )}
        </div>
        <div className="flex flex-col gap-4">{rail}</div>
      </div>
      {setup && <ScheduleDialog open={scheduling} onOpenChange={setScheduling} market={market} text={debounced} universe={universe} defaultTime={setup.schedule_time} />}
    </FactsProvider>
  );
}
