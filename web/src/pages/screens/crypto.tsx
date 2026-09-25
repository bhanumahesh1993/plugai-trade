/* Portfolio › Crypto Monitor (Chapter 25). Public data only, no exchange keys, paper only. */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { ChevronDown, Database, ExternalLink, KeyRound, Plus } from "lucide-react";
import { get, post, type Market } from "@/lib/api";
import { money, num } from "@/lib/format";
import { cn } from "@/lib/cn";
import { Button, Panel, Field, Slider, Tabs, TabList, Tab, TabPanel } from "@/components/ui";
import { FactsProvider, FactTile } from "@/components/facts";
import { Badge, Callout, DataTable, Dialog, EmptyState, Hypothetical, Select, Textarea, EChart, chartTokens, ScreenGrid, useToast, type Column } from "@/components/kit";
import { useMarket } from "@/components/shell";
import { LocalExplainPanel, TileGrid, RailTitle, FilePick, fileToB64, errText, NumInput, type ApiTileT } from "@/components/portfolio/common";

interface Pos { index: number; symbol: string; side: string; notional: number; notional_text: string; leverage: number; entry: number; margin_mode: string; venue: string; kind: string }
interface WatchData { rows: Record<string, unknown>[]; source: string; positions: Pos[]; venues: string[]; default_maintenance_pct: number; fiu_url: string }

/** Provenance strings from the engine use middle dots; the new design uses commas. */
const plain = (s: unknown) => String(s ?? "").replace(/ · /g, ", ");

const watchKey = (m: Market) => ["crypto", m, "watch"];
const useWatch = (m: Market) => useQuery({ queryKey: watchKey(m), queryFn: () => get<WatchData>(`/api/portfolio/crypto/watch?market=${m}`) });

function Collapsible({ title, children, defaultOpen = false }: { title: string; children: React.ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="rounded-[var(--radius-panel)] border border-line bg-panel">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="flex w-full items-center gap-1.5 px-4 py-2.5 text-left text-[14px] font-semibold hover:text-indigo">
        <ChevronDown size={15} className={cn("transition-transform", !open && "-rotate-90")} /> {title}
      </button>
      {open && <div className="border-t border-line p-4">{children}</div>}
    </section>
  );
}

/* ------------------------------------------------------------------ Add position */
function AddPositionDialog({ open, onOpenChange, market, venues, mm }: { open: boolean; onOpenChange: (v: boolean) => void; market: Market; venues: string[]; mm: number }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [f, setF] = useState({ venue: "binance", symbol: "BTC", kind: "perpetual", side: "long", notional: market === "IN" ? 500_000 : 5_000,
    leverage: 10, margin_mode: "isolated", entry: 60_000, maintenance_pct: mm });
  const add = useMutation({
    mutationFn: () => post<WatchData>("/api/portfolio/crypto/positions", { market, ...f }),
    onSuccess: (d) => { qc.setQueryData(watchKey(market), d); qc.invalidateQueries({ queryKey: ["crypto", market] }); toast("Added position"); onOpenChange(false); },
  });
  const sel = (k: keyof typeof f, opts: string[]) => (
    <Select value={String(f[k])} onChange={(e) => setF({ ...f, [k]: e.target.value })}>{opts.map((o) => <option key={o}>{o}</option>)}</Select>
  );
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Add position"
      footer={<><Button variant="quiet" onClick={() => onOpenChange(false)}>Cancel</Button><Button variant="primary" onClick={() => add.mutate()} disabled={add.isPending}>Add</Button></>}>
      <div className="grid grid-cols-3 gap-3">
        <Field label="Venue">{sel("venue", venues)}</Field>
        <Field label="Contract">{sel("symbol", ["BTC", "ETH"])}</Field>
        <Field label="Type">{sel("kind", ["perpetual", "spot"])}</Field>
        <Field label="Side">{sel("side", ["long", "short"])}</Field>
        <Field label={`Notional (${market === "IN" ? "₹" : "$"})`}><NumInput value={f.notional} min={0} step={1000} onChange={(v) => setF({ ...f, notional: v })} /></Field>
        <Field label="Leverage"><NumInput value={f.leverage} min={1} max={125} step={1} onChange={(v) => setF({ ...f, leverage: v })} /></Field>
        <Field label="Margin mode">{sel("margin_mode", ["isolated", "cross"])}</Field>
        <Field label="Entry price"><NumInput value={f.entry} min={0} onChange={(v) => setF({ ...f, entry: v })} /></Field>
        <Field label="Maintenance margin % (venue tier)"><NumInput value={f.maintenance_pct} min={0} max={10} step={0.1} onChange={(v) => setF({ ...f, maintenance_pct: v })} /></Field>
      </div>
      <p className="mt-3 flex items-center gap-1.5 text-[13px] text-muted"><KeyRound size={13} /> No exchange key is needed or accepted. The position is watched on paper only.</p>
      {add.error && <p className="mt-2 text-[13px] text-bear">{errText(add.error)}</p>}
    </Dialog>
  );
}

