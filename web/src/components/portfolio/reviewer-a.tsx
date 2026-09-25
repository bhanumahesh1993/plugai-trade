/* Portfolio Reviewer: Holdings, Overlap, Costs, Concentration tabs. */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { get, post, type Market } from "@/lib/api";
import { money, num } from "@/lib/format";
import { Button, Panel, Field, inputCls } from "@/components/ui";
import { FactTile } from "@/components/facts";
import { Badge, Callout, DataTable, EmptyState, Hypothetical, Select, Switch, EChart, chartTokens, ScreenGrid, useToast, type Column } from "@/components/kit";
import { LocalExplainPanel, TileGrid, RailTitle, FilePick, fileToB64, download, errText, NumInput, type ApiTileT } from "./common";

export interface HoldingRow { index: number; name: string; units: number; price: number; value: number; asset_class: string; account: string; plan: string; match: string | null; matched_to: string | null }
export interface HoldingsData { market: Market; label: string; rows: HoldingRow[]; count: number; total: number; total_text: string; unmatched: number; catalogue: { id: string; name: string }[] }

export const holdingsKey = (m: Market) => ["pf", m, "holdings"];
export function useHoldings(market: Market) {
  return useQuery({ queryKey: holdingsKey(market), queryFn: () => get<HoldingsData>(`/api/portfolio/holdings?market=${market}`) });
}

/* ------------------------------------------------------------------ Holdings */
export function HoldingsTab({ market }: { market: Market }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: h } = useHoldings(market);
  const match = useMutation({
    mutationFn: (v: { index: number; fund_id: string }) => post<HoldingsData>("/api/portfolio/match", { market, ...v }),
    onSuccess: (d) => { qc.setQueryData(holdingsKey(market), d); qc.invalidateQueries({ queryKey: ["pf", market] }); toast("Matched by hand"); },
    onError: (e) => toast(errText(e), "danger"),
  });
  const cols: Column<HoldingRow & Record<string, unknown>>[] = [
    { key: "name", header: "Name" },
    { key: "units", header: "Units", align: "right", render: (r) => num(r.units, market, 3) },
    { key: "price", header: "Price / NAV", align: "right", render: (r) => num(r.price, market) },
    { key: "value", header: "Value", align: "right", render: (r) => money(r.value, market) },
    { key: "asset_class", header: "Asset class" },
    { key: "account", header: "Account" },
    { key: "plan", header: "Plan", render: (r) => r.plan || "—" },
    { key: "matched_to", header: "Matched to", render: (r) => r.matched_to ?? <Badge tone="warn">Unmatched</Badge> },
  ];
  const unmatched = h?.rows.filter((r) => !r.match) ?? [];
  return (
    <ScreenGrid rail={
      <>
        <RailTitle>Check against your statement</RailTitle>
        <div className="grid grid-cols-2 gap-2.5">
          <div className="col-span-2"><FactTile label="Total value" value={h?.total_text ?? "…"} big /></div>
          <FactTile label="Holdings" value={h?.count ?? "…"} />
          <FactTile label="Unmatched" value={h?.unmatched ?? "…"} sub={h?.unmatched ? "Match by hand below" : "All matched"} />
        </div>
        <p className="text-[13px] text-muted">Rows the importer could not match to a known fund are marked Unmatched. Pick the scheme or ticker by hand so they count in Overlap, Costs and Concentration.</p>
      </>
    }>
      <Panel title="Holdings" action={<span className="text-[13px] text-muted">{h?.label}</span>}>
        <DataTable rows={(h?.rows ?? []) as (HoldingRow & Record<string, unknown>)[]} columns={cols} rowKey={(r) => r.index}
          empty="No holdings yet. Click Import holdings above, or Load sample portfolio." />
      </Panel>
      {unmatched.length > 0 && (
        <Panel title="Match by hand">
          <div className="flex flex-col gap-3">
            {unmatched.map((r) => (
              <Field key={r.index} label={`Match '${r.name}' by hand`}>
                <Select value="" disabled={match.isPending}
                  onChange={(e) => e.target.value && match.mutate({ index: r.index, fund_id: e.target.value })}>
                  <option value="">Pick the scheme or ticker</option>
                  {h?.catalogue.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </Select>
              </Field>
            ))}
          </div>
        </Panel>
      )}
    </ScreenGrid>
  );
}

