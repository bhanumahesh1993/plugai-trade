import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Copy, Download, FolderOpen, Play, Plus, ShieldCheck } from "lucide-react";
import { get, post, type Market } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button, Field, MarketChip, Panel, inputCls } from "@/components/ui";
import { Badge, Callout, DataTable, EChart, EmptyState, Hypothetical, Select, chartTokens, useToast } from "@/components/kit";
import { ExplainPanel, FactTile, FactsProvider } from "@/components/facts";
import { useMarket } from "@/components/shell";
import { ErrorLine, Note, OkMark, Plain, TextField, stamp } from "@/components/automate/common";

interface CheckItem { name: string; ok: boolean; value: string; shown: boolean; hits: string[] }
interface Report { name: string; passed: boolean; red_flags: number; items: CheckItem[]; summary: string; text: string; facts: string[] }
interface Plugin {
  name: string; folder: string; kind: string | null; markets: string[]; network: string[]; licence?: string; error: string | null;
  status: { checked: string; passed: boolean; red_flags: number; enabled: boolean };
}
interface Adapter {
  key: string; title: string; licence: string; repo: string; tag: string; installed: boolean; tools: string[]; plan: string;
  install: { state: "running" | "done" | "failed"; message: string } | null;
}
interface PState { plugins: Plugin[]; adapters: Adapter[]; kinds: string[]; plugins_dir: string; reports: Record<string, Report> }
interface RunOut {
  name: string; kind: string; symbol: string; market: Market; columns: string[]; height: number; rows: Record<string, unknown>[];
  facts: string[]; backtest: { dates: string[]; equity: number[]; grade: string; facts: string[] } | null;
}

const KEY = ["automate", "plugins"];
const fmtCell = (v: unknown) => (typeof v === "number" ? (Number.isInteger(v) ? v.toLocaleString() : v.toFixed(2)) : String(v ?? "—"));

/* ------------------------------------------------------------ Plugin check (the book's format) */
function CheckReportView({ r }: { r: Report }) {
  return (
    <div className="rounded-[var(--radius-tile)] border border-line bg-panel-2 p-3.5">
      <ul className="flex flex-col gap-1.5 text-[14px]">
        {r.items.filter((i) => i.shown).map((i) => (
          <li key={i.name}>
            <div className="flex items-baseline gap-2">
              <span className="relative top-[3px]"><OkMark ok={i.ok} /></span>
              <span className={cn("shrink-0 font-medium", !i.ok && "text-bear")}>{i.name}</span>
              <span aria-hidden className="min-w-4 flex-1 translate-y-[-3px] border-b border-dotted border-line-strong" />
              <span className="num text-right text-muted">{i.value.replace(/\s*[✓✗]$/, "")}</span>
            </div>
            {!i.ok && i.hits.length > 0 && (
              <ul className="ml-6 mt-1 flex flex-col gap-0.5 text-[13px] text-muted">{i.hits.map((h, k) => <li key={k} className="break-all">{h}</li>)}</ul>
            )}
          </li>
        ))}
      </ul>
      <p className={cn("mt-3 border-t border-line pt-2.5 text-[14px] font-medium", r.passed ? "text-bull" : "text-bear")}>{r.summary}</p>
    </div>
  );
}

/* ------------------------------------------------------------ run panel */
function EquityLine({ dates, equity }: { dates: string[]; equity: number[] }) {
  const option = useMemo(() => {
    const t = chartTokens();
    return {
      grid: { left: 64, right: 16, top: 12, bottom: 28 },
      tooltip: { trigger: "axis", backgroundColor: t.panel, borderColor: t.line, textStyle: { color: t.ink }, valueFormatter: (v: number) => v.toLocaleString(undefined, { maximumFractionDigits: 0 }) },
      xAxis: { type: "category", data: dates.map((d) => String(d).slice(0, 10)), axisLabel: { color: t.muted }, axisLine: { lineStyle: { color: t.line } } },
      yAxis: { type: "value", scale: true, axisLabel: { color: t.muted }, splitLine: { lineStyle: { color: t.line } } },
      series: [{ type: "line", data: equity, showSymbol: false, lineStyle: { color: t.indigo, width: 2 }, areaStyle: { color: t.indigo, opacity: 0.08 } }],
    };
  }, [dates, equity]);
  return <EChart option={option} height={240} />;
}

