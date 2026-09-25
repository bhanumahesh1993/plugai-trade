import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileText, Upload, X } from "lucide-react";
import { get, post, type Market } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button, Field, MarketChip, Panel, Tab, TabList, TabPanel, Tabs, inputCls } from "@/components/ui";
import { Badge, Callout, DataTable, EmptyState, Segmented, Select, Switch, Textarea, useToast } from "@/components/kit";
import { ExplainPanel, FactTile, FactsProvider } from "@/components/facts";
import { useMarket } from "@/components/shell";
import { Disclosure, ErrorLine, Hint, download, readFile } from "@/components/research/common";

interface Doc { name: string; check: string; market: Market; kind: string; pages: number; untrusted: boolean; source: string }
interface Desk { documents: Doc[]; samples: string[]; templates: string[]; added?: string }
interface Answer {
  question: string; found: boolean; quotes: { text: string; cite: string; closeness: number }[]; searched: string[];
  narration: string; where: string; unverified: string[];
  hits: { cite: string; closeness: number; method: string; passage: string }[]; facts: string[];
}
interface Extraction {
  template: string; document: string; found: number; csv: string; filename: string; facts: string[];
  rows: { field: string; quote: string; cite: string; status: string; searched: string[] }[];
}
interface Tone { words: number; hedging: number; confident: number }
interface Comparison {
  doc_a: string; doc_b: string; facts: string[]; tone_a: Tone; tone_b: Tone;
  rows: { topic: string; quote_a: string; cite_a: string; quote_b: string; cite_b: string; change: string }[];
}
interface Library {
  counts: { documents: number; chunks: number; scanned: number };
  docs: { name: string; market: Market; pages: number; chunks: number; scanned: boolean }[];
  line?: string; errors?: string[];
}

const SCOPES = ["This document", "Ask my documents"] as const;
type Scope = (typeof SCOPES)[number];

const Chip = ({ children }: { children: string }) => (
  <span className="num ml-1 inline-flex h-5 items-center whitespace-nowrap rounded-[4px] bg-indigo-soft px-1.5 font-sans text-[12px] font-medium text-indigo">{children}</span>
);

/* ------------------------------------------------------------------ load */
function LoadPanel({ market, desk, onDesk }: { market: Market; desk?: Desk; onDesk: (d: Desk) => void }) {
  const toast = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const [link, setLink] = useState("");
  const [text, setText] = useState("");
  const [name, setName] = useState("Pasted text");
  const [sample, setSample] = useState("");
  useEffect(() => { if (desk && !sample) setSample(desk.samples[0]); }, [desk, sample]);

  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      let last: Desk | undefined;
      for (const f of files) {
        if (desk?.documents.some((d) => d.name === f.name.replace(/\.pdf$/i, ""))) continue;
        last = await post<Desk>("/api/research/documents/upload", { name: f.name, data_b64: await readFile(f, "dataurl"), market });
      }
      return last;
    },
    onSuccess: (d) => { if (d) { onDesk(d); toast(`Loaded ${d.added}`); } },
  });
  const fetchLink = useMutation({
    mutationFn: () => post<Desk>("/api/research/documents/link", { url: link, market }),
    onSuccess: (d) => { onDesk(d); toast(`Loaded ${d.added}`); },
  });
  const paste = useMutation({
    mutationFn: () => post<Desk>("/api/research/documents/text", { text, name, market }),
    onSuccess: (d) => { onDesk(d); toast(`Added ${d.added}`); },
  });
  const loadSample = useMutation({
    mutationFn: () => post<Desk>("/api/research/documents/sample", { name: sample }),
    onSuccess: (d) => { onDesk(d); toast(`Loaded ${d.added}`); },
  });

  return (
    <Panel title="Load a document">
      <div className="grid gap-5 lg:grid-cols-[1.2fr_1fr]">
        <div className="flex flex-col gap-3">
          <button type="button" onClick={() => fileRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); upload.mutate(Array.from(e.dataTransfer.files)); }}
            className={cn("flex h-[104px] flex-col items-center justify-center gap-1 rounded-[var(--radius-tile)] border border-dashed text-muted",
              drag ? "border-indigo bg-indigo-soft text-indigo" : "border-line-strong hover:border-indigo hover:text-ink")}>
            <Upload size={18} />
            <span className="font-medium text-ink">{upload.isPending ? "Reading the PDF…" : "Drop a PDF"}</span>
            <span className="text-[12px]">or click to choose. PDF, .txt or .md, several at once</span>
          </button>
          <input ref={fileRef} type="file" accept=".pdf,.txt,.md" multiple hidden
            onChange={(e) => { upload.mutate(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
          <ErrorLine error={upload.error} />
          <Field label="Paste a link">
            <div className="flex gap-2">
              <input className={inputCls} placeholder="https://… (exchange filing, EDGAR, IR page)" value={link} onChange={(e) => setLink(e.target.value)} />
              <Button onClick={() => fetchLink.mutate()} disabled={!link.trim() || fetchLink.isPending}>{fetchLink.isPending ? "Fetching…" : "Fetch link"}</Button>
            </div>
          </Field>
          <ErrorLine error={fetchLink.error} />
        </div>
        <div className="flex flex-col gap-3">
          <Field label="Or paste text" hint="Pasted text is fenced as untrusted: instructions inside it are ignored.">
            <Textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} />
          </Field>
          <div className="flex items-end gap-2">
            <Field label="Name for pasted text"><input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <Button onClick={() => paste.mutate()} disabled={!text.trim() || paste.isPending}>Add pasted text</Button>
          </div>
          <ErrorLine error={paste.error} />
          <div className="flex items-end gap-2">
            <Field label="Sample documents (fictional)">
              <Select value={sample} onChange={(e) => setSample(e.target.value)}>
                {desk?.samples.map((s) => <option key={s}>{s}</option>)}
              </Select>
            </Field>
            <Button onClick={() => loadSample.mutate()} disabled={!sample || loadSample.isPending}>Load sample</Button>
          </div>
        </div>
      </div>
    </Panel>
  );
}

