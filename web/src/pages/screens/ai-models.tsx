import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lock, Cloud, DownloadCloud, Gauge, Plus, Trash2 } from "lucide-react";
import { get, post } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button, Field, Panel, inputCls } from "@/components/ui";
import { Badge, Callout, DataTable, Segmented, Select, useToast } from "@/components/kit";
import { ExplainPanel, FactTile, FactsProvider } from "@/components/facts";
import { useMarket } from "@/components/shell";
import { ErrorLine, FitBar, PullProgress, TextInput, usePull, type Fit } from "@/components/settings/common";

interface ModelRow { size: string; label: string; tag: string; download_gb: number; good_for: string; fit: Fit }
interface AIM {
  ram_gb: number | null; free_ram_gb: number | null; ollama: boolean; ollama_host: string; default: string; local_models: string[]; installed: string[];
  local_servers: string[]; lm_studio: string; contexts: number[]; context_length: number; models: ModelRow[]; suggestion: string;
  cloud_models: string[]; providers: { provider: string; key: string; masked: string }[]; drafting: string; journal: string;
  drafting_options: string[]; journal_options: string[]; use_for: { section: string; policy: string; forced: boolean }[];
  budget: number; spend: number; embedding: string; embedding_default: { tag: string; download_gb: number };
}
interface TestOut { model: string; ok: boolean; tokens_per_s: number; prompt_s: number; detail: string; facts: string[] }
const KEY = ["ai-models"];

export const LocalBadge = () => <Badge tone="indigo" className="gap-1"><Lock size={11} /> Local</Badge>;
export const CloudBadge = () => <Badge tone="warn" className="gap-1"><Cloud size={11} /> Cloud</Badge>;

function LocalSection({ m }: { m: AIM }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [pick, setPick] = useState(m.default);
  useEffect(() => setPick(m.default), [m.default]);
  const setDefault = useMutation({ mutationFn: () => post("/api/settings/ai-models/default", { tag: pick }), onSuccess: () => { qc.invalidateQueries({ queryKey: KEY }); qc.invalidateQueries({ queryKey: ["status"] }); toast(`Set ${pick} as Default`); } });
  const test = useMutation({ mutationFn: () => post<TestOut>("/api/settings/ai-models/test", { tag: pick }) });
  const [url, setUrl] = useState(m.lm_studio);
  const [adding, setAdding] = useState(false);
  const addServer = useMutation({ mutationFn: () => post("/api/settings/ai-models/local-server", { url }), onSuccess: () => { qc.invalidateQueries({ queryKey: KEY }); setAdding(false); toast(`Added local server ${url}, marked Local`); } });
  const rmServer = useMutation({ mutationFn: (u: string) => post("/api/settings/ai-models/local-server/remove", { url: u }), onSuccess: (_r, u) => { qc.invalidateQueries({ queryKey: KEY }); toast(`Removed ${u}`); } });
  const rows = [
    ...m.local_models.map((n) => ({ model: n, where: "Ollama", isDefault: n === m.default, server: false })),
    ...m.local_servers.map((u) => ({ model: u, where: "Local server", isDefault: false, server: true })),
  ];
  const t = test.data;
  return (
    <Panel title="Local (Ollama)">
      <div className="flex flex-col gap-4">
        <DataTable rows={rows as unknown as Record<string, unknown>[]} rowKey={(r) => String(r.model)} columns={[
          { key: "model", header: "Model", render: (r) => <span className="font-medium">{String(r.model)}</span> },
          { key: "where", header: "Where", render: (r) => <span className="flex items-center gap-2"><LocalBadge /><span className="text-[13px] text-muted">{String(r.where)}</span></span> },
          { key: "isDefault", header: "Default", render: (r) => (r.isDefault ? <Badge tone="indigo">Default</Badge> : r.server ? <Button size="sm" variant="quiet" onClick={() => rmServer.mutate(String(r.model))}><Trash2 size={13} /> Remove</Button> : null) },
        ]} />
        {!m.ollama && <p className="text-[13px] text-muted">Ollama not found at <span className="num">{m.ollama_host}</span>: start the Ollama app (or <code>ollama serve</code>), then reload.</p>}
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Default local model"><Select className="w-56 font-sans" value={pick} onChange={(e) => setPick(e.target.value)}>{m.local_models.map((n) => <option key={n}>{n}</option>)}</Select></Field>
          <Button onClick={() => setDefault.mutate()} disabled={pick === m.default || setDefault.isPending}>Set as Default</Button>
          <Button variant="primary" onClick={() => test.mutate()} disabled={test.isPending}><Gauge size={14} /> {test.isPending ? "Testing…" : "Test model"}</Button>
          {!adding && <Button variant="quiet" onClick={() => setAdding(true)}><Plus size={14} /> Add local server</Button>}
        </div>
        {adding && (
          <div className="flex flex-wrap items-end gap-2 rounded-[var(--radius-tile)] border border-dashed border-line-strong p-3">
            <div className="min-w-[260px] flex-1"><TextInput label="Server address (OpenAI-compatible)" value={url} onChange={setUrl} hint="LM Studio's local server is http://localhost:1234/v1" /></div>
            <Button className="mb-[22px]" variant="primary" onClick={() => addServer.mutate()} disabled={!url.trim() || addServer.isPending}>Add local server</Button>
            <Button className="mb-[22px]" variant="quiet" onClick={() => setAdding(false)}>Cancel</Button>
          </div>
        )}
        {t && (
          <div className="flex flex-col gap-3">
            <div className="grid gap-2.5 sm:grid-cols-3">
              <FactTile label="Speed" value={t.tokens_per_s ? `${t.tokens_per_s.toFixed(1)} tokens/s` : "—"} sub={t.model} />
              <FactTile label="Prompt reading time" value={t.prompt_s ? `${t.prompt_s.toFixed(2)} s` : "—"} />
              <FactTile label="Accuracy" value={t.ok ? "No invented numbers" : "Check"} tone={t.ok ? "bull" : undefined} />
            </div>
            <Callout tone={t.ok ? "ok" : "warn"}>{t.detail}</Callout>
          </div>
        )}
        <ErrorLine error={setDefault.error ?? test.error ?? addServer.error ?? rmServer.error} />
      </div>
    </Panel>
  );
}

