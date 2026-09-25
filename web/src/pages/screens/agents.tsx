import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Loader2, Play, Send, Square, X as XIcon } from "lucide-react";
import { get, post, type Market } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button, Field, Panel, inputCls } from "@/components/ui";
import { Badge, Callout, EmptyState, Segmented, Switch, useToast } from "@/components/kit";
import { ExplainPanel, FactTile, FactsProvider } from "@/components/facts";
import { useMarket } from "@/components/shell";
import { ErrorLine, Note, NumField, OkMark, TextField } from "@/components/automate/common";

interface Team { key: string; title: string; installed: boolean; tag: string | null }
interface Meta { teams: Team[]; tools: string[]; default_symbol: Record<Market, string>; default_as_of: string; latest: string | null }
interface Ev {
  kind: "tool" | "turn" | "stop"; agent: string; tool?: string; ok?: boolean; summary?: string;
  args?: Record<string, unknown>; data?: string[]; lines?: string[];
}
interface Proposal {
  symbol: string; market: Market; as_of: string; team: string; note: string; cost: number; steps: number; kind: string;
  stopped: string; mask_names: boolean; trials_added: number; rules: { text: string } | null;
  facts: string[]; sections: Record<string, string[]>; warnings: string[]; bull: number; bear: number; risk: number;
}
interface Run {
  id: string; status: "running" | "done" | "stopped" | "error"; error: string | null; events: Ev[]; warning: string;
  config_path: string; settings: { team: string; symbol: string; market: Market; as_of: string; mask: boolean; max_steps: number; max_cost: number };
  proposal: Proposal | null; sent: number | null; rejected: { id: number; reason: string } | null;
}

const SECTION_ORDER: [string, string[]][] = [
  ["Analysts", ["Technical", "News", "Fundamentals"]], ["Bull case", ["Bull"]], ["Bear case", ["Bear"]],
  ["Risk manager", ["Risk manager"]], ["Agent's own test", ["Agent's own test"]],
];