/* ------------------------------------------------------------------ ask */
function AskPanel({ current, initial }: { current?: string; initial: string }) {
  const [scope, setScope] = useState<Scope>("This document");
  const [q, setQ] = useState(initial);
  useEffect(() => { if (initial) setQ(initial); }, [initial]);
  const ask = useMutation({ mutationFn: () => post<Answer>("/api/research/documents/ask", { question: q, scope, document: current }) });
  const a = ask.data;
  const noDoc = scope === "This document" && !current;
  return (
    <Panel title="Ask">
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-[12px] text-muted">Scope</span>
          <Segmented label="Scope" value={scope} options={SCOPES} onChange={setScope} />
          {scope === "This document" && current && <span className="truncate text-[13px] text-muted">{current}</span>}
        </div>
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (q.trim() && !noDoc) ask.mutate(); }}>
          <input aria-label="Question" className={cn(inputCls, "font-sans")} value={q} onChange={(e) => setQ(e.target.value)}
            placeholder="What did management say about receivables and credit terms?" />
          <Button type="submit" variant="primary" disabled={!q.trim() || noDoc || ask.isPending}>{ask.isPending ? "Searching…" : "Ask"}</Button>
        </form>
        {noDoc && <Hint>Load a document first, or switch the scope to Ask my documents.</Hint>}
        <ErrorLine error={ask.error} />
        {a && (
          <div className="flex flex-col gap-3">
            {a.found ? (
              <ol className="flex list-decimal flex-col gap-2 pl-5 font-serif text-[15px] leading-[1.6]">
                {a.quotes.map((x, i) => <li key={i}>“{x.text}”<Chip>{x.cite}</Chip></li>)}
              </ol>
            ) : (
              <Callout tone="warn" title="Not found in source">
                Pages searched: {a.searched.join(", ") || "none"}. Reword the question or open those pages yourself.
              </Callout>
            )}
            {a.narration && (a.where === "Fallback" ? <Hint>{a.narration}</Hint> : <Callout tone="info">{a.narration}</Callout>)}
            {a.unverified.length > 0 && (
              <Callout tone="warn" title="Quotes in the model's reply not found word for word in the source">{a.unverified.join(" | ")}</Callout>
            )}
            <Disclosure title="Passages searched (closeness scores)">
              <DataTable rows={a.hits} empty="No passages were searched." columns={[
                { key: "cite", header: "Citation", width: "150px" },
                { key: "closeness", header: "Closeness", align: "right", width: "90px", render: (h) => h.closeness.toFixed(3) },
                { key: "method", header: "Method", width: "80px" },
                { key: "passage", header: "Passage", render: (h) => <span className="text-[13px] text-muted">{h.passage}</span> },
              ]} />
            </Disclosure>
            <ExplainPanel facts={a.facts} section="Documents" />
          </div>
        )}
      </div>
    </Panel>
  );
}

