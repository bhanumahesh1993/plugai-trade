import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, Play, Send } from "lucide-react";
import { get, post, type Market } from "@/lib/api";
import { money, pct } from "@/lib/format";
import { cn } from "@/lib/cn";
import { Button, Panel, Slider, inputCls } from "@/components/ui";
import { FactTile, FactsProvider, ExplainPanel } from "@/components/facts";
import { useMarket } from "@/components/shell";
import { Callout, Hypothetical, ScreenGrid, Segmented, Select, Switch, useToast } from "@/components/kit";
import {
  DataChoice, ErrorText, Labelled, PaperOnlyNote, ResultChart, SummaryTiles, drawdownSentence, useSessionState, type Summary,
} from "@/components/strategy/shared";
import { HeatmapView, type HeatmapData } from "@/components/strategy/heatmap";

const PRESETS = ["MA crossover", "Time-series momentum", "Rotation"] as const;
type Preset = (typeof PRESETS)[number];
const CHECKS = [{ value: "weekly", label: "Weekly" }, { value: "daily", label: "Daily" }, { value: "monthly", label: "Monthly" }];
const FUTURES = "Back-adjusted futures (from Futures & Roll)";

interface Options {
  instruments: string[]; profiles: string[]; sectors: string[]; default_slippage: number; default_sleeve: number;
  futures: { symbol: string; rows: number } | null;
}
interface Sizing { sleeve: number; daily_vol: number; annual_vol: number; weight: number; exposure: number; units: number; price: number; formula: string }
interface Preview { read_back: string; digest: string; trials: number; profile: string; notice: string | null; sizing?: Sizing }
type RunResult = Summary & { run_id: string; notice: string | null };
interface Tax { total_tax: number; after_tax_return: number; short_rate: number; long_rate: number; short_rate_assumed: boolean; line: number[]; as_of: string }
type Axes = Record<Preset, { rows: { label: string; default: string }; cols: { label: string; default: string } | null }>;

interface Settings {
  symbol: string; years: number; synthetic: boolean; fast: number; slow: number; months: number; check: string;
  sleeve: number | null; target: number; buffer: number; cap: number; lookback: number; profile: string | null; slippage_pct: number | null;
  universe: string[] | null; rot_lookback: number; top_n: number; rot_years: number; rot_synthetic: boolean;
}
const DEFAULTS = (m: Market): Settings => ({
  symbol: m === "IN" ? "NIFTY" : "SPY", years: 15, synthetic: true, fast: 50, slow: 200, months: 12, check: "weekly",
  sleeve: null, target: 12, buffer: 10, cap: 100, lookback: 20, profile: null, slippage_pct: null,
  universe: null, rot_lookback: 6, top_n: 2, rot_years: 15, rot_synthetic: true,
});

function Num({ label, value, onChange, min, max, step = 1, hint }: {
  label: string; value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number; hint?: string;
}) {
  return (
    <Labelled label={label}>
      <input className={inputCls} type="number" value={Number.isFinite(value) ? value : ""} min={min} max={max} step={step} title={hint}
        onChange={(e) => onChange(Number(e.target.value))} />
    </Labelled>
  );
}

