import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, AlertTriangle, ExternalLink, ScanSearch } from "lucide-react";
import { get, post, type Market } from "@/lib/api";
import { Button, Field, Panel, MarketSwitch } from "@/components/ui";
import { Badge, Callout, DataTable, Segmented, Select, Textarea } from "@/components/kit";
import { CiteTarget, ExplainPanel, FactTile, FactsProvider } from "@/components/facts";
import { useMarket } from "@/components/shell";
import { DownloadButton, ErrorLine, Tick } from "@/components/settings/common";

interface Item { key: string; text: string; ok: boolean; detail: string; manual: boolean }
interface Sec { items: Item[]; score: string; passed: number; total: number; facts: string[]; reg_types: string[]; note: string; filters: string[] }
interface Pitch { flags: { kind: string; flag: string; quote: string }[]; names: string[]; compound: { pct: number; multiple: number }[]; ai_text: string; where: string; model: string; facts: string[] }
interface AuditRow { time: string; kind: string; category: string; detail: string; [k: string]: unknown }
const KEY = ["security"];

function Checklist({ s }: { s: Sec }) {
  const qc = useQueryClient();
  const tick = useMutation({ mutationFn: (b: { key: string; on: boolean }) => post<Sec>("/api/settings/security/tick", b), onSuccess: (d) => qc.setQueryData(KEY, d) });
  const auto = s.items.filter((i) => !i.manual), manual = s.items.filter((i) => i.manual);
  return (
    <Panel title="Security checklist" action={<span className="num text-[13px] text-muted">{s.score}</span>}>
      <ul className="flex flex-col divide-y divide-line">
        {auto.map((i) => (
          <li key={i.key} className="py-1 first:pt-0"><CiteTarget label={`${i.ok ? "✓" : "!"} ${i.text}`} className="flex items-start gap-2.5 px-1 py-1">
            {i.ok ? <CheckCircle2 size={17} className="mt-0.5 shrink-0 text-bull" aria-label="passed" /> : <AlertTriangle size={17} className="mt-0.5 shrink-0 text-saffron" aria-label="warning" />}
            <span><span className="font-medium">{i.text}</span><span className="block text-[13px] text-muted">{i.detail}</span></span>
          </CiteTarget></li>
        ))}
      </ul>
      <h3 className="mb-1 mt-4 text-[13px] font-medium text-muted">Only you can tick these; the lab cannot see them</h3>
      {manual.map((i) => <CiteTarget key={i.key} label={`${i.ok ? "✓" : "!"} ${i.text}`} className="px-1"><Tick checked={i.ok} disabled={tick.isPending} onChange={(on) => tick.mutate({ key: i.key, on })}>{i.text.replace(/ \(you\)$/, "")}</Tick></CiteTarget>)}
      <ErrorLine error={tick.error} />
    </Panel>
  );
}

