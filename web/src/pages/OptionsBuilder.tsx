import { useMemo, useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { post, type Market } from "@/lib/api";
import { money } from "@/lib/format";
import { cn } from "@/lib/cn";
import { Button, Panel, Slider, Field, inputCls } from "@/components/ui";
import { FactTile, FactsProvider, ExplainPanel } from "@/components/facts";
import { PayoffChart } from "@/components/charts";
import { useMarket } from "@/components/shell";

interface LegIn { kind: "call" | "put"; strike: number; side: "buy" | "sell"; qty: number; expiry: "weekly" | "monthly" }
interface Quote {
  symbol: string; spot: number; lot: number; name: string; tiles: Record<string, string>;
  payoff: { spot: number[]; expiry: number[]; now: number[] }; band: [number, number];
  breakevens: number[]; facts: string[]; legs: (LegIn & { premium: number; days: number })[];
}

const DEFAULTS: Record<Market, { symbol: string; legs: LegIn[] }> = {
  IN: { symbol: "NIFTY", legs: [{ kind: "call", strike: 25000, side: "buy", qty: 1, expiry: "weekly" }] },
  US: { symbol: "SPY", legs: [{ kind: "call", strike: 565, side: "buy", qty: 1, expiry: "weekly" }] },
};

const PRESETS: Record<Market, Record<string, LegIn[]>> = {
  IN: {
    "Iron condor": [
      { kind: "put", strike: 24100, side: "buy", qty: 1, expiry: "monthly" },
      { kind: "put", strike: 24300, side: "sell", qty: 1, expiry: "monthly" },
      { kind: "call", strike: 25400, side: "sell", qty: 1, expiry: "monthly" },
      { kind: "call", strike: 25600, side: "buy", qty: 1, expiry: "monthly" },
    ],
    "Bull put spread": [
      { kind: "put", strike: 24300, side: "sell", qty: 1, expiry: "monthly" },
      { kind: "put", strike: 24100, side: "buy", qty: 1, expiry: "monthly" },
    ],
  },
  US: {
    "Iron condor": [
      { kind: "put", strike: 530, side: "buy", qty: 1, expiry: "monthly" },
      { kind: "put", strike: 540, side: "sell", qty: 1, expiry: "monthly" },
      { kind: "call", strike: 580, side: "sell", qty: 1, expiry: "monthly" },
      { kind: "call", strike: 590, side: "buy", qty: 1, expiry: "monthly" },
    ],
    "Bull put spread": [
      { kind: "put", strike: 540, side: "sell", qty: 1, expiry: "monthly" },
      { kind: "put", strike: 530, side: "buy", qty: 1, expiry: "monthly" },
    ],
  },
};

const TONE: Record<string, "bull" | "bear" | "indigo" | undefined> = {
  "Max loss": "bear", "Credit": "bull", "Max profit": "bull", "Required move": "indigo",
};
/** Theta is a cost when it is negative (buyers) and income when positive (sellers). */
const toneOf = (k: string, v: string) =>
  k === "Theta/day" ? (v.trim().startsWith("−") || v.trim().startsWith("-") ? "bear" : "bull") : TONE[k];

function LegRow({ leg, onChange, onRemove, cur }: { leg: LegIn; onChange: (l: LegIn) => void; onRemove: () => void; cur: string }) {
  const seg = (on: boolean, tone: "bull" | "bear" | "ink") => cn("h-7 px-2.5 text-[13px] font-medium",
    on ? (tone === "bull" ? "bg-bull text-white" : tone === "bear" ? "bg-bear text-white" : "bg-ink text-panel") : "text-muted hover:text-ink");
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-line py-2.5 last:border-0">
      <div className="inline-flex overflow-hidden rounded-[6px] border border-line-strong">
        <button className={seg(leg.side === "buy", "bull")} onClick={() => onChange({ ...leg, side: "buy" })}>Buy</button>
        <button className={seg(leg.side === "sell", "bear")} onClick={() => onChange({ ...leg, side: "sell" })}>Sell</button>
      </div>
      <div className="inline-flex overflow-hidden rounded-[6px] border border-line-strong">
        <button className={seg(leg.kind === "call", "ink")} onClick={() => onChange({ ...leg, kind: "call" })}>Call</button>
        <button className={seg(leg.kind === "put", "ink")} onClick={() => onChange({ ...leg, kind: "put" })}>Put</button>
      </div>
      <input aria-label="Strike" className={cn(inputCls, "h-7 w-24")} type="number" value={leg.strike}
        onChange={(e) => onChange({ ...leg, strike: Number(e.target.value) })} />
      <select aria-label="Expiry" className={cn(inputCls, "h-7 w-[104px]")} value={leg.expiry}
        onChange={(e) => onChange({ ...leg, expiry: e.target.value as LegIn["expiry"] })}>
        <option value="weekly">Weekly</option><option value="monthly">Monthly</option>
      </select>
      <span className="sr-only">{cur}</span>
      <button onClick={onRemove} className="ml-auto text-muted hover:text-bear" aria-label="Remove leg"><X size={15} /></button>
    </div>
  );
}

