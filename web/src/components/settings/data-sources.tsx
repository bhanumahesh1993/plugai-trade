/* Settings › Data Sources parts: source cards, the drag-and-drop fallback strip, Compare sources. */
import { useEffect, useRef, useState, type DragEvent, type KeyboardEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, ExternalLink, GripVertical, KeyRound, PlugZap, Plus, RotateCcw, X, ArrowLeft, Save } from "lucide-react";
import { post, type Market } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button, Field, Panel, inputCls } from "@/components/ui";
import { Badge, Callout, DataTable, Select, Switch, useToast } from "@/components/kit";
import { ExplainPanel, FactTile } from "@/components/facts";
import { ErrorLine, Meta, StatusDot, TextInput } from "./common";

export interface Source {
  name: string; label: string; tier: string; description: string; needs: string; license_class: string; markets: string[];
  set_up: boolean; working: boolean; last_test: { ok: boolean; message: string; at: string } | null;
  key_fields: { key: string; label: string; saved: boolean }[]; connect_url: string | null; testable: boolean;
  live_capable: boolean; live: { on: boolean; symbols: string[] }; remind: { at: string } | null;
  expiry: { expires: string; days_left: number; expired: boolean } | null; for_market: boolean;
}
export interface Strip { key: string; head: string; chain: { name: string; label: string; active: boolean }[]; text: string; is_default: boolean }
export interface DS {
  market: Market; tiers: { tier: string; sources: Source[] }[]; paid_brokers: string; strips: Strip[]; known_keys: string[];
  edgar_contact: string; licence_note: string[]; alpaca_free_symbols: number; watchlists: Record<Market, string[]>;
  working: number; total: number;
  compare: { symbol: string; a: string; b: string; start: string; end: string; sources: { name: string; label: string }[] };
}
interface Probe { ok: boolean; message: string; frames: { what: string; tag: string; license_class: string; columns: string[]; rows: Record<string, unknown>[] }[]; facts: string[] }

const KEY = ["data-sources"];

function expiryText(e: NonNullable<Source["expiry"]>) {
  return e.expired ? `Token expired ${e.expires}` : `Token: ${e.days_left} days left (to ${e.expires})`;
}

/* ------------------------------------------------------------ live stream + remind me */
function LiveControls({ s, d }: { s: Source; d: DS }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [add, setAdd] = useState("");
  const live = useMutation({
    mutationFn: (b: { on: boolean; symbols?: string[] }) => post(`/api/settings/data-sources/${s.name}/live`, b),
    onSuccess: (_r, b) => { qc.invalidateQueries({ queryKey: KEY }); qc.invalidateQueries({ queryKey: ["status"] }); if (b.symbols === undefined) toast(b.on ? `Live stream on for ${s.label}` : `Live stream off for ${s.label}`); },
  });
  const [at, setAt] = useState(s.remind?.at ?? "08:55");
  const remind = useMutation({
    mutationFn: () => post(`/api/settings/data-sources/${s.name}/remind`, { at }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: KEY }); toast(`Remind me set for ${at} IST`); },
  });
  const syms = s.live.symbols;
  const setSyms = (x: string[]) => live.mutate({ on: true, symbols: x });
  const cap = s.name === "alpaca" ? d.alpaca_free_symbols : null;
  return (
    <div className="flex flex-col gap-2 border-t border-line pt-3">
      {s.live_capable && <Switch checked={s.live.on} onChange={(on) => live.mutate({ on })} label="Live stream" hint="Outside market hours, Test connection shows the last recorded bar." />}
      {s.live_capable && s.live.on && (
        <div className="flex flex-col gap-1.5">
          <span className="text-[12px] text-muted">Symbols to stream</span>
          <div className="flex flex-wrap items-center gap-1.5">
            {syms.map((x) => (
              <span key={x} className="inline-flex h-7 items-center gap-1 rounded-[4px] border border-line bg-panel-2 pl-2 pr-1 text-[13px]">
                {x}<button type="button" aria-label={`Remove ${x}`} className="rounded p-0.5 text-muted hover:text-ink" onClick={() => setSyms(syms.filter((y) => y !== x))}><X size={12} /></button>
              </span>
            ))}
            <form className="flex gap-1" onSubmit={(e) => { e.preventDefault(); if (add.trim()) { setSyms([...syms, add.trim().toUpperCase()]); setAdd(""); } }}>
              <input aria-label="Add a symbol" className={cn(inputCls, "h-7 w-28 font-sans text-[13px]")} placeholder="Add symbol" value={add} onChange={(e) => setAdd(e.target.value)} />
              <Button size="sm" type="submit" disabled={!add.trim()}>Add</Button>
            </form>
          </div>
          {cap !== null && <span className={cn("num text-[12px]", syms.length > cap ? "text-bear" : "text-muted")}>{syms.length} of {cap} free IEX symbols used{syms.length > cap ? ". Alpaca's free plan streams at most 30 symbols." : ""}</span>}
        </div>
      )}
      {s.remind && (
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Remind me" hint="This broker's login expires daily; get a nudge before the open (08:55 IST works for most traders).">
            <input type="time" className={cn(inputCls, "w-32")} value={at} onChange={(e) => setAt(e.target.value)} />
          </Field>
          <Button size="sm" className="mb-[22px] h-9" onClick={() => remind.mutate()} disabled={remind.isPending || at === s.remind.at}>Save reminder</Button>
        </div>
      )}
      <ErrorLine error={live.error ?? remind.error} />
    </div>
  );
}

