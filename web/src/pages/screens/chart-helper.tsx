import { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { CheckCircle2, XCircle, BookmarkPlus, Send } from "lucide-react";
import { post, type Market } from "@/lib/api";
import { num } from "@/lib/format";
import { cn } from "@/lib/cn";
import { Button, Panel, Field, inputCls } from "@/components/ui";
import { FactTile, FactsProvider, ExplainPanel } from "@/components/facts";
import { Badge, Callout, DataTable, EmptyState, Hypothetical, Segmented, Select, Switch, useToast, type Column } from "@/components/kit";
import { useMarket } from "@/components/shell";
import { LevelChart, type Bar, type LevelLine } from "@/components/research-b/LevelChart";
import { ChipPicker, Disclosure, MetaList, Placeholder, errText } from "@/components/research-b/common";

const P = "/api/research-b/chart";
const DEFAULT_SYMBOL: Record<Market, string> = { IN: "NIFTY", US: "SPY" };
const TIMEFRAMES = ["Daily", "Weekly", "15-min", "5-min"] as const;
const SOURCES = ["Synthetic", "Data Sources (Settings)"] as const;

interface Provenance { source: string; fetched_at: string; license_class: string; asof: string; bars: number }
interface BarsOut { symbol: string; bars: Bar[]; provenance: Provenance }
type Row = Record<string, string | number | null>;
interface DescribeOut {
  symbol: string; timeframe: string; asof: string; values: Record<string, number>; lines: string[]; facts: string[];
  claims: { Claim: string; Check: string; "Against the table": string }[] | null; crosses?: number;
}
interface LevelsOut {
  symbol: string; set: string; table: Row[]; lines: LevelLine[]; facts: string[];
  close?: number; atr?: number; asof?: string; values?: Record<string, number>; or_minutes?: number;
}

type View = "describe" | "levels" | null;

export default function ChartHelper() {
  const [market] = useMarket();
  const toast = useToast();
  const [symbols, setSymbols] = useState<Record<Market, string>>(DEFAULT_SYMBOL);
  const [draft, setDraft] = useState(symbols[market]);
  useEffect(() => setDraft(symbols[market]), [market, symbols]);
  const symbol = symbols[market];
  const [timeframe, setTimeframe] = useState<(typeof TIMEFRAMES)[number]>("Daily");
  const [data, setData] = useState<(typeof SOURCES)[number]>("Synthetic");
  const [shot, setShot] = useState(false);
  const [view, setView] = useState<View>(null);
  const [levelSet, setLevelSet] = useState<"Zones" | "Intraday">("Zones");
  const [orm, setOrm] = useState<"5" | "15" | "30">("15");

  const base = { symbol, market, timeframe, data };
  const commit = () => {
    const s = draft.trim().toUpperCase();
    if (s && s !== symbol) setSymbols((x) => ({ ...x, [market]: s }));
  };

  const barsQ = useQuery({
    queryKey: ["rb-bars", base],
    queryFn: () => post<BarsOut>(`${P}/bars`, base),
    placeholderData: keepPreviousData,
  });
  const descQ = useQuery({
    queryKey: ["rb-describe", base, shot],
    queryFn: () => post<DescribeOut>(`${P}/describe`, { ...base, screenshot: shot }),
    placeholderData: keepPreviousData,
    enabled: !barsQ.isError,
  });
  const lvBody = { ...base, set: levelSet, or_minutes: Number(orm) };
  const levelsQ = useQuery({
    queryKey: ["rb-levels", lvBody],
    queryFn: () => post<LevelsOut>(`${P}/levels`, lvBody),
    placeholderData: keepPreviousData,
    enabled: view === "levels",
  });
  const save = useMutation({
    mutationFn: () => post<{ id: number }>(`${P}/levels/save`, lvBody),
    onSuccess: () => toast("Saved levels to journal"),
    onError: (e) => toast(errText(e), "danger"),
  });
  const send = useMutation({
    mutationFn: () => post<{ id: number }>(`${P}/levels/send`, lvBody),
    onSuccess: () => toast("Sent levels to Paper Desk"),
    onError: (e) => toast(errText(e), "danger"),
  });

  const d = descQ.data;
  const lv = view === "levels" ? levelsQ.data : undefined;
  const chartLevels = useMemo(() => lv?.lines ?? [], [lv]);
  const prov = barsQ.data?.provenance;
  const intradayTiles = lv?.set === "Intraday" && lv.values;

  return (
    <FactsProvider>
      <div className="flex flex-col gap-5">
        <Panel>
          <div className="grid items-end gap-3 md:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1.2fr)_auto]">
            <Field label="Symbol">
              <input className={inputCls} value={draft} aria-label="Symbol"
                onChange={(e) => setDraft(e.target.value.toUpperCase())}
                onBlur={commit} onKeyDown={(e) => e.key === "Enter" && commit()} />
            </Field>
            <Field label="Timeframe">
              <Select value={timeframe} onChange={(e) => setTimeframe(e.target.value as typeof timeframe)}>
                {TIMEFRAMES.map((t) => <option key={t}>{t}</option>)}
              </Select>
            </Field>
            <Field label="Data">
              <Select value={data} onChange={(e) => setData(e.target.value as typeof data)}
                title="Data Sources uses the chain in Settings, Data Sources, and falls back to the synthetic sample when a source returns too little history.">
                {SOURCES.map((s) => <option key={s}>{s}</option>)}
              </Select>
            </Field>
            <div className="min-w-[250px]">
              <Switch checked={shot} onChange={setShot} label="Screenshot mode (unreliable)" />
            </div>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button variant="primary" onClick={() => { commit(); setView("describe"); }}>Describe</Button>
            <Button onClick={() => { commit(); setView("levels"); }}>Levels</Button>
            <p className="ml-auto text-[13px] text-muted">The model receives the table and the computed values, never the picture.</p>
          </div>
        </Panel>

        {barsQ.isError && (
          <Callout tone="danger" title={`Could not load ${symbol}`}>{errText(barsQ.error)}</Callout>
        )}

        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
          <div className="flex min-w-0 flex-col gap-5">
            <Panel
              title={`${barsQ.data?.symbol ?? symbol}, ${timeframe.toLowerCase()} bars`}
              action={<div className="flex items-center gap-2">{barsQ.isFetching && <span className="text-[12px] text-muted">Loading…</span>}<Hypothetical /></div>}
            >
              {barsQ.data ? <LevelChart bars={barsQ.data.bars} levels={chartLevels} /> : <Placeholder height={340} />}
              <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                {prov && <MetaList items={[["Source", prov.source], ["Last bar", String(prov.asof).replace("T", " ")], ["Fetched", String(prov.fetched_at).slice(0, 16).replace("T", " ")], ["Bars", prov.bars]]} />}
                <span className="text-[12px] text-muted">Last 60 bars shown. A study, not a signal.</span>
              </div>
              {view === "levels" && chartLevels.length > 0 && (
                <p className="mt-2 text-[12px] text-muted">
                  Lines: {lv?.set === "Intraday" ? "PDH, PDL, opening range (dashed) and VWAP (solid)" : "zones with two or more touches, next-session pivot and the POC band (dotted)"}. Values in the right margin.
                </p>
              )}
            </Panel>

            {view === "levels" && (
              <Panel title="Levels" action={levelsQ.isFetching && <span className="text-[12px] text-muted">Computing…</span>}>
                <div className="mb-4 flex flex-wrap items-center gap-4">
                  <div className="flex items-center gap-2">
                    <span className="text-[13px] text-muted">Levels set</span>
                    <Segmented label="Levels set" value={levelSet} options={["Zones", "Intraday"] as const} onChange={setLevelSet} />
                  </div>
                  {levelSet === "Intraday" && (
                    <div className="flex items-center gap-2">
                      <span className="text-[13px] text-muted">Opening range (minutes)</span>
                      <Segmented label="Opening range (minutes)" value={orm} options={["5", "15", "30"] as const} onChange={setOrm} />
                    </div>
                  )}
                </div>
                {levelsQ.isError && <Callout tone="danger" title="Levels could not be computed">{errText(levelsQ.error)}</Callout>}
                {lv ? <LevelsTable lv={lv} /> : !levelsQ.isError && <Placeholder height={200} />}
                {lv?.set === "Intraday" && levelSet === "Intraday" && timeframe !== "5-min" && timeframe !== "15-min" && (
                  <p className="mt-2 text-[12px] text-muted">Intraday levels use the last 5-minute session; the chart shows {timeframe.toLowerCase()} bars.</p>
                )}
                <div className="mt-4 flex flex-wrap gap-2">
                  <Button onClick={() => save.mutate()} disabled={!lv || save.isPending}><BookmarkPlus size={15} /> Save levels to journal</Button>
                  <Button onClick={() => send.mutate()} disabled={!lv || send.isPending}><Send size={15} /> Send levels to Paper Desk</Button>
                </div>
                {save.isSuccess && <p className="mt-2 text-[13px] text-muted">Saved with today's date for the weekly review.</p>}
                {send.isSuccess && <p className="mt-2 text-[13px] text-muted">Sent. Alerts can reference them by name, for example "OR high" or "VWAP".</p>}
              </Panel>
            )}

            {view === "describe" && (
              <Panel title="Describe" action={descQ.isFetching && <span className="text-[12px] text-muted">Reading the numbers…</span>}>
                {descQ.isError && <Callout tone="danger" title="Could not describe this chart">{errText(descQ.error)}</Callout>}
                {d && (d.claims ? (
                  <div className="grid gap-5 lg:grid-cols-2">
                    <div>
                      <h3 className="mb-2 text-[14px] font-semibold">Numbers answer</h3>
                      <NumberLines lines={d.lines} />
                    </div>
                    <div>
                      <h3 className="mb-1 text-[14px] font-semibold">Screenshot answer (unreliable)</h3>
                      <p className="mb-3 text-[12px] text-muted">Simulated vision reading: this build does not send images to a model. Each claim is checked against the table.</p>
                      <ClaimList claims={d.claims} />
                      <p className="num mt-3 text-[13px]"><span className="font-semibold text-bear">✗</span> marks: {d.crosses} of {d.claims.length}</p>
                    </div>
                  </div>
                ) : <NumberLines lines={d.lines} />)}
              </Panel>
            )}

            {view === null && (
              <EmptyState>Click Describe for a numbers-only reading of this chart, or Levels for its computed zones. Every value is computed in code first.</EmptyState>
            )}

            <AddTimeframe symbol={symbol} market={market} data={data} />
          </div>

          <div className="flex flex-col gap-3">
            <h2 className="text-[14px] font-semibold">{intradayTiles ? "Intraday levels" : "The numbers behind the chart"}</h2>
            {intradayTiles && lv?.values ? (
              <div className="grid grid-cols-2 gap-2.5">
                {Object.entries(lv.values).map(([k, v], i) => (
                  <FactTile key={k} label={k} value={num(v, market)} big={i === 4} />
                ))}
              </div>
            ) : d ? (
              <div className="grid grid-cols-2 gap-2.5">
                <FactTile label="Close" value={num(d.values.close, market)} big sub={`Last bar ${d.asof}`} />
                <FactTile label="ATR(14)" value={num(d.values.atr_14, market)} sub={`${((d.values.atr_14 / d.values.close) * 100).toFixed(2)}% of the close`} />
                <FactTile label="RSI(14)" value={d.values.rsi_14.toFixed(1)} sub={d.values.rsi_14_5ago !== undefined ? `${d.values.rsi_14_5ago.toFixed(1)} five bars ago` : undefined} />
                <FactTile label="SMA20" value={d.values.sma_20 !== undefined ? num(d.values.sma_20, market) : "—"} />
                <FactTile label="SMA50" value={d.values.sma_50 !== undefined ? num(d.values.sma_50, market) : "—"} />
                <FactTile label="20-bar range" value={<span className="text-[16px]">{num(d.values.low_20, market, 0)} to {num(d.values.high_20, market, 0)}</span>} />
              </div>
            ) : <Placeholder height={260} />}
            {view === "describe" && d && (
              <div className="mt-2">
                <ExplainPanel key={d.facts.join("|")} facts={d.facts} section="Research"
                  question={d.claims ? undefined : "Describe this chart from the numbers only. Cite each value."} />
              </div>
            )}
            {view === "levels" && lv && (
              <div className="mt-2">
                <ExplainPanel key={lv.facts.join("|")} facts={lv.facts} section="Research"
                  question="Describe where price is relative to each level, from the numbers only. Do not predict direction or suggest entries." />
              </div>
            )}
          </div>
        </div>
      </div>
    </FactsProvider>
  );
}

function NumberLines({ lines }: { lines: string[] }) {
  return (
    <ul className="flex flex-col gap-1.5">
      {lines.map((l, i) => (
        <li key={i} className="num flex gap-2 text-[14px]"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-muted" />{l}</li>
      ))}
    </ul>
  );
}

function ClaimList({ claims }: { claims: NonNullable<DescribeOut["claims"]> }) {
  return (
    <ul className="flex flex-col divide-y divide-line rounded-[var(--radius-tile)] border border-line">
      {claims.map((c, i) => {
        const ok = c.Check === "✓";
        return (
          <li key={i} className="flex gap-2.5 px-3 py-2">
            {ok ? <CheckCircle2 size={17} className="mt-0.5 shrink-0 text-bull" aria-label="Matches the table" />
              : <XCircle size={17} className="mt-0.5 shrink-0 text-bear" aria-label="Does not match the table" />}
            <div>
              <div className="text-[14px]">{c.Claim}</div>
              <div className="num text-[12px] text-muted">Against the table: {c["Against the table"]}</div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function LevelsTable({ lv }: { lv: LevelsOut }) {
  if (lv.set === "Intraday") {
    const cols: Column<Row>[] = [
      { key: "Level", header: "Level" },
      { key: "Value", header: "Value", align: "right", render: (r) => num(Number(r.Value)) },
    ];
    return (
      <>
        <DataTable rows={lv.table} columns={cols} />
        <p className="mt-2 text-[12px] text-muted">Opening range uses the first {lv.or_minutes} minutes. VWAP resets at the session open.</p>
      </>
    );
  }
  const cols: Column<Row>[] = [
    { key: "Level", header: "Level" },
    { key: "Zone", header: "Zone", align: "right" },
    { key: "Touches", header: "Touches", align: "right" },
    { key: "Distance", header: "Distance", align: "right",
      render: (r) => <span className={cn(r.Distance === "inside" && "font-medium text-indigo")}>{String(r.Distance)}</span> },
    { key: "±1 ATR", header: "±1 ATR", render: (r) => (r["±1 ATR"] ? <Badge tone="indigo">yes</Badge> : "") },
    { key: "From", header: "From", render: (r) => <span className="text-muted">{String(r.From)}</span> },
  ];
  return (
    <>
      <MetaList items={[["Close", num(lv.close)], ["ATR(14)", num(lv.atr)], ["As of", lv.asof]]} />
      <div className="mt-3"><DataTable rows={lv.table} columns={cols} /></div>
      <p className="mt-2 text-[12px] text-muted">Distance is from the nearest edge of the zone, in ATR; positive is above the close.</p>
    </>
  );
}

function AddTimeframe({ symbol, market, data }: { symbol: string; market: Market; data: string }) {
  const [frames, setFrames] = useState<string[]>(["Daily", "Weekly", "15-min"]);
  const run = useMutation({
    mutationFn: () => post<{ rows: Row[] }>(`${P}/timeframes`, { symbol, market, data, frames }),
  });
  useEffect(() => { run.reset(); }, [symbol, market]); // eslint-disable-line react-hooks/exhaustive-deps
  const rows = useMemo(() => run.data?.rows ?? [], [run.data]);
  // A row whose "Close vs SMA20" differs from the majority is worth a note.
  const majority = useMemo(() => {
    const n = rows.filter((r) => r["Close vs SMA20"] === "above").length;
    return n * 2 >= rows.length ? "above" : "below";
  }, [rows]);
  const cols: Column<Row>[] = [
    { key: "Timeframe", header: "Timeframe", render: (r) => (
      <span className="flex items-center gap-2">{r.Timeframe}{rows.length > 1 && r["Close vs SMA20"] !== majority && <Badge tone="warn">disagrees</Badge>}</span>) },
    { key: "Close", header: "Close", align: "right", render: (r) => num(Number(r.Close), market) },
    { key: "SMA20", header: "SMA20", align: "right", render: (r) => (r.SMA20 === null ? "—" : num(Number(r.SMA20), market)) },
    { key: "Close vs SMA20", header: "Close vs SMA20" },
    { key: "RSI(14)", header: "RSI(14)", align: "right", render: (r) => Number(r["RSI(14)"]).toFixed(1) },
    { key: "ATR(14)", header: "ATR(14)", align: "right", render: (r) => num(Number(r["ATR(14)"]), market) },
    { key: "20-bar high", header: "20-bar high", align: "right", render: (r) => num(Number(r["20-bar high"]), market) },
    { key: "20-bar low", header: "20-bar low", align: "right", render: (r) => num(Number(r["20-bar low"]), market) },
  ];
  return (
    <Disclosure title="Add timeframe" hint={`${symbol}, side by side`}>
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-[13px] text-muted">Timeframes</span>
        <ChipPicker label="Timeframes" options={[...TIMEFRAMES]} value={frames} onChange={setFrames} />
        <Button size="sm" onClick={() => run.mutate()} disabled={!frames.length || run.isPending}>
          {run.isPending ? "Adding…" : "Add timeframe"}
        </Button>
      </div>
      {run.isError && <div className="mt-3"><Callout tone="danger" title="Could not add these timeframes">{errText(run.error)}</Callout></div>}
      {run.data && (
        <div className="mt-4">
          <DataTable rows={rows} columns={cols} />
          <p className="mt-2 text-[12px] text-muted">A row that disagrees with the others is worth a note, not a decision.</p>
        </div>
      )}
    </Disclosure>
  );
}