function PullAndFit({ m }: { m: AIM }) {
  const qc = useQueryClient();
  const toast = useToast();
  const ctx = useMutation({ mutationFn: (tokens: number) => post<AIM>("/api/settings/ai-models/context", { tokens }), onSuccess: (d) => { qc.setQueryData(KEY, d); toast(`Set context length to ${d.context_length / 1024}k`); } });
  const [tag, setTag] = useState(m.suggestion);
  const pull = usePull((msg) => { toast(msg); qc.invalidateQueries({ queryKey: KEY }); qc.invalidateQueries({ queryKey: ["status"] }); });
  return (
    <Panel title="Pull model and Fit check">
      <div className="flex flex-col gap-4">
        <Field label="Context length">
          <Segmented label="Context length" value={String(m.context_length)} onChange={(v) => ctx.mutate(Number(v))}
            options={m.contexts.map((c) => ({ value: String(c), label: `${c / 1024}k` }))} />
        </Field>
        <div className="flex flex-col gap-4">
          {m.models.map((x) => (
            <FitBar key={x.tag} fit={x.fit} label={<span><span className="font-medium">{x.label}</span> <span className="text-muted">({x.tag}, download ≈ {x.download_gb} GB)</span></span>} />
          ))}
        </div>
        <p className="text-[13px] text-muted">An estimate: model file + context scratchpad + what your system already uses. Green up to 80% of RAM, amber up to 100%. Real use varies with the runner.</p>
        <div className="flex flex-wrap items-end gap-2 border-t border-line pt-4">
          <Field label="Model size"><Select className="w-[340px] font-sans" value={tag} onChange={(e) => setTag(e.target.value)}>{m.models.map((x) => <option key={x.tag} value={x.tag}>{x.label} ({x.tag}){x.tag === m.suggestion ? ", suggested" : ""}</option>)}</Select></Field>
          <Button variant="primary" onClick={() => pull.start(tag, true)} disabled={pull.running}><DownloadCloud size={15} /> Pull model</Button>
        </div>
        <PullProgress st={pull} />
        <ErrorLine error={ctx.error} />
      </div>
    </Panel>
  );
}