/* ------------------------------------------------------------ one source */
export function SourceCard({ s, d, market }: { s: Source; d: DS; market: Market }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [connect, setConnect] = useState(false);
  const [vals, setVals] = useState<Record<string, string>>({});
  const [contact, setContact] = useState(d.edgar_contact);
  const save = useMutation({
    mutationFn: () => post<{ message: string }>(`/api/settings/data-sources/${s.name}/keys`, { values: vals }),
    onSuccess: (r) => { setVals({}); setConnect(false); qc.invalidateQueries({ queryKey: KEY }); toast(`${r.message} to the keychain`); },
  });
  const test = useMutation({
    mutationFn: () => post<Probe>(`/api/settings/data-sources/${s.name}/test`, { market }),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: KEY }); toast(r.ok ? `Tested the connection: ${r.message}` : `Test connection failed: ${r.message}`, r.ok ? "ok" : "danger"); },
  });
  const saveContact = useMutation({
    mutationFn: () => post("/api/settings/data-sources/edgar-contact", { contact }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: KEY }); toast("Saved the EDGAR contact. It is sent only to sec.gov, in the User-Agent header."); },
  });
  const extra = s.name === "upstox" && s.expiry ? expiryText(s.expiry) : null;
  return (
    <div className={cn("rounded-[var(--radius-tile)] border bg-panel", open ? "border-line-strong" : "border-line", !s.for_market && "opacity-80")}>
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="flex w-full items-center gap-2.5 px-3 py-2.5 text-left">
        <StatusDot on={s.working} label={s.working ? "Working" : s.set_up ? "Set up, last test failed" : "Not set up"} />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium">{s.label}</span>
          {extra && <span className={cn("block text-[12px]", s.expiry?.expired || (s.expiry?.days_left ?? 99) < 15 ? "text-bear" : "text-muted")}>{extra}</span>}
        </span>
        {s.set_up && s.last_test && !s.last_test.ok && <Badge tone="bear">Test failed</Badge>}
        {open ? <ChevronDown size={15} className="text-muted" /> : <ChevronRight size={15} className="text-muted" />}
      </button>
      {open && (
        <div className="flex flex-col gap-3 border-t border-line px-3 pb-3 pt-2.5 text-[13px]">
          <p>{s.description}</p>
          <Meta items={[["Needs", s.needs], ["Licence", s.license_class], ["Markets", s.markets.join(", ")]]} />
          {s.last_test && <p className="text-muted">Last test {s.last_test.at.slice(0, 16).replace("T", " ")} UTC: {s.last_test.ok ? "working" : s.last_test.message}</p>}

          {s.key_fields.length > 0 && !connect && (
            <div><Button size="sm" variant={s.set_up ? "outline" : "primary"} onClick={() => setConnect(true)}><PlugZap size={13} /> {s.set_up ? "Connect again" : "Connect"}</Button></div>
          )}
          {connect && (
            <div className="flex flex-col gap-2.5 rounded-[6px] border border-line bg-panel-2 p-3">
              {s.connect_url && <a href={s.connect_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-indigo hover:underline">Open the {s.label} page <ExternalLink size={12} /></a>}
              <p className="text-muted">Paste here, never into a chatbot. Stored in your OS keychain; only the last four characters are shown.</p>
              {s.key_fields.map((f) => (
                <TextInput key={f.key} label={f.label + (f.saved ? " (saved; paste to replace)" : "")} type="password" value={vals[f.key] ?? ""} onChange={(v) => setVals({ ...vals, [f.key]: v })} />
              ))}
              <div className="flex gap-2">
                <Button size="sm" variant="primary" onClick={() => save.mutate()} disabled={save.isPending || !Object.values(vals).some((v) => v.trim())}><KeyRound size={13} /> Save to keychain</Button>
                <Button size="sm" variant="quiet" onClick={() => { setConnect(false); setVals({}); }}>Cancel</Button>
              </div>
              <ErrorLine error={save.error} />
            </div>
          )}

          {s.name === "sec_edgar" && (
            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-[200px] flex-1"><TextInput label="EDGAR contact (name and email)" hint="The SEC asks every program to identify itself." value={contact} onChange={setContact} placeholder="Your Name you@example.com" /></div>
              <Button size="sm" className="mb-[22px] h-9" onClick={() => saveContact.mutate()} disabled={saveContact.isPending}>Save contact</Button>
            </div>
          )}

          {s.testable && (
            <div className="flex flex-col gap-2">
              <div><Button size="sm" onClick={() => test.mutate()} disabled={test.isPending}>{test.isPending ? `Asking ${s.label} for a small sample…` : "Test connection"}</Button></div>
              {test.data && (
                <div className="flex flex-col gap-2">
                  <p className={cn("font-medium", test.data.ok ? "text-bull" : "text-bear")}>{test.data.message}</p>
                  {test.data.frames.map((f) => (
                    <div key={f.what} className="flex flex-col gap-1">
                      <span className="text-muted">{f.what}, tag <span className="font-medium text-ink">{f.tag}</span>, licence {f.license_class}</span>
                      <DataTable rows={f.rows} columns={f.columns.filter((c) => !["fetched_at", "license_class"].includes(c)).map((c) => ({ key: c, header: c, align: typeof f.rows[0]?.[c] === "number" ? "right" as const : "left" as const }))} />
                    </div>
                  ))}
                </div>
              )}
              <ErrorLine error={test.error} />
            </div>
          )}
          {(s.live_capable || s.remind) && <LiveControls s={s} d={d} />}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------ + Add key */
export function AddKey({ known }: { known: string[] }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(known[0]);
  const [value, setValue] = useState("");
  const save = useMutation({
    mutationFn: () => post<{ message: string }>("/api/settings/data-sources/add-key", { name, value }),
    onSuccess: (r) => { setValue(""); setOpen(false); qc.invalidateQueries({ queryKey: KEY }); toast(`${r.message} to the keychain`); },
  });
  if (!open) return <Button size="sm" variant="quiet" className="self-start" onClick={() => setOpen(true)}><Plus size={14} /> Add key</Button>;
  return (
    <div className="flex flex-col gap-2.5 rounded-[var(--radius-tile)] border border-dashed border-line-strong p-3">
      <Field label="Key"><Select className="font-sans" value={name} onChange={(e) => setName(e.target.value)}>{known.map((k) => <option key={k}>{k}</option>)}</Select></Field>
      <TextInput label="Value" type="password" value={value} onChange={setValue} />
      <div className="flex gap-2">
        <Button size="sm" variant="primary" onClick={() => save.mutate()} disabled={save.isPending || !value.trim()}><KeyRound size={13} /> Save to keychain</Button>
        <Button size="sm" variant="quiet" onClick={() => setOpen(false)}>Cancel</Button>
      </div>
      <ErrorLine error={save.error} />
    </div>
  );
}

/* ------------------------------------------------------------ fallback strip (drag and drop) */
export function FallbackStrip({ strip }: { strip: Strip }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [order, setOrder] = useState(strip.chain);
  const [drag, setDrag] = useState<number | null>(null);
  const [over, setOver] = useState<number | null>(null);
  const refs = useRef<(HTMLLIElement | null)[]>([]);
  useEffect(() => setOrder(strip.chain), [strip]);
  const save = useMutation({
    mutationFn: (b: { chain?: string[]; reset?: boolean }) => post<Strip>("/api/settings/data-sources/fallback", { key: strip.key, ...b }),
    onSuccess: (r, b) => { qc.invalidateQueries({ queryKey: KEY }); toast(b.reset ? `Reset the ${strip.head} strip` : `Reordered the ${strip.head} strip: ${r.chain[0]?.label} first`); },
    onError: () => setOrder(strip.chain),
  });
  const move = (from: number, to: number) => {
    if (from === to || to < 0 || to >= order.length) return;
    const next = [...order];
    const [x] = next.splice(from, 1);
    next.splice(to, 0, x);
    setOrder(next);
    save.mutate({ chain: next.map((n) => n.name) });
    return next;
  };
  const onDrop = (e: DragEvent, i: number) => { e.preventDefault(); if (drag !== null) move(drag, i); setDrag(null); setOver(null); };
  const onKey = (e: KeyboardEvent, i: number) => {
    const to = e.key === "ArrowLeft" || e.key === "ArrowUp" ? i - 1 : e.key === "ArrowRight" || e.key === "ArrowDown" ? i + 1 : e.key === "Home" ? 0 : null;
    if (to === null) return;
    e.preventDefault();
    if (move(i, to)) setTimeout(() => refs.current[to]?.focus(), 0);
  };
  return (
    <div className="flex flex-col gap-2 border-b border-line py-3 last:border-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[13px] font-medium">{strip.head}</span>
        <span className="text-[12px] text-muted">In use: {strip.text}</span>
        {!strip.is_default && <Button size="sm" variant="quiet" className="ml-auto" onClick={() => save.mutate({ reset: true })} disabled={save.isPending}><RotateCcw size={13} /> Reset</Button>}
      </div>
      <ol className="flex flex-wrap items-center gap-1.5" aria-label={`${strip.head} fallback order`}>
        {order.map((n, i) => (
          <li key={n.name} ref={(el) => { refs.current[i] = el; }} draggable tabIndex={0}
            aria-label={`${n.label}, position ${i + 1} of ${order.length}${n.active ? "" : ", not set up"}. Arrow keys move it.`}
            onDragStart={(e) => { setDrag(i); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", n.name); }}
            onDragOver={(e) => { e.preventDefault(); setOver(i); }}
            onDragLeave={() => setOver((o) => (o === i ? null : o))}
            onDrop={(e) => onDrop(e, i)} onDragEnd={() => { setDrag(null); setOver(null); }}
            onKeyDown={(e) => onKey(e, i)}
            className={cn("flex h-8 cursor-grab select-none items-center gap-1.5 rounded-[6px] border bg-panel pl-1 pr-2.5 text-[13px] active:cursor-grabbing",
              n.active ? "border-line-strong" : "border-dashed border-line text-muted",
              drag === i && "opacity-40", over === i && drag !== null && drag !== i && "border-indigo ring-2 ring-indigo/30")}>
            <GripVertical size={13} className="text-muted" aria-hidden />
            <span className="num text-[11px] text-muted">{i + 1}</span>
            <StatusDot on={n.active} label={n.active ? "Set up" : "Not set up"} />
            {n.label}
          </li>
        ))}
      </ol>
      <ErrorLine error={save.error} />
    </div>
  );
}

/* ------------------------------------------------------------ Compare sources */
interface CmpRow { date: string; close_a: number | null; close_b: number | null; diff: number | null; status: "ok" | "missing" | "disagree"; [k: string]: unknown }
interface Prov { close: number; source: string; fetched_at: string; license_class: string }
interface Cmp {
  summary: string; symbol: string; market: Market; source_a: string; source_b: string; rows_compared: number; missing: number; disagree: number;
  table: CmpRow[]; provenance: Record<string, { A: Prov | null; B: Prov | null }>; facts: string[];
}

export function CompareSources({ d, market, onBack }: { d: DS; market: Market; onBack: () => void }) {
  const toast = useToast();
  const [f, setF] = useState({ symbol: d.compare.symbol, start: d.compare.start, end: d.compare.end, source_a: d.compare.a, source_b: d.compare.b });
  useEffect(() => setF({ symbol: d.compare.symbol, start: d.compare.start, end: d.compare.end, source_a: d.compare.a, source_b: d.compare.b }), [market]); // eslint-disable-line react-hooks/exhaustive-deps
  const [sel, setSel] = useState<string | null>(null);
  const run = useMutation({ mutationFn: () => post<Cmp>("/api/settings/data-sources/compare", { ...f, market }), onSuccess: () => setSel(null) });
  const save = useMutation({ mutationFn: () => post("/api/settings/data-sources/compare/save"), onSuccess: () => toast("Saved to journal with today's date") });
  const r = run.data;
  const names = d.compare.sources;
  const opt = (v: string) => names.some((n) => n.name === v) ? v : names[0]?.name;
  const prov = sel && r ? r.provenance[sel] : null;
  return (
    <div className="flex flex-col gap-5">
      <div><Button variant="quiet" onClick={onBack}><ArrowLeft size={15} /> Back to Data Sources</Button></div>
      <Panel title="Compare sources">
        <div className="grid gap-3 md:grid-cols-[1fr_150px_150px_1fr_1fr_auto] md:items-end">
          <TextInput label="Symbol" value={f.symbol} onChange={(v) => setF({ ...f, symbol: v.toUpperCase() })} />
          <Field label="From"><input type="date" className={inputCls} value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} /></Field>
          <Field label="To"><input type="date" className={inputCls} value={f.end} onChange={(e) => setF({ ...f, end: e.target.value })} /></Field>
          <Field label="Source A"><Select className="font-sans" value={opt(f.source_a)} onChange={(e) => setF({ ...f, source_a: e.target.value })}>{names.map((n) => <option key={n.name} value={n.name}>{n.label}</option>)}</Select></Field>
          <Field label="Source B"><Select className="font-sans" value={opt(f.source_b)} onChange={(e) => setF({ ...f, source_b: e.target.value })}>{names.map((n) => <option key={n.name} value={n.name}>{n.label}</option>)}</Select></Field>
          <Button variant="primary" onClick={() => run.mutate()} disabled={run.isPending}>{run.isPending ? "Running…" : "Run"}</Button>
        </div>
        {run.error && <div className="mt-3"><Callout tone="danger" title="Could not compare">{(run.error as Error).message}. Pick a source that works offline (Synthetic), or Test connection on the source first.</Callout></div>}
      </Panel>
      {!r && !run.error && <p className="text-muted">Choose a symbol, a date range and two sources, then click Run. Flagged rows are the ones to check.</p>}
      {r && (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
          <div className="flex min-w-0 flex-col gap-4">
            <p className="text-[15px] font-medium">{r.summary}</p>
            <Panel title={`${r.symbol}: ${r.source_a} against ${r.source_b}`} action={<span className="text-[12px] text-muted">Click a row to see both values and their tags</span>}>
              <div className="scroll-thin max-h-[440px] overflow-auto">
                <table className="w-full text-[14px]">
                  <thead className="sticky top-0 bg-panel"><tr className="border-b border-line text-left text-[12px] text-muted">
                    <th className="pb-2 pr-3 font-normal">Date</th><th className="pb-2 pr-3 text-right font-normal">Close A</th><th className="pb-2 pr-3 text-right font-normal">Close B</th>
                    <th className="pb-2 pr-3 text-right font-normal">Gap</th><th className="pb-2 font-normal">Status</th></tr></thead>
                  <tbody>
                    {r.table.map((row) => (
                      <tr key={row.date} onClick={() => setSel(row.date)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && setSel(row.date)}
                        className={cn("cursor-pointer border-b border-line last:border-0 hover:bg-panel-2", row.status !== "ok" && "bg-saffron/10", sel === row.date && "outline outline-2 -outline-offset-2 outline-indigo")}>
                        <td className="num py-1.5 pr-3">{row.date}</td>
                        <td className="num py-1.5 pr-3 text-right">{row.close_a?.toFixed(2) ?? "—"}</td>
                        <td className="num py-1.5 pr-3 text-right">{row.close_b?.toFixed(2) ?? "—"}</td>
                        <td className="num py-1.5 pr-3 text-right">{row.diff == null ? "—" : `${(row.diff * 100).toFixed(2)}%`}</td>
                        <td className="py-1.5">{row.status === "ok" ? <span className="text-muted">ok</span> : <Badge tone="warn">{row.status === "missing" ? "Missing" : "Over 0.5%"}</Badge>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {prov && (
                <div className="mt-3 grid gap-2 border-t border-line pt-3 text-[13px] md:grid-cols-2">
                  {(["A", "B"] as const).map((side) => {
                    const p = prov[side];
                    return (
                      <div key={side} className="rounded-[6px] border border-line bg-panel-2 p-2.5">
                        <div className="font-medium">Source {side}: {side === "A" ? r.source_a : r.source_b}, {sel}</div>
                        {p ? <Meta items={[["Close", <span key="c" className="num">{p.close?.toFixed(2)}</span>], ["Tag", p.source], ["Fetched", p.fetched_at], ["Licence", p.license_class]]} />
                          : <span className="text-muted">No bar on this date</span>}
                      </div>
                    );
                  })}
                </div>
              )}
            </Panel>
            <div><Button onClick={() => save.mutate()} disabled={save.isPending}><Save size={14} /> Save to journal</Button><ErrorLine error={save.error} /></div>
          </div>
          <div className="flex flex-col gap-4">
            <div className="grid grid-cols-2 gap-2.5">
              <div className="col-span-2"><FactTile big label="Rows compared" value={r.rows_compared} sub={`${r.source_a} against ${r.source_b}`} /></div>
              <FactTile label="Missing dates" value={r.missing} />
              <FactTile label="Rows over 0.5%" value={r.disagree} />
            </div>
            <Panel title="Explain the flags">
              <ExplainPanel facts={r.facts} section="Research"
                question="Describe the likely cause of each flagged row (missing session, stale value, adjustment) using only these facts. Do not calculate anything." />
            </Panel>
          </div>
        </div>
      )}
    </div>
  );
}
