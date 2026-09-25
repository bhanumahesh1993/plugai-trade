import { useEffect, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CirclePause, CirclePlay, ListChecks, Play, Plus, Trash2 } from "lucide-react";
import { get, post, type Market } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button, Field, MarketChip, Panel, inputCls } from "@/components/ui";
import { Badge, Callout, DataTable, Dialog, EmptyState, Select, Switch, useToast } from "@/components/kit";
import { FactTile, FactsProvider } from "@/components/facts";
import { useMarket } from "@/components/shell";
import { ErrorLine, Note, NumField, stamp } from "@/components/automate/common";

interface Job {
  id: number; job: string; mkt: Market; when: string; model: string; enabled: boolean;
  last_run: string; last_result: string; next_run: string | null;
}
interface SchedState {
  jobs: Job[]; paused: boolean; catch_up: boolean; health_alert: boolean; running: boolean;
  cost: string; all_local: boolean; job_types: string[]; kinds: string[]; weekdays: string[]; models: string[];
  presets: Record<string, { kind: string; at: string; day?: string; until?: string; minutes?: number }>;
  default_model: Record<string, string>;
}
interface LogRow extends Record<string, unknown> {
  id: number; start: string; job: string; mkt: Market; status: string; rows: number; duration_s: number;
  model: string; trigger: string; output: string;
}
interface Entry { job: string; status: string; output: string }

const KEY = ["automate", "scheduler"];

function statusTone(s: string): "indigo" | "warn" | "neutral" {
  if (s === "ok") return "indigo";
  if (s === "error" || s.startsWith("missed")) return "warn";
  return "neutral";
}
/** "✓ ok" → "ok", "missed · asleep" stays. */
const cleanResult = (s: string) => s.replace(/^[✓✗?–]\s*/, "");

