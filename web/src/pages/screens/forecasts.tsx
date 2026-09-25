/* Portfolio › Forecast Journal (Chapter 26). US only; disabled with the book's explanation for IN. */
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, EyeOff, Plus, Sparkles } from "lucide-react";
import { get, post, type Market } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button, Panel, Field, inputCls } from "@/components/ui";
import { FactsProvider, FactTile } from "@/components/facts";
import { Callout, DataTable, EmptyState, Segmented, Select, Switch, Textarea, EChart, chartTokens, ScreenGrid, useToast } from "@/components/kit";
import { useMarket } from "@/components/shell";
import { LocalExplainPanel, TileGrid, RailTitle, errText, NumInput, type ApiTileT } from "@/components/portfolio/common";

interface Bin { lo: number; hi: number; mean_prob: number; hit_rate: number; n: number }
interface Card { n: number; brier?: number; ready: boolean; facts: string[]; tiles: ApiTileT[]; bins: Bin[]; min?: number }
interface Journal { market: Market; disabled: boolean; note: string | null; rows: Record<string, unknown>[]; open: { id: number; question: string }[]; score: Card; sample: Card }

const KEY = (m: Market) => ["forecasts", m];

function useDebounced<T>(v: T, ms = 350) {
  const [d, setD] = useState(v);
  useEffect(() => { const h = setTimeout(() => setD(v), ms); return () => clearTimeout(h); }, [v, ms]);
  return d;
}

/* ------------------------------------------------------------------ Calibration */
function CalibrationChart({ bins, title }: { bins: Bin[]; title: string }) {
  const t = chartTokens();
  const option = {
    title: { text: title, left: 0, top: 0, textStyle: { color: t.muted, fontSize: 13, fontWeight: 500 } },
    grid: { left: 56, right: 20, top: 36, bottom: 44 },
    tooltip: { backgroundColor: t.panel, borderColor: t.line, textStyle: { color: t.ink },
      formatter: (p: { data: number[] }) => `You said ${Math.round(p.data[0] * 100)}% on average<br/>It happened ${Math.round(p.data[1] * 100)}% of ${p.data[2]}` },
    xAxis: { type: "value", min: 0, max: 1, name: "Probability you gave", nameLocation: "middle", nameGap: 28, nameTextStyle: { color: t.muted },
      axisLabel: { color: t.muted, formatter: (v: number) => `${Math.round(v * 100)}%` }, splitLine: { lineStyle: { color: t.line } } },
    yAxis: { type: "value", min: 0, max: 1, name: "How often it happened", nameLocation: "middle", nameGap: 40, nameTextStyle: { color: t.muted },
      axisLabel: { color: t.muted, formatter: (v: number) => `${Math.round(v * 100)}%` }, splitLine: { lineStyle: { color: t.line } } },
    series: [
      { type: "line", data: [[0, 0], [1, 1]], showSymbol: false, silent: true, lineStyle: { color: t.muted, type: "dashed", width: 1 } },
      { type: "scatter", data: bins.map((b) => [b.mean_prob, b.hit_rate, b.n]), itemStyle: { color: t.indigo },
        symbolSize: (d: number[]) => 8 + Math.sqrt(d[2]) * 2.2 },
    ],
  };
  return (
    <div>
      <EChart option={option} height={300} />
      <p className="text-[13px] text-muted">Dashed diagonal: perfect calibration. Dots below it on the right and above it on the left mean overconfidence.</p>
    </div>
  );
}

function Score({ card, title, sample }: { card: Card; title: string; sample?: boolean }) {
  if (card.n === 0) return <p className="text-[13px] text-muted">Brier score appears after the first resolved forecast.</p>;
  return (
    <div className="flex flex-col gap-4" data-facts-scope>
      <TileGrid tiles={card.tiles} cols={3} />
      {card.ready ? <CalibrationChart bins={card.bins} title={title} />
        : <p className="text-[13px] text-muted num">{card.n}/{card.min ?? 30} resolved. The calibration chart appears after 30.</p>}
      <LocalExplainPanel facts={card.facts} section="Portfolio" question={sample ? "Explain what this synthetic journal's calibration shows." : undefined} />
    </div>
  );
}

