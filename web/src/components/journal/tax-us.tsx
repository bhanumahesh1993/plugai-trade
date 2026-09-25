/* Tax Export, US tabs: Classify / Wash sales / 1099-B check / Export (Chapter 32, Chapter 25 crypto). */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { get, post } from "@/lib/api";
import { money } from "@/lib/format";
import { Button, Panel, Field, Tabs, TabList, Tab, TabPanel, inputCls } from "@/components/ui";
import { Callout, EmptyState, Segmented, Select, Switch, useToast } from "@/components/kit";
import { LocalExplainPanel, Tile } from "./local";
import { FilePick, MismatchTable, RowsTable, downloadText, readB64, type Rec } from "./common";

interface State { rows: number; as_of: string; accounts: Record<string, string>; account_types: string[]; crypto_default: boolean; account_names: string[] }
interface Form { rows: Record<string, unknown>[]; form_6781: Record<string, unknown>[]; flags: string[]; excluded_ira: number; facts: string[]; short_total: number; long_total: number; net_1256: number }
interface Wash { hits: Record<string, unknown>[]; warnings: Record<string, unknown>[]; disallowed: number; crypto_checked: boolean; facts: string[]; form: Form | null }

const usd = (x: number | null | undefined, d = 2) => money(x, "US", d);
const HEAD: Record<string, string> = { loss_row: "Loss row", replacement_row: "Replacement row", days_from_sale: "Days from sale", new_basis: "New basis", sec_1256: "Section 1256", ask_ca: "ASK CA",
  date_acquired: "Acquired", date_sold: "Sold", cost_basis: "Cost basis", long_term_60: "60% long-term", short_term_40: "40% short-term" };