function RunPanel({ p }: { p: Plugin }) {
  const [market] = useMarket();
  const toast = useToast();
  const [symbol, setSymbol] = useState(market === "IN" ? "NIFTY" : "SPY");
  const [from, setFrom] = useState("2024-06-01");
  const [to, setTo] = useState("2026-05-29");
  useEffect(() => setSymbol(market === "IN" ? "NIFTY" : "SPY"), [market]);
  const run = useMutation({
    mutationFn: () => post<RunOut>(`/api/automate/plugins/${p.name}/run`, { market, symbol, start: from, end: to }),
    onSuccess: (d) => toast(`Ran ${d.name} on ${d.symbol}: ${d.height} rows`),
  });
  const r = run.data;
  const declared = p.markets.includes(market);
  return (
    <Panel title={`Run ${p.name}`} action={r?.backtest ? <Hypothetical /> : undefined}>
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-32"><TextField label="Symbol" value={symbol} onChange={(v) => setSymbol(v.toUpperCase())} /></div>
        <Field label="From"><input type="date" className={cn(inputCls, "w-40")} value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
        <Field label="To"><input type="date" className={cn(inputCls, "w-40")} value={to} onChange={(e) => setTo(e.target.value)} /></Field>
        <Button variant="primary" onClick={() => run.mutate()} disabled={run.isPending || !declared}><Play size={14} /> {run.isPending ? "Running in its own process…" : "Run"}</Button>
        <span className="flex items-center gap-1.5 pb-2 text-[13px] text-muted">Market <MarketChip m={market} /> from the top bar{!declared && `; ${p.name} declares ${p.markets.join(", ")} only`}</span>
      </div>
      <ErrorLine error={run.error} />
      {r && (
        <div className="mt-4 grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="flex min-w-0 flex-col gap-4">
            <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3">
              <FactTile big label="Rows returned" value={r.height.toLocaleString()} sub={`${r.symbol}, ${r.kind}`} />
              {r.backtest && <FactTile label="Report Card grade" value={r.backtest.grade} sub="Fills at the next open, costs on" />}
            </div>
            {r.backtest && <EquityLine dates={r.backtest.dates} equity={r.backtest.equity} />}
            <div className="scroll-thin max-h-[320px] overflow-y-auto">
              <DataTable rows={r.rows} columns={r.columns.map((c) => ({ key: c, header: c, align: typeof r.rows[0]?.[c] === "number" ? "right" as const : undefined, render: (row: Record<string, unknown>) => fmtCell(row[c]) }))} />
            </div>
            {r.height > r.rows.length && <Note>Showing the first {r.rows.length.toLocaleString()} of {r.height.toLocaleString()} rows.</Note>}
          </div>
          <div className="flex flex-col gap-2">
            <ExplainPanel facts={r.backtest ? [...r.facts] : r.facts} section="Automate" question="Narrate this plugin's table. Compute nothing new." />
            <Note>The AI narrates the table and Show sources links each sentence to rows. It computes nothing new.</Note>
          </div>
        </div>
      )}
    </Panel>
  );
}

/* ------------------------------------------------------------ agent plugin (Install) */
function AdapterCard({ a, onState }: { a: Adapter; onState: (d: PState) => void }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const install = useMutation({
    mutationFn: () => post<PState>(`/api/automate/plugins/install/${a.key}`),
    onSuccess: (d) => { onState(d); toast(`Installing ${a.title} ${a.tag} from GitHub`); },
  });
  const st = a.install;
  return (
    <div className="rounded-[var(--radius-tile)] border border-line p-3.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">{a.title}</span>
        <Badge>{a.licence}</Badge>
        <span className="text-[13px] text-muted">pinned tag <span className="num text-ink">{a.tag}</span></span>
        <span className="ml-auto">{a.installed ? <Badge tone="indigo">Installed</Badge> : st?.state === "running" ? <Badge tone="indigo">Installing…</Badge> : <Badge>Not installed</Badge>}</span>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[13px]">
        <span className="text-muted">Allowed tools:</span>
        {a.tools.map((t) => <span key={t} className="inline-flex h-5 items-center rounded-[4px] bg-indigo-soft px-1.5 font-medium text-indigo">{t}</span>)}
        <span className="text-muted">There is no order or paper-order tool.</span>
      </div>
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="mt-2 flex items-center gap-1 text-[13px] text-muted hover:text-ink">
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />} What Install will do
      </button>
      {open && <Plain className="mt-2" text={a.plan} />}
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button onClick={() => install.mutate()} disabled={a.installed || st?.state === "running" || install.isPending}><Download size={14} /> Install</Button>
        <Note>From {a.repo} at the pinned tag, never the PyPI package. Needs internet; runs as a separate process with no keys.</Note>
      </div>
      {st && st.state !== "running" && <div className="mt-2"><Callout tone={st.state === "done" ? "ok" : "warn"}>{st.message}</Callout></div>}
      <ErrorLine error={install.error} />
    </div>
  );
}