/* ------------------------------------------------------------------ extract */
function ExtractPanel({ current, templates, market }: { current: string; templates: string[]; market: Market }) {
  const toast = useToast();
  const [tpl, setTpl] = useState(templates[0]);
  const [open, setOpen] = useState<Record<number, boolean>>({});
  const { data: f } = useQuery({ queryKey: ["dd-fields", tpl], queryFn: () => get<{ fields: string }>(`/api/research/documents/fields?template=${encodeURIComponent(tpl)}`) });
  const [fields, setFields] = useState("");
  useEffect(() => { if (f) setFields(f.fields); }, [f]);
  const body = { document: current, template: tpl, fields: fields || null };
  const ext = useMutation({ mutationFn: () => post<Extraction>("/api/research/documents/extract", body), onSuccess: () => setOpen({}) });
  const accept = useMutation({
    mutationFn: () => post("/api/research/documents/accept", { kind: "extraction", market, extract: { document: e!.document, template: e!.template, fields: fields || null } }),
    onSuccess: () => toast("Saved to the Thesis tracker"),
  });
  const e = ext.data;
  return (
    <Panel title="Extract to table">
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Template">
            <Select value={tpl} onChange={(ev) => setTpl(ev.target.value)} className="w-[220px]">
              {templates.map((t) => <option key={t}>{t}</option>)}
            </Select>
          </Field>
          <Button variant="primary" onClick={() => ext.mutate()} disabled={ext.isPending || !fields.trim()}>Extract to table</Button>
        </div>
        <Disclosure title="Edit fields">
          <Field label="One field per line: Name: search words, comma-separated">
            <Textarea rows={7} className="text-[13px]" value={fields} onChange={(ev) => setFields(ev.target.value)} />
          </Field>
        </Disclosure>
        <ErrorLine error={ext.error} />
        {e && (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-[13px] text-muted">{e.template} on {e.document}: <b className="num text-ink">{e.found} of {e.rows.length}</b> found</span>
              <Button size="sm" onClick={() => download(e.csv, e.filename)}><Download size={14} /> Export CSV</Button>
            </div>
            <DataTable rows={e.rows.map((r, i) => ({ ...r, i }))} columns={[
              { key: "field", header: "Field", width: "180px", render: (r) => <span className="font-medium">{r.field}</span> },
              { key: "quote", header: "Quote", render: (r) => r.status === "found"
                ? <span className="font-serif text-[14px]">“{r.quote}”</span>
                : (
                  <div>
                    <span className="text-muted">Not found in source.</span>
                    <Button size="sm" variant="quiet" className="ml-1" onClick={() => setOpen((o) => ({ ...o, [r.i]: !o[r.i] }))}>Show sources</Button>
                    {open[r.i] && <div className="mt-1 text-[12px] text-muted">Pages searched: {r.searched.join(", ")}</div>}
                  </div>
                ) },
              { key: "cite", header: "Citation", width: "110px", render: (r) => (r.cite ? <Chip>{r.cite}</Chip> : "—") },
              { key: "status", header: "Status", width: "140px", render: (r) => <Badge tone={r.status === "found" ? "indigo" : "warn"}>{r.status}</Badge> },
            ]} />
            <Hint>The desk extracts figures; it never calculates them. Compute growth rates in your spreadsheet.</Hint>
            <ExplainPanel facts={e.facts} section="Documents" onAccept={() => accept.mutate()} />
            <ErrorLine error={accept.error} />
          </>
        )}
      </div>
    </Panel>
  );
}

