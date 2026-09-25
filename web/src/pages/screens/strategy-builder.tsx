import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpenText, LineChart, Play } from "lucide-react";
import { get, post } from "@/lib/api";
import { Button, Panel, inputCls } from "@/components/ui";
import { FactTile, FactsProvider, ExplainPanel } from "@/components/facts";
import { useMarket } from "@/components/shell";
import { Badge, Callout, EmptyState, Hypothetical, Select, useToast } from "@/components/kit";
import {
  DataChoice, ErrorText, Labelled, ResultChart, SummaryTiles, useSessionState, type RuleCard, type Summary,
} from "@/components/strategy/shared";
import { DraftCards, RuleCardsEditor, type Spec } from "@/components/strategy/rule-cards";
import { ChartCheckChart, type ChartCheckData } from "@/components/strategy/chart-check";

interface Options { instruments: string[]; profiles: string[]; default_slippage: number }
interface Draft { spec: Spec; cards: RuleCard[]; read_back?: string }
interface Checked { spec: Spec; cards: RuleCard[]; read_back: string; facts: string[]; trials: number; digest: string; family: string }
interface Proposal { id: number; subject: string; created: string; team?: string; spec?: Spec; cards?: RuleCard[]; error?: string }
type BtResult = Summary & { id: number; notice: string | null };

const PLACEHOLDER = "Buy when the price is above the 50-day average; get out when it falls below the 20-day average";