/* ------------------------------------------------------------------ Watch */
function FiuCheck({ url }: { url: string }) {
  const toast = useToast();
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const { data: notes = [] } = useQuery({ queryKey: ["crypto", "fiu"], queryFn: () => get<{ created: string; text: string }[]>("/api/portfolio/crypto/fiu-notes") });
  const save = useMutation({
    mutationFn: () => post<{ created: string; text: string }[]>("/api/portfolio/crypto/fiu-notes", { text: note }),
    onSuccess: (d) => { qc.setQueryData(["crypto", "fiu"], d); setNote(""); toast("Saved note"); },
  });
  return (
    <Collapsible title="FIU-IND registration check">
      <p className="text-[14px]">Indian venues serving Indian users must register with FIU-IND. Check the official list before you deposit:{" "}
        <a href={url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-indigo underline">{url} <ExternalLink size={12} /></a>. The lab does not judge any venue.</p>
      <div className="mt-3"><Field label="Your note (venue, date you checked, what the list showed)"><Textarea value={note} onChange={(e) => setNote(e.target.value)} /></Field></div>
      <Button className="mt-2" onClick={() => save.mutate()} disabled={!note.trim() || save.isPending}>Save note</Button>
      {notes.map((n, i) => <p key={i} className="mt-2 text-[13px] text-muted"><span className="num">{n.created}</span>: {n.text}</p>)}
    </Collapsible>
  );
}

function WatchTab({ market }: { market: Market }) {
  const { data: w } = useWatch(market);
  const [adding, setAdding] = useState(false);
  const perp = w?.rows.find((r) => r.Type === "perpetual");
  const cols: Column<Record<string, unknown>>[] = [
    { key: "Symbol", header: "Symbol" }, { key: "Type", header: "Type" }, { key: "Venue", header: "Venue" }, { key: "Side", header: "Side" },
    { key: "Spot", header: "Spot", align: "right", render: (r) => num(r.Spot as number, "US") },
    { key: "Perp", header: "Perp", align: "right", render: (r) => r.Perp == null ? "—" : num(r.Perp as number, "US") },
    { key: "Basis", header: "Basis", align: "right", render: (r) => r.Basis == null ? "—" : `${(r.Basis as number) >= 0 ? "+" : "−"}${Math.abs((r.Basis as number) * 100).toFixed(3)}%` },
    { key: "Notional", header: "Notional", align: "right" }, { key: "Leverage", header: "Leverage", align: "right" },
    { key: "Margin mode", header: "Margin mode" }, { key: "Source", header: "Source", render: (r) => plain(r.Source) },
  ];
  return (
    <ScreenGrid rail={
      <>
        <RailTitle>Perp against spot</RailTitle>
        <FactTile label="Basis" big value={perp ? `${(perp.Basis as number) >= 0 ? "+" : "−"}${Math.abs((perp.Basis as number) * 100).toFixed(3)}%` : "—"}
          sub={perp ? `${perp.Symbol} perp against spot` : "Add a perpetual position"} />
        <p className="text-[13px] text-muted">Basis is the perp's gap to spot, the input behind the funding rate.</p>
      </>
    }>
      <Panel title="Watch" action={<Button size="sm" onClick={() => setAdding(true)} disabled={!w}><Plus size={14} /> Add position</Button>}>
        <DataTable rows={w?.rows ?? []} columns={cols} empty="Nothing watched yet. Click Add position." />
      </Panel>
      {market === "IN" && w && <FiuCheck url={w.fiu_url} />}
      {w && <AddPositionDialog open={adding} onOpenChange={setAdding} market={market} venues={w.venues} mm={w.default_maintenance_pct} />}
    </ScreenGrid>
  );
}

/* ------------------------------------------------------------------ Funding rates */
interface FundingData {
  empty: boolean; index: number; source: string; prints: number; print_no: number; rate: number; times_per_day: number;
  perps: { index: number; label: string }[]; tiles: ApiTileT[]; facts: string[];
  history: { print: number[]; time: string[]; rate_pct: number[]; cumulative: number[] };
  liquidation: Record<string, unknown>[]; position: Pos;
}

function FundingTab({ market }: { market: Market }) {
  const toast = useToast();
  const qc = useQueryClient();
  const [idx, setIdx] = useState<number | null>(null);
  const [times, setTimes] = useState(3);
  const [printNo, setPrint] = useState<number | null>(null);
  const [level, setLevel] = useState(0.03);
  const { data: d } = useQuery({
    queryKey: ["crypto", market, "funding", idx, times, printNo],
    queryFn: () => post<FundingData>("/api/portfolio/crypto/funding", { market, index: idx, times_per_day: times, print_no: printNo }),
    placeholderData: keepPreviousData,
  });
  const send = useMutation({
    mutationFn: () => post<{ count: number }>("/api/portfolio/crypto/send-alerts", { market, index: d?.index, level_pct: level }),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["crypto", "alerts"] }); toast(`Sent ${r.count} alerts to Alerts as proposals`); },
    onError: (e) => toast(errText(e), "danger"),
  });
  const t = chartTokens();
  if (d?.empty) return <EmptyState>Add a perpetual position on the Watch tab to see funding tiles.</EmptyState>;
  const h = d?.history;
  const option = h && {
    grid: [{ left: 60, right: 16, top: 16, height: 150 }, { left: 60, right: 16, top: 214, height: 100 }],
    tooltip: { trigger: "axis", backgroundColor: t.panel, borderColor: t.line, textStyle: { color: t.ink } },
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    xAxis: [{ type: "category", data: h.print, gridIndex: 0, axisLabel: { show: false }, axisLine: { lineStyle: { color: t.line } } },
      { type: "category", data: h.print, gridIndex: 1, name: "Funding print", nameLocation: "middle", nameGap: 26, nameTextStyle: { color: t.muted }, axisLabel: { color: t.muted, interval: 14 }, axisLine: { lineStyle: { color: t.line } } }],
    yAxis: [{ type: "value", gridIndex: 0, name: "% per 8 h", nameTextStyle: { color: t.muted, align: "left" }, axisLabel: { color: t.muted }, splitLine: { lineStyle: { color: t.line } } },
      { type: "value", gridIndex: 1, splitNumber: 3, name: "Cumulative paid", nameTextStyle: { color: t.muted, align: "left" }, axisLabel: { color: t.muted, formatter: (v: number) => money(v, market) }, splitLine: { lineStyle: { color: t.line } } }],
    series: [
      { name: "Funding % per 8 h", type: "bar", data: h.rate_pct.map((v, i) => ({ value: +v.toFixed(4), itemStyle: { color: i + 1 === d!.print_no ? t.ink : t.indigo } })),
        markLine: { symbol: "none", silent: true, data: [{ yAxis: level, lineStyle: { color: t.muted, type: "dashed" }, label: { formatter: `Alert ${level}%`, color: t.muted, position: "insideEndTop" } }] } },
      { name: "Cumulative paid", type: "line", xAxisIndex: 1, yAxisIndex: 1, data: h.cumulative.map((v) => Math.round(v)), showSymbol: false, lineStyle: { color: t.ink, width: 2 }, itemStyle: { color: t.ink },
        markLine: { symbol: "none", silent: true, data: [{ xAxis: String(d!.print_no), lineStyle: { color: t.ink }, label: { show: false } }] } },
    ],
  };
  return (
    <ScreenGrid rail={
      <>
        <RailTitle>What the position costs to hold</RailTitle>
        <TileGrid tiles={d?.tiles.filter((x) => x.big)} />
        <TileGrid tiles={d?.tiles.filter((x) => !x.big)} />
        {d && <LocalExplainPanel facts={d.facts} />}
        <Panel title="Funding alert">
          <Field label="Funding alert level (% per 8 h)"><NumInput value={level} min={0} max={1} step={0.005} onChange={setLevel} /></Field>
          <Button className="mt-3" onClick={() => send.mutate()} disabled={!d || send.isPending}>Send to Alerts</Button>
          <p className="mt-2 text-[13px] text-muted">Proposes the funding, liquidation-distance, price-band and exchange-notice alerts in Paper Trading, Alerts (From Crypto Monitor). Nothing is active until you click Accept there.</p>
        </Panel>
      </>
    }>
      <Panel title="Funding rates" action={<span className="flex items-center gap-1.5 text-[12px] text-muted"><Database size={13} /> Funding source: {d ? plain(d.source) : "…"}</span>}>
        <div className="grid gap-3 md:grid-cols-[minmax(0,1.3fr)_140px_minmax(0,1fr)] md:items-end">
          <Field label="Position">
            <Select value={d?.index ?? ""} onChange={(e) => { setIdx(Number(e.target.value)); setPrint(null); }}>
              {d?.perps.map((p) => <option key={p.index} value={p.index}>{p.label}</option>)}
            </Select>
          </Field>
          <Field label="Funding times per day"><NumInput value={times} min={1} max={24} step={1} onChange={(v) => setTimes(Math.min(24, Math.max(1, Math.round(v))))} /></Field>
          <Field label={`Print ${d?.print_no ?? ""} of ${d?.prints ?? ""}${d ? `, ${plain(d.history.time[d.print_no - 1])}` : ""}`}>
            <div className="flex h-9 items-center"><Slider label="Print" min={1} max={d?.prints ?? 90} value={d?.print_no ?? 40} onChange={setPrint} /></div>
          </Field>
        </div>
        <div className="mt-4">{option ? <EChart option={option} height={340} /> : <div style={{ height: 340 }} />}</div>
        <p className="mt-1 text-[13px] text-muted">Bars: each completed funding print (highlighted bar: the print the tiles use). Line: funding paid so far on this notional (negative means received).</p>
      </Panel>
      <Collapsible title="Leverage and the liquidation line">
        <DataTable rows={d?.liquidation ?? []} columns={[
          { key: "Leverage", header: "Leverage" },
          { key: "Fall to liquidation %", header: "Fall to liquidation %", align: "right", render: (r) => `${r["Fall to liquidation %"]}%` },
          { key: "Liquidation price", header: "Liquidation price", align: "right", render: (r) => num(r["Liquidation price"] as number, "US") },
          { key: "Margin", header: "Margin", align: "right", render: (r) => money(r.Margin as number, market) },
        ]} />
        <p className="mt-2 text-[13px] text-muted">Model: isolated margin, maintenance as a share of entry notional, fees and funding ignored. Funding paid comes out of margin, so the real line is closer.</p>
      </Collapsible>
    </ScreenGrid>
  );
}