/* ------------------------------------------------------------------ compare */
function ComparePanel({ docs, market }: { docs: Doc[]; market: Market }) {
  const toast = useToast();
  const names = docs.map((d) => d.name);
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  useEffect(() => {
    if (!names.includes(a)) setA(names[0] ?? "");
    if (!names.includes(b)) setB(names[names.length - 1] ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [names.join("|")]);
  const cmp = useMutation({ mutationFn: () => post<Comparison>("/api/research/documents/compare", { a, b }) });
  const accept = useMutation({
    mutationFn: () => post("/api/research/documents/accept", { kind: "comparison", market, compare: { a: c!.doc_a, b: c!.doc_b } }),
    onSuccess: () => toast("Saved to the Thesis tracker"),
  });
  const c = cmp.data;
  const delta = (x: number, y: number) => { const d = Math.round((y - x) * 10) / 10; return `${d > 0 ? "+" : d < 0 ? "−" : ""}${Math.abs(d)} vs earlier`; };
  return (
    <Panel title="Compare">
      {names.length < 2 ? (
        <p className="text-muted">Load two documents (for example two quarters' transcripts) to compare.</p>
      ) : (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-end gap-2">
            <Field label="Earlier"><Select className="w-[240px]" value={a} onChange={(e) => setA(e.target.value)}>{names.map((n) => <option key={n}>{n}</option>)}</Select></Field>
            <Field label="Later"><Select className="w-[240px]" value={b} onChange={(e) => setB(e.target.value)}>{names.map((n) => <option key={n}>{n}</option>)}</Select></Field>
            <Button variant="primary" onClick={() => cmp.mutate()} disabled={!a || !b || a === b || cmp.isPending}>Compare</Button>
          </div>
          {a === b && a && <Hint>Pick two different documents.</Hint>}
          <ErrorLine error={cmp.error} />
          {c && (
            <>
              <DataTable rows={c.rows} columns={[
                { key: "topic", header: "Topic", width: "110px", render: (r) => <span className="font-medium">{r.topic}</span> },
                { key: "quote_a", header: c.doc_a, render: (r) => <span className="text-[13px]">{r.quote_a}{r.cite_a && <Chip>{r.cite_a}</Chip>}</span> },
                { key: "quote_b", header: c.doc_b, render: (r) => <span className="text-[13px]">{r.quote_b}{r.cite_b && <Chip>{r.cite_b}</Chip>}</span> },
                { key: "change", header: "Change", width: "190px", render: (r) => <span className="text-[13px] text-muted">{r.change}</span> },
              ]} />
              <div className="mt-1 text-[14px] font-semibold">Tone count <span className="font-normal text-muted">(computed in code, per 1,000 words)</span></div>
              <div className="grid grid-cols-2 gap-2.5">
                <FactTile label="Tone A" value={`${c.tone_a.hedging} hedging`} sub={`${c.tone_a.confident} confident, ${c.doc_a}`} />
                <FactTile label="Tone B" value={`${c.tone_b.hedging} hedging`}
                  sub={`${c.tone_b.confident} confident, ${c.doc_b}. Hedging ${delta(c.tone_a.hedging, c.tone_b.hedging)}`} />
              </div>
              <ExplainPanel facts={c.facts} section="Documents" onAccept={() => accept.mutate()} />
              <ErrorLine error={accept.error} />
            </>
          )}
        </div>
      )}
    </Panel>
  );
}

/* ------------------------------------------------------------------ library */
function LibraryTab({ market }: { market: Market }) {
  const toast = useToast();
  const qc = useQueryClient();
  const { data: lib, error } = useQuery({ queryKey: ["dd-library"], queryFn: () => get<Library>("/api/research/documents/library") });
  const [folder, setFolder] = useState("");
  const [fm, setFm] = useState<Market>(market);
  const [emb, setEmb] = useState(false);
  const [report, setReport] = useState<Library | null>(null);
  const done = (r: Library) => { setReport(r); qc.setQueryData(["dd-library"], r); };
  const add = useMutation({ mutationFn: () => post<Library>("/api/research/documents/library/folder", { folder, market: fm, embed: emb }), onSuccess: (r) => { done(r); toast("Folder indexed"); } });
  const samples = useMutation({ mutationFn: () => post<Library>("/api/research/documents/library/samples"), onSuccess: (r) => { done(r); toast("Sample documents indexed"); } });
  const n = lib?.counts;
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
      <div className="flex min-w-0 flex-col gap-5">
        <div className="grid grid-cols-3 gap-2.5">
          <FactTile label="Documents" value={n?.documents ?? "…"} big />
          <FactTile label="Chunks" value={n ? n.chunks.toLocaleString("en-US") : "…"} />
          <FactTile label="Scanned PDFs skipped" value={n?.scanned ?? "…"} />
        </div>
        <Panel title="Indexed documents">
          <DataTable rows={lib?.docs ?? []} empty="Nothing indexed yet. Add a folder, or index the sample documents." columns={[
            { key: "name", header: "Document", render: (d) => <span className="font-medium">{d.name}</span> },
            { key: "market", header: "Market", width: "80px", render: (d) => <MarketChip m={d.market} /> },
            { key: "pages", header: "Pages", align: "right", width: "80px" },
            { key: "chunks", header: "Chunks", align: "right", width: "80px" },
            { key: "scanned", header: "Scanned", width: "90px", render: (d) => (d.scanned ? "Yes" : "No") },
          ]} />
          <ErrorLine error={error} />
        </Panel>
        <Hint>Ask my documents: switch the Ask scope on the Desk tab. Answers quote each chunk with its file and page; Show sources lists every chunk with its closeness score.</Hint>
      </div>
      <div className="flex flex-col gap-4">
        <Panel title="Add a folder">
          <div className="flex flex-col gap-3">
            <Field label="Folder"><input className={inputCls} placeholder="~/Documents/trading-notes" value={folder} onChange={(e) => setFolder(e.target.value)} /></Field>
            <div className="flex flex-col gap-1">
              <span className="text-[12px] text-muted">Market for this folder</span>
              <Segmented label="Market for this folder" value={fm} options={[{ value: "IN", label: "India" }, { value: "US", label: "US" }]} onChange={setFm} />
            </div>
            <Switch checked={emb} onChange={setEmb} label="Embed with the local embedding model" hint="Only if one is reachable; otherwise the desk searches by words." />
            <Button variant="primary" onClick={() => add.mutate()} disabled={!folder.trim() || add.isPending}>{add.isPending ? "Chunking and indexing on this computer…" : "Add folder"}</Button>
            <ErrorLine error={add.error} />
            <Button onClick={() => samples.mutate()} disabled={samples.isPending}>Index the sample documents</Button>
            {report?.line && <Callout tone="ok">{report.line}</Callout>}
            {report?.errors?.map((e) => <Callout key={e} tone="warn">{e}</Callout>)}
          </div>
        </Panel>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ screen */
export default function DocumentDesk() {
  const [market] = useMarket();
  const qc = useQueryClient();
  const [params] = useSearchParams();   // Lessons › Prompt Library sends ?q=
  const { data: desk, error } = useQuery({ queryKey: ["dd-desk"], queryFn: () => get<Desk>("/api/research/documents") });
  const [current, setCurrent] = useState<string>("");
  const onDesk = (d: Desk) => { qc.setQueryData(["dd-desk"], d); if (d.added) setCurrent(d.added); };
  const docs = desk?.documents ?? [];
  const cur = docs.find((d) => d.name === current) ?? docs[docs.length - 1];
  const remove = useMutation({ mutationFn: (name: string) => post<Desk>("/api/research/documents/remove", { name }), onSuccess: onDesk });

  return (
    <FactsProvider>
      <Tabs defaultValue="desk" className="flex flex-col gap-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <TabList><Tab value="desk">Desk</Tab><Tab value="library">My library</Tab></TabList>
          <span className="pb-2 text-[13px] text-muted">Quote first, cite every page. The desk extracts figures; it never calculates them.</span>
        </div>
        <TabPanel value="desk" className="flex flex-col gap-5">
          <LoadPanel market={market} desk={desk} onDesk={onDesk} />
          <ErrorLine error={error} />
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
            <div className="flex min-w-0 flex-col gap-5">
              <AskPanel current={cur?.name} initial={params.get("q") ?? ""} />
              {cur ? <ExtractPanel current={cur.name} templates={desk?.templates ?? []} market={market} />
                : <Panel title="Extract to table"><p className="text-muted">Load a document to extract a template such as the Red-flag checklist.</p></Panel>}
              <ComparePanel docs={docs} market={market} />
            </div>
            <div className="flex flex-col gap-4">
              <div className="grid grid-cols-2 gap-2.5">
                <FactTile label="Pages" value={cur?.pages ?? "—"} sub={cur ? (cur.check.includes("text OK") ? "text OK" : "check the scan") : "no document"} big />
                <FactTile label="On the desk" value={docs.length} sub={docs.length === 1 ? "document" : "documents"} />
              </div>
              <Panel title="Documents">
                {!docs.length ? (
                  <EmptyState>Drop a PDF, paste a link or text, or load a fictional sample to begin.</EmptyState>
                ) : (
                  <div className="flex flex-col gap-3">
                    <Field label="Document">
                      <Select value={cur?.name} onChange={(e) => setCurrent(e.target.value)}>
                        {docs.map((d) => <option key={d.name}>{d.name}</option>)}
                      </Select>
                    </Field>
                    <ul className="flex flex-col">
                      {docs.map((d) => (
                        <li key={d.name} className={cn("flex items-start gap-2 border-b border-line py-2 last:border-0", d.name === cur?.name && "text-indigo")}>
                          <FileText size={15} className="mt-0.5 shrink-0 text-muted" />
                          <div className="min-w-0 flex-1">
                            <div className="truncate font-medium">{d.name}</div>
                            <div className="flex flex-wrap items-center gap-1.5 text-[12px] text-muted">
                              <span className="num">{d.check}</span><MarketChip m={d.market} />
                              {d.untrusted && <Badge tone="warn">Untrusted</Badge>}
                            </div>
                          </div>
                          <button type="button" aria-label={`Remove ${d.name}`} onClick={() => remove.mutate(d.name)} className="text-muted hover:text-ink"><X size={14} /></button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </Panel>
            </div>
          </div>
        </TabPanel>
        <TabPanel value="library"><LibraryTab market={market} /></TabPanel>
      </Tabs>
    </FactsProvider>
  );
}
