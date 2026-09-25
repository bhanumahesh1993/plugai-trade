/* Home › First-run wizard (Chapter 4): five short screens and a ten-second self-test. */
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, XCircle, RefreshCw, DownloadCloud, ExternalLink, Play } from "lucide-react";
import { get, post, type Market } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button, Panel, Field, MarketSwitch } from "@/components/ui";
import { Callout, DataTable, Select, useToast } from "@/components/kit";
import { FactTile } from "@/components/facts";
import { CopyButton, ErrorLine, FitBar, PullProgress, TextInput, usePull, type Fit } from "./common";

interface Machine { ram_gb: number | null; free_ram_gb: number | null; disk_free_gb: number; ollama: boolean; lines: string[]; suggestion: string }
interface ModelSize { size: string; label: string; tag: string; params_b: number; download_gb: number; good_for: string }
export interface WizardState {
  done: boolean; step: number; steps: string[]; machine: Machine; models: ModelSize[]; ram_rows: string[];
  context_length: number; fits: Record<string, Fit>; ollama_host: string; ollama_download: string;
  cloud_providers: string[]; market: Market; local_model: string; sample_loaded: string[];
  self_test: { passed: boolean; failed: string[] } | null;
}
interface SampleOut { market: Market; facts: string[]; rows: { symbol: string; bars: number; last_close: number }[] }
interface SelfTestOut { passed: boolean; seconds: number; score: string; facts: string[]; checks: { name: string; passed: boolean; detail: string }[] }

function NavRow({ step, onGo, children, next = "Next" }: { step: number; onGo: (n: number) => void; children?: ReactNode; next?: string | null }) {
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-line pt-4">
      {step > 0 && <Button onClick={() => onGo(step - 1)}>Back</Button>}
      {children}
      {next && <Button variant="primary" onClick={() => onGo(step + 1)}>{next}</Button>}
    </div>
  );
}

