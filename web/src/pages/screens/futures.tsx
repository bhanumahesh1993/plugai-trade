import { useCallback, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { get, post } from "@/lib/api";
import { Tabs, TabList, Tab, TabPanel } from "@/components/ui";
import { ScreenGrid, useToast } from "@/components/kit";
import { FactsProvider, ExplainPanel } from "@/components/facts";
import { useMarket } from "@/components/shell";
import { DatedNote, Note, PAPER_NOTE } from "@/components/derivatives/common";
import { BasisTab, ContractTab, MarginTab, RollTab, type Choices } from "@/components/derivatives/futures-tabs";

const TABS = ["Contract", "Basis", "Roll calendar", "Margin & MTM"] as const;
type TabName = (typeof TABS)[number];
// Keep every tab mounted (as the classic page renders all four) so Explain sees all their numbers.
const panelCls = "pt-5 outline-none data-[state=inactive]:hidden";

export default function FuturesRoll() {
  const [market] = useMarket();
  const toast = useToast();
  const [tab, setTab] = useState<TabName>("Contract");
  const [facts, setFacts] = useState<Record<TabName, string[]>>({ Contract: [], Basis: [], "Roll calendar": [], "Margin & MTM": [] });
  const [accepted, setAccepted] = useState("");
  const { data: choices } = useQuery({ queryKey: ["fut-choices", market], queryFn: () => get<Choices>(`/api/derivatives/choices?market=${market}`) });
  const setter = useCallback((k: TabName) => (f: string[]) => setFacts((s) => (s[k] === f ? s : { ...s, [k]: f })), []);
  const on = useMemo(() => Object.fromEntries(TABS.map((k) => [k, setter(k)])) as Record<TabName, (f: string[]) => void>, [setter]);
  // The open tab's numbers first, then the rest: the narration starts where the reader is.
  const all = useMemo(() => [tab, ...TABS.filter((k) => k !== tab)].flatMap((k) => facts[k]), [facts, tab]);

  const plan = useMutation({
    mutationFn: (p: { symbol: string; entry: number; qty: number; side: string; call_price?: number }) =>
      post<{ name: string; version: number }>("/api/derivatives/plan", { ...p, market, facts: facts["Margin & MTM"], ai_explanation: accepted }),
    onSuccess: (r) => toast(`Saved to plan: ${r.name}, version ${r.version}`),
    onError: (e) => toast((e as Error).message, "danger"),
  });

  return (
    <FactsProvider>
      <ScreenGrid rail={
        <>
          <h2 className="text-[14px] font-semibold">Explain these numbers</h2>
          <ExplainPanel facts={all} section="Derivatives" onAccept={(t) => { setAccepted(t); toast("Accepted the explanation for the plan"); }}
            question="Narrate the ledger, shock, basis and roll numbers in plain words, citing each number. Do not recommend any trade." />
          <Note>{PAPER_NOTE}</Note>
          <DatedNote asOf={choices?.as_of}>Margins are illustrative; your broker's file is the real figure.</DatedNote>
        </>
      }>
        <Tabs value={tab} onValueChange={(v) => setTab(v as TabName)}>
          <TabList>{TABS.map((t) => <Tab key={t} value={t}>{t}</Tab>)}</TabList>
          {choices && (<>
            <TabPanel forceMount value="Contract" className={panelCls}><ContractTab market={market} choices={choices} onFacts={on.Contract} /></TabPanel>
            <TabPanel forceMount value="Basis" className={panelCls}><BasisTab market={market} choices={choices} onFacts={on.Basis} /></TabPanel>
            <TabPanel forceMount value="Roll calendar" className={panelCls}><RollTab market={market} choices={choices} onFacts={on["Roll calendar"]} /></TabPanel>
            <TabPanel forceMount value="Margin & MTM" className={panelCls}>
              <MarginTab market={market} choices={choices} onFacts={on["Margin & MTM"]} onPlan={(p) => plan.mutate(p)} />
            </TabPanel>
          </>)}
        </Tabs>
      </ScreenGrid>
    </FactsProvider>
  );
}
