/* Tax Export, India tabs: Classify / Turnover / AIS check / Export (Chapter 32, Chapter 25 VDA). */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { get, post } from "@/lib/api";
import { money } from "@/lib/format";
import { Button, Panel, Field, Tabs, TabList, Tab, TabPanel, inputCls } from "@/components/ui";
import { Badge, DataTable, EmptyState, Segmented, Select, Switch, useToast, type Column } from "@/components/kit";
import { LocalExplainPanel, Tile } from "./local";
import { Disclosure, FilePick, MismatchTable, RowsTable, downloadText, plain, readB64, toneOf, type Rec } from "./common";

interface Classified {
  counts: { bucket: string; name: string; full: string; n: number }[]; rows: Record<string, unknown>[]; excluded_simulated: number;
  facts: string[]; section_map: Record<string, unknown>[]; fys: string[]; tds_rec: Rec | null;
  vda: { gains: number; losses: number; tds: number; rows: Record<string, unknown>[]; facts: string[] } | null;
}
interface Turnover {
  fo: { trades: number; gains: number; losses: number; net: number; turnover: number }; speculative: { turnover: number };
  per_contract_fo: number; old_method_fo: number; notional_fo: number; deemed_profit: number; annualised: number;
  audit: { status: string; detail: string; lock_in: string; lock_short: string }; carry_forward: number; presumptive_note: string;
  threshold_source: string; as_of: string; per_trade: Record<string, unknown>[]; facts: string[];
  ledger: { rows: Record<string, unknown>[]; facts: string[] }; suggested_losses: { fy: string; bucket: string; amount: number }[];
}
interface State { rows: number; as_of: string; loss_buckets: string[]; draft: string }

const inr = (x: number | null | undefined, d = 0) => money(x, "IN", d);
const BUCKET_LABEL: Record<string, string> = { SPECULATIVE: "Speculative", NON_SPECULATIVE: "Non-speculative (F&O)", STCG: "STCG", LTCG: "LTCG", VDA: "VDA", "ASK CA": "ASK CA" };

const clsCols: Column<Record<string, unknown>>[] = [
  { key: "trade_id", header: "Row", align: "right" },
  { key: "fy", header: "FY" },
  { key: "symbol", header: "Symbol" },
  { key: "side", header: "Side" },
  { key: "gross", header: "Gross", align: "right", render: (r) => <span className={toneOf(r.gross)}>{inr(r.gross as number)}</span> },
  { key: "bucket", header: "Bucket", render: (r) => r.bucket === "ASK CA" ? <Badge tone="warn">ASK CA</Badge> : BUCKET_LABEL[String(r.bucket)] ?? String(r.bucket) },
  { key: "rule", header: "Rule that put it there", render: (r) => <span className="text-[13px]">{String(r.rule ?? "")}</span> },
  { key: "section_old", header: "1961 Act" },
  { key: "section_new", header: "2025 Act" },
];

