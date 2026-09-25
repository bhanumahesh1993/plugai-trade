/* Portfolio › Portfolio Reviewer (Chapters 15 and 16). */
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Lock } from "lucide-react";
import { post, type Market } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button, Field, Tabs, TabList, Tab, TabPanel, inputCls } from "@/components/ui";
import { FactsProvider } from "@/components/facts";
import { useToast } from "@/components/kit";
import { useMarket } from "@/components/shell";
import { FilePick, fileToB64, errText } from "@/components/portfolio/common";
import { HoldingsTab, OverlapTab, CostsTab, ConcentrationTab, useHoldings, holdingsKey, type HoldingsData } from "@/components/portfolio/reviewer-a";
import { AllocationTab, EtfTab, IncomeTab } from "@/components/portfolio/reviewer-b";
import { SipTab, ThesisTab } from "@/components/portfolio/reviewer-c";

const TABS = ["Holdings", "Overlap", "Costs", "Concentration", "Allocation", "ETF check", "Income", "SIP planner", "Thesis tracker"] as const;

function ImportPanel({ market }: { market: Market }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: h } = useHoldings(market);
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [pwd, setPwd] = useState("");
  const [account, setAccount] = useState("");
  const done = (d: HoldingsData, msg: string) => {
    qc.setQueryData(holdingsKey(market), d);
    qc.invalidateQueries({ queryKey: ["pf", market] });
    toast(msg);
  };
  const imp = useMutation({
    mutationFn: async () => post<HoldingsData & { imported: number }>("/api/portfolio/import", {
      market, filename: file!.name, content_b64: await fileToB64(file!), password: pwd, account,
    }),
    onSuccess: (d) => { done(d, `Imported ${d.imported} holdings locally`); setPwd(""); },
  });
  const sample = useMutation({
    mutationFn: () => post<HoldingsData>("/api/portfolio/sample", { market }),
    onSuccess: (d) => done(d, "Loaded sample portfolio"),
  });
  const isPdf = file?.name.toLowerCase().endsWith(".pdf");
  return (
    <section className="rounded-[var(--radius-panel)] border border-line bg-panel">
      <div className="flex flex-wrap items-center gap-3 px-4 py-2.5">
        <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
          className="flex items-center gap-1.5 text-[14px] font-semibold hover:text-indigo">
          <ChevronDown size={15} className={cn("transition-transform", !open && "-rotate-90")} /> Import holdings
        </button>
        <span className="text-[13px] text-muted">Showing: {h?.label ?? "…"}</span>
        <span className="ml-auto flex items-center gap-1.5 text-[13px] text-muted"><Lock size={13} /> Holdings stay on this computer. AI uses the local model only.</span>
      </div>
      {open && (
        <div className="border-t border-line p-4">
          <p className="mb-3 text-[13px] text-muted">The file is read on your computer and never sent to an AI model.</p>
          <div className="grid gap-3 md:grid-cols-3 md:items-start">
            <Field label="CAS PDF, broker holdings CSV or generic CSV">
              <FilePick accept=".pdf,.csv" file={file} onFile={(f) => { setFile(f); imp.reset(); }} />
            </Field>
            <Field label="CAS password" hint="Often your PAN in capitals. Used only to open the file locally.">
              <input type="password" className={inputCls} value={pwd} onChange={(e) => setPwd(e.target.value)} disabled={!!file && !isPdf} autoComplete="off" />
            </Field>
            <Field label="Account type (US: 401(k), IRA, Brokerage)" hint="Tags every row of a broker CSV.">
              <input className={inputCls} value={account} onChange={(e) => setAccount(e.target.value)} />
            </Field>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="primary" onClick={() => imp.mutate()} disabled={!file || imp.isPending}>{imp.isPending ? "Importing…" : "Import holdings"}</Button>
            <Button onClick={() => sample.mutate()} disabled={sample.isPending}>Load sample portfolio</Button>
          </div>
          {imp.error && <p className="mt-2 text-[13px] text-bear">{errText(imp.error)}</p>}
        </div>
      )}
    </section>
  );
}

export default function PortfolioReviewer() {
  const [market] = useMarket();
  const [tab, setTab] = useState<string>("Holdings");
  return (
    <FactsProvider>
      <div className="flex flex-col gap-5">
        <ImportPanel market={market} />
        <Tabs value={tab} onValueChange={setTab}>
          <div className="scroll-thin overflow-x-auto"><TabList>{TABS.map((t) => <Tab key={t} value={t}><span className="whitespace-nowrap">{t}</span></Tab>)}</TabList></div>
          <div className="pt-5">
            <TabPanel value="Holdings"><HoldingsTab market={market} /></TabPanel>
            <TabPanel value="Overlap"><OverlapTab market={market} /></TabPanel>
            <TabPanel value="Costs"><CostsTab market={market} /></TabPanel>
            <TabPanel value="Concentration"><ConcentrationTab market={market} /></TabPanel>
            <TabPanel value="Allocation"><AllocationTab market={market} /></TabPanel>
            <TabPanel value="ETF check"><EtfTab market={market} /></TabPanel>
            <TabPanel value="Income"><IncomeTab market={market} /></TabPanel>
            <TabPanel value="SIP planner"><SipTab market={market} /></TabPanel>
            <TabPanel value="Thesis tracker"><ThesisTab market={market} /></TabPanel>
          </div>
        </Tabs>
        <p className="text-[12px] text-muted">Paper only. PlugAI-Trade never places real orders.</p>
      </div>
    </FactsProvider>
  );
}