/* ------------------------------------------------------------ Classify (accounts + 1256) */
function ClassifyTab({ st }: { st?: State }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState(st?.account_names[0] ?? "Taxable");
  const [kind, setKind] = useState("Taxable");
  const add = useMutation({
    mutationFn: () => post<{ accounts: Record<string, string> }>("/api/tax/us/account", { name, kind }),
    onSuccess: () => { toast(`Account ${name} tagged ${kind}`); qc.invalidateQueries({ queryKey: ["tax-state"] }); },
  });
  const [show1256, setShow1256] = useState(false);
  const tags = useQuery({ queryKey: ["tax-1256", st?.rows], enabled: show1256, queryFn: () => get<{ rows: Record<string, unknown>[] }>("/api/tax/us/1256?market=US") });
  const accounts = Object.entries(st?.accounts ?? {});
  return (
    <div className="flex flex-col gap-5">
      <Panel title="Accounts" action={<span className="text-[12px] text-muted">tag each as Taxable, IRA or Spouse</span>}>
        <div className="flex flex-col gap-3">
          <div className="grid items-end gap-3 md:grid-cols-[1fr_1fr_auto]">
            <Field label="Account name">
              <input className={inputCls} list="tax-account-names" value={name} onChange={(e) => setName(e.target.value)} />
              <datalist id="tax-account-names">{st?.account_names.map((n) => <option key={n} value={n} />)}</datalist>
            </Field>
            <Field label="Type">
              <Select value={kind} onChange={(e) => setKind(e.target.value)}>{(st?.account_types ?? ["Taxable", "IRA", "Spouse"]).map((t) => <option key={t}>{t}</option>)}</Select>
            </Field>
            <Button onClick={() => add.mutate()} disabled={!name.trim() || add.isPending}>Add account</Button>
          </div>
          {add.error && <p className="text-[13px] text-bear">{(add.error as Error).message}</p>}
          <p className="text-[13px] text-muted">{accounts.length ? accounts.map(([n, t]) => `${n}: ${t}`).join("; ") : "No accounts tagged yet: untagged accounts count as Taxable."}</p>
        </div>
      </Panel>
      <div className="flex flex-col gap-3">
        <div><Button variant="primary" onClick={() => setShow1256(true)} disabled={!st?.rows}>1256 tagging</Button></div>
        {show1256 && tags.data && (
          <>
            <RowsTable rows={tags.data.rows} headers={HEAD} empty="No instruments loaded." />
            <p className="text-[12px] text-muted">The IRS publishes no product list: confirm with the 1099-B's regulated-futures section.</p>
          </>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ Wash sales */
function WashTab({ st, w, run, pending, error }: { st?: State; w?: Wash; run: (crypto: boolean, pairs: string) => void; pending: boolean; error: Error | null }) {
  const [crypto, setCrypto] = useState(st?.crypto_default ?? false);
  const [pairs, setPairs] = useState("");
  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 md:grid-cols-2">
        <Switch checked={crypto} onChange={setCrypto} label="Crypto wash-sale check" hint={`Default off: rules as of ${st?.as_of ?? "—"} (H.R. 9172 is not law).`} />
        <Field label="Pairs you consider possibly identical (e.g. SPY/VOO, QQQ/QQQM)">
          <input className={inputCls} value={pairs} onChange={(e) => setPairs(e.target.value)} placeholder="SPY/VOO" />
        </Field>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" onClick={() => run(crypto, pairs)} disabled={pending || !st?.rows}>Wash-sale check</Button>
        <Button onClick={() => run(crypto, pairs)} disabled={pending || !st?.rows}>Substantially identical warnings</Button>
      </div>
      {error && <p className="text-[13px] text-bear">{error.message}</p>}
      {w && (
        <>
          <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3">
            <Tile label="Disallowed loss" value={usd(w.disallowed)} big sub="added to the replacement's basis unless an IRA bought it" />
            <Tile label="Wash-sale hits" value={w.hits.length} />
            <Tile label="Crypto wash-sale check" value={w.crypto_checked ? "On" : "Off"} sub={w.crypto_checked ? undefined : "default"} />
          </div>
          <RowsTable rows={w.hits} headers={HEAD} empty="No wash sales found across the tagged accounts." />
          {w.warnings.length > 0 && (
            <Callout tone="warn" title="Substantially identical: warnings, never determinations">
              <div className="mt-2"><RowsTable rows={w.warnings} headers={HEAD} /></div>
            </Callout>
          )}
          <LocalExplainPanel facts={w.facts} section="Tax" />
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------ 1099-B check */
function Check1099({ ready }: { ready: boolean }) {
  const [f, setF] = useState<File | null>(null);
  const rec = useMutation({ mutationFn: async () => post<Rec>("/api/tax/us/compare-1099b", { market: "US", file_b64: await readB64(f!) }) });
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-3">
        <FilePick label="1099-B / 1099-DA (CSV)" file={f} onFile={setF} />
        <Button variant="primary" onClick={() => rec.mutate()} disabled={!f || !ready || rec.isPending}>Compare with 1099-B</Button>
      </div>
      {!ready && <p className="text-[13px] text-muted">Load rows first: Import tradebook above, or a lesson sample.</p>}
      {rec.error && <p className="text-[13px] text-bear">{(rec.error as Error).message}</p>}
      {rec.data && <MismatchTable rec={rec.data} />}
      {rec.data && <LocalExplainPanel facts={rec.data.facts} section="Tax" />}
    </div>
  );
}

/* ------------------------------------------------------------ Export */
function ExportTab({ form }: { form: Form | null | undefined }) {
  const toast = useToast();
  const exp = useMutation({ mutationFn: () => post<{ csv: string; filename: string }>("/api/tax/us/export?market=US"), onSuccess: () => toast("8949-shaped CSV ready (Draft for your CA / CPA)") });
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col items-start gap-1">
        <span className="text-[12px] text-muted">Format</span>
        <Segmented label="Format" value="8949-shaped CSV" options={["8949-shaped CSV"] as const} onChange={() => {}} />
      </div>
      {!form ? <EmptyState>Load rows first: Import tradebook above, or a lesson sample.</EmptyState> : (
        <>
          <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
            <Tile label="Short-term total" value={usd(form.short_total)} tone={form.short_total > 0 ? "bull" : form.short_total < 0 ? "bear" : undefined} big />
            <Tile label="Long-term total" value={usd(form.long_total)} tone={form.long_total > 0 ? "bull" : form.long_total < 0 ? "bear" : undefined} />
            <Tile label="Section 1256 rows (Form 6781)" value={form.form_6781.length} sub={form.form_6781.length ? `net ${usd(form.net_1256)}, 60/40` : undefined} />
            <Tile label="IRA rows left out" value={form.excluded_ira} />
          </div>
          <RowsTable rows={form.rows} headers={HEAD} empty="No Form 8949 rows." />
          {form.form_6781.length > 0 && (
            <div className="flex flex-col gap-2"><span className="text-[13px] font-medium">Form 6781 (Section 1256): 60% long-term, 40% short-term</span><RowsTable rows={form.form_6781} headers={HEAD} /></div>
          )}
          {form.flags.map((f) => <p key={f} className="text-[13px] text-saffron">{f}</p>)}
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" onClick={() => exp.mutate()} disabled={exp.isPending}>Export</Button>
            {exp.data && <Button onClick={() => downloadText(exp.data.filename, exp.data.csv)}><Download size={14} /> Download 8949-shaped CSV (Draft for your CA / CPA)</Button>}
          </div>
          {exp.error && <p className="text-[13px] text-bear">{(exp.error as Error).message}</p>}
          {exp.data && <pre className="scroll-thin num max-h-[260px] overflow-auto rounded-[var(--radius-tile)] border border-line bg-panel-2 p-3 text-[12px]">{exp.data.csv.slice(0, 1500)}</pre>}
          <LocalExplainPanel facts={form.facts} section="Tax" />
        </>
      )}
    </div>
  );
}

export function UsTax({ st }: { st?: State }) {
  const toast = useToast();
  const [w, setW] = useState<Wash | undefined>();
  const form = useQuery({ queryKey: ["tax-8949", st?.rows, w], queryFn: () => get<{ form: Form | null }>("/api/tax/us/8949?market=US") });
  const run = useMutation({
    mutationFn: ({ crypto, pairs }: { crypto: boolean; pairs: string }) => post<Wash>("/api/tax/us/wash", { market: "US", crypto, pairs }),
    onSuccess: (d) => { setW(d); toast(`Wash-sale check done: ${d.hits.length} hits`); },
  });
  return (
    <Tabs defaultValue="classify">
      <TabList><Tab value="classify">Classify</Tab><Tab value="wash">Wash sales</Tab><Tab value="1099">1099-B check</Tab><Tab value="export">Export</Tab></TabList>
      <TabPanel value="classify" className="pt-4"><ClassifyTab key={st?.account_names.join()} st={st} /></TabPanel>
      <TabPanel value="wash" className="pt-4"><WashTab st={st} w={w} run={(crypto, pairs) => run.mutate({ crypto, pairs })} pending={run.isPending} error={run.error as Error | null} /></TabPanel>
      <TabPanel value="1099" className="pt-4"><Check1099 ready={!!st?.rows} /></TabPanel>
      <TabPanel value="export" className="pt-4"><ExportTab form={form.data?.form} /></TabPanel>
    </Tabs>
  );
}