function Registration({ s }: { s: Sec }) {
  const [top] = useMarket();
  const [mkt, setMkt] = useState<Market>(top);
  useEffect(() => setMkt(top), [top]);
  const [kind, setKind] = useState(s.reg_types[0]);
  const { data, error } = useQuery({
    queryKey: ["registers", mkt, kind],
    queryFn: () => get<{ registers: { name: string; url: string; covers: string }[] }>(`/api/settings/security/registers?market=${mkt}&kind=${encodeURIComponent(kind)}`),
  });
  return (
    <Panel title="Registration check">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Market"><MarketSwitch value={mkt} onChange={setMkt} /></Field>
        <Field label="Type"><Select className="w-48 font-sans" value={kind} onChange={(e) => setKind(e.target.value)}>{s.reg_types.map((t) => <option key={t}>{t}</option>)}</Select></Field>
      </div>
      <ul className="mt-3 flex flex-col gap-2">
        {data?.registers.map((r) => (
          <li key={r.name + r.url} className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <a href={r.url} target="_blank" rel="noreferrer" className="inline-flex h-8 items-center gap-1.5 rounded-[6px] border border-line-strong px-3 text-[13px] font-medium hover:border-indigo hover:text-indigo">
              Open {r.name} <ExternalLink size={13} />
            </a>
            <span className="text-[13px] text-muted">{r.covers}</span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-[13px] text-muted">{s.note}</p>
      <ErrorLine error={error} />
    </Panel>
  );
}

function CheckPitch() {
  const [text, setText] = useState("");
  const run = useMutation({ mutationFn: () => post<Pitch>("/api/settings/security/pitch", { text }) });
  const pc = run.data;
  return (
    <Panel title="Check a pitch">
      <div className="flex flex-col gap-3">
        <Field label="Paste the pitch, website text or terms (remove your personal details)">
          <Textarea className="min-h-[120px]" value={text} onChange={(e) => setText(e.target.value)} placeholder="Earn 3% a day with our SEBI-registered AI bot. Only 5 seats left…" />
        </Field>
        <div><Button variant="primary" onClick={() => run.mutate()} disabled={run.isPending || !text.trim()}><ScanSearch size={14} /> {run.isPending ? "Checking…" : "Check a pitch"}</Button></div>
        <ErrorLine error={run.error} />
        {pc && (
          <div className="flex flex-col gap-3">
            {pc.flags.length ? (
              <div className="flex flex-col gap-1">
                {pc.flags.map((f, i) => (
                  <CiteTarget key={i} label={f.kind} className="grid gap-x-3 border-b border-line px-2 py-2 last:border-0 md:grid-cols-[minmax(0,1fr)_110px_220px]">
                    <q className="font-serif text-[15px]">{f.quote}</q>
                    <span className="text-[13px] capitalize text-muted">{f.kind}</span>
                    <span className="text-[13px] font-medium">{f.flag}</span>
                  </CiteTarget>
                ))}
              </div>
            ) : <Callout tone="info">No red-flag phrases matched the scan. That is not a clean bill of health: check the register yourself.</Callout>}
            {pc.compound.map((c) => (
              <Callout key={c.pct} tone="danger" title="Calculator test">{c.pct}% a day for 250 trading days multiplies the stake by <span className="num font-semibold">{Math.round(c.multiple).toLocaleString("en-US")}</span>.</Callout>
            ))}
            {pc.names.length > 0 && <p className="text-[13px]"><span className="text-muted">Names, numbers and sites mentioned:</span> {pc.names.map((n) => <Badge key={n} className="mr-1">{n}</Badge>)}</p>}
            {pc.ai_text ? (
              <div className="rounded-[var(--radius-tile)] border border-line bg-panel-2 p-3.5">
                <div className="mb-1 text-[12px] text-muted">Model reading ({pc.where}, {pc.model})</div>
                <p className="whitespace-pre-line font-serif text-[15px] leading-[1.6]">{pc.ai_text}</p>
              </div>
            ) : <p className="text-[13px] text-muted">No model connected: the red-flag scan above is computed in code.</p>}
            <ExplainPanel facts={pc.facts} section="Research" />
          </div>
        )}
      </div>
    </Panel>
  );
}

function AuditLog({ s }: { s: Sec }) {
  const [f, setF] = useState("All");
  const { data, error } = useQuery({ queryKey: ["audit", f], queryFn: () => get<{ rows: AuditRow[] }>(`/api/settings/security/audit?filter=${f}`) });
  return (
    <Panel title="Audit log" action={<DownloadButton path={`/api/settings/security/export?filter=${f}`} name="plugai-trade-audit-log.csv" type="text/csv" label="Export log" done="Exported the audit log as plugai-trade-audit-log.csv" />}>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <Segmented label="Filter" value={f} options={s.filters} onChange={setF} />
        <span className="text-[13px] text-muted">{f === "Cloud" ? "Exactly what left your computer." : "Every key use, data fetch, AI call and MCP tool call."}</span>
      </div>
      <div className="scroll-thin max-h-[420px] overflow-auto">
        <DataTable rows={data?.rows ?? []} empty="Nothing logged for this filter yet." columns={[
          { key: "time", header: "Time", render: (r) => <span className="num whitespace-nowrap">{r.time.slice(0, 19).replace("T", " ")}</span> },
          { key: "kind", header: "Kind" },
          { key: "category", header: "Category", render: (r) => <Badge tone={r.category === "Cloud" ? "warn" : "neutral"}>{r.category}</Badge> },
          { key: "detail", header: "Detail", render: (r) => <span className="break-all text-[12px] text-muted">{r.detail}</span> },
        ]} />
      </div>
      <p className="mt-3 text-[13px] text-muted">Export the log once a month and keep the file with your journal. If anything in it surprises you, revoke the key concerned at your broker first, then investigate.</p>
      <ErrorLine error={error} />
    </Panel>
  );
}

export default function Security() {
  const { data: s, error } = useQuery({ queryKey: KEY, queryFn: () => get<Sec>("/api/settings/security") });
  if (error) return <Callout tone="danger" title="Security could not load">{(error as Error).message}</Callout>;
  if (!s) return <div className="min-h-[60vh]" aria-busy="true" />;
  const warn = s.items.filter((i) => !i.ok).length;
  return (
    <FactsProvider>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="flex min-w-0 flex-col gap-5">
          <p className="text-[13px] text-muted">The lab holds no money and places no orders; this page protects your keys, journal and accounts.</p>
          <Checklist s={s} />
          <Registration s={s} />
          <CheckPitch />
          <AuditLog s={s} />
        </div>
        <div className="flex flex-col gap-4 xl:sticky xl:top-0 xl:self-start">
          <FactTile big label="Security checklist" value={s.score} sub={warn ? `${warn} item${warn > 1 ? "s" : ""} to fix or tick` : "every item is done"} />
          <Panel title="Explain the checklist"><ExplainPanel facts={s.facts} section="Settings" /></Panel>
        </div>
      </div>
    </FactsProvider>
  );
}