/* ------------------------------------------------------------ transcript */
function ToolChip({ ev }: { ev: Ev }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-[var(--radius-tile)] border border-line bg-panel-2">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[13px]">
        {open ? <ChevronDown size={14} className="text-muted" /> : <ChevronRight size={14} className="text-muted" />}
        <span className="inline-flex h-5 items-center gap-1 rounded-[4px] bg-indigo-soft px-1.5 font-medium text-indigo">{ev.tool} <OkMark ok={!!ev.ok} /></span>
        <span className="text-muted">{ev.agent}</span>
        <span className="min-w-0 truncate">{ev.summary}</span>
      </button>
      {open && (
        <div className="border-t border-line px-3 py-2 text-[13px]">
          <div className="text-muted">Arguments: {Object.entries(ev.args ?? {}).map(([k, v]) => `${k} = ${String(v)}`).join(", ") || "none"}</div>
          <ul className="mt-1.5 flex flex-col gap-0.5">
            {(ev.data?.length ? ev.data : ["(nothing returned)"]).map((d, i) => <li key={i} className="num">{d}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

function Transcript({ run }: { run: Run | undefined }) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { if (run?.status === "running") end.current?.scrollIntoView({ block: "nearest" }); }, [run?.events.length, run?.status]);
  if (!run) return <EmptyState>Click Run. Each agent's turn appears here, and every tool call as a chip you can open to see exactly what data came back.</EmptyState>;
  return (
    <div className="flex flex-col gap-2.5">
      {run.events.map((ev, i) => {
        if (ev.kind === "tool") return <ToolChip key={i} ev={ev} />;
        if (ev.kind === "stop") return <Callout key={i} tone="danger" title="Run stopped">{ev.lines?.[0]}</Callout>;
        return (
          <div key={i} className="border-l-2 border-line pl-3">
            <div className="text-[13px] font-semibold">{ev.agent}</div>
            <ul className="mt-0.5 list-disc pl-4 text-[14px]">{ev.lines?.map((l, j) => <li key={j}>{l}</li>)}</ul>
          </div>
        );
      })}
      {run.status === "running" && <div className="flex items-center gap-2 text-[13px] text-muted"><Loader2 size={14} className="animate-spin motion-reduce:animate-none" /> The team is working…</div>}
      {run.status === "error" && <Callout tone="danger" title="The run failed">{run.error} Try again, or switch to the Built-in research team.</Callout>}
      <div ref={end} />
    </div>
  );
}

/* ------------------------------------------------------------ proposal */
function ProposalCard({ run, onRun }: { run: Run; onRun: (r: Run) => void }) {
  const toast = useToast();
  const p = run.proposal!;
  const [reason, setReason] = useState("");
  const [showNote, setShowNote] = useState(false);
  const send = useMutation({
    mutationFn: () => post<Run>(`/api/automate/agents/runs/${run.id}/send`),
    onSuccess: (d) => { onRun(d); toast(`Sent to Strategy Builder as proposal #${d.sent}, tagged PROPOSED`); },
  });
  const reject = useMutation({
    mutationFn: () => post<Run>(`/api/automate/agents/runs/${run.id}/reject`, { reason }),
    onSuccess: (d) => { onRun(d); toast("Rejected; the reason went to your journal"); },
  });
  return (
    <div className="flex flex-col gap-4">
      <section className="rounded-[var(--radius-panel)] border-2 border-dashed border-indigo/50 bg-panel">
        <header className="flex items-center justify-between gap-2 border-b border-line px-4 py-2.5">
          <h2 className="text-[14px] font-semibold tracking-wide text-indigo">PROPOSAL · NOT AN ORDER</h2>
          {run.rejected ? <Badge tone="warn">Rejected</Badge> : run.sent ? <Badge tone="indigo">Sent, PROPOSED</Badge> : <Badge>Untested by you</Badge>}
        </header>
        <div className="flex flex-col gap-3 p-4">
          <div>
            <div className="text-[12px] text-muted">Rule</div>
            <p className="font-serif text-[16px] leading-snug">{p.rules?.text ?? "No rule: the run stopped before one was drafted."}</p>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <FactTile big label="Steps used" value={p.steps} sub={`of ${run.settings.max_steps} in the budget`} />
            <FactTile label="Cost" value={`$${p.cost.toFixed(2)}`} sub={p.cost === 0 ? "₹0 / $0 on a local model" : `of $${run.settings.max_cost.toFixed(2)}`} />
          </div>
          <FactTile label="Agent's own backtests (added to the Trials counter)" value={`+${p.trials_added}`} tone="indigo" />
          <p className="text-[13px] text-muted">Bull {p.bull} point{p.bull === 1 ? "" : "s"}, bear {p.bear} point{p.bear === 1 ? "" : "s"}, risk {p.risk} objection{p.risk === 1 ? "" : "s"}. Data up to {p.mask_names ? "t-0 (names and dates hidden from the team)" : p.as_of}.</p>
          {p.stopped && <Callout tone="warn" title="Run stopped early">{p.stopped}</Callout>}
          <Button size="sm" variant="quiet" className="self-start" onClick={() => setShowNote((v) => !v)} aria-expanded={showNote}>
            {showNote ? <ChevronDown size={14} /> : <ChevronRight size={14} />} Research note
          </Button>
          {showNote && (
            <div className="flex flex-col gap-3 rounded-[var(--radius-tile)] border border-line bg-panel-2 p-3 text-[14px]">
              {SECTION_ORDER.map(([title, keys]) => {
                const lines = keys.flatMap((k) => p.sections[k] ?? []);
                if (!lines.length) return null;
                return <div key={title}><div className="font-medium">{title}</div><ul className="list-disc pl-5">{lines.map((l, i) => <li key={i}>{l}</li>)}</ul></div>;
              })}
            </div>
          )}
          <Note>Untested by you. Send to the backtester to grade.</Note>
        </div>
      </section>

      <Panel title="Explain">
        <ExplainPanel facts={p.facts} section="Research" />
      </Panel>

      <Panel title="What happens next">
        <div className="flex flex-col gap-3">
          <div>
            <Button variant="primary" onClick={() => send.mutate()} disabled={!p.rules || !!run.sent || !!run.rejected || send.isPending}><Send size={14} /> Send to Strategy Builder</Button>
            {run.sent && <Note className="mt-2">Sent as proposal #{run.sent}, tagged PROPOSED. Open Strategy › Strategy Builder: Read back in English, Chart check, then Backtest with the right cost profile.</Note>}
          </div>
          <div className="flex flex-wrap items-end gap-2 border-t border-line pt-3">
            <div className="min-w-[200px] flex-1"><TextField label="Reason (one line, for the journal)" value={reason} onChange={setReason} placeholder="Too few trades to judge" /></div>
            <Button onClick={() => reject.mutate()} disabled={!reason.trim() || !!run.rejected || reject.isPending}><XIcon size={14} /> Reject</Button>
          </div>
          {run.rejected && <Note>Rejected: {run.rejected.reason}. The reason went to your journal.</Note>}
          <ErrorLine error={send.error ?? reject.error} />
        </div>
      </Panel>
    </div>
  );
}

/* ------------------------------------------------------------ screen */
export default function Agents() {
  const [market] = useMarket();
  const qc = useQueryClient();
  const toast = useToast();
  const meta = useQuery({ queryKey: ["automate", "agents-meta"], queryFn: () => get<Meta>("/api/automate/agents/meta") });
  const [runId, setRunId] = useState<string | null>(null);
  useEffect(() => { if (runId === null && meta.data?.latest) setRunId(meta.data.latest); }, [meta.data, runId]);
  const runQ = useQuery({
    queryKey: ["automate", "agents-run", runId], enabled: !!runId,
    queryFn: () => get<Run>(`/api/automate/agents/runs/${runId}`),
    refetchInterval: (q) => (q.state.data?.status === "running" ? 400 : false),
  });
  const run = runQ.data;
  const setRun = (r: Run) => qc.setQueryData(["automate", "agents-run", r.id], r);

  const [team, setTeam] = useState("builtin");
  const [symbol, setSymbol] = useState(market === "IN" ? "NIFTY" : "SPY");
  const [asOf, setAsOf] = useState("2026-05-29");
  const [mask, setMask] = useState(true);
  const [steps, setSteps] = useState<number | null>(40);
  const [cost, setCost] = useState<number | null>(0.5);
  useEffect(() => setSymbol(market === "IN" ? "NIFTY" : "SPY"), [market]);

  const start = useMutation({
    mutationFn: () => post<Run>("/api/automate/agents/run", { market, team, symbol, as_of: asOf, mask, max_steps: steps ?? 40, max_cost: cost ?? 0.5 }),
    onSuccess: (r) => { setRun(r); setRunId(r.id); toast(`Started ${r.settings.team} on ${r.settings.symbol}`); },
  });
  const stop = useMutation({
    mutationFn: () => post<Run>(`/api/automate/agents/runs/${runId}/stop`),
    onSuccess: (r) => { setRun(r); toast("Stopped the run; nothing after this step is called"); },
  });
  const prevStatus = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (prevStatus.current === "running" && run && run.status !== "running") toast(run.status === "error" ? "The run failed" : "The Proposal card is ready", run.status === "error" ? "danger" : "ok");
    prevStatus.current = run?.status;
  }, [run?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  if (meta.error) return <Callout tone="danger" title="Agents could not load">{(meta.error as Error).message} Restart the lab, then open this screen again.</Callout>;
  const teams = meta.data?.teams ?? [];
  const chosen = teams.find((t) => t.key === team);
  const running = run?.status === "running";

  return (
    <FactsProvider>
      <div className="flex flex-col gap-5">
        <p className="text-[14px] text-muted">A research team writes notes and proposes rules. It has no order tool, no keys and no Accept button.</p>

        <Panel>
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-end gap-4">
              <Field label="Team">
                <Segmented label="Team" value={team} onChange={setTeam}
                  options={(teams.length ? teams : [{ key: "builtin", title: "Built-in research team" } as Team]).map((t) => ({ value: t.key, label: t.title }))} />
              </Field>
              <div className="w-32"><TextField label="Subject" value={symbol} onChange={(v) => setSymbol(v.toUpperCase())} /></div>
              <Field label="As-of date"><input type="date" className={cn(inputCls, "w-40")} value={asOf} onChange={(e) => setAsOf(e.target.value)} /></Field>
              <div className="w-40"><NumField label="Budget: max steps" value={steps} min={1} max={200} step={1} onChange={setSteps} /></div>
              <div className="w-44"><NumField label="Budget: max cost (USD)" value={cost} min={0} max={50} step={0.1} onChange={setCost} /></div>
            </div>
            <div className="flex flex-wrap items-center gap-4">
              <div className="w-[300px]"><Switch checked={mask} onChange={setMask} label="Mask names" hint="The team sees 'Index A' and relative dates, not the name." /></div>
              <Note className="max-w-[420px]">Tools return data only up to the as-of date. With a local model the cost line shows ₹0 / $0 and the step limit does the work.</Note>
              <div className="ml-auto flex gap-2">
                <Button variant="primary" onClick={() => start.mutate()} disabled={running || start.isPending}><Play size={14} /> Run</Button>
                <Button onClick={() => stop.mutate()} disabled={!running || stop.isPending}><Square size={13} /> Stop</Button>
              </div>
            </div>
            {chosen && !chosen.installed && (
              <Callout tone="warn" title={`${chosen.title} is not installed`}>
                Automate › Plugins › Install fetches the official GitHub repository at the pinned tag {chosen.tag}. Until then the Built-in research team runs.
              </Callout>
            )}
            <ErrorLine error={start.error ?? stop.error} />
          </div>
        </Panel>

        {run?.warning && <Callout tone="warn">{run.warning}</Callout>}

        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
          <Panel title="Transcript" action={run ? <span className="text-[12px] text-muted">{run.settings.team}, {run.settings.symbol} ({run.settings.market}), data up to {run.settings.as_of}{run.settings.mask ? ", names masked" : ""}</span> : undefined}>
            <Transcript run={run} />
          </Panel>
          <div>
            {run?.proposal ? <ProposalCard key={run.id} run={run} onRun={setRun} />
              : <EmptyState>{running ? "The Proposal card appears here when the run ends." : "The Proposal card appears here after a run."}</EmptyState>}
          </div>
        </div>
        <Note>Tools: {(meta.data?.tools ?? []).join(", ")}. Agent backtests count as trials. Settings file: {run?.config_path ?? "written when you click Run"}. Paper only: nothing here can place an order.</Note>
      </div>
    </FactsProvider>
  );
}
