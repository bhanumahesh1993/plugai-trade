import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { FileUp } from "lucide-react";
import { get, post, type Market } from "@/lib/api";
import { Button, Field, Panel } from "@/components/ui";
import { Callout, DataTable, EChart, EmptyState, Hypothetical, Select, Switch, chartTokens } from "@/components/kit";
import { ExplainPanel, FactTile, FactsProvider } from "@/components/facts";
import { useMarket } from "@/components/shell";
import { ErrorLine, Hint, readFile } from "@/components/research/common";

interface Setup { fields: string[]; horizons: Record<string, number>; horizon: string; presets: string[]; preset: string }
interface Columns { columns: string[]; guess: Record<string, string | null>; rows: number; preview: Record<string, string>[] }
interface Report {
  market: Market; horizon_days: number; buckets: { label: string; return: number; names: number }[];
  universe_return: number; spread: number; hit_share: number; hit_dates: number; n_dates: number;
  coverage: { min: number; median: number; max: number }; cost_preset: string; cost_pct: number;
  include_delisted: boolean; warnings: string[]; facts: string[]; assumed_next_day: boolean;
}

const NONE = "";
const signed = (x: number, unit: string, d = 2) => `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x).toFixed(d)}${unit}`;
const tone = (x: number) => (x > 0 ? "bull" : x < 0 ? "bear" : undefined);

function BucketChart({ r }: { r: Report }) {
  const t = chartTokens();
  return (
    <EChart height={260} option={{
      grid: { left: 56, right: 16, top: 24, bottom: 44 },
      tooltip: { trigger: "axis", backgroundColor: t.panel, borderColor: t.line, textStyle: { color: t.ink },
        formatter: (ps: { dataIndex: number }[]) => { const b = r.buckets[ps[0].dataIndex]; return `${b.label}<br/>${signed(b.return, "%")} after costs<br/>${b.names} score-dates`; } },
      xAxis: { type: "category", name: "Score bucket", nameLocation: "middle", nameGap: 28, nameTextStyle: { color: t.muted },
        data: r.buckets.map((b) => b.label), axisLine: { lineStyle: { color: t.line } }, axisLabel: { color: t.muted }, axisTick: { show: false } },
      yAxis: { type: "value", name: "Average return after costs, %", nameTextStyle: { color: t.muted, align: "left" },
        axisLabel: { color: t.muted, formatter: (v: number) => `${v}%` }, splitLine: { lineStyle: { color: t.line } } },
      series: [{
        type: "bar", barMaxWidth: 56,
        data: r.buckets.map((b) => ({ value: b.return, itemStyle: { color: b.return >= 0 ? t.bull : t.bear, borderRadius: 3 } })),
        markLine: { symbol: "none", silent: true, lineStyle: { color: t.ink, type: "dashed" },
          label: { formatter: `Universe ${signed(r.universe_return, "%")}`, color: t.muted, position: "insideEndTop" },
          data: [{ yAxis: r.universe_return }] },
      }],
    }} />
  );
}