/* ------------------------------------------------------------------ Add forecast */
function AddForecast({ market, disabled }: { market: Market; disabled: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [rules, setRules] = useState("");
  const [platform, setPlatform] = useState("");
  const [hide, setHide] = useState(true);
  const [prob, setProb] = useState(50);
  const [reason, setReason] = useState("");
  const [price, setPrice] = useState(62);
  const [fee, setFee] = useState(1);
  const [committed, setCommitted] = useState<number | null>(null);
  const dRules = useDebounced(rules);
  const found = useQuery({
    queryKey: ["forecasts", "rules", dRules], enabled: !!dRules.trim(),
    queryFn: () => post<Record<string, string[]>>("/api/portfolio/forecasts/rules", { rules: dRules }),
  });
  const readAi = useMutation({ mutationFn: () => post<{ text: string }>("/api/portfolio/forecasts/rules-ai", { rules }) });
  const showPrice = !hide || committed !== null;
  const be = useQuery({
    queryKey: ["forecasts", "be", price, fee], enabled: showPrice,
    queryFn: () => post<{ break_even: number }>("/api/portfolio/forecasts/break-even", { price_cents: price, fee_cents: fee }),
  });
  const commit = useMutation({
    mutationFn: () => post<{ id: number }>("/api/portfolio/forecasts", {
      market, question: q, rules, prob_pct: prob, reason, platform,
      price_cents: hide ? null : price, fee_cents: hide ? 0 : fee,
    }),
    onSuccess: (r) => { setCommitted(r.id); qc.invalidateQueries({ queryKey: KEY(market) }); toast("Committed forecast"); },
  });
  const finish = useMutation({
    mutationFn: () => post(`/api/portfolio/forecasts/${committed}/price`, { market, price_cents: price, fee_cents: fee }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEY(market) });
      toast("Forecast saved. Nothing is bought: the journal records forecasts only.");
      setOpen(false); setCommitted(null); setQ(""); setRules(""); setReason(""); setPlatform(""); setProb(50); readAi.reset();
    },
  });
  if (!open) {
    return (
      <Panel title="New forecast">
        <Button variant="primary" onClick={() => setOpen(true)} disabled={disabled}><Plus size={14} /> Add forecast</Button>
        <p className="mt-2 text-[13px] text-muted">{disabled ? "Switch the market to US to add forecasts." : "Paste the contract's question and rules, then commit your own probability before the price appears."}</p>
      </Panel>
    );
  }
  const beVal = be.data?.break_even;
  return (
    <Panel title="Add forecast" action={<Button size="sm" variant="quiet" onClick={() => { setOpen(false); setCommitted(null); }}>Close</Button>}>
      <div className="flex flex-col gap-3">
        <Field label="Contract question"><input className={inputCls} value={q} onChange={(e) => setQ(e.target.value)} disabled={committed !== null} /></Field>
        <Field label="Rules text (paste the contract's rules, source and deadline)"><Textarea value={rules} onChange={(e) => setRules(e.target.value)} disabled={committed !== null} /></Field>
        <div className="max-w-sm"><Field label="Platform"><input className={inputCls} value={platform} onChange={(e) => setPlatform(e.target.value)} disabled={committed !== null} /></Field></div>
        {rules.trim() && (
          <div className="rounded-[var(--radius-tile)] border border-line bg-panel-2 p-3.5">
            <div className="mb-2 flex items-center justify-between gap-3">
              <h3 className="text-[14px] font-semibold">Resolution rules</h3>
              <Button size="sm" onClick={() => readAi.mutate()} disabled={readAi.isPending}><Sparkles size={14} /> Read the rules with AI</Button>
            </div>
            {Object.entries(found.data ?? {}).map(([label, ss]) => (
              <div key={label} className="mb-2">
                <div className="text-[12px] text-muted">{label}</div>
                {(ss.length ? ss : ["(not found in the text — check the platform's rules page)"]).map((s, i) => (
                  <blockquote key={i} className={cn("border-l-2 border-line-strong pl-2.5 font-serif text-[14px]", !ss.length && "text-muted")}>{s}</blockquote>
                ))}
              </div>
            ))}
            {readAi.data && <div className="mt-2"><Callout tone="info"><span className="whitespace-pre-line font-serif">{readAi.data.text}</span></Callout></div>}
            {readAi.error && <p className="text-[13px] text-bear">{errText(readAi.error)}</p>}
          </div>
        )}
        <div className="max-w-md"><Switch checked={hide} onChange={setHide} label="Hide price until I commit" hint="Type your probability before you see the market's. This keeps the score honest." /></div>
        <div className="grid gap-3 md:grid-cols-[160px_minmax(0,1fr)]">
          <Field label="Your probability (%)"><NumInput value={prob} min={0} max={100} step={1} onChange={(v) => committed === null && setProb(Math.min(100, Math.max(0, v)))} /></Field>
          <Field label="One-line reason"><input className={inputCls} value={reason} onChange={(e) => setReason(e.target.value)} disabled={committed !== null} /></Field>
        </div>
        {showPrice ? (
          <div className="grid gap-3 md:grid-cols-[140px_minmax(0,1fr)_minmax(0,1.2fr)] md:items-end">
            <Field label="YES price (¢)"><NumInput value={price} min={0} max={100} step={1} onChange={setPrice} /></Field>
            <Field label="Fee per contract (¢, platform's current schedule)"><NumInput value={fee} min={0} max={20} step={0.5} onChange={setFee} /></Field>
            <FactTile label="Fee-adjusted break-even" value={beVal === undefined ? "…" : `${Math.round(beVal * 100)}%`}
              sub={`your ${Math.round(prob)}%`} big />
          </div>
        ) : (
          <p className="flex items-center gap-1.5 text-[13px] text-muted"><EyeOff size={14} /> The price is hidden until you commit.</p>
        )}
        {showPrice && <p className="text-[13px] text-muted">A YES contract only pays off on average if the true chance is above the break-even. Computed in code; nothing is bought.</p>}
        <div className="flex gap-2">
          {committed === null
            ? <Button variant="primary" onClick={() => commit.mutate()} disabled={!q.trim() || commit.isPending}>Commit forecast</Button>
            : <Button variant="primary" onClick={() => finish.mutate()} disabled={finish.isPending}>Save price and finish</Button>}
        </div>
        {(commit.error || finish.error) && <p className="text-[13px] text-bear">{errText(commit.error ?? finish.error)}</p>}
      </div>
    </Panel>
  );
}