/* ------------------------------------------------------------------ Alerts */
interface AlertsData { types: string[]; rows: { id: number; type: string; alert: string; quiet_hours: string; status: string }[] }

function AlertsTab({ market }: { market: Market }) {
  const toast = useToast();
  const qc = useQueryClient();
  const { data: a } = useQuery({ queryKey: ["crypto", "alerts"], queryFn: () => get<AlertsData>("/api/portfolio/crypto/alerts") });
  const { data: w } = useWatch(market);
  const [kinds, setKinds] = useState<string[] | null>(null);
  const [pos, setPos] = useState(0);
  const chosen = kinds ?? a?.types ?? [];
  const send = useMutation({
    mutationFn: () => post<{ count: number }>("/api/portfolio/crypto/send-alerts", { market, index: pos, kinds: chosen }),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["crypto", "alerts"] }); toast(`Sent ${r.count} alerts to Alerts as proposals`); },
    onError: (e) => toast(errText(e), "danger"),
  });
  return (
    <ScreenGrid rail={
      <>
        <RailTitle>Propose alerts</RailTitle>
        <Field label="Position">
          <Select value={pos} onChange={(e) => setPos(Number(e.target.value))}>
            {w?.positions.map((p) => <option key={p.index} value={p.index}>{`${p.symbol} ${p.kind}, ${p.side}, ${p.venue}`}</option>)}
          </Select>
        </Field>
        <div role="group" aria-label="Propose" className="flex flex-col gap-1.5">
          <span className="text-[12px] text-muted">Propose</span>
          {(a?.types ?? []).map((k) => (
            <label key={k} className="flex items-center gap-2 text-[14px]">
              <input type="checkbox" className="h-4 w-4 accent-[var(--indigo)]" checked={chosen.includes(k)}
                onChange={(e) => setKinds(e.target.checked ? [...chosen, k] : chosen.filter((x) => x !== k))} /> {k}
            </label>
          ))}
        </div>
        <Button onClick={() => send.mutate()} disabled={!chosen.length || send.isPending}>Send to Alerts</Button>
        <p className="text-[13px] text-muted">Accept them in Paper Trading, Alerts. Nothing is active until you do.</p>
      </>
    }>
      <Panel title="Crypto alerts">
        <p className="mb-1 text-[13px] text-muted">Crypto alert types: {a?.types.join(", ")}. Checked in code on completed prints and 4-hour closes; every message starts with SIMULATED.</p>
        <p className="mb-3 text-[13px] text-muted">Quiet hours (set in Alerts): only Funding and Liquidation distance may sound between 23:00 and 06:00.</p>
        <DataTable rows={(a?.rows ?? []) as unknown as Record<string, unknown>[]} rowKey={(r) => r.id as number}
          empty="No crypto alerts yet. Use Send to Alerts on the Funding rates tab, or propose them here." columns={[
            { key: "type", header: "Type" }, { key: "alert", header: "Alert" },
            { key: "quiet_hours", header: "Quiet hours", render: (r) => r.quiet_hours === "may sound" ? <Badge tone="indigo">May sound</Badge> : <Badge>Held</Badge> },
            { key: "status", header: "Status", render: (r) => <Badge tone={r.status === "active" ? "indigo" : "neutral"}>{String(r.status).charAt(0).toUpperCase() + String(r.status).slice(1)}</Badge> },
          ]} />
      </Panel>
    </ScreenGrid>
  );
}