export default function TrendLab() {
  const [market] = useMarket();
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const [preset, setPreset] = useSessionState<Preset>("tl-preset", "MA crossover");
  const [byMarket, setByMarket] = useSessionState<Record<string, Settings>>("tl-settings", {});
  const s: Settings = { ...DEFAULTS(market), ...(byMarket[market] ?? {}) };
  const set = (patch: Partial<Settings>) => setByMarket({ ...byMarket, [market]: { ...s, ...patch } });

  const { data: opts } = useQuery({ queryKey: ["strategy-options", market], queryFn: () => get<Options>(`/api/strategy/options?market=${market}`) });
  const { data: axes } = useQuery({ queryKey: ["tl-axes"], queryFn: () => get<Axes>("/api/strategy/trend/heatmap-axes") });
  const universe = s.universe ?? opts?.sectors ?? [];
  const body = {
    preset, market, symbol: s.symbol, years: preset === "Rotation" ? s.rot_years : s.years,
    synthetic: preset === "Rotation" ? s.rot_synthetic : s.synthetic, fast: s.fast, slow: s.slow, months: s.months, check: s.check,
    sleeve: s.sleeve ?? opts?.default_sleeve ?? null, target: s.target, buffer: s.buffer, cap: s.cap, lookback: s.lookback,
    profile: s.profile, slippage_pct: s.slippage_pct ?? opts?.default_slippage ?? null,
    universe, rot_lookback: s.rot_lookback, top_n: s.top_n,
  };
  const ready = !!opts;
  const preview = useQuery({
    queryKey: ["tl-preview", body], queryFn: () => post<Preview>("/api/strategy/trend/preview", body),
    enabled: ready, placeholderData: keepPreviousData, retry: false,
  });

  const [results, setResults] = useState<Record<string, RunResult>>({});
  const key = `${market}:${preset}`;
  const res = results[key];
  const run = useMutation({
    mutationFn: () => post<RunResult>("/api/strategy/trend/run", body),
    onSuccess: (r) => { setResults((x) => ({ ...x, [key]: r })); qc.invalidateQueries({ queryKey: ["tl-preview"] }); },
  });

  const [taxOn, setTaxOn] = useState(false);
  const [bracket, setBracket] = useState(24);
  const tax = useQuery({
    queryKey: ["tl-tax", res?.run_id, market === "US" ? bracket : null],
    queryFn: () => post<Tax>("/api/strategy/after-tax", { run_id: res!.run_id, short_rate: market === "US" ? bracket / 100 : null }),
    enabled: taxOn && !!res, placeholderData: keepPreviousData, retry: false,
  });

  const [hmOpen, setHmOpen] = useState(false);
  const [hmText, setHmText] = useState<Record<string, { rows: string; cols: string }>>({});
  const [split, setSplit] = useState(2 / 3);
  const [maps, setMaps] = useState<Record<string, HeatmapData>>({});
  const ax = axes?.[preset];
  const txt = hmText[preset] ?? { rows: ax?.rows.default ?? "", cols: ax?.cols?.default ?? "" };
  const sweep = useMutation({
    mutationFn: () => post<HeatmapData>("/api/strategy/trend/heatmap", { settings: body, rows: txt.rows, cols: ax?.cols ? txt.cols : null, split }),
    onSuccess: (hm) => { setMaps((x) => ({ ...x, [key]: hm })); qc.invalidateQueries({ queryKey: ["tl-preview"] }); toast(`Swept ${hm.cells} settings, trials now ${hm.trials}`); },
  });
  const hm = maps[key];

  const [sentId, setSentId] = useState<number | null>(null);
  const sendBt = useMutation({
    mutationFn: () => post<{ id: number }>("/api/strategy/send-backtest", { run_id: res!.run_id, tag: "trend_lab" }),
    onSuccess: (x) => { setSentId(x.id); toast("Sent to Backtest Report"); },
    onError: (e) => toast((e as Error).message, "danger"),
  });
  const sendPaper = useMutation({
    mutationFn: () => post<{ ids: number[]; orders: unknown[]; grade: string }>("/api/strategy/send-paper", { run_id: res!.run_id }),
    onSuccess: (x) => toast(x.ids.length ? `${x.ids.length} pending paper order${x.ids.length > 1 ? "s" : ""} drafted in Paper Desk` : "No paper order drafted: the rule holds nothing now"),
    onError: (e) => toast((e as Error).message, "danger"),
  });

  const stale = res && preview.data && res.digest !== preview.data.digest;
  const sz = preview.data?.sizing;
  const instruments = [...(opts?.instruments ?? []), ...(opts?.futures ? [FUTURES] : [])];
  const extra = taxOn && tax.data ? [{ name: "Rule, after costs and tax", values: tax.data.line }] : [];

  return (
    <FactsProvider>
      <div className="flex flex-col gap-5">
        <div className="flex flex-wrap items-center gap-3">
          <Segmented label="Preset" value={preset} options={PRESETS} onChange={(p) => { setPreset(p); setSentId(null); }} />
          <span className="text-[13px] text-muted">Signal, size, buffer, weekly clock. All results are HYPOTHETICAL.</span>
        </div>

        <ScreenGrid rail={
          <>
            <FactTile label="Trials" value={preview.data?.trials ?? "…"} big sub="Distinct variants in this family, sweeps included" />
            <Button variant="primary" onClick={() => run.mutate()} disabled={!preview.data || preview.isError || run.isPending}>
              <Play size={15} /> {run.isPending ? "Running…" : "Run"}
            </Button>
            <ErrorText error={run.error} />
            <div className="flex flex-col gap-2 rounded-[var(--radius-panel)] border border-line bg-panel p-4">
              <Button onClick={() => sendBt.mutate()} disabled={!res || sendBt.isPending}><Send size={14} /> Send to Backtest Report</Button>
              <Button onClick={() => sendPaper.mutate()} disabled={!res || sendPaper.isPending}><Send size={14} /> Send to Paper Desk</Button>
              {sentId && <Button variant="quiet" size="sm" onClick={() => navigate(`/backtest-report?id=${sentId}`)}>Open Backtest Report</Button>}
              <p className="text-[12px] text-muted">Send to Paper Desk drafts pending paper orders for the next session's open, with the rule and its Report Card grade. Nothing fills until you click Accept there.</p>
              <PaperOnlyNote />
            </div>
            {res && <ExplainPanel facts={res.facts} section="Strategy" />}
          </>
        }>
          {preset !== "Rotation" ? (
            <Panel title="Rule">
              <div className="grid gap-4 sm:grid-cols-[minmax(0,1.3fr)_100px_auto]">
                <Labelled label="Instrument">
                  <Select value={instruments.includes(s.symbol) ? s.symbol : instruments[0]} onChange={(e) => set({ symbol: e.target.value })}>
                    {instruments.map((x) => <option key={x}>{x}</option>)}
                  </Select>
                </Labelled>
                <Num label="Years" value={s.years} min={3} max={15} onChange={(v) => set({ years: Math.min(15, Math.max(3, v || 3)) })} />
                <DataChoice synthetic={s.synthetic} onChange={(v) => set({ synthetic: v })} />
              </div>
              <div className="mt-4 grid gap-4 sm:grid-cols-3">
                {preset === "MA crossover" ? (
                  <>
                    <Num label="Fast average (days)" value={s.fast} min={2} max={400} onChange={(v) => set({ fast: v })} />
                    <Num label="Slow average (days)" value={s.slow} min={3} max={600} onChange={(v) => set({ slow: v })} />
                  </>
                ) : (
                  <Num label="Lookback (months)" value={s.months} min={1} max={36} onChange={(v) => set({ months: v })} />
                )}
                <div className={cn("flex flex-col gap-1", preset !== "MA crossover" && "sm:col-span-2")}>
                  <span className="text-[12px] text-muted">Check</span>
                  <Segmented label="Check" value={s.check} options={CHECKS} onChange={(v) => set({ check: v })} />
                </div>
              </div>
            </Panel>
          ) : (
            <Panel title="Rotation">
              <div className="flex flex-col gap-1">
                <span className="text-[12px] text-muted">Universe ({universe.length} selected)</span>
                <div className="flex flex-wrap gap-1.5" role="group" aria-label="Universe">
                  {(opts?.sectors ?? []).map((x) => {
                    const on = universe.includes(x);
                    return (
                      <button key={x} type="button" aria-pressed={on} onClick={() => set({ universe: on ? universe.filter((u) => u !== x) : [...universe, x] })}
                        className={cn("h-7 rounded-[4px] border px-2 text-[13px]", on ? "border-indigo bg-indigo-soft font-medium text-indigo" : "border-line-strong text-muted hover:text-ink")}>{x}</button>
                    );
                  })}
                </div>
              </div>
              <div className="mt-4 grid gap-4 sm:grid-cols-[140px_100px_100px_auto]">
                <Num label="Lookback (months)" value={s.rot_lookback} min={1} max={24} onChange={(v) => set({ rot_lookback: v })} />
                <Num label="Top N" value={s.top_n} min={1} max={10} onChange={(v) => set({ top_n: v })} />
                <Num label="Years" value={s.rot_years} min={3} max={15} onChange={(v) => set({ rot_years: Math.min(15, Math.max(3, v || 3)) })} />
                <DataChoice synthetic={s.rot_synthetic} onChange={(v) => set({ rot_synthetic: v })} />
              </div>
              <p className="mt-3 text-[13px] text-muted">Rebalance and costs: monthly, after the last session's close; switches fill at the next open. Benchmark: equal weight, all {universe.length}, bought once and held.</p>
            </Panel>
          )}

          {preset !== "Rotation" && (
            <Panel title="Volatility sizing">
              <div className="grid gap-4 sm:grid-cols-5">
                <Num label="Sleeve" value={s.sleeve ?? opts?.default_sleeve ?? 0} min={1000} step={10000} onChange={(v) => set({ sleeve: v })} />
                <Num label="Target vol % a year" value={s.target} min={1} max={60} onChange={(v) => set({ target: v })} />
                <Num label="Buffer %" value={s.buffer} min={0} max={50} onChange={(v) => set({ buffer: v })} />
                <Num label="Cap %" value={s.cap} min={1} max={100} hint="100% = no borrowing" onChange={(v) => set({ cap: v })} />
                <Num label="Vol lookback (sessions)" value={s.lookback} min={5} max={250} onChange={(v) => set({ lookback: v })} />
              </div>
              <div className="mt-4 grid grid-cols-2 gap-2.5 md:grid-cols-4">
                <FactTile label="Realised volatility" value={sz ? `${(sz.annual_vol * 100).toFixed(1)}% a year` : "…"} sub={sz ? `Daily move ${(sz.daily_vol * 100).toFixed(2)}%` : undefined} />
                <FactTile label="Target exposure" value={sz ? money(sz.exposure, market) : "…"} sub={sz ? `${(sz.weight * 100).toFixed(0)}% of sleeve` : undefined} />
                <FactTile label="Units (rounded down)" value={sz ? sz.units.toLocaleString() : "…"} />
                <FactTile label="Last close" value={sz ? sz.price.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "…"} />
              </div>
              {sz && <p className="mt-2 text-[13px] text-muted">{sz.formula}</p>}
            </Panel>
          )}

          <Panel title="Costs">
            <div className="grid gap-4 sm:grid-cols-2">
              <Labelled label="Costs">
                <Select value={preview.data?.profile ?? s.profile ?? ""} onChange={(e) => set({ profile: e.target.value })}>
                  {(opts?.profiles ?? []).map((p) => <option key={p}>{p}</option>)}
                </Select>
              </Labelled>
              <Num label="Slippage % a side" value={s.slippage_pct ?? opts?.default_slippage ?? 0} min={0} max={2} step={0.01} onChange={(v) => set({ slippage_pct: v })} />
            </div>
            {preview.isError ? <div className="mt-3"><Callout tone="danger" title="These settings cannot be tested">{(preview.error as Error).message}</Callout></div>
              : preview.data && <p className="mt-3 font-serif text-[15px] leading-[1.6]"><span className="font-sans text-[13px] text-muted">Read back: </span>{preview.data.read_back}</p>}
            {preview.data?.notice && <div className="mt-3"><Callout tone="warn">{preview.data.notice}</Callout></div>}
            <div className="mt-3 flex items-center gap-3 xl:hidden">
              <Button variant="primary" onClick={() => run.mutate()} disabled={!preview.data || preview.isError || run.isPending}>
                <Play size={15} /> {run.isPending ? "Running…" : "Run"}
              </Button>
              <span className="num text-[14px]">Trials: {preview.data?.trials ?? "…"}</span>
            </div>
          </Panel>

          {res ? (
            <Panel title={`Result, ${res.meta.symbol}`} action={<Hypothetical />}>
              {stale && <div className="mb-3"><Callout tone="info">Settings changed since this run. Click Run to test the new version.</Callout></div>}
              <SummaryTiles s={res.stats} g={res.gross} trials={res.trials} market={market} />
              <div className="mt-4 flex flex-col gap-3 rounded-[var(--radius-tile)] border border-line px-3.5 py-2">
                <Switch checked={taxOn} onChange={setTaxOn} label="After-tax" hint="Tax each year's realised gains at the dated table's rates." />
                {taxOn && market === "US" && (
                  <label className="flex w-72 flex-col gap-1">
                    <span className="text-[12px] text-muted">Your short-term (ordinary income) rate %</span>
                    <input className={inputCls} type="number" min={0} max={50} value={bracket} onChange={(e) => setBracket(Number(e.target.value))} />
                  </label>
                )}
                {taxOn && tax.data && (
                  <>
                    <div className="grid grid-cols-3 gap-2.5">
                      <FactTile label="Tax paid (all years)" value={money(tax.data.total_tax, market)} />
                      <FactTile label="After costs and tax" value={pct(tax.data.after_tax_return, 1)} tone={tax.data.after_tax_return >= 0 ? "bull" : "bear"} />
                      <FactTile label="Rates used" value={`${(tax.data.short_rate * 100).toFixed(0)}% short`} sub={`${(tax.data.long_rate * 100).toFixed(1)}% long`} />
                    </div>
                    <p className="pb-2 text-[13px] text-muted">Short-term rate from {tax.data.short_rate_assumed ? "your rate (assumed)" : "the dated tax table"}; long-term from the dated tax table ({tax.data.as_of}). Losses offset gains within a year; carry-forward not modelled. Buy-and-hold never sells, so it pays no tax here.</p>
                  </>
                )}
                <ErrorText error={tax.error} />
              </div>
              <div className="mt-4"><ResultChart frame={res.frame} extra={extra} /></div>
              {drawdownSentence(res.drawdown_story, res.stats.bh_max_drawdown) && (
                <p className="mt-2 text-[13px] text-muted">{drawdownSentence(res.drawdown_story, res.stats.bh_max_drawdown)}</p>
              )}
            </Panel>
          ) : (
            <Callout tone="info">Set the rule and the sizing, then click Run. The equity curve and drawdown appear with the HYPOTHETICAL mark, and the Trials counter records the test.</Callout>
          )}

          <Panel title="Parameter heatmap" action={<Button size="sm" variant="quiet" onClick={() => setHmOpen((o) => !o)}>{hmOpen || hm ? "Hide" : "Open"}</Button>}>
            {hmOpen || hm ? (
              <div className="flex flex-col gap-4">
                <div className="grid gap-4 sm:grid-cols-3">
                  <Labelled label={ax?.rows.label ?? "Rows"}>
                    <input className={inputCls} value={txt.rows} onChange={(e) => setHmText({ ...hmText, [preset]: { ...txt, rows: e.target.value } })} />
                  </Labelled>
                  {ax?.cols && (
                    <Labelled label={ax.cols.label}>
                      <input className={inputCls} value={txt.cols} onChange={(e) => setHmText({ ...hmText, [preset]: { ...txt, cols: e.target.value } })} />
                    </Labelled>
                  )}
                  <div className="flex flex-col gap-1">
                    <span className="text-[12px] text-muted">Tuning share of the years: {(split * 100).toFixed(0)}%</span>
                    <div className="flex h-9 items-center"><Slider label="Tuning share of the years" min={0.5} max={0.85} step={0.05} value={split} onChange={setSplit} /></div>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <Button variant="primary" onClick={() => sweep.mutate()} disabled={sweep.isPending || !preview.data}>{sweep.isPending ? "Running every setting…" : "Sweep"}</Button>
                  <span className="text-[13px] text-muted">Every cell is one trial. Look at the whole map before any single cell, and do not sweep again around a bright corner.</span>
                </div>
                <ErrorText error={sweep.error} />
                {hm && (
                  <>
                    <div className="flex items-center gap-2"><Hypothetical /><span className="text-[13px] text-muted">Sharpe in each cell; the setting you chose is outlined.</span></div>
                    <HeatmapView hm={hm} />
                    <div className="flex flex-wrap items-center gap-3">
                      <p className="text-[13px] text-muted">Split at {hm.split_date}. Buy-and-hold Sharpe {hm.benchmark_tuning.toFixed(2)} tuning, {hm.benchmark_unseen.toFixed(2)} unseen. {hm.cells} settings = {hm.cells} trials; the family counter now reads {hm.trials}. Look for a plateau, not a lone bright cell.</p>
                      <Button size="sm" onClick={async () => { try { await navigator.clipboard.writeText(hm.text); toast("Copied the grid as text"); } catch { toast("Could not reach the clipboard", "danger"); } }}>
                        <Copy size={14} /> Copy grid as text
                      </Button>
                    </div>
                    <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3">
                      <FactTile label="Settings in the sweep" value={hm.cells} />
                      <FactTile label="Trials" value={hm.trials} />
                      <FactTile label="Buy-and-hold Sharpe" value={`${hm.benchmark_tuning.toFixed(2)} / ${hm.benchmark_unseen.toFixed(2)}`} sub="Tuning / unseen" />
                    </div>
                    <ExplainPanel facts={hm.facts} section="Strategy" question="Is the tuning grid a broad plateau or a lone peak? Describe only what is in the grids." />
                  </>
                )}
              </div>
            ) : <p className="text-[13px] text-muted">Sweep two settings and score every cell on the tuning years and on the unseen years. Every cell counts as a trial.</p>}
          </Panel>
        </ScreenGrid>
      </div>
    </FactsProvider>
  );
}
