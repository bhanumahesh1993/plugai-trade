import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, CheckCircle2, HelpCircle } from "lucide-react";
import { get, post, type Market } from "@/lib/api";
import { Button, Field, Panel, inputCls } from "@/components/ui";
import { Badge, Callout, Dialog, EmptyState, Select, Switch, useToast } from "@/components/kit";
import { ExplainPanel, FactTile, FactsProvider } from "@/components/facts";
import { useMarket } from "@/components/shell";
import { ChipToggle, Disclosure, ErrorLine, Hint } from "@/components/research/common";

interface Setup {
  sample_name: string; sample: string[]; saved: { name: string; symbols: string[]; review_by?: string }[];
  defaults: { run_time: string; cutoff: string; days: string }; tz: string; channels: string[];
}
interface Line { panel: string; text: string; sourced: boolean; source: string; published: string; reason: string }
interface Briefing {
  market: Market; day: string; cutoff: string; edition: number; tz: string; sources: string[]; header: string;
  panels: Record<string, Line[]>; questions: string[]; yesterday: string; sourced: number; unsourced: number;
  dropped: string[]; facts: string[];
}
interface Runs {
  editions: { edition: number; cutoff: string; created: string }[];
  jobs: { market: string; days: string; run_time: string; news_cutoff: string; refresh_time?: string | null; delivery: string[]; tz: string }[];
}

const QUESTION = "Write the morning briefing from these facts. Keep every flag; no advice.";

function BriefLine({ ln }: { ln: Line }) {
  return (
    <li className="flex gap-2.5 border-b border-line py-2.5 last:border-0">
      {ln.sourced
        ? <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-muted" aria-label="Sourced" />
        : <HelpCircle size={16} className="mt-0.5 shrink-0 text-saffron" aria-label="Unsourced" />}
      <div className="min-w-0">
        <div className="num">{ln.text}</div>
        <div className="text-[12px] text-muted">
          {ln.sourced ? <>{ln.source}{ln.published && <>, {ln.published}</>}</> : <span className="text-saffron">Unsourced: {ln.reason}</span>}
        </div>
      </div>
    </li>
  );
}

function BriefPanel({ title, lines }: { title: string; lines: Line[] }) {
  return (
    <Panel title={title}>
      {lines.length ? <ul>{lines.map((ln, i) => <BriefLine key={i} ln={ln} />)}</ul>
        : <p className="text-muted">Nothing on your list for this panel.</p>}
    </Panel>
  );
}