/* ------------------------------------------------------------------ India VDA ledger */
interface LedgerData { rows: Record<string, unknown>[]; tiles: ApiTileT[]; facts: string[]; cess_pct: number; cess_in_table: boolean; vda_rate: number; vda_tds: number }
interface RecData { rows: Record<string, unknown>[]; self_check: boolean; mismatches: number }

function LedgerTab({ market }: { market: Market }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [cess, setCess] = useState<number | null>(null);
  const [trades, setTrades] = useState<File | null>(null);
  const [stmt, setStmt] = useState<File | null>(null);
  const { data: d } = useQuery({
    queryKey: ["crypto", "ledger", cess], enabled: market === "IN",
    queryFn: () => post<LedgerData>("/api/portfolio/crypto/ledger", { cess_pct: cess }), placeholderData: keepPreviousData,
  });
  const imp = useMutation({
    mutationFn: async () => post<{ imported: number }>("/api/portfolio/crypto/ledger/import", { content_b64: await fileToB64(trades!) }),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["crypto", "ledger"] }); rec.reset(); toast(`Imported tradebook: ${r.imported} sales`); },
  });
  const rec = useMutation({
    mutationFn: async () => post<RecData>("/api/portfolio/crypto/ledger/reconcile", { cess_pct: cess, statement_b64: stmt ? await fileToB64(stmt) : null }),
  });
  if (market !== "IN") return <Callout tone="info" title="India only">The India VDA ledger applies to Indian residents. US readers: Tax, Tax Export has the 1099-DA check (rows with basis not reported are flagged).</Callout>;
  const rupee = (k: string) => (r: Record<string, unknown>) => r[k] == null ? "—" : money(r[k] as number, "IN");
  return (
    <ScreenGrid rail={
      <>
        <RailTitle>Schedule VDA, draft for your CA</RailTitle>
        <TileGrid tiles={d?.tiles.slice(0, 1)} />
        <TileGrid tiles={d?.tiles.slice(1)} />
        {d && <LocalExplainPanel facts={d.facts} section="Tax" />}
      </>
    }>
      <Panel title="India VDA ledger">
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto_140px] md:items-end">
          <Field label="Exchange trade-history CSV (trade, asset, bought, sold, tds)"><FilePick accept=".csv" file={trades} onFile={setTrades} /></Field>
          <Button onClick={() => imp.mutate()} disabled={!trades || imp.isPending}>Import tradebook</Button>
          <Field label="Cess %" hint={d && !d.cess_in_table ? "Not in the dated table yet; confirm the rate." : undefined}>
            <NumInput value={cess ?? d?.cess_pct ?? 4} min={0} max={10} step={0.5} onChange={setCess} />
          </Field>
        </div>
        {imp.error && <p className="mt-2 text-[13px] text-bear">{errText(imp.error)}</p>}
        <div className="mt-4">
          <DataTable rows={d?.rows ?? []} columns={[
            { key: "Trade", header: "Trade" }, { key: "Asset", header: "Asset" },
            { key: "Bought", header: "Bought", align: "right", render: rupee("Bought") }, { key: "Sold", header: "Sold", align: "right", render: rupee("Sold") },
            { key: "Gains", header: "Gains", align: "right", render: (r) => <span className={(r.Gains as number) > 0 ? "text-bull" : ""}>{money(r.Gains as number, "IN")}</span> },
            { key: "Losses", header: "Losses", align: "right", render: (r) => <span className={(r.Losses as number) < 0 ? "text-bear" : ""}>{money(r.Losses as number, "IN")}</span> },
            { key: "TDS 1%", header: "TDS 1%", align: "right", render: rupee("TDS 1%") },
          ]} />
        </div>
        <p className="mt-2 text-[13px] text-muted">Gains and losses are kept apart and never netted: a VDA loss cannot be set off.
          {d && ` Rates from the dated table (VDA ${Math.round(d.vda_rate * 100)}%, TDS ${Math.round(d.vda_tds * 100)}%).`}</p>
      </Panel>
      <Panel title="Reconcile TDS">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Form 26AS / AIS export (CSV with a TDS column)"><FilePick accept=".csv" file={stmt} onFile={(f) => { setStmt(f); rec.reset(); }} /></Field>
          <Button onClick={() => rec.mutate()} disabled={rec.isPending}>Reconcile TDS</Button>
        </div>
        {rec.error && <p className="mt-2 text-[13px] text-bear">{errText(rec.error)}</p>}
        {rec.data && (
          <div className="mt-3">
            <DataTable rows={rec.data.rows} columns={[
              { key: "Trade", header: "Trade" },
              { key: "Ledger TDS", header: "Ledger TDS", align: "right", render: rupee("Ledger TDS") },
              { key: "26AS / AIS", header: "26AS / AIS", align: "right", render: rupee("26AS / AIS") },
              { key: "Status", header: "Status", render: (r) => r.Status === "matched" ? <Badge>Matched</Badge> : <Badge tone="warn">Mismatch, ask your CA</Badge> },
            ]} />
            {rec.data.self_check && <p className="mt-2 text-[13px] text-muted">No statement chosen: showing the ledger against itself. Import 26AS or AIS.</p>}
          </div>
        )}
      </Panel>
    </ScreenGrid>
  );
}