function CloudSection({ m }: { m: AIM }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [prov, setProv] = useState(m.providers[0].provider);
  const [name, setName] = useState("");
  const add = useMutation({ mutationFn: () => post<{ added: string }>("/api/settings/ai-models/cloud", { provider: prov, name }), onSuccess: (r) => { setName(""); qc.invalidateQueries({ queryKey: KEY }); toast(`Added cloud model ${r.added}, marked Cloud`); } });
  const rm = useMutation({ mutationFn: (n: string) => post("/api/settings/ai-models/cloud/remove", { name: n }), onSuccess: (_r, n) => { qc.invalidateQueries({ queryKey: KEY }); toast(`Removed ${n}`); } });
  const p = m.providers.find((x) => x.provider === prov)!;
  return (
    <Panel title="Cloud (your keys)">
      <div className="flex flex-col gap-4">
        {m.cloud_models.length === 0 ? <p className="text-muted">No cloud model. Nothing in the book needs one.</p> : (
          <ul className="flex flex-col divide-y divide-line">
            {m.cloud_models.map((c) => (
              <li key={c} className="flex items-center gap-3 py-2"><span className="font-medium">{c}</span><CloudBadge />
                <Button size="sm" variant="quiet" className="ml-auto" onClick={() => rm.mutate(c)}><Trash2 size={13} /> Remove</Button></li>
            ))}
          </ul>
        )}
        <div className="grid gap-3 rounded-[var(--radius-tile)] border border-line bg-panel-2 p-3 md:grid-cols-[160px_1fr_auto] md:items-end">
          <Field label="Provider"><Select className="font-sans" value={prov} onChange={(e) => setProv(e.target.value)}>{m.providers.map((x) => <option key={x.provider}>{x.provider}</option>)}</Select></Field>
          <TextInput label="Model name (as the provider lists it)" value={name} onChange={setName} placeholder="e.g. gemini-flash" />
          <Button onClick={() => add.mutate()} disabled={!name.trim() || add.isPending}><Plus size={14} /> Add cloud model</Button>
          <p className="text-[13px] text-muted md:col-span-3">Key: <span className="num">{p.masked}</span>{p.masked === "not set" && <> (add it in <Link to="/keys" className="font-medium text-indigo hover:underline">Settings › Keys</Link>)</>}</p>
        </div>
        <ErrorLine error={add.error ?? rm.error} />
      </div>
    </Panel>
  );
}

function Roles({ m }: { m: AIM }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [d, setD] = useState(m.drafting);
  const [j, setJ] = useState(m.journal);
  const save = useMutation({ mutationFn: () => post("/api/settings/ai-models/roles", { drafting: d, journal: j }), onSuccess: () => { qc.invalidateQueries({ queryKey: KEY }); qc.invalidateQueries({ queryKey: ["status"] }); toast("Saved models"); } });
  return (
    <Panel title="Which model does which job">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Drafting"><Select className="w-60 font-sans" value={d} onChange={(e) => setD(e.target.value)}>{m.drafting_options.map((x) => <option key={x}>{x}</option>)}</Select></Field>
        <Field label="Journal and portfolio (local only)"><Select className="w-60 font-sans" value={j} onChange={(e) => setJ(e.target.value)}>{m.journal_options.map((x) => <option key={x}>{x}</option>)}</Select></Field>
        <Button onClick={() => save.mutate()} disabled={save.isPending || (d === m.drafting && j === m.journal)}>Save models</Button>
      </div>
      <ErrorLine error={save.error} />
    </Panel>
  );
}

function UseFor({ m }: { m: AIM }) {
  const qc = useQueryClient();
  const toast = useToast();
  const set = useMutation({ mutationFn: (b: { section: string; policy: string }) => post("/api/settings/ai-models/use-for", b), onSuccess: (_r, b) => { qc.invalidateQueries({ queryKey: KEY }); toast(`${b.section}: ${b.policy}`); } });
  return (
    <Panel title="Use for">
      <div className="grid gap-x-6 md:grid-cols-2">
        {m.use_for.map((u) => (
          <div key={u.section} className="flex items-center justify-between gap-3 border-b border-line py-2">
            <span>{u.section}{u.forced && <span className="block text-[12px] text-muted">Kept Local only by <Link to="/privacy" className="text-indigo hover:underline">Settings › Privacy</Link></span>}</span>
            {u.forced ? <Badge tone="indigo" className="gap-1"><Lock size={11} /> Local only</Badge>
              : <Segmented label={`${u.section} routing`} value={u.policy} options={["Local only", "Cloud allowed"] as const} onChange={(v) => set.mutate({ section: u.section, policy: v })} />}
          </div>
        ))}
      </div>
      <p className="mt-3 text-[13px] text-muted">Sections set to Local only never reach the privacy gate at all.</p>
      <ErrorLine error={set.error} />
    </Panel>
  );
}