/* ------------------------------------------------------------------ Journal and resolve */
function JournalPanel({ j, market }: { j: Journal; market: Market }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [fid, setFid] = useState<number | null>(null);
  const [outcome, setOutcome] = useState<"1" | "0">("1");
  const id = fid ?? j.open[0]?.id ?? null;
  const resolve = useMutation({
    mutationFn: () => post<Journal>(`/api/portfolio/forecasts/${id}/resolve`, { market, outcome: Number(outcome) }),
    onSuccess: (d) => { qc.setQueryData(KEY(market), d); setFid(null); toast("Resolved forecast"); },
    onError: (e) => toast(errText(e), "danger"),
  });
  const cents = (v: unknown) => (v == null ? "—" : `${Math.round((v as number) * 100)}¢`);
  return (
    <Panel title="Your journal">
      <DataTable rows={j.rows} rowKey={(r) => r.id as number} empty="No forecasts yet. Click Add forecast." columns={[
        { key: "id", header: "#", width: "40px" }, { key: "question", header: "Question" },
        { key: "your %", header: "Your %", align: "right", render: (r) => `${r["your %"]}%` },
        { key: "price", header: "Price", align: "right", render: (r) => cents(r.price) },
        { key: "fee", header: "Fee", align: "right", render: (r) => cents(r.fee) },
        { key: "outcome", header: "Outcome", align: "right", render: (r) => r.outcome == null ? "Open" : String(r.outcome) },
      ]} />
      {j.open.length > 0 && (
        <div className="mt-4 grid gap-3 md:grid-cols-[minmax(0,1fr)_auto_auto] md:items-end">
          <Field label="Forecast">
            <Select value={id ?? ""} onChange={(e) => setFid(Number(e.target.value))} disabled={j.disabled}>
              {j.open.map((o) => <option key={o.id} value={o.id}>#{o.id}: {o.question.slice(0, 60)}</option>)}
            </Select>
          </Field>
          <Field label="Outcome">
            <Segmented label="Outcome" value={outcome} onChange={setOutcome} options={[{ value: "1", label: "Happened (1)" }, { value: "0", label: "Did not (0)" }]} />
          </Field>
          <Button onClick={() => resolve.mutate()} disabled={j.disabled || id === null || resolve.isPending}>Resolve</Button>
        </div>
      )}
    </Panel>
  );
}

export default function ForecastJournal() {
  const [market] = useMarket();
  const { data: j } = useQuery({ queryKey: KEY(market), queryFn: () => get<Journal>(`/api/portfolio/forecasts?market=${market}`) });
  const [lessonOpen, setLessonOpen] = useState<boolean | null>(null);
  const lesson = lessonOpen ?? market === "IN";
  return (
    <FactsProvider>
      <div className="flex flex-col gap-5">
        {j?.disabled && <Callout tone="warn" title="Forecast Journal is US only">{j.note}</Callout>}
        <ScreenGrid rail={
          <div data-facts-scope className="flex flex-col gap-4">
            <RailTitle>Your calibration</RailTitle>
            {j ? <Score card={j.score} title="Your calibration" /> : <div style={{ height: 120 }} />}
          </div>
        }>
          <div className={cn("flex flex-col gap-5", j?.disabled && "opacity-60")} aria-disabled={j?.disabled}>
            <AddForecast market={market} disabled={!j || j.disabled} />
            {j ? <JournalPanel j={j} market={market} /> : <EmptyState>Loading your journal…</EmptyState>}
          </div>
        </ScreenGrid>
        <section className="rounded-[var(--radius-panel)] border border-line bg-panel">
          <button type="button" onClick={() => setLessonOpen(!lesson)} aria-expanded={lesson}
            className="flex w-full items-center gap-1.5 px-4 py-2.5 text-left text-[14px] font-semibold hover:text-indigo">
            <ChevronDown size={15} className={cn("transition-transform", !lesson && "-rotate-90")} /> Calibration lesson (synthetic journal of 160 forecasts)
          </button>
          {lesson && j && (
            <div className="border-t border-line p-4">
              <div className="max-w-[860px]"><Score card={j.sample} title="Synthetic, deliberately overconfident" sample /></div>
            </div>
          )}
        </section>
        <p className="text-[12px] text-muted">The journal records forecasts, not positions. Paper only: PlugAI-Trade never places real orders.</p>
      </div>
    </FactsProvider>
  );
}