export default function CryptoMonitor() {
  const [market] = useMarket();
  const [tab, setTab] = useState("Watch");
  const { data: w } = useWatch(market);
  return (
    <FactsProvider>
      <div className="flex flex-col gap-5">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1 rounded-[var(--radius-panel)] border border-line bg-panel px-4 py-2.5 text-[13px]">
          <span className="flex items-center gap-1.5"><KeyRound size={14} className="text-muted" /> Public data only. No exchange keys. Paper only.</span>
          <span className="flex items-center gap-1.5 text-muted"><Database size={14} /> {w ? plain(w.source) : "…"}</span>
          <span className="ml-auto"><Hypothetical /></span>
        </div>
        <Tabs value={tab} onValueChange={setTab}>
          <TabList>{["Watch", "Funding rates", "Alerts", "India VDA ledger"].map((t) => <Tab key={t} value={t}>{t}</Tab>)}</TabList>
          <div className="pt-5">
            <TabPanel value="Watch"><WatchTab market={market} /></TabPanel>
            <TabPanel value="Funding rates"><FundingTab market={market} /></TabPanel>
            <TabPanel value="Alerts"><AlertsTab market={market} /></TabPanel>
            <TabPanel value="India VDA ledger"><LedgerTab market={market} /></TabPanel>
          </div>
        </Tabs>
        <p className="text-[12px] text-muted">Paper only. PlugAI-Trade never places real orders.</p>
      </div>
    </FactsProvider>
  );
}