/* ------------------------------------------------------------------ Overlap */
interface OverlapData { funds: { id: string; name: string }[]; cells: { row: string; col: string; overlap: number; shared: { company: string; weight: number }[] }[]; facts: string[]; tiles: ApiTileT[]; csv: string }

function Heatmap({ d }: { d: OverlapData }) {
  const t = chartTokens();
  const ids = d.funds.map((f) => f.id);
  const nameOf = Object.fromEntries(d.funds.map((f) => [f.id, f.name]));
  const data = d.cells.map((c) => [ids.indexOf(c.col), ids.indexOf(c.row), c.overlap]);
  const shared = Object.fromEntries(d.cells.map((c) => [`${c.row}|${c.col}`, c.shared]));
  const option = {
    grid: { left: 150, right: 12, top: 8, bottom: 30 },
    tooltip: {
      backgroundColor: t.panel, borderColor: t.line, textStyle: { color: t.ink, fontSize: 12 },
      formatter: (p: { value: number[] }) => {
        const [x, y, v] = p.value;
        const s = shared[`${ids[y]}|${ids[x]}`] ?? [];
        return `<b>${nameOf[ids[y]]} and ${nameOf[ids[x]]}: ${v}%</b><br/>` +
          (x === y ? "Same fund" : s.length ? "Shared: " + s.map((r) => `${r.company} ${r.weight.toFixed(1)}%`).join(", ") : "No shared companies");
      },
    },
    xAxis: { type: "category", data: ids, axisLine: { lineStyle: { color: t.line } }, axisLabel: { color: t.muted }, splitArea: { show: false } },
    yAxis: { type: "category", data: d.funds.map((f) => f.name), inverse: true, axisLine: { lineStyle: { color: t.line } }, axisLabel: { color: t.ink } },
    visualMap: { show: false, min: 0, max: 100, inRange: { color: [t.panel, t.indigo] } },
    series: [{ type: "heatmap", data, itemStyle: { borderColor: t.panel, borderWidth: 3, borderRadius: 4 },
      label: { show: true, fontSize: 13, fontWeight: 600,
        formatter: (p: { value: number[] }) => `{${p.value[2] > 60 ? "hi" : "lo"}|${p.value[2]}}`,
        rich: { hi: { color: t.panel, fontSize: 13, fontWeight: 600 }, lo: { color: t.ink, fontSize: 13, fontWeight: 600 } } } }],
  };
  return <EChart option={option} height={48 * d.funds.length + 44} />;
}

export function OverlapTab({ market }: { market: Market }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: d, isLoading } = useQuery({ queryKey: ["pf", market, "overlap"], queryFn: () => get<OverlapData>(`/api/portfolio/overlap?market=${market}`) });
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const add = useMutation({
    mutationFn: async () => post<OverlapData & { added: string; companies: number }>("/api/portfolio/fund-file",
      { market, name, content_b64: await fileToB64(file!) }),
    onSuccess: (r) => { qc.setQueryData(["pf", market, "overlap"], r); qc.invalidateQueries({ queryKey: ["pf", market] }); toast(`Added ${r.added}: ${r.companies} companies`); setFile(null); setName(""); },
  });
  const ok = (d?.funds.length ?? 0) >= 2;
  return (
    <ScreenGrid rail={
      <>
        <RailTitle>Overlap</RailTitle>
        <TileGrid tiles={d?.tiles.slice(0, 1)} />
        <TileGrid tiles={d?.tiles.slice(1)} />
        {ok && <LocalExplainPanel facts={d!.facts} />}
      </>
    }>
      <Panel title="Overlap matrix" action={ok && <Button size="sm" onClick={() => { download("overlap.csv", d!.csv); toast("Exported overlap.csv"); }}><Download size={14} /> Export CSV</Button>}>
        <p className="mb-3 text-[13px] text-muted">Overlap is the share of money in the same companies (the sum of the smaller weight). Uses each fund's latest published portfolio; the bundled funds are synthetic. Hover a cell to see the shared companies.</p>
        {isLoading ? <div style={{ height: 284 }} /> : ok ? <Heatmap d={d!} /> :
          <EmptyState>Overlap needs at least two funds with look-through holdings. Match holdings by hand, or add a fund holdings file below.</EmptyState>}
      </Panel>
      <Panel title="Add fund holdings file (AMFI monthly portfolio / fund-house CSV)">
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-end">
          <Field label="Holdings CSV: company, weight (% to NAV), sector">
            <FilePick accept=".csv" file={file} onFile={setFile} />
          </Field>
          <Field label="Fund name"><input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Button onClick={() => add.mutate()} disabled={!file || !name.trim() || add.isPending}>Add fund</Button>
        </div>
        {add.error && <p className="mt-2 text-[13px] text-bear">{errText(add.error)}</p>}
      </Panel>
    </ScreenGrid>
  );
}