function ScheduleDialog({ open, onOpenChange, market, setup }: { open: boolean; onOpenChange: (v: boolean) => void; market: Market; setup: Setup }) {
  const toast = useToast();
  const qc = useQueryClient();
  const [run, setRun] = useState(setup.defaults.run_time);
  const [cut, setCut] = useState(setup.defaults.cutoff);
  const [refresh, setRefresh] = useState("");
  const [where, setWhere] = useState<string[]>(["Dashboard"]);
  useEffect(() => { setRun(setup.defaults.run_time); setCut(setup.defaults.cutoff); }, [setup]);
  const save = useMutation({
    mutationFn: () => post("/api/research/briefing/schedule", { market, run_time: run, cutoff: cut, delivery: where, refresh_time: refresh || null }),
    onSuccess: () => { toast("Scheduled. It appears in Automate › Scheduler."); qc.invalidateQueries({ queryKey: ["briefing-runs"] }); onOpenChange(false); },
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Schedule"
      footer={<><Button variant="quiet" onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button variant="primary" onClick={() => save.mutate()} disabled={save.isPending || !run || !cut}>Accept</Button></>}>
      <div className="flex flex-col gap-4">
        <Hint>Runs on {setup.defaults.days}; exchange holidays are skipped. Times in {setup.tz}.</Hint>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Run time"><input type="time" className={inputCls} value={run} onChange={(e) => setRun(e.target.value)} /></Field>
          <Field label="News cutoff"><input type="time" className={inputCls} value={cut} onChange={(e) => setCut(e.target.value)} /></Field>
          <Field label="Second edition" hint="Optional refresh"><input type="time" className={inputCls} value={refresh} onChange={(e) => setRefresh(e.target.value)} /></Field>
        </div>
        <div className="flex flex-col gap-1.5">
          <span className="text-[12px] text-muted">Delivery</span>
          <ChipToggle label="Delivery" options={setup.channels} value={where} onChange={setWhere} />
          <Hint>Desktop, Email and Telegram go through Paper Trading › Alerts.</Hint>
        </div>
        <Hint>Model: the local default ({market === "IN" ? "₹0" : "$0"}). Each run is saved with its cutoff time.</Hint>
        <ErrorLine error={save.error} />
      </div>
    </Dialog>
  );
}

function SavedRuns({ market }: { market: Market }) {
  const { data } = useQuery({ queryKey: ["briefing-runs", market], queryFn: () => get<Runs>(`/api/research/briefing/runs?market=${market}`) });
  const eds = data?.editions ?? [], jobs = data?.jobs ?? [];
  return (
    <Disclosure title={`Editions today (${eds.length}), saved runs (${jobs.length})`}>
      {!eds.length && !jobs.length && <p className="text-muted">No editions today and no schedule yet. Generate a briefing, or click Schedule.</p>}
      <ul className="flex flex-col gap-1.5 text-[13px]">
        {eds.map((e, i) => (
          <li key={`e${i}`} className="num">Edition {e.edition}, cutoff {e.cutoff}, saved {e.created?.slice(11, 16)} UTC</li>
        ))}
        {jobs.map((j, i) => (
          <li key={`j${i}`} className="num">{j.market} on {j.days}: run {j.run_time}, cutoff {j.news_cutoff}{j.refresh_time ? `, refresh ${j.refresh_time}` : ""}, delivered to {j.delivery.join(", ")}</li>
        ))}
      </ul>
    </Disclosure>
  );
}

export default function DailyBriefing() {
  const [market] = useMarket();
  const qc = useQueryClient();
  const { data: setup, error: setupError } = useQuery({ queryKey: ["briefing-setup", market], queryFn: () => get<Setup>(`/api/research/briefing/setup?market=${market}`) });
  const [choice, setChoice] = useState("Sample watchlist");
  const [names, setNames] = useState("");
  const [cutoff, setCutoff] = useState("");
  const [online, setOnline] = useState(false);
  const [scheduling, setScheduling] = useState(false);

  // A new market or watchlist choice refills the names (the classic page keys the field the same way).
  useEffect(() => {
    if (!setup) return;
    const saved = setup.saved.find((w) => w.name === choice);
    setNames((saved?.symbols ?? setup.sample).join(", "));
  }, [setup, choice]);
  useEffect(() => { if (setup) setCutoff(setup.defaults.cutoff); }, [setup]);
  useEffect(() => { setChoice("Sample watchlist"); }, [market]);

  const gen = useMutation({
    mutationFn: () => post<Briefing>("/api/research/briefing/generate", {
      symbols: names.split(",").map((s) => s.trim()).filter(Boolean), market, cutoff, online }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["briefing-runs"] }),
  });
  const b = gen.data && gen.data.market === market ? gen.data : undefined;
  const day = b ? new Date(b.day + "T00:00:00").toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short", year: "numeric" }) : "";

  return (
    <FactsProvider>
      <div className="flex flex-col gap-5">
        <Panel title="Your list and cutoff" action={<span className="text-[13px] text-muted">Scheduled facts and your questions. Nothing here is a trade suggestion.</span>}>
          <div className="grid gap-3 md:grid-cols-[220px_minmax(0,1fr)_140px_auto] md:items-end">
            <Field label="Watchlist">
              <Select value={choice} onChange={(e) => setChoice(e.target.value)} title="Saved watchlists come from Research › Screener › Save as watchlist.">
                <option>Sample watchlist</option>
                {setup?.saved.map((w) => <option key={w.name}>{w.name}</option>)}
              </Select>
            </Field>
            <Field label="Names (comma-separated)">
              <input className={inputCls} value={names} onChange={(e) => setNames(e.target.value)} />
            </Field>
            <Field label={`News cutoff (${setup?.tz ?? ""})`}>
              <input type="time" className={inputCls} value={cutoff} onChange={(e) => setCutoff(e.target.value)} />
            </Field>
            <div className="min-w-[210px]">
              <Switch checked={online} onChange={setOnline} label="Read RSS feeds"
                hint={market === "IN" ? "On: NSE and BSE announcements" : "On: SEC EDGAR 8-K feed"} />
            </div>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button variant="primary" onClick={() => gen.mutate()} disabled={gen.isPending || !names.trim()}>
              {gen.isPending ? "Gathering closes, headlines and the calendar…" : "Generate briefing"}
            </Button>
            <Button onClick={() => setScheduling(true)} disabled={!setup}><CalendarClock size={15} /> Schedule</Button>
            <span className="text-[13px] text-muted">Off: offline sample items, clearly labelled.</span>
          </div>
          <div className="mt-3"><ErrorLine error={gen.error ?? setupError} /></div>
        </Panel>

        {!b && (
          <EmptyState>
            Click <b className="text-ink">Generate briefing</b>. The filter runs in code first: nothing after the cutoff, nothing older than the previous close, nothing off your list.
          </EmptyState>
        )}

        {b && (
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
            <div className="flex min-w-0 flex-col gap-5">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="mr-2 text-[20px] font-semibold">Daily Briefing, {day}</h2>
                <Badge tone={b.market === "IN" ? "in" : "us"}>{b.market}</Badge>
                <Badge>Edition {b.edition}</Badge>
                <Badge>Cutoff {b.cutoff} {b.tz}</Badge>
                {b.sources.map((s) => <Badge key={s}>{s}</Badge>)}
              </div>
              <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
                <FactTile label="Sourced lines" value={b.sourced} sub="flag set by code" big />
                <FactTile label="Unsourced lines" value={b.unsourced} sub={b.unsourced ? "check before you act" : "none today"} big />
                <FactTile label="Filtered out" value={b.dropped.length} sub="after the cutoff or too old" />
                <FactTile label="Questions for you" value={b.questions.length} sub="answer against your Rule Card" />
              </div>
              <div className="grid gap-5 lg:grid-cols-2">
                <div className="flex flex-col gap-5">
                  <BriefPanel title="Watchlist" lines={b.panels["Watchlist"]} />
                  <BriefPanel title="Events today" lines={b.panels["Events today"]} />
                </div>
                <div className="flex flex-col gap-5">
                  <BriefPanel title="Overnight news" lines={b.panels["Overnight news"]} />
                  <Panel title="Questions for you">
                    <ol className="flex list-decimal flex-col gap-2 pl-5 font-serif text-[15px] leading-[1.55]">
                      {b.questions.map((q, i) => <li key={i}>{q}</li>)}
                    </ol>
                  </Panel>
                </div>
              </div>
              <Callout tone="info" title="Yesterday">{b.yesterday}</Callout>
              <Hint>{b.sourced} sourced, {b.unsourced} unsourced. Flags are set by code, not by the model.</Hint>
              {b.dropped.length > 0 && (
                <Disclosure title={`Filtered out (${b.dropped.length})`}>
                  <ul className="flex list-disc flex-col gap-1 pl-5 text-[13px] text-muted">
                    {b.dropped.map((d, i) => <li key={i}>{d}</li>)}
                  </ul>
                </Disclosure>
              )}
            </div>
            <div className="flex flex-col gap-4">
              <Panel title="Write it up">
                <Hint className="mb-3">The model writes the page from the lines above. Every flag stays; there is no buy or sell field.</Hint>
                <ExplainPanel facts={b.facts} section="Today" question={QUESTION} />
              </Panel>
              <SavedRuns market={market} />
            </div>
          </div>
        )}
        {!b && <SavedRuns market={market} />}
        {setup && <ScheduleDialog open={scheduling} onOpenChange={setScheduling} market={market} setup={setup} />}
      </div>
    </FactsProvider>
  );
}