export default function OptionsBuilder() {
  const [market] = useMarket();
  const [legsByMarket, setLegs] = useState<Record<Market, LegIn[]>>({ IN: DEFAULTS.IN.legs, US: DEFAULTS.US.legs });
  const [daysOverride, setDays] = useState<number | null>(null);
  const legs = legsByMarket[market];
  const symbol = DEFAULTS[market].symbol;
  const setMarketLegs = (l: LegIn[]) => { setLegs((s) => ({ ...s, [market]: l })); setDays(null); };

  const { data: q, error, isFetching } = useQuery({
    queryKey: ["opt", market, legs, daysOverride],
    queryFn: () => post<Quote>("/api/options/quote", { symbol, market, legs, days_left: daysOverride }),
    placeholderData: keepPreviousData,
    enabled: legs.length > 0,
  });
  const maxDays = useMemo(() => Math.max(1, ...(q?.legs.map((l) => Math.round(l.days)) ?? [5])), [q]);
  const fmt = (x: number) => money(x, market);

  return (
    <FactsProvider>
      <div className="grid gap-5 xl:grid-cols-[340px_minmax(0,1fr)_320px]">
        <div className="flex flex-col gap-5">
          <Panel title={`${symbol} legs`} action={<span className="num text-[13px] text-muted">Spot {q ? q.spot.toLocaleString() : "…"}</span>}>
            {legs.map((l, i) => (
              <LegRow key={i} leg={l} cur={market} onChange={(nl) => setMarketLegs(legs.map((x, j) => (j === i ? nl : x)))}
                onRemove={() => setMarketLegs(legs.filter((_, j) => j !== i))} />
            ))}
            <div className="mt-3 flex flex-wrap gap-2">
              <Button size="sm" onClick={() => setMarketLegs([...legs, { ...(legs[legs.length - 1] ?? DEFAULTS[market].legs[0]) }])}><Plus size={14} /> Add leg</Button>
              <Button size="sm" variant="quiet" onClick={() => setMarketLegs(DEFAULTS[market].legs)}>New strategy</Button>
            </div>
          </Panel>
          <Panel title="Income presets">
            <div className="flex flex-wrap gap-2">
              {Object.entries(PRESETS[market]).map(([name, l]) => (
                <Button key={name} size="sm" onClick={() => setMarketLegs(l)}>{name}</Button>
              ))}
            </div>
            <p className="mt-3 text-[13px] text-muted">Presets load the book's worked examples on the synthetic lesson chain.</p>
          </Panel>
        </div>

        <div className="flex min-w-0 flex-col gap-5">
          <Panel title={q?.name ?? "Payoff"} action={isFetching && <span className="text-[12px] text-muted">Repricing…</span>}>
            {error && <p className="text-bear">{(error as Error).message}</p>}
            {q && <PayoffChart spot={q.payoff.spot} expiry={q.payoff.expiry} now={q.payoff.now} current={q.spot}
              band={q.band} breakevens={q.breakevens} money={fmt} />}
            <div className="mt-4 flex items-center gap-4">
              <span className="w-24 text-[13px] text-muted">Days left</span>
              <Slider label="Days left" min={0} max={maxDays} value={daysOverride ?? maxDays} onChange={setDays} />
              <span className="num w-10 text-right font-medium">{daysOverride ?? maxDays}</span>
            </div>
            <p className="mt-2 text-[13px] text-muted">Solid line: profit or loss at expiry. Dashed: today, repriced as days pass. Shaded band: the market's own ±1σ expected move.</p>
          </Panel>
        </div>

        <div className="flex flex-col gap-3">
          <h2 className="text-[14px] font-semibold">What you're paying for</h2>
          <div className="grid grid-cols-2 gap-2.5">
            {q && Object.entries(q.tiles).map(([k, v], i) => (
              <FactTile key={k} label={k} value={v} tone={toneOf(k, v)} big={i === 0} />
            ))}
          </div>
          <div className="mt-2">
            {q && <ExplainPanel facts={q.facts} section="Derivatives" />}
          </div>
          <Field label="Lot" hint="From the dated Contract Table">
            <span className="num text-[14px]">{q?.lot ?? "…"} units</span>
          </Field>
        </div>
      </div>
    </FactsProvider>
  );
}