function Budget({ m }: { m: AIM }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [market] = useMarket();
  const [b, setB] = useState(String(m.budget));
  const save = useMutation({ mutationFn: () => post("/api/settings/ai-models/budget", { usd: Number(b) }), onSuccess: () => { qc.invalidateQueries({ queryKey: KEY }); qc.invalidateQueries({ queryKey: ["status"] }); toast(`Set the monthly budget to $${Number(b).toFixed(2)}`); } });
  const share = m.budget ? Math.min(1, m.spend / m.budget) : 0;
  return (
    <Panel title="Monthly budget">
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end gap-2">
          <Field label={`Monthly budget for cloud calls, in US dollars (the cost meter counts in ${market === "IN" ? "₹" : "$"})`}>
            <input type="number" min={0} step={1} className={cn(inputCls, "w-32")} value={b} onChange={(e) => setB(e.target.value)} />
          </Field>
          <Button onClick={() => save.mutate()} disabled={save.isPending || b === "" || Number(b) === m.budget}>Save budget</Button>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-panel-2 ring-1 ring-line"><div className="h-full bg-indigo" style={{ width: `${share * 100}%` }} /></div>
        <p className="num text-[13px] text-muted">This month ${m.spend.toFixed(2)} of ${m.budget.toFixed(2)}. Cloud calls pause at the limit and fall back to the local model.</p>
        <ErrorLine error={save.error} />
      </div>
    </Panel>
  );
}

function Embeddings({ m }: { m: AIM }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [e, setE] = useState(m.embedding);
  const save = useMutation({ mutationFn: () => post("/api/settings/ai-models/embedding", { model: e }), onSuccess: () => { qc.invalidateQueries({ queryKey: KEY }); toast(`Set the embedding model to ${e}`); } });
  const pull = usePull((msg) => toast(msg));
  return (
    <Panel title="Embeddings">
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end gap-2">
          <div className="w-72"><TextInput label="Embedding model (Document Desk search by meaning)" value={e} onChange={setE} /></div>
          <Button onClick={() => save.mutate()} disabled={save.isPending || e === m.embedding}>Save</Button>
          <Button variant="primary" onClick={() => pull.start(e.trim(), false)} disabled={pull.running || !e.trim()}><DownloadCloud size={15} /> Pull model</Button>
        </div>
        <p className="text-[13px] text-muted">Small default: {m.embedding_default.tag}, about {m.embedding_default.download_gb} GB.</p>
        <PullProgress st={pull} />
        <ErrorLine error={save.error} />
      </div>
    </Panel>
  );
}

export default function AIModels() {
  const { data: m, error } = useQuery({ queryKey: KEY, queryFn: () => get<AIM>("/api/settings/ai-models") });
  if (error) return <Callout tone="danger" title="AI Models could not load">{(error as Error).message}</Callout>;
  if (!m) return <div className="min-h-[60vh]" aria-busy="true" />;
  const def = m.models.find((x) => x.tag === m.default) ?? m.models.find((x) => x.tag === m.suggestion)!;
  // The engine's Fit facts read "Model file 6.6 GB"; a colon after the label lets citations light the tiles.
  const facts = [...def.fit.facts.map((f) => f.replace(/^(Model file|Context scratchpad|Already in use|Total) /, "$1: ")),
    `Memory: ${m.ram_gb ? `${m.ram_gb.toFixed(0)} GB` : "unknown"}`, `Default local model: ${m.default}`, `Context length: ${m.context_length / 1024}k`];
  return (
    <FactsProvider>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="flex min-w-0 flex-col gap-5">
          <p className="text-[13px] text-muted">The model explains numbers; code computes them.</p>
          <LocalSection m={m} />
          <PullAndFit m={m} />
          <CloudSection m={m} />
          <Roles key={`${m.drafting}-${m.journal}`} m={m} />
          <UseFor m={m} />
          <Budget key={m.budget} m={m} />
          <Embeddings key={m.embedding} m={m} />
        </div>
        <div className="flex flex-col gap-4 xl:sticky xl:top-0 xl:self-start">
          <FactTile big label="Total" value={`${def.fit.total_gb.toFixed(1)} GB`} sub={`of ${def.fit.ram_gb.toFixed(0)} GB RAM for ${def.tag}, ${Math.round(def.fit.share * 100)}%`} />
          <div className="grid grid-cols-2 gap-2.5">
            <FactTile label="Memory" value={m.ram_gb ? `${m.ram_gb.toFixed(0)} GB` : "Unknown"} sub="total" />
            <FactTile label="Free right now" value={m.free_ram_gb != null ? `${m.free_ram_gb.toFixed(1)} GB` : "—"} />
            <FactTile label="Model file" value={`${def.fit.model_gb.toFixed(1)} GB`} />
            <FactTile label="Context scratchpad" value={`${def.fit.context_gb.toFixed(2)} GB`} sub={`${m.context_length / 1024}k context`} />
            <FactTile label="Already in use" value={`${def.fit.used_gb.toFixed(1)} GB`} />
            <FactTile label="Default local model" value={<span className="text-[16px]">{m.default}</span>} />
          </div>
          <Panel title="Explain the Fit check">
            <ExplainPanel facts={facts} section="Settings" />
          </Panel>
        </div>
      </div>
    </FactsProvider>
  );
}