/* ------------------------------------------------------------ Classify */
function ClassifyTab({ c, onClassify, pending, rows }: { c: Classified | null; onClassify: () => void; pending: boolean; rows: number }) {
  const qc = useQueryClient();
  const [tds, setTds] = useState<File | null>(null);
  const rec = useMutation({
    mutationFn: async () => post<Rec>("/api/tax/in/reconcile-tds", { market: "IN", file_b64: await readB64(tds!) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tax-classified"] }),
  });
  const tdsRec = rec.data ?? c?.tds_rec ?? null;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" onClick={onClassify} disabled={pending || !rows}>{pending ? "Classifying…" : "Classify"}</Button>
        {!c && <span className="text-[13px] text-muted">{rows ? "Click Classify: each round trip gets a bucket and the rule that put it there." : "Load rows first: Import tradebook above, or a lesson sample."}</span>}
      </div>
      {c && (
        <>
          <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3 xl:grid-cols-6">
            {c.counts.map((b) => <Tile key={b.bucket} label={b.name} keys={[b.full]} value={b.n} tone={b.bucket === "ASK CA" && b.n ? "warn" : undefined} />)}
          </div>
          <div className="max-h-[380px] overflow-y-auto scroll-thin"><DataTable rows={c.rows} columns={clsCols} empty="No rows classified." /></div>
          {c.excluded_simulated > 0 && <p className="text-[13px] text-muted">{c.excluded_simulated} PAPER / REPLAY / BLOCKED rows left out.</p>}
          <Disclosure summary="Old and new section numbers (1961 Act and Income-tax Act 2025)">
            <RowsTable rows={c.section_map} />
            <p className="mt-2 text-[12px] text-muted">As printed in Chapter 32 (Sep 2026). Cross-check against the bare Act.</p>
          </Disclosure>
          {c.vda && (
            <Panel title="India VDA ledger" action={<span className="text-[12px] text-muted">gains and losses kept apart, never netted</span>}>
              <div className="flex flex-col gap-4">
                <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
                  <Tile label="Gains" value={inr(c.vda.gains)} tone="bull" keys={["vda gains"]} />
                  <Tile label="Losses (no set-off)" value={inr(c.vda.losses)} tone="bear" keys={["vda losses"]} />
                  <Tile label="Taxable VDA income" value={inr(c.vda.gains)} big />
                  <Tile label="TDS 1% (credit)" value={inr(c.vda.tds)} keys={["tds deducted"]} />
                </div>
                <RowsTable rows={c.vda.rows} headers={{ trade_id: "Row" }} />
                <div className="flex flex-wrap items-end gap-3">
                  <FilePick label="Form 26AS / AIS TDS rows (CSV)" file={tds} onFile={setTds} />
                  <Button onClick={() => rec.mutate()} disabled={!tds || rec.isPending}>Reconcile TDS</Button>
                </div>
                {rec.error && <p className="text-[13px] text-bear">{(rec.error as Error).message}</p>}
                {tdsRec && <MismatchTable rec={tdsRec} />}
              </div>
            </Panel>
          )}
          <LocalExplainPanel facts={[...c.facts, ...(c.vda?.facts ?? [])]} section="Tax" />
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------ Turnover */
function TurnoverTab({ classified, st }: { classified: boolean; st?: State }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [months, setMonths] = useState(12);
  const [opted, setOpted] = useState("");
  const { data: t, error } = useQuery({
    queryKey: ["tax-turnover", months, opted], enabled: classified, placeholderData: keepPreviousData,
    queryFn: () => get<Turnover>(`/api/tax/in/turnover?market=IN&months=${months}&opted=${encodeURIComponent(opted)}`),
  });
  const [loss, setLoss] = useState({ fy: "2025-26", bucket: "SPECULATIVE", amount: "", on_time: true });
  const refresh = () => qc.invalidateQueries({ queryKey: ["tax-turnover"] });
  const add = useMutation({ mutationFn: () => post("/api/tax/in/ledger/add", { ...loss, amount: Number(loss.amount) }), onSuccess: () => { toast("Loss added to the carry-forward ledger"); setLoss({ ...loss, amount: "" }); refresh(); } });
  const fromRows = useMutation({ mutationFn: () => post<{ added: number }>("/api/tax/in/ledger/from-classified?market=IN"), onSuccess: (d) => { toast(`Added ${d.added} losses from the classified rows`); refresh(); } });
  if (!classified) return <EmptyState>Classify first: open the Classify tab and click Classify.</EmptyState>;
  if (error) return <p className="text-bear">{(error as Error).message}</p>;
  if (!t) return <div className="h-40" />;
  return (
    <div className="flex flex-col gap-5">
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Months in these rows (to annualise for the audit check)">
          <input type="number" min={1} max={12} className={inputCls} value={months} onChange={(e) => setMonths(Math.min(12, Math.max(1, Number(e.target.value) || 1)))} />
        </Field>
        <Field label="Year you opted for s.44AD / s.58, if ever (e.g. 2024-25)">
          <input className={inputCls} value={opted} onChange={(e) => setOpted(e.target.value)} placeholder="Never" />
        </Field>
      </div>
      <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3">
        <Tile label="F&O turnover (ICAI)" keys={["f&o turnover (icai"]} value={inr(t.fo.turnover)} big sub="Σ |P&L| per trade" />
        <Tile label="F&O net result" keys={["f&o round trips", "f&o gains"]} value={inr(t.fo.net)} tone={t.fo.net > 0 ? "bull" : t.fo.net < 0 ? "bear" : undefined} sub={`${t.fo.trades} round trips`} />
        <Tile label="Audit check" keys={["audit check", "turnover tested"]} value={t.audit.status} tone={t.audit.status.startsWith("Audit") ? "warn" : undefined} sub={t.audit.detail} />
        <Tile label="Per-contract view" value={inr(t.per_contract_fo)} sub="Zerodha's segment-wise method; use tradewise for filing" />
        <Tile label="s.58 / 44AD status" keys={["s.58 / 44ad"]} value={t.audit.lock_short} sub={t.audit.lock_in !== t.audit.lock_short ? t.audit.lock_in : undefined} />
        <Tile label="Carry forward" value={inr(t.carry_forward)} sub="if filed on time" />
      </div>
      <div className="flex flex-col gap-1 text-[13px] text-muted">
        <p className="num">Speculative turnover (kept separate): {inr(t.speculative.turnover)}. Pre-2022 method {inr(t.old_method_fo)}. Notional (not turnover) {inr(t.notional_fo)}.</p>
        <p>{t.presumptive_note}</p>
        <p>Audit thresholds from the dated table (as of {t.as_of}; ₹1 crore limit: {t.threshold_source}).</p>
      </div>
      <Disclosure summary={`Turnover per trade (${t.per_trade.length} rows)`}>
        <RowsTable rows={t.per_trade} headers={{ trade_id: "Row", abs_pnl: "|P&L|", pnl: "P&L" }} />
      </Disclosure>
      <LocalExplainPanel facts={t.facts} section="Tax" />

      <Panel title="Carry-forward ledger" action={<span className="text-[12px] text-muted">one line per year per bucket</span>}>
        <div className="flex flex-col gap-3">
          <div className="grid items-end gap-3 md:grid-cols-[1fr_1.4fr_1fr_auto_auto]">
            <Field label="Tax year (FY)"><input className={inputCls} value={loss.fy} onChange={(e) => setLoss({ ...loss, fy: e.target.value })} /></Field>
            <Field label="Bucket">
              <Select value={loss.bucket} onChange={(e) => setLoss({ ...loss, bucket: e.target.value })}>
                {(st?.loss_buckets ?? ["SPECULATIVE", "NON_SPECULATIVE", "STCL", "LTCL"]).map((b) => <option key={b}>{b}</option>)}
              </Select>
            </Field>
            <Field label="Loss (₹)"><input type="number" min={0} step={1000} className={inputCls} value={loss.amount} onChange={(e) => setLoss({ ...loss, amount: e.target.value })} /></Field>
            <div className="pb-0.5"><Switch checked={loss.on_time} onChange={(v) => setLoss({ ...loss, on_time: v })} label="Return filed on time" /></div>
            <Button onClick={() => add.mutate()} disabled={!Number(loss.amount) || add.isPending}>Add loss</Button>
          </div>
          {add.error && <p className="text-[13px] text-bear">{(add.error as Error).message}</p>}
          {t.suggested_losses.length > 0 && (
            <div><Button variant="quiet" onClick={() => fromRows.mutate()} disabled={fromRows.isPending}>Add this year's losses from the classified rows</Button></div>
          )}
          <RowsTable rows={t.ledger.rows} headers={{ fy: "FY", expires_after_fy: "Carries to FY" }} empty="No losses recorded yet. Add last year's losses above." />
          <p className="text-[12px] text-muted">Speculative: 4 years, speculative profit only. F&O: 8 years. Capital: 8 years. VDA: no set-off, no carry-forward (dated table).</p>
        </div>
      </Panel>
      <AdvancePlanner />
    </div>
  );
}

function AdvancePlanner() {
  const [a, setA] = useState({ est: 60000, fy: "2026-27", paid: 0 });
  const { data: p, error } = useQuery({
    queryKey: ["tax-advance", a], placeholderData: keepPreviousData,
    queryFn: () => get<{ rows: Record<string, unknown>[]; due: boolean; facts: string[] }>(`/api/tax/in/advance?estimated=${a.est}&fy=${encodeURIComponent(a.fy)}&paid=${a.paid}`),
  });
  return (
    <Panel title="Advance-tax planner">
      <div className="flex flex-col gap-3">
        <div className="grid gap-3 md:grid-cols-3">
          <Field label="Your estimated tax for the year (₹)"><input type="number" min={0} step={1000} className={inputCls} value={a.est} onChange={(e) => setA({ ...a, est: Number(e.target.value) || 0 })} /></Field>
          <Field label="Tax year"><input className={inputCls} value={a.fy} onChange={(e) => setA({ ...a, fy: e.target.value })} /></Field>
          <Field label="Paid so far (₹)"><input type="number" min={0} step={1000} className={inputCls} value={a.paid} onChange={(e) => setA({ ...a, paid: Number(e.target.value) || 0 })} /></Field>
        </div>
        {error && <p className="text-[13px] text-bear">{(error as Error).message}</p>}
        {p && <RowsTable rows={p.rows} headers={{ cumulative_pct: "Cumulative %" }} />}
        {p && !p.due && <p className="text-[13px] text-muted">Below the advance-tax threshold: not due.</p>}
        {p && <LocalExplainPanel facts={p.facts} section="Tax" />}
      </div>
    </Panel>
  );
}

/* ------------------------------------------------------------ AIS check */
function AisTab({ classified }: { classified: boolean }) {
  const [broker, setBroker] = useState<File | null>(null);
  const [ais, setAis] = useState<File | null>(null);
  const [focus, setFocus] = useState<Record<string, unknown> | null>(null);
  const rec = useMutation({
    mutationFn: async () => post<Rec>("/api/tax/in/reconcile-ais", { market: "IN", ais_b64: await readB64(ais!), broker_b64: broker ? await readB64(broker) : null }),
    onSuccess: () => setFocus(null),
  });
  const r = rec.data;
  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 md:grid-cols-2">
        <FilePick label="Broker tax P&L (CSV), or leave empty to use the classified rows" file={broker} onFile={setBroker} />
        <FilePick label="AIS or Form 26AS export (CSV)" file={ais} onFile={setAis} />
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" onClick={() => rec.mutate()} disabled={!ais || (!broker && !classified) || rec.isPending}>Reconcile AIS</Button>
        {!broker && !classified && <span className="text-[13px] text-muted">Classify first, or choose your broker's tax P&L.</span>}
      </div>
      {rec.error && <p className="text-[13px] text-bear">{(rec.error as Error).message}</p>}
      {r && <MismatchTable rec={r} onExplain={setFocus} />}
      {r && (
        <LocalExplainPanel key={focus ? JSON.stringify(focus) : "all"} facts={r.facts} section="Tax"
          question={focus ? `Explain this mismatch row in plain English for my CA, and what record would settle it: ${focus.side}, ${focus.date}, ${focus.security}, ${plain(focus.amount)} (other side ${plain(focus.other_amount)}): ${focus.reason}` : undefined}
          label={focus ? `Explain ${String(focus.security)} ${String(focus.date)}` : "Explain"} />
      )}
    </div>
  );
}

/* ------------------------------------------------------------ Export */
function ExportTab({ fys, classified }: { fys: string[]; classified: boolean }) {
  const toast = useToast();
  const [fy, setFy] = useState("all");
  const exp = useMutation({ mutationFn: () => post<{ csv: string; filename: string; format: string }>("/api/tax/in/export", { market: "IN", fy }), onSuccess: () => toast("ITR-shaped CSV ready (Draft for your CA / CPA)") });
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col items-start gap-1">
        <span className="text-[12px] text-muted">Format</span>
        <Segmented label="Format" value="ITR-shaped CSV" options={["ITR-shaped CSV"] as const} onChange={() => {}} />
      </div>
      {!classified ? <EmptyState>Classify first: open the Classify tab and click Classify.</EmptyState> : (
        <>
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Tax year">
              <Select value={fy} onChange={(e) => setFy(e.target.value)} className="w-40">
                {["all", ...fys].map((f) => <option key={f}>{f}</option>)}
              </Select>
            </Field>
            <Button variant="primary" onClick={() => exp.mutate()} disabled={exp.isPending}>Export</Button>
            {exp.data && <Button onClick={() => downloadText(exp.data.filename, exp.data.csv)}><Download size={14} /> Download ITR-shaped CSV (Draft for your CA / CPA)</Button>}
          </div>
          {exp.error && <p className="text-[13px] text-bear">{(exp.error as Error).message}</p>}
          {exp.data && <pre className="scroll-thin num max-h-[320px] overflow-auto rounded-[var(--radius-tile)] border border-line bg-panel-2 p-3 text-[12px]">{exp.data.csv.slice(0, 1500)}</pre>}
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------ tabs */
export function IndiaTax({ st }: { st?: State }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { data } = useQuery({ queryKey: ["tax-classified"], queryFn: () => get<{ classified: Classified | null }>("/api/tax/in/classify?market=IN") });
  const classify = useMutation({
    mutationFn: () => post<Classified>("/api/tax/in/classify?market=IN"),
    onSuccess: (c) => { qc.setQueryData(["tax-classified"], { classified: c }); qc.invalidateQueries({ queryKey: ["tax-turnover"] }); toast(`Classified ${c.rows.length} rows`); },
  });
  const c = data?.classified ?? null;
  return (
    <Tabs defaultValue="classify">
      <TabList><Tab value="classify">Classify</Tab><Tab value="turnover">Turnover</Tab><Tab value="ais">AIS check</Tab><Tab value="export">Export</Tab></TabList>
      <TabPanel value="classify" className="pt-4"><ClassifyTab c={c} onClassify={() => classify.mutate()} pending={classify.isPending} rows={st?.rows ?? 0} /></TabPanel>
      <TabPanel value="turnover" className="pt-4"><TurnoverTab classified={!!c} st={st} /></TabPanel>
      <TabPanel value="ais" className="pt-4"><AisTab classified={!!c} /></TabPanel>
      <TabPanel value="export" className="pt-4"><ExportTab fys={c?.fys ?? []} classified={!!c} /></TabPanel>
    </Tabs>
  );
}