export default function StrategyBuilder() {
  const [market] = useMarket();
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const [setup, setSetup] = useSessionState("sb-setup", { symbol: { IN: "NIFTY", US: "SPY" } as Record<string, string>, years: 5, synthetic: true });
  const [idea, setIdea] = useSessionState("sb-idea", "");
  const [draft, setDraft] = useSessionState<Draft | null>("sb-draft", null);
  const [spec, setSpec] = useSessionState<Spec | null>("sb-spec", null);
  const [show, setShow] = useSessionState("sb-show", { readback: false, chart: false });
  const [draftError, setDraftError] = useState<string | null>(null);
  const [result, setResult] = useState<BtResult | null>(null);
  const [showProposals, setShowProposals] = useState(false);

  const { data: opts } = useQuery({ queryKey: ["strategy-options", market], queryFn: () => get<Options>(`/api/strategy/options?market=${market}`) });
  const { data: proposals = [] } = useQuery({ queryKey: ["strategy-proposals"], queryFn: () => get<Proposal[]>("/api/strategy/proposals") });
  const symbol = setup.symbol[market] ?? opts?.instruments[0] ?? "NIFTY";

  // A cost profile from the other market is not valid here: fall back to this market's first.
  useEffect(() => {
    if (spec && opts && spec.cost.profile && !opts.profiles.includes(spec.cost.profile)) {
      setSpec({ ...spec, cost: { ...spec.cost, profile: opts.profiles[0] } });
    }
  }, [opts, spec, setSpec]);

  const check = useQuery({
    queryKey: ["strategy-check", market, spec],
    queryFn: () => post<Checked>("/api/strategy/check", { spec, market }),
    enabled: !!spec, placeholderData: keepPreviousData, retry: false,
  });
  const valid = !!spec && !check.isError && !!check.data;
  const runBody = { spec, market, symbol, years: setup.years, synthetic: setup.synthetic };

  const draftIt = useMutation({
    mutationFn: () => post<Draft>("/api/strategy/draft", { idea: idea || PLACEHOLDER, market }),
    onSuccess: (d) => { setDraft(d); setDraftError(null); if (!idea) setIdea(PLACEHOLDER); },
    onError: (e) => { setDraftError((e as Error).message); setDraft(null); },
  });
  const chart = useQuery({
    queryKey: ["strategy-chart", market, symbol, setup.years, setup.synthetic, check.data?.digest],
    queryFn: () => post<ChartCheckData>("/api/strategy/chart-check", runBody),
    enabled: show.chart && valid, placeholderData: keepPreviousData, retry: false,
  });
  const backtest = useMutation({
    mutationFn: () => post<BtResult>("/api/strategy/backtest", runBody),
    onSuccess: (r) => { setResult(r); qc.invalidateQueries({ queryKey: ["strategy-check"] }); toast(`Backtest done, trials: ${r.trials}`); },
  });

  const accept = () => {
    if (!draft) return;
    setSpec(draft.spec);
    setDraft(null);
    setShow({ readback: false, chart: false });
    setResult(null);
    toast("Rule cards accepted");
  };
  const loadProposal = (p: Proposal) => {
    if (p.spec && p.cards) { setDraft({ spec: p.spec, cards: p.cards }); setShowProposals(false); }
  };
  const trials = check.data?.trials ?? 0;
  const current = result && check.data && result.digest === check.data.digest ? result : null;
  const proposedDraft = draft?.spec.origin === "agent";

  return (
    <FactsProvider>
      <div className="flex flex-col gap-5">
        <Panel title="Test setup" action={<span className="text-[13px] text-muted">Describe your idea, accept the rule cards, read back, chart check, backtest</span>}>
          <div className="grid gap-4 sm:grid-cols-[minmax(0,1.2fr)_120px_auto]">
            <Labelled label="Instrument">
              <Select value={symbol} onChange={(e) => setSetup({ ...setup, symbol: { ...setup.symbol, [market]: e.target.value } })}>
                {(opts?.instruments ?? [symbol]).map((s) => <option key={s}>{s}</option>)}
              </Select>
            </Labelled>
            <Labelled label="Years">
              <input className={inputCls} type="number" min={1} max={15} value={setup.years}
                onChange={(e) => setSetup({ ...setup, years: Math.min(15, Math.max(1, Number(e.target.value) || 1)) })} />
            </Labelled>
            <DataChoice synthetic={setup.synthetic} onChange={(s) => setSetup({ ...setup, synthetic: s })} />
          </div>
        </Panel>

        {proposals.length > 0 && (
          <Panel title={`Agent proposals waiting (${proposals.length})`}
            action={<Button size="sm" variant="quiet" onClick={() => setShowProposals((s) => !s)}>{showProposals ? "Hide" : "Show"}</Button>}>
            {showProposals ? (
              <ul className="flex flex-col divide-y divide-line">
                {proposals.map((p) => (
                  <li key={p.id} className="flex flex-wrap items-center gap-3 py-2">
                    <Badge tone="indigo">PROPOSED</Badge>
                    <span className="font-medium">#{p.id} {p.subject}</span>
                    <span className="num text-[13px] text-muted">{p.created}</span>
                    {p.error ? <span className="text-[13px] text-bear">{p.error}</span>
                      : <Button size="sm" className="ml-auto" onClick={() => loadProposal(p)}>Load #{p.id}</Button>}
                  </li>
                ))}
              </ul>
            ) : <p className="text-[13px] text-muted">An agent team sent rules from Automate, Agents. Load one to see it as draft rule cards; nothing is applied until you click Accept.</p>}
          </Panel>
        )}

        <Panel title="Describe your idea">
          <form className="flex flex-col gap-3 md:flex-row" onSubmit={(e) => { e.preventDefault(); draftIt.mutate(); }}>
            <input aria-label="Describe your idea" value={idea} onChange={(e) => setIdea(e.target.value)} placeholder={PLACEHOLDER}
              className="h-10 min-w-0 flex-1 rounded-[6px] border border-line-strong bg-panel px-3 font-serif text-[15px] outline-none focus:border-indigo" />
            <Button type="submit" variant="primary" disabled={draftIt.isPending}>{draftIt.isPending ? "Drafting…" : "Draft rule cards"}</Button>
          </form>
          <p className="mt-2 text-[13px] text-muted">Press Enter. The lab drafts the rule cards; you Accept them, fill anything marked assumed, then read them back.</p>
          {draftError && <div className="mt-3"><Callout tone="danger" title="The lab could not read that rule">{draftError}</Callout></div>}
        </Panel>

        {draft && (
          <Panel title="Draft rule cards"
            action={<div className="flex items-center gap-2">
              {proposedDraft && <Badge tone="indigo">PROPOSED</Badge>}
              <Button size="sm" variant="quiet" onClick={() => setDraft(null)}>Discard</Button>
              <Button size="sm" variant="primary" onClick={accept}>Accept</Button>
            </div>}>
            <p className="mb-3 text-[13px] text-muted">Nothing is applied until you click Accept. Amber marks are choices the lab made for you.</p>
            <DraftCards cards={draft.cards} />
          </Panel>
        )}

        {!spec && !draft && (
          <EmptyState>Type your idea and press Enter. The lab drafts the rule cards; you Accept them, fill anything marked assumed, then read them back.</EmptyState>
        )}

        {spec && (
          <>
            <RuleCardsEditor spec={spec} cards={check.data?.cards} onChange={setSpec}
              profiles={opts?.profiles ?? []} defaultSlippage={opts?.default_slippage ?? 0.05} />
            {check.isError && <Callout tone="danger" title="These rule cards cannot be tested yet">{(check.error as Error).message}</Callout>}

            <div className="grid items-stretch gap-4 lg:grid-cols-[minmax(0,1fr)_220px]">
              <div className="flex flex-wrap items-center gap-2 rounded-[var(--radius-panel)] border border-line bg-panel px-4 py-3">
                <Button onClick={() => setShow({ ...show, readback: true })} disabled={!valid}><BookOpenText size={15} /> Read back in English</Button>
                <Button onClick={() => setShow({ ...show, chart: true })} disabled={!valid}><LineChart size={15} /> Chart check</Button>
                <Button variant="primary" onClick={() => backtest.mutate()} disabled={!valid || backtest.isPending}>
                  <Play size={15} /> {backtest.isPending ? "Running…" : "Backtest"}
                </Button>
                <span className="text-[13px] text-muted">Every backtest of a new variant adds one to the Trials counter. Chart check does not.</span>
              </div>
              <FactTile label="Trials" value={trials} big sub="Distinct variants in this family" />
            </div>
            <ErrorText error={backtest.error} />

            {show.readback && check.data && (
              <Panel title="Read back in English" action={<Button size="sm" variant="quiet" onClick={() => setShow({ ...show, readback: false })}>Hide</Button>}>
                <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
                  <p className="font-serif text-[16px] leading-[1.65]">{check.data.read_back}</p>
                  <ExplainPanel facts={check.data.facts} section="Strategy" question="Explain these rules to a new trader in three plain sentences." />
                </div>
                <p className="mt-3 text-[13px] text-muted">If it says anything you did not mean, edit the card, not the paragraph.</p>
              </Panel>
            )}

            {show.chart && (
              <Panel title={`Chart check, ${symbol}`} action={<div className="flex items-center gap-2"><Hypothetical />
                <Button size="sm" variant="quiet" onClick={() => setShow({ ...show, chart: false })}>Hide</Button></div>}>
                <ErrorText error={chart.error} />
                {chart.data ? (
                  <>
                    {chart.data.notice && <div className="mb-3"><Callout tone="warn">{chart.data.notice}</Callout></div>}
                    <ChartCheckChart d={chart.data} />
                    <div className="mt-3">
                      {chart.data.chip
                        ? <Callout tone="warn" title={chart.data.chip}>Clusters of exits and re-entries: the rule may be churning. Check the markers around them.</Callout>
                        : <Callout tone="ok">No clusters of exits and re-entries, {chart.data.round_trips} round trips.</Callout>}
                    </div>
                    <p className="mt-2 text-[13px] text-muted">Markers sit on the fill session (the open after the signal). Drag the slider to scroll through the years. Chart check does not add a trial.</p>
                  </>
                ) : !chart.error && <div className="h-[340px]" aria-busy="true" />}
              </Panel>
            )}

            {current && (
              <Panel title="Backtest" action={<Hypothetical />}>
                <div className="mb-4 flex flex-wrap items-center gap-3">
                  <Callout tone="ok">Backtest done. Trials: {current.trials}. Open the Backtest Report for costs, walk-forward and the Report Card.</Callout>
                  <Button variant="primary" onClick={() => navigate(`/backtest-report?id=${current.id}`)}>Open Backtest Report</Button>
                </div>
                {current.notice && <div className="mb-3"><Callout tone="warn">{current.notice}</Callout></div>}
                <SummaryTiles s={current.stats} g={current.gross} trials={current.trials} market={market} />
                <div className="mt-4"><ResultChart frame={current.frame} height={300} showDrawdown={false} /></div>
              </Panel>
            )}
          </>
        )}
      </div>
    </FactsProvider>
  );
}