/* ------------------------------------------------------------ 1. Check your computer */
function MachineScreen({ w, onGo }: { w: WizardState; onGo: (n: number) => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const again = useMutation({
    mutationFn: () => get<Machine>("/api/wizard/machine"),
    onSuccess: (m) => { qc.setQueryData<WizardState>(["wizard"], (x) => x && { ...x, machine: m }); toast(m.ollama ? "Checked again: Ollama is running" : "Checked again: Ollama still not found"); },
  });
  const m = w.machine;
  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-2.5 sm:grid-cols-3">
        <FactTile big label="Memory (RAM)" value={m.ram_gb ? `${m.ram_gb.toFixed(0)} GB` : "Unknown"} sub={m.free_ram_gb ? `${m.free_ram_gb.toFixed(1)} GB free now` : undefined} />
        <FactTile label="Free disk" value={`${m.disk_free_gb.toFixed(0)} GB`} />
        <FactTile label="Ollama" value={m.ollama ? "Running" : "Not found"} tone={m.ollama ? "bull" : undefined} />
      </div>
      {!m.ollama && (
        <Callout tone="warn" title="Ollama not found">
          Ollama is a free app (MIT licence) that runs AI models on your own computer. Install it like any other app, then click Check again.
          <div className="mt-2"><a href={w.ollama_download} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-indigo hover:underline">Download Ollama <ExternalLink size={13} /></a></div>
        </Callout>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => again.mutate()} disabled={again.isPending}><RefreshCw size={14} className={cn(again.isPending && "animate-spin")} /> Check again</Button>
        <span className="text-[13px] text-muted">Ollama address: <span className="num">{w.ollama_host}</span> (set OLLAMA_HOST for Docker).</span>
      </div>
      <ErrorLine error={again.error} />
      <NavRow step={0} onGo={onGo} />
    </div>
  );
}

/* ------------------------------------------------------------ 2. Local model */
function ModelScreen({ w, onGo }: { w: WizardState; onGo: (n: number) => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [tag, setTag] = useState(w.machine.suggestion);
  const pull = usePull((msg) => { toast(msg); qc.invalidateQueries({ queryKey: ["status"] }); });
  const model = w.models.find((x) => x.tag === tag) ?? w.models[1];
  const sug = w.models.find((x) => x.tag === w.machine.suggestion);
  return (
    <div className="flex flex-col gap-4">
      <DataTable rows={w.models.map((x, i) => ({ ...x, ram: w.ram_rows[i] })) as unknown as Record<string, unknown>[]} rowKey={(r) => String(r.tag)} columns={[
        { key: "ram", header: "Your RAM" },
        { key: "label", header: "Suggested local model", render: (r) => <span>{String(r.label)} <span className="text-muted">({String(r.tag)})</span></span> },
        { key: "download_gb", header: "Download", align: "right", render: (r) => `≈ ${r.download_gb} GB` },
        { key: "good_for", header: "Good for" },
      ]} />
      <fieldset className="flex flex-col gap-1.5">
        <legend className="mb-1 text-[12px] text-muted">Model to pull</legend>
        {w.models.map((x) => (
          <label key={x.tag} className="flex cursor-pointer items-center gap-2.5 py-0.5">
            <input type="radio" name="wiz-model" className="h-4 w-4 accent-[var(--indigo)]" checked={tag === x.tag} onChange={() => setTag(x.tag)} />
            <span>{x.label} <span className="text-muted">({x.tag})</span></span>
            {x.tag === w.machine.suggestion && <span className="text-[12px] font-medium text-indigo">Suggested</span>}
          </label>
        ))}
      </fieldset>
      <p className="text-[13px] text-muted">{w.machine.ram_gb ? `Suggested for ${w.machine.ram_gb.toFixed(0)} GB RAM: ${sug?.label}.` : "RAM unknown: the 9B default is suggested."}</p>
      <FitBar fit={w.fits[model.tag]} label={<span>Fit check for {model.label}, {Math.round(w.context_length / 1024)}k context</span>} />
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" onClick={() => pull.start(model.tag, true)} disabled={pull.running}><DownloadCloud size={15} /> Pull model</Button>
        <span className="text-[13px] text-muted">Leave this tab open while it downloads. Pull model again resumes an interrupted download.</span>
      </div>
      <PullProgress st={pull} />
      <NavRow step={1} onGo={onGo} />
    </div>
  );
}

/* ------------------------------------------------------------ 3. Cloud key (optional) */
function CloudScreen({ w, onGo }: { w: WizardState; onGo: (n: number) => void }) {
  const toast = useToast();
  const [prov, setProv] = useState(w.cloud_providers[0]);
  const [key, setKey] = useState("");
  const save = useMutation({
    mutationFn: () => post<{ message: string }>("/api/wizard/cloud-key", { provider: prov, key }),
    onSuccess: (r) => { setKey(""); toast(r.message); },
  });
  return (
    <div className="flex flex-col gap-4">
      <p>A cloud key is optional: nothing in the book needs one. Keys go to your operating system's keychain, never to a file.</p>
      <div className="grid max-w-[640px] gap-3 sm:grid-cols-[180px_1fr_auto] sm:items-end">
        <Field label="Provider"><Select value={prov} onChange={(e) => setProv(e.target.value)} className="font-sans">{w.cloud_providers.map((p) => <option key={p}>{p}</option>)}</Select></Field>
        <TextInput label="Key" type="password" value={key} onChange={setKey} placeholder="Paste it here, never into a chatbot" />
        <Button onClick={() => save.mutate()} disabled={!key.trim() || save.isPending}>Save key</Button>
      </div>
      {save.data && <p className="text-[13px] text-bull">{save.data.message}</p>}
      <ErrorLine error={save.error} />
      <Link to="/keys" className="text-[13px] font-medium text-indigo hover:underline">Or open Settings › Keys</Link>
      <NavRow step={2} onGo={onGo}><Button onClick={() => onGo(3)}>Skip for now</Button></NavRow>
    </div>
  );
}

/* ------------------------------------------------------------ 4. Sample data */
function SampleScreen({ w, onGo }: { w: WizardState; onGo: (n: number) => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [mkt, setMkt] = useState<Market>(w.market);
  const load = useMutation({
    mutationFn: () => post<SampleOut>("/api/wizard/sample", { market: mkt }),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["status"] }); qc.invalidateQueries({ queryKey: ["watch"] }); toast(`Loaded sample data for ${r.market}`); },
  });
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Which market do you trade?"><div><MarketSwitch value={mkt} onChange={setMkt} /></div></Field>
        <Button variant="primary" onClick={() => load.mutate()} disabled={load.isPending}>Load sample data</Button>
      </div>
      <p className="text-[13px] text-muted">Synthetic NIFTY, BANKNIFTY and SENSEX for India; SPY, QQQ and DIA for the US. Fixed dates to 29 May 2026, so your numbers match the book.</p>
      {load.data && (
        <div className="flex flex-col gap-2">
          <Callout tone="ok" title={`Synthetic sample loaded for ${load.data.market}`}>Every lesson now runs offline on these bars.</Callout>
          <div className="grid gap-2.5 sm:grid-cols-3">
            {load.data.rows.map((r) => <FactTile key={r.symbol} label={r.symbol} value={r.last_close.toLocaleString(load.data!.market === "IN" ? "en-IN" : "en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} sub={`${r.bars} synthetic bars, last close`} />)}
          </div>
        </div>
      )}
      <ErrorLine error={load.error} />
      <NavRow step={3} onGo={onGo} />
    </div>
  );
}

/* ------------------------------------------------------------ 5. Self-test */
function SelfTestScreen({ w, onGo, onOpen }: { w: WizardState; onGo: (n: number) => void; onOpen: () => void }) {
  const [res, setRes] = useState<SelfTestOut | null>(null);
  const [diag, setDiag] = useState("");
  const run = useMutation({ mutationFn: () => post<SelfTestOut>("/api/wizard/self-test", { market: w.market }), onSuccess: setRes });
  const diagnostic = async () => {
    const t = (await post<{ text: string }>("/api/wizard/diagnostic")).text;
    setDiag(t);
    return t;
  };
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" onClick={() => run.mutate()} disabled={run.isPending}><Play size={14} /> {run.isPending ? "Running self-test…" : "Run self-test"}</Button>
        <span className="text-[13px] text-muted">Six checks on the {w.market === "IN" ? "NIFTY" : "SPY"} sample. Only the model check needs Ollama.</span>
      </div>
      <ErrorLine error={run.error} />
      {res && (
        <div className="grid items-start gap-4 md:grid-cols-[200px_1fr]">
          <FactTile big label="Self-test" value={res.score} sub={`passed, in ${res.seconds.toFixed(1)} s`} tone={res.passed ? "bull" : undefined} />
          <ul className="flex flex-col divide-y divide-line rounded-[var(--radius-tile)] border border-line">
            {res.checks.map((c) => (
              <li key={c.name} className="flex items-start gap-2.5 px-3 py-2">
                {c.passed ? <CheckCircle2 size={17} className="mt-0.5 shrink-0 text-bull" aria-label="passed" /> : <XCircle size={17} className="mt-0.5 shrink-0 text-bear" aria-label="failed" />}
                <span><span className="font-medium">{c.name}</span><span className="block text-[13px] text-muted">{c.detail}</span></span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {res && !res.passed && (
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => run.mutate()} disabled={run.isPending}><RefreshCw size={14} /> Check again</Button>
          <CopyButton text={diagnostic} label="Copy diagnostic" done="Copied the diagnostic. No keys or journal rows are in it." />
        </div>
      )}
      {diag && (
        <div>
          <p className="mb-1 text-[13px] text-muted">No keys or journal rows are included.</p>
          <pre className="scroll-thin max-h-64 overflow-auto whitespace-pre-wrap rounded-[var(--radius-tile)] border border-line bg-panel-2 p-3 text-[13px]">{diag}</pre>
        </div>
      )}
      <NavRow step={4} onGo={onGo} next={null}><Button variant="primary" onClick={onOpen}>Open dashboard</Button></NavRow>
    </div>
  );
}

export function FirstRunWizard({ w }: { w: WizardState }) {
  const qc = useQueryClient();
  const toast = useToast();
  const n = w.step;
  const go = useMutation({
    mutationFn: (s: number) => post<{ step: number }>("/api/wizard/step", { step: s }),
    onSuccess: (r) => qc.setQueryData<WizardState>(["wizard"], (x) => x && { ...x, step: r.step }),
  });
  const open = useMutation({
    mutationFn: () => post("/api/wizard/done", { done: true }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["wizard"] }); qc.invalidateQueries({ queryKey: ["wizard-home"] }); toast("Opened the dashboard. Run the wizard again from Home any time."); },
  });
  const onGo = (s: number) => go.mutate(s);
  const screens = [
    <MachineScreen key="0" w={w} onGo={onGo} />, <ModelScreen key="1" w={w} onGo={onGo} />, <CloudScreen key="2" w={w} onGo={onGo} />,
    <SampleScreen key="3" w={w} onGo={onGo} />, <SelfTestScreen key="4" w={w} onGo={onGo} onOpen={() => open.mutate()} />,
  ];
  return (
    <div className="mx-auto flex max-w-[980px] flex-col gap-5">
      <div>
        <h2 className="text-[20px] font-semibold">First-run wizard</h2>
        <p className="text-muted">Five short screens, then a ten-second self-test. Paper only: PlugAI-Trade never places real orders.</p>
      </div>
      <ol className="grid grid-cols-5 gap-2" aria-label="Wizard progress">
        {w.steps.map((s, i) => (
          <li key={s}>
            <button type="button" onClick={() => onGo(i)} aria-current={i === n ? "step" : undefined}
              className={cn("flex w-full flex-col items-start gap-1 rounded-[6px] px-1 pb-1 text-left", i === n ? "text-ink" : "text-muted hover:text-ink")}>
              <span className={cn("h-1 w-full rounded-full", i <= n ? "bg-indigo" : "bg-line-strong")} />
              <span className="text-[12px]">Screen {i + 1}</span>
              <span className={cn("text-[13px] leading-tight", i === n && "font-medium")}>{s}</span>
            </button>
          </li>
        ))}
      </ol>
      <Panel title={`Screen ${n + 1} of ${w.steps.length}: ${w.steps[n]}`}>{screens[n]}</Panel>
      <ErrorLine error={go.error ?? open.error} />
    </div>
  );
}