/* ------------------------------------------------------------------ Costs */
interface CostsData {
  rows: Record<string, unknown>[]; tiles: ApiTileT[]; facts: string[];
  fee_gap: { amount: number; years: number; gross_pct: number; low_pct: number; high_pct: number; cheaper_text: string; dearer_text: string; difference_text: string };
}

export function CostsTab({ market }: { market: Market }) {
  const [equityOnly, setEquityOnly] = useState(true); // the book's Ch 15 figure (₹10,680) is equity funds only
  const [gap, setGap] = useState<Record<Market, { amount?: number; years?: number; gross_pct?: number; low_pct?: number; high_pct?: number }>>({ IN: {}, US: {} });
  const g = gap[market];
  const { data: d, error } = useQuery({
    queryKey: ["pf", market, "costs", equityOnly, g],
    queryFn: () => post<CostsData>("/api/portfolio/costs", { market, equity_only: equityOnly, ...g }),
    placeholderData: keepPreviousData,
  });
  const fg = d?.fee_gap;
  const setG = (k: keyof typeof g) => (v: number) => setGap((s) => ({ ...s, [market]: { ...s[market], [k]: v } }));
  const pctCell = (k: string) => (r: Record<string, unknown>) => (r[k] == null ? "—" : `${num(r[k] as number, market)}%`);
  const moneyCell = (k: string) => (r: Record<string, unknown>) => money(r[k] as number | null, market);
  const cols: Column<Record<string, unknown>>[] = [
    { key: "Fund", header: "Fund" }, { key: "Plan", header: "Plan" },
    { key: "Value", header: "Value", align: "right", render: moneyCell("Value") },
    { key: "TER %", header: "TER %", align: "right", render: pctCell("TER %") },
    ...(market === "IN" ? [{ key: "Direct TER %", header: "Direct TER %", align: "right" as const, render: pctCell("Direct TER %") }] : []),
    { key: "A year", header: "A year", align: "right", render: moneyCell("A year") },
    ...(market === "IN" ? [
      { key: "Direct, a year", header: "Direct, a year", align: "right" as const, render: moneyCell("Direct, a year") },
      { key: "Difference a year", header: "Difference a year", align: "right" as const, render: moneyCell("Difference a year") },
    ] : []),
  ];
  return (
    <ScreenGrid rail={
      <>
        <RailTitle>What the funds cost you</RailTitle>
        <TileGrid tiles={d?.tiles.slice(0, 1)} />
        <TileGrid tiles={d?.tiles.slice(1)} />
        {d && <LocalExplainPanel facts={d.facts} />}
      </>
    }>
      <Panel title="Expense ratios" action={market === "IN" && (
        <div className="w-[190px]"><Switch checked={equityOnly} onChange={setEquityOnly} label="Equity funds only" /></div>)}>
        {error && <p className="text-bear">{errText(error)}</p>}
        <DataTable rows={d?.rows ?? []} columns={cols} empty="No matched funds yet. Match holdings by hand on the Holdings tab." />
        {market === "IN" && <div className="mt-3"><Callout tone="warn">Switching to direct plans can trigger capital-gains tax and exit loads. New SIP money can switch at once; old units are a tax judgment for you or your CA.</Callout></div>}
      </Panel>
      <Panel title="What an expense-ratio gap does over time" action={<Hypothetical />}>
        <p className="mb-3 text-[13px] text-muted">Illustrative assumption, held constant.</p>
        <div className="grid grid-cols-2 items-end gap-3 md:grid-cols-5">
          <Field label="Amount"><NumInput value={fg?.amount ?? ""} step={1000} onChange={setG("amount")} /></Field>
          <Field label="Years"><NumInput value={fg?.years ?? ""} step={1} onChange={setG("years")} /></Field>
          <Field label="Assumed return % (before fees)"><NumInput value={fg?.gross_pct ?? ""} step={0.5} onChange={setG("gross_pct")} /></Field>
          <Field label="Cheaper fee %"><NumInput value={fg?.low_pct ?? ""} step={0.05} onChange={setG("low_pct")} /></Field>
          <Field label="Dearer fee %"><NumInput value={fg?.high_pct ?? ""} step={0.05} onChange={setG("high_pct")} /></Field>
        </div>
        <div className="mt-4 grid grid-cols-3 gap-2.5">
          <FactTile label="Cheaper fund" value={fg?.cheaper_text ?? "…"} />
          <FactTile label="Dearer fund" value={fg?.dearer_text ?? "…"} />
          <FactTile label="Difference" value={fg?.difference_text ?? "…"} tone="bear" />
        </div>
      </Panel>
    </ScreenGrid>
  );
}