/* ------------------------------------------------------------ Add job form */
function JobForm({ s, market, onDone }: { s: SchedState; market: Market; onDone: (st: SchedState) => void }) {
  const toast = useToast();
  const [job, setJob] = useState(s.job_types[0]);
  const preset = s.presets[job];
  const [f, setF] = useState({ market, kind: preset.kind, model: s.default_model[job], at: preset.at,
    day: preset.day ?? "Sat", minutes: preset.minutes ?? 15, until: preset.until ?? "23:00" });
  useEffect(() => {
    const p = s.presets[job];
    setF((x) => ({ ...x, kind: p.kind, model: s.default_model[job], at: p.at, day: p.day ?? (p.kind === "monthly" ? "1" : "Sat"),
      minutes: p.minutes ?? 15, until: p.until ?? "23:00" }));
    // Only a new job type resets the form (not the list's background refresh).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job]);
  const body = { job, ...f, day: String(f.day) };
  const preview = useQuery({ queryKey: ["automate", "sched-preview", body], queryFn: () => post<{ text: string; next_run: string | null }>("/api/automate/scheduler/preview", body),
    placeholderData: keepPreviousData, retry: false });
  const add = useMutation({
    mutationFn: () => post<SchedState & { added: number }>("/api/automate/scheduler/jobs", body),
    onSuccess: (d) => { onDone(d); toast(`Added job #${d.added}: ${job}`); },
  });
  const set = (k: keyof typeof f, v: string | number) => setF((x) => ({ ...x, [k]: v }));
  return (
    <Panel title="New job" className="border-indigo/40">
      <div className="grid gap-3 md:grid-cols-3">
        <Field label="Job">
          <Select className="font-sans" value={job} onChange={(e) => setJob(e.target.value)}>{s.job_types.map((j) => <option key={j}>{j}</option>)}</Select>
        </Field>
        <Field label="Market" hint="IN runs on NSE trading days; US on NYSE trading days. Holidays come from the dated reference tables.">
          <Select className="font-sans" value={f.market} onChange={(e) => set("market", e.target.value)}>
            <option value="IN">India (NSE calendar)</option><option value="US">US (NYSE calendar)</option>
          </Select>
        </Field>
        <Field label="When">
          <Select className="font-sans" value={f.kind} onChange={(e) => {
            const k = e.target.value;
            setF((x) => ({ ...x, kind: k, day: k === "monthly" ? (/^\d+$/.test(String(x.day)) ? x.day : "1") : k === "weekly" ? (/^\d+$/.test(String(x.day)) ? "Sat" : x.day) : x.day }));
          }}>{s.kinds.map((k) => <option key={k}>{k}</option>)}</Select>
        </Field>
        <Field label="Model">
          <Select className="font-sans" value={f.model} onChange={(e) => set("model", e.target.value)}>{s.models.map((m) => <option key={m}>{m}</option>)}</Select>
        </Field>
        <Field label="Run time (HH:MM, market time)">
          <input className={cn(inputCls)} value={f.at} onChange={(e) => set("at", e.target.value)} placeholder="07:30" />
        </Field>
        {f.kind === "weekly" && (
          <Field label="Day">
            <Select className="font-sans" value={String(f.day)} onChange={(e) => set("day", e.target.value)}>{s.weekdays.map((d) => <option key={d}>{d}</option>)}</Select>
          </Field>
        )}
        {f.kind === "monthly" && (
          <NumField label="Day of month" value={Number(f.day) || null} min={1} max={28} step={1} onChange={(v) => set("day", String(v ?? ""))} />
        )}
        {f.kind === "every N minutes" && (
          <>
            <NumField label="Every (minutes)" value={f.minutes} min={5} max={240} step={1} onChange={(v) => set("minutes", v ?? 0)} />
            <Field label="Last run (HH:MM)">
              <input className={inputCls} value={f.until} onChange={(e) => set("until", e.target.value)} placeholder="23:00" />
            </Field>
          </>
        )}
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-line pt-3">
        <div className="min-w-0 flex-1">
          {preview.error ? <ErrorLine error={preview.error} /> : (
            <p className="text-[14px]"><span className="text-muted">Preview: </span>{preview.data?.text ?? "…"}
              {preview.data?.next_run && <span className="text-muted">. Next run {preview.data.next_run}</span>}</p>
          )}
        </div>
        <Button onClick={() => onDone(s)}>Cancel</Button>
        <Button variant="primary" onClick={() => add.mutate()} disabled={add.isPending || !!preview.error}>Accept</Button>
      </div>
      <ErrorLine error={add.error} />
    </Panel>
  );
}

/* ------------------------------------------------------------ screen */
export default function Scheduler() {
  const [market] = useMarket();
  const qc = useQueryClient();
  const toast = useToast();
  const { data: s, error } = useQuery({ queryKey: KEY, queryFn: () => get<SchedState>("/api/automate/scheduler"), refetchInterval: 60_000 });
  const setS = (d: SchedState) => { qc.setQueryData(KEY, d); qc.invalidateQueries({ queryKey: ["automate", "sched-log"] }); };
  const [adding, setAdding] = useState(false);
  const [showLog, setShowLog] = useState(false);
  const [pick, setPick] = useState<number | null>(null);
  const [confirmDel, setConfirmDel] = useState<Job | null>(null);
  const [lastEntry, setLastEntry] = useState<Entry | null>(null);

  const log = useQuery({ queryKey: ["automate", "sched-log", pick], enabled: showLog,
    queryFn: () => get<LogRow[]>(`/api/automate/scheduler/log${pick != null ? `?job_id=${pick}` : ""}`) });
  const run = useMutation({
    mutationFn: (id: number) => post<SchedState & { entry: Entry }>(`/api/automate/scheduler/jobs/${id}/run`),
    onSuccess: (d) => { setS(d); setLastEntry(d.entry); toast(`Ran ${d.entry.job}: ${d.entry.status}`, d.entry.status === "error" ? "danger" : "ok"); },
  });
  const enable = useMutation({
    mutationFn: ({ id, on }: { id: number; on: boolean }) => post<SchedState>(`/api/automate/scheduler/jobs/${id}/enabled`, { on }),
    onSuccess: (d, v) => { setS(d); toast(v.on ? `Switched on job #${v.id}` : `Switched off job #${v.id}`); },
  });
  const del = useMutation({
    mutationFn: (id: number) => post<SchedState>(`/api/automate/scheduler/jobs/${id}/delete`),
    onSuccess: (d, id) => { setS(d); setConfirmDel(null); if (pick === id) setPick(null); toast(`Deleted job #${id}`); },
  });
  const pause = useMutation({
    mutationFn: (on: boolean) => post<SchedState>("/api/automate/scheduler/pause", { on }),
    onSuccess: (d) => { setS(d); toast(d.paused ? "Paused all jobs" : "Resumed all jobs"); },
  });
  const settings = useMutation({
    mutationFn: (b: { catch_up?: boolean; health_alert?: boolean }) => post<SchedState>("/api/automate/scheduler/settings", b),
    onSuccess: (d, b) => {
      setS(d);
      if (b.catch_up !== undefined) toast(b.catch_up ? "Catch-up switched on" : "Catch-up switched off");
      if (b.health_alert !== undefined) toast(b.health_alert ? "Health alert switched on" : "Health alert switched off");
    },
  });

  if (error) return <Callout tone="danger" title="The Scheduler could not load">{(error as Error).message} Restart the lab, then open this screen again.</Callout>;
  const jobs = s?.jobs ?? [];
  const on = jobs.filter((j) => j.enabled).length;
  const lastRun = [...jobs].filter((j) => j.last_run).sort((a, b) => b.last_run.localeCompare(a.last_run))[0];
  const picked = jobs.find((j) => j.id === pick) ?? null;

  return (
    <FactsProvider>
      <div className="flex flex-col gap-5">
        <p className="text-[14px] text-muted">Jobs run on NSE and NYSE trading days, on your own computer. The lab has no order code, so the worst a runaway job can do is write a report you did not need.</p>

        <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
          <FactTile big label="Scheduled AI cost" value={s?.cost ?? "—"} sub={s ? (s.all_local ? "Every job on a local model or none" : "At least one job uses a metered model") : undefined} />
          <FactTile label="Jobs" value={s ? jobs.length : "—"} sub={s ? `${on} switched on` : undefined} />
          <FactTile label="Last run" value={lastRun ? cleanResult(lastRun.last_result) : "Not yet"} sub={lastRun ? `${lastRun.job}, ${stamp(lastRun.last_run)} UTC` : "Click Run now to test a job"} />
          <FactTile label="Background checks" value={s ? (s.paused ? "Paused" : s.running ? "Running" : "Stopped") : "—"} sub="Every minute while the app is open" />
        </div>

        {s?.paused && <Callout tone="warn" title="Paused">No job runs on schedule until you click Resume all. Run now still works.</Callout>}

        {adding && s && <JobForm s={s} market={market} onDone={(d) => { setS(d); setAdding(false); }} />}

        <Panel title="Jobs" action={
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="primary" onClick={() => setAdding(true)} disabled={adding || !s}><Plus size={14} /> Add job</Button>
            <Button size="sm" onClick={() => setShowLog((v) => !v)} aria-pressed={showLog}><ListChecks size={14} /> View log</Button>
            <Button size="sm" onClick={() => s && pause.mutate(!s.paused)} disabled={!s || pause.isPending}>
              {s?.paused ? <><CirclePlay size={14} /> Resume all</> : <><CirclePause size={14} /> Pause all</>}
            </Button>
          </div>
        }>
          {!s ? <div className="h-[120px]" /> : jobs.length === 0 ? (
            <EmptyState action={<Button variant="primary" onClick={() => setAdding(true)}><Plus size={14} /> Add job</Button>}>
              No jobs yet. Click Add job. Jobs you schedule elsewhere (Daily Briefing › Schedule, Workspace templates) appear here too.
            </EmptyState>
          ) : (
            <div className="scroll-thin overflow-x-auto">
              <table className="w-full text-[14px]">
                <thead>
                  <tr className="border-b border-line text-left text-[12px] text-muted">
                    <th className="pb-2 pr-3 text-right font-normal">#</th>
                    <th className="pb-2 pr-3 font-normal">Job</th>
                    <th className="pb-2 pr-3 font-normal">Mkt</th>
                    <th className="pb-2 pr-3 font-normal">When</th>
                    <th className="pb-2 pr-3 font-normal">Model</th>
                    <th className="pb-2 pr-3 font-normal">Last run</th>
                    <th className="pb-2 pr-3 font-normal">Next run</th>
                    <th className="pb-2 pr-3 font-normal">On</th>
                    <th className="pb-2 font-normal"><span className="sr-only">Actions</span></th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.map((j) => (
                    <tr key={j.id} onClick={() => setPick(pick === j.id ? null : j.id)} aria-selected={pick === j.id}
                      className={cn("cursor-pointer border-b border-line last:border-0 hover:bg-panel-2", pick === j.id && "bg-indigo-soft/50 hover:bg-indigo-soft/60")}>
                      <td className="num py-2 pr-3 text-right text-muted">{j.id}</td>
                      <td className="py-2 pr-3 font-medium">{j.job}</td>
                      <td className="py-2 pr-3"><MarketChip m={j.mkt} /></td>
                      <td className="num py-2 pr-3">{j.when}</td>
                      <td className="py-2 pr-3">{j.model}</td>
                      <td className="py-2 pr-3">{j.last_run ? <span className="flex items-center gap-1.5"><Badge tone={statusTone(cleanResult(j.last_result))}>{cleanResult(j.last_result)}</Badge><span className="num text-[13px] text-muted">{stamp(j.last_run)}</span></span> : <span className="text-muted">Not yet</span>}</td>
                      <td className="num py-2 pr-3 text-[13px] text-muted">{j.enabled ? (s.paused ? "Paused" : j.next_run ?? "—") : "Off"}</td>
                      <td className="py-2 pr-3" onClick={(e) => e.stopPropagation()}>
                        <div className="w-10"><SwitchOnly checked={j.enabled} label={`Job #${j.id} switched on`} onChange={(v) => enable.mutate({ id: j.id, on: v })} /></div>
                      </td>
                      <td className="py-2 text-right" onClick={(e) => e.stopPropagation()}>
                        <div className="flex justify-end gap-1">
                          <Button size="sm" onClick={() => run.mutate(j.id)} disabled={run.isPending}><Play size={13} /> {run.isPending && run.variables === j.id ? "Running…" : "Run now"}</Button>
                          <Button size="sm" variant="quiet" aria-label={`Delete job #${j.id}`} onClick={() => setConfirmDel(j)}><Trash2 size={14} /></Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {lastEntry && (
            <div className="mt-3"><Callout tone={lastEntry.status === "ok" ? "ok" : "warn"} title={`${lastEntry.job}: ${lastEntry.status}`}>{lastEntry.output}</Callout></div>
          )}
          <ErrorLine error={run.error ?? enable.error ?? del.error ?? pause.error} />
        </Panel>

        {showLog && (
          <Panel title={picked ? `Run log, job #${picked.id} ${picked.job}` : "Run log, all jobs"} action={picked ? <Button size="sm" variant="quiet" onClick={() => setPick(null)}>Show all jobs</Button> : <span className="text-[12px] text-muted">Click a job row to see only its runs</span>}>
            {log.isLoading ? <div className="h-[80px]" /> : (
              <DataTable rows={log.data ?? []} rowKey={(r) => r.id} empty="No runs yet. Click Run now to test a job." columns={[
                { key: "start", header: "Start", render: (r) => <span className="num whitespace-nowrap">{r.start.slice(0, 19).replace("T", " ")}</span> },
                { key: "job", header: "Job" },
                { key: "mkt", header: "Mkt", render: (r) => <MarketChip m={r.mkt} /> },
                { key: "status", header: "Status", render: (r) => <Badge tone={statusTone(r.status)}>{r.status}</Badge> },
                { key: "rows", header: "Rows", align: "right" },
                { key: "duration_s", header: "Duration (s)", align: "right", render: (r) => r.duration_s.toFixed(2) },
                { key: "model", header: "Model" },
                { key: "trigger", header: "Trigger" },
                { key: "output", header: "Output", render: (r) => <span className="text-[13px]">{r.output}</span> },
              ]} />
            )}
            <ErrorLine error={log.error} />
          </Panel>
        )}

        <Panel title="When the computer sleeps, or a feed goes quiet">
          <div className="flex max-w-[720px] flex-col gap-1">
            <Switch checked={s?.catch_up ?? true} onChange={(v) => settings.mutate({ catch_up: v })}
              label="Catch up missed runs when the computer wakes" hint="A job missed while the laptop slept runs at the next wake-up. Off: the log marks it missed." />
            <Switch checked={s?.health_alert ?? false} onChange={(v) => settings.mutate({ health_alert: v })}
              label="Health alert" hint="If a news feed returns nothing for two hours of market time, you get a SIMULATED alert in Alerts. A silent feed looks exactly like a quiet news day." />
          </div>
          <Note className="mt-3">Background checks every minute while the app is open, {s ? (s.running ? "running" : "stopped") : "…"}. A job needs the computer on and awake; catch-up runs a missed job at the next wake-up. Stagger jobs by a few minutes so only one model is loaded at a time.</Note>
          <ErrorLine error={settings.error} />
        </Panel>
      </div>

      <Dialog open={!!confirmDel} onOpenChange={(v) => !v && setConfirmDel(null)} title={`Delete job #${confirmDel?.id ?? ""}?`}
        footer={<><Button onClick={() => setConfirmDel(null)}>Keep job</Button><Button variant="danger" onClick={() => confirmDel && del.mutate(confirmDel.id)} disabled={del.isPending}><Trash2 size={14} /> Delete job</Button></>}>
        <p>{confirmDel?.job} ({confirmDel?.mkt}, {confirmDel?.when}) stops running. Its past runs stay in the log.</p>
      </Dialog>
    </FactsProvider>
  );
}

/** A bare switch for table cells (the kit Switch carries a label row). */
function SwitchOnly({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button type="button" role="switch" aria-checked={checked} aria-label={label} onClick={() => onChange(!checked)}
      className={cn("relative h-5 w-9 shrink-0 rounded-full transition-colors", checked ? "bg-indigo" : "bg-line-strong")}>
      <span className={cn("absolute left-0.5 top-0.5 block h-4 w-4 rounded-full bg-white transition-transform", checked && "translate-x-4")} />
    </button>
  );
}