export default function ScoreTester() {
  const [market] = useMarket();
  const fileRef = useRef<HTMLInputElement>(null);
  const { data: setup } = useQuery({ queryKey: ["st-setup", market], queryFn: () => get<Setup>(`/api/research/score-tester/setup?market=${market}`) });
  const [raw, setRaw] = useState<{ name: string; csv: string } | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [horizon, setHorizon] = useState("3 months");
  const [delisted, setDelisted] = useState(true);
  const [preset, setPreset] = useState("");
  useEffect(() => { if (setup) { setPreset(setup.preset); setHorizon(setup.horizon); } }, [setup]);

  const cols = useQuery({
    queryKey: ["st-cols", raw?.csv], enabled: !!raw,
    queryFn: () => post<Columns>("/api/research/score-tester/columns", { csv: raw!.csv }), retry: false,
  });
  useEffect(() => {
    if (cols.data) setMapping(Object.fromEntries(Object.entries(cols.data.guess).map(([k, v]) => [k, v ?? (k === "Published at" ? NONE : cols.data!.columns[0])])));
  }, [cols.data]);

  const sample = useMutation({
    mutationFn: () => get<{ name: string; csv: string }>(`/api/research/score-tester/sample?market=${market}`),
    onSuccess: (s) => { setRaw(s); test.reset(); },
  });
  const test = useMutation({
    mutationFn: () => post<Report>("/api/research/score-tester/run", {
      csv: raw!.csv, market, horizon, include_delisted: delisted, cost_preset: preset,
      mapping: Object.fromEntries(Object.entries(mapping).map(([k, v]) => [k, v || null])) }),
  });
  const r = test.data && test.data.market === market ? test.data : undefined;
  const onFile = async (f?: File) => { if (f) { setRaw({ name: f.name, csv: await readFile(f, "text") }); test.reset(); } };

  return (
    <FactsProvider>
      <div className="flex flex-col gap-5">
        <Panel title="Vendor scores" action={<span className="text-[13px] text-muted">Did higher scores do better after costs, on the dates they were published?</span>}>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="primary" onClick={() => fileRef.current?.click()}><FileUp size={15} /> Import vendor score CSV</Button>
            <input ref={fileRef} type="file" accept=".csv,text/csv" hidden onChange={(e) => { onFile(e.target.files?.[0]); e.target.value = ""; }} />
            <Button onClick={() => sample.mutate()} disabled={sample.isPending}>Use the synthetic sample CSV</Button>
            {raw && <span className="text-[13px] text-muted">{raw.name}{cols.data && `, ${cols.data.rows.toLocaleString("en-US")} rows`}</span>}
          </div>
          <div className="mt-3"><ErrorLine error={cols.error ?? sample.error} /></div>
          {!raw && (
            <EmptyState>Export past scores from the vendor as a CSV with date, symbol and score (and ideally a published-at column), then import it.</EmptyState>
          )}
          {cols.data && (
            <div className="mt-2 flex flex-col gap-4">
              <div>
                <div className="mb-2 text-[14px] font-semibold">Column mapper</div>
                <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                  {(setup?.fields ?? ["Date", "Symbol", "Score", "Published at"]).map((fld) => (
                    <Field key={fld} label={fld}>
                      <Select value={mapping[fld] ?? ""} onChange={(e) => setMapping((m) => ({ ...m, [fld]: e.target.value }))}>
                        {fld === "Published at" && <option value={NONE}>None (assume next-day use)</option>}
                        {cols.data.columns.map((c) => <option key={c}>{c}</option>)}
                      </Select>
                    </Field>
                  ))}
                </div>
                {!mapping["Published at"] && <Hint className="mt-2">No publication time: the lab assumes next-day use and says so in Warnings.</Hint>}
              </div>
              <div className="grid gap-3 md:grid-cols-[180px_220px_240px_auto] md:items-end">
                <Field label="Horizon">
                  <Select value={horizon} onChange={(e) => setHorizon(e.target.value)}>
                    {Object.keys(setup?.horizons ?? {}).map((h) => <option key={h}>{h}</option>)}
                  </Select>
                </Field>
                <div className="pb-0.5"><Switch checked={delisted} onChange={setDelisted} label="Include delisted" hint="At last traded price" /></div>
                <Field label="Cost preset">
                  <Select value={preset} onChange={(e) => setPreset(e.target.value)}>
                    {setup?.presets.map((p) => <option key={p}>{p}</option>)}
                  </Select>
                </Field>
                <Button variant="primary" className="justify-self-start" onClick={() => test.mutate()} disabled={test.isPending}>
                  {test.isPending ? "Lining up scores with later prices…" : "Point-in-time test"}
                </Button>
              </div>
              <ErrorLine error={test.error} />
            </div>
          )}
        </Panel>

        {r && (
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
            <div className="flex min-w-0 flex-col gap-5">
              <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
                <FactTile label="Top-minus-bottom spread" value={signed(r.spread, " pts")} tone={tone(r.spread)} sub="top bucket minus bottom, after costs" big />
                <FactTile label="Universe average" value={signed(r.universe_return, "%")} tone={tone(r.universe_return)} sub={`over ${r.horizon_days} days`} />
                <FactTile label="Hit share (top beat universe)" value={`${r.hit_share.toFixed(0)}%`} sub={`${r.hit_dates} of ${r.n_dates} dates`} />
                <FactTile label="Coverage" value={r.coverage.median.toFixed(0)} sub={`names per date, ${r.coverage.min.toFixed(0)}–${r.coverage.max.toFixed(0)}`} />
              </div>
              <Panel title="Report" action={<Hypothetical />}>
                {r.buckets.length ? <BucketChart r={r} /> : <p className="text-muted">No score could be matched to prices. Check the column mapper and the market.</p>}
                <div className="mt-3 grid grid-cols-2 gap-2.5 md:grid-cols-5">
                  {r.buckets.map((b) => (
                    <FactTile key={b.label} label={`Bucket ${b.label}`} value={signed(b.return, "%")} tone={tone(b.return)} sub={`${b.names} score-dates`} />
                  ))}
                </div>
                <Hint className="mt-3">Costs: {r.cost_preset}, {r.cost_pct.toFixed(2)}% round trip from the dated table. Delisted names {r.include_delisted ? "included at last traded price" : "excluded"}. Hypothetical.</Hint>
              </Panel>
              <Panel title="Warnings">
                {r.warnings.length ? (
                  <div className="flex flex-col gap-2">{r.warnings.map((w) => <Callout key={w} tone="warn">{w}</Callout>)}</div>
                ) : <p className="text-muted">No warnings.</p>}
              </Panel>
            </div>
            <div className="flex flex-col gap-4">
              <Panel title="Explain the report">
                <Hint className="mb-3">The AI narrates the report and quotes its numbers. Second opinion argues the opposite reading.</Hint>
                <ExplainPanel facts={r.facts} section="Research" />
              </Panel>
              {cols.data && (
                <Panel title="First rows of your CSV">
                  <DataTable rows={cols.data.preview} columns={cols.data.columns.slice(0, 4).map((c) => ({ key: c, header: c, render: (row: Record<string, string>) => <span className="num whitespace-nowrap text-[13px]">{row[c]}</span> }))} />
                </Panel>
              )}
            </div>
          </div>
        )}
      </div>
    </FactsProvider>
  );
}