/* ------------------------------------------------------------ screen */
export default function Plugins() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: s, error } = useQuery({
    queryKey: KEY, queryFn: () => get<PState>("/api/automate/plugins"),
    refetchInterval: (q) => (q.state.data?.adapters.some((a) => a.install?.state === "running") ? 1500 : false),
  });
  const set = (d: PState) => qc.setQueryData(KEY, d);
  const [kind, setKind] = useState("Report");
  const [name, setName] = useState("gap_report");
  const [sel, setSel] = useState<string | null>(null);
  const [created, setCreated] = useState<string | null>(null);
  const [folder, setFolder] = useState<{ path: string; files: string[] } | null>(null);
  useEffect(() => { if (s && !sel && s.plugins.length) setSel(s.plugins[0].name); }, [s, sel]);
  useEffect(() => setFolder(null), [sel]);

  const create = useMutation({
    mutationFn: () => post<PState & { message: string; name: string }>("/api/automate/plugins/new", { name, kind }),
    onSuccess: (d) => { set(d); setCreated(d.message); setSel(d.name); toast(d.message.includes("already exists") ? `${d.name} already exists` : `Created ${d.name} from the ${kind} template`); },
  });
  const openFolder = useMutation({ mutationFn: (n: string) => get<{ path: string; files: string[] }>(`/api/automate/plugins/${n}/folder`), onSuccess: setFolder });
  const check = useMutation({
    mutationFn: (n: string) => post<PState & { report: Report }>(`/api/automate/plugins/${n}/check`),
    onSuccess: (d) => { set(d); toast(d.report.passed ? `Plugin check passed for ${d.report.name}` : `Plugin check: ${d.report.red_flags} red flag${d.report.red_flags === 1 ? "" : "s"} in ${d.report.name}`, d.report.passed ? "ok" : "danger"); },
  });
  const enable = useMutation({
    mutationFn: ({ n, on }: { n: string; on: boolean }) => post<PState & { message: string }>(`/api/automate/plugins/${n}/enable`, { on }),
    onSuccess: (d, v) => { set(d); toast(`${v.on ? "Enabled" : "Disabled"} ${v.n}`); },
  });

  if (error) return <Callout tone="danger" title="Plugins could not load">{(error as Error).message} Restart the lab, then open this screen again.</Callout>;
  const plugins = s?.plugins ?? [];
  const p = plugins.find((x) => x.name === sel) ?? null;
  const rep = p ? s?.reports[p.name] : undefined;
  const enabledN = plugins.filter((x) => x.status.enabled).length;

  return (
    <FactsProvider>
      <div className="flex flex-col gap-5">
        <p className="text-[14px] text-muted">Your code, under the lab's rules: checked, contained, no keys, no order code. Plugins run in their own process after the Plugin check passes.</p>

        <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
          <FactTile big label="Red flags" value={p?.status.checked ? p.status.red_flags : "—"} sub={p ? (p.status.checked ? `${p.name}, last Plugin check ${stamp(p.status.checked)}` : `${p.name} not checked yet`) : "Select a plugin"} />
          <FactTile label="Plugins" value={s ? plugins.length : "—"} sub="In your lab folder" />
          <FactTile label="Enabled" value={s ? enabledN : "—"} />
          <FactTile label="Agent plugins installed" value={s ? s.adapters.filter((a) => a.installed).length : "—"} sub={s ? `of ${s.adapters.length}` : undefined} />
        </div>

        <Panel title="New from template">
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Template"><Select className="w-36 font-sans" value={kind} onChange={(e) => setKind(e.target.value)}>{(s?.kinds ?? ["Screen", "Strategy", "Report"]).map((k) => <option key={k}>{k}</option>)}</Select></Field>
            <div className="w-56"><TextField label="Name" value={name} onChange={setName} placeholder="gap_report" /></div>
            <Button variant="primary" onClick={() => create.mutate()} disabled={!name.trim() || create.isPending}><Plus size={14} /> New from template</Button>
          </div>
          <Note className="mt-2">Lower-case letters, digits and _. From a terminal, plugai-trade plugin new {name || "gap_report"} --kind {kind.toLowerCase()} does the same. The folder holds plugin.toml, plugin.py, tests/ and AGENTS.md.</Note>
          {created && <div className="mt-2"><Callout tone="ok">{created}</Callout></div>}
          <ErrorLine error={create.error} />
        </Panel>

        <div className="grid gap-5 xl:grid-cols-[400px_minmax(0,1fr)]">
          <Panel title="Your plugins" className="self-start">
            {!s ? <div className="h-[80px]" /> : plugins.length === 0 ? <EmptyState>No plugins yet. Click New from template.</EmptyState> : (
              <ul className="flex flex-col gap-2" role="listbox" aria-label="Your plugins">
                {plugins.map((x) => {
                  const on = x.name === sel;
                  return (
                    <li key={x.name}>
                      <button type="button" role="option" aria-selected={on} onClick={() => setSel(x.name)}
                        className={cn("flex w-full items-start gap-3 rounded-[var(--radius-tile)] border px-3 py-2.5 text-left", on ? "border-indigo bg-indigo-soft/40" : "border-line hover:bg-panel-2")}>
                        <div className="min-w-0 flex-1">
                          <div className="font-semibold">{x.name}</div>
                          {x.error ? <div className="text-[13px] text-bear">{x.error}</div> : (
                            <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[13px] text-muted">
                              <span>{x.kind}</span>{x.markets.map((m) => (m === "IN" || m === "US" ? <MarketChip key={m} m={m} /> : <Badge key={m}>{m}</Badge>))}
                              <span>network: {x.network.join(", ") || "none"}</span>
                            </div>
                          )}
                        </div>
                        <div className="flex shrink-0 flex-col items-end gap-1 text-[13px]">
                          {x.status.checked ? (
                            <span className={cn("flex items-center gap-1 font-medium", x.status.passed ? "text-bull" : "text-bear")}>
                              <OkMark ok={x.status.passed} /> {x.status.passed ? "checks passed" : `${x.status.red_flags} red flag${x.status.red_flags === 1 ? "" : "s"}`}
                            </span>
                          ) : <span className="text-muted">not checked yet</span>}
                          <span className={cn(x.status.enabled ? "font-semibold text-ink" : "text-muted")}>{x.status.enabled ? "Enabled" : x.status.checked && !x.status.passed ? "Blocked" : "Off"}</span>
                        </div>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </Panel>

          <div className="flex min-w-0 flex-col gap-5">
            {p ? (
              <Panel title={p.name} action={
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" onClick={() => openFolder.mutate(p.name)}><FolderOpen size={14} /> Open folder</Button>
                  <Button size="sm" onClick={() => check.mutate(p.name)} disabled={check.isPending}><ShieldCheck size={14} /> {check.isPending ? "Running tests and scans…" : "Run checks"}</Button>
                  <Button size="sm" variant="primary" onClick={() => enable.mutate({ n: p.name, on: true })} disabled={!p.status.passed || p.status.enabled || enable.isPending}>Enable</Button>
                  <Button size="sm" onClick={() => enable.mutate({ n: p.name, on: false })} disabled={!p.status.enabled || enable.isPending}>Disable</Button>
                </div>
              }>
                <div className="flex flex-col gap-4">
                  {folder && (
                    <div className="flex flex-col gap-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <code className="min-w-0 flex-1 break-all rounded-[4px] bg-panel-2 px-2 py-1.5 text-[13px]">{folder.path}</code>
                        <Button size="sm" variant="quiet" onClick={() => { navigator.clipboard?.writeText(folder.path).then(() => toast("Copied the folder path"), () => toast("Could not copy; select the path and copy it", "danger")); }}><Copy size={13} /> Copy path</Button>
                      </div>
                      <Note>Open this path in your editor (Cursor or VS Code), or start your coding agent inside it. Files: {folder.files.join(", ")}.</Note>
                    </div>
                  )}
                  <ErrorLine error={openFolder.error ?? check.error ?? enable.error} />
                  {rep ? (
                    <div>
                      <div className="mb-2 text-[14px] font-semibold">Plugin check, {p.name}</div>
                      <CheckReportView r={rep} />
                    </div>
                  ) : p.status.checked ? (
                    <Note>Last Plugin check {stamp(p.status.checked)}: {p.status.passed ? "passed" : `${p.status.red_flags} red flags`}. Click Run checks to see every line.</Note>
                  ) : (
                    <EmptyState>Click Run checks. The Plugin check runs your tests and scans the code for order code, keys, undeclared network use, unknown packages and look-ahead. Every line must be green.</EmptyState>
                  )}
                  {!p.status.passed && p.status.checked && <Callout tone="danger" title="Blocked">A plugin that fails the Plugin check is never run. Fix the red flags, then click Run checks again.</Callout>}
                  {p.status.passed && !p.status.enabled && <Note>Every line is green. Click Enable to add {p.name} to the plugin list; it can then be scheduled like any other screen.</Note>}
                </div>
              </Panel>
            ) : (
              <EmptyState>Create a plugin from a template, or select one from the list.</EmptyState>
            )}
          </div>
        </div>
        {p?.status.passed && <RunPanel key={p.name} p={p} />}

        <Panel title="Agent plugins">
          <div className="flex flex-col gap-3">
            <Note>TradingAgents and ai-hedge-fund run as separate processes for Automate › Agents. The lab still owns the tools, the rules and the budget.</Note>
            {(s?.adapters ?? []).map((a) => <AdapterCard key={a.key} a={a} onState={set} />)}
          </div>
        </Panel>
        <Note>Paper only. PlugAI-Trade never places real orders. Plugins never receive keys and have no order code to call.</Note>
      </div>
    </FactsProvider>
  );
}