/* ------------------------------------------------------------------ Concentration */
interface ConcData { empty: boolean; tiles: ApiTileT[]; facts: string[]; top: { company: string; share: number }[]; sectors: { sector: string; share: number }[] }

export function ConcentrationTab({ market }: { market: Market }) {
  const { data: d } = useQuery({ queryKey: ["pf", market, "conc"], queryFn: () => get<ConcData>(`/api/portfolio/concentration?market=${market}`) });
  const t = chartTokens();
  if (d?.empty) return <EmptyState>No look-through holdings yet. Match your funds on the Holdings tab, or add a fund holdings file on the Overlap tab.</EmptyState>;
  const secs = d?.sectors ?? [];
  const option = {
    grid: { left: 150, right: 40, top: 6, bottom: 24 },
    tooltip: { backgroundColor: t.panel, borderColor: t.line, textStyle: { color: t.ink }, valueFormatter: (v: number) => `${v.toFixed(1)}%` },
    xAxis: { type: "value", axisLabel: { color: t.muted, formatter: "{value}%" }, splitLine: { lineStyle: { color: t.line } } },
    yAxis: { type: "category", inverse: true, data: secs.map((s) => s.sector), axisLabel: { color: t.ink }, axisLine: { lineStyle: { color: t.line } } },
    series: [{ type: "bar", data: secs.map((s) => +(s.share * 100).toFixed(1)), itemStyle: { color: t.indigo, borderRadius: [0, 3, 3, 0] }, barWidth: 14,
      label: { show: true, position: "right", color: t.muted, formatter: "{c}%" } }],
  };
  return (
    <ScreenGrid rail={
      <>
        <RailTitle>Look-through</RailTitle>
        <TileGrid tiles={d?.tiles.slice(0, 1)} />
        <TileGrid tiles={d?.tiles.slice(1)} />
        {d && <LocalExplainPanel facts={d.facts} />}
      </>
    }>
      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Top 10 companies">
          <DataTable rows={(d?.top ?? []) as unknown as Record<string, unknown>[]} columns={[
            { key: "company", header: "Company" },
            { key: "share", header: "Share", align: "right", render: (r) => `${((r.share as number) * 100).toFixed(2)}%` },
          ]} />
        </Panel>
        <Panel title="Sectors">
          <EChart option={option} height={Math.max(220, secs.length * 26 + 30)} />
        </Panel>
      </div>
    </ScreenGrid>
  );
}
