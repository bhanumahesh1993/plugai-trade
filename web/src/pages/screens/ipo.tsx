import { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, CheckCircle2, HelpCircle, Plus, Trash2, XCircle, BookmarkPlus, MessageSquareWarning } from "lucide-react";
import { get, post } from "@/lib/api";
import { money } from "@/lib/format";
import { cn } from "@/lib/cn";
import { Button, Panel, Field, Tabs, TabList, Tab, TabPanel, inputCls } from "@/components/ui";
import { FactTile, FactsProvider, ExplainPanel } from "@/components/facts";
import {
  Badge, Callout, DataTable, Dialog, EChart, EmptyState, Hypothetical, Segmented, Select, chartTokens, useToast, type Column,
} from "@/components/kit";
import { useMarket } from "@/components/shell";
import { MetaList, PageChip, Placeholder, errText, useDebounced } from "@/components/research-b/common";

const P = "/api/research-b/ipo";
type Row = Record<string, string | number | null>;
const inr = (x: number | null | undefined, d = 0) => money(x, "IN", d);

interface Issue {
  name: string; board: string; platform: string; price_low: number; price_high: number; lot: number;
  open_date: string; close_date: string; listing_date: string; allotment_date: string; rhp_sample: string;
}
interface Issues { issues: Issue[]; rules_as_of: string; sme_source: string; gmp_banner: string; scenarios: number[] }

export default function IpoDashboard() {
  const [market] = useMarket();
  const q = useQuery({ queryKey: ["rb-ipos"], queryFn: () => get<Issues>(`${P}/issues`) });
  const [pick, setPick] = useState<string | null>(null);
  const issues = q.data?.issues ?? [];
  const x = issues.find((i) => i.name === pick) ?? issues[0];

  return (
    <FactsProvider>
      <div className="flex flex-col gap-4">
        <p className="text-[13px] text-muted">Facts from the RHP with page chips; odds and tiles computed in code.</p>
        {market !== "IN" && (
          <Callout tone="info" title="The IPO Dashboard follows India's IPO process">
            ASBA, categories and SME platforms are Indian. Switch the market to India in the top bar; the fictional samples stay readable here.
          </Callout>
        )}
        <div className="grid gap-5 lg:grid-cols-[220px_minmax(0,1fr)]">
          <aside className="flex flex-col gap-3">
            <h2 className="text-[14px] font-semibold">IPOs open</h2>
            <div role="radiogroup" aria-label="IPOs open" className="flex flex-col gap-1.5">
              {!q.data && <Placeholder height={100} />}
              {issues.map((i) => {
                const on = i.name === x?.name;
                return (
                  <button key={i.name} role="radio" aria-checked={on} onClick={() => setPick(i.name)}
                    className={cn("rounded-[var(--radius-tile)] border px-3 py-2 text-left",
                      on ? "border-indigo bg-indigo-soft" : "border-line bg-panel hover:border-line-strong")}>
                    <div className={cn("text-[14px] font-medium", on && "text-indigo")}>{i.name}</div>
                    <div className="num text-[12px] text-muted">{i.board}, {inr(i.price_low)}–{inr(i.price_high)}</div>
                  </button>
                );
              })}
            </div>
            <AddIpo onAdded={(n) => setPick(n)} />
          </aside>

          {x ? <IssueView key={x.name} x={x} meta={q.data!} /> : q.isError ? <Callout tone="danger" title="Could not load IPOs">{errText(q.error)}</Callout> : <Placeholder height={400} />}
        </div>
      </div>
    </FactsProvider>
  );
}

function IssueView({ x, meta }: { x: Issue; meta: Issues }) {
  const sample = !!x.rhp_sample;
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-[var(--radius-panel)] border border-line bg-panel px-4 py-3">
        <span className="text-[16px] font-semibold">{x.name}</span>
        <Badge tone="neutral">{x.board}</Badge>
        <MetaList items={[["Platform", x.platform], ["Price band", `${inr(x.price_low)}–${inr(x.price_high)}`], ["Lot", x.lot],
          ["Open", x.open_date && x.close_date ? `${x.open_date} to ${x.close_date}` : "not set"]]} />
        {sample && <span className="ml-auto"><Badge tone="neutral">Fictional sample</Badge></span>}
      </div>
      <Tabs defaultValue="rhp">
        <TabList>
          <Tab value="rhp">RHP digest</Tab>
          <Tab value="sub">Subscription</Tab>
          <Tab value="gmp">GMP · unofficial</Tab>
          <Tab value="sme">SME checker</Tab>
          <Tab value="plan">Listing-day plan</Tab>
        </TabList>
        <TabPanel value="rhp" className="pt-5 outline-none"><RhpTab x={x} /></TabPanel>
        <TabPanel value="sub" className="pt-5 outline-none"><SubscriptionTab x={x} /></TabPanel>
        <TabPanel value="gmp" className="pt-5 outline-none"><GmpTab /></TabPanel>
        <TabPanel value="sme" className="pt-5 outline-none"><SmeTab x={x} /></TabPanel>
        <TabPanel value="plan" className="pt-5 outline-none"><PlanTab x={x} scenarios={meta.scenarios} /></TabPanel>
      </Tabs>
    </div>
  );
}

/* ================================================================ Add IPO */
function AddIpo({ onAdded }: { onAdded: (name: string) => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const blank = { name: "", board: "Mainboard" as "Mainboard" | "SME", platform: "", price_low: "100", price_high: "105", lot: "140", rhp_link: "" };
  const [f, setF] = useState(blank);
  const platform = f.platform || (f.board === "Mainboard" ? "NSE / BSE" : "NSE Emerge");
  const add = useMutation({
    mutationFn: () => post<{ name: string }>(`${P}/add`, { ...f, platform, price_low: Number(f.price_low), price_high: Number(f.price_high), lot: Number(f.lot) }),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["rb-ipos"] }); toast("Added IPO"); setOpen(false); setF(blank); onAdded(r.name); },
  });
  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)}><Plus size={14} /> Add IPO</Button>
      <Dialog open={open} onOpenChange={setOpen} title="Add IPO"
        footer={<><Button variant="quiet" onClick={() => setOpen(false)}>Cancel</Button>
          <Button variant="primary" onClick={() => add.mutate()} disabled={!f.name.trim() || add.isPending}>Add IPO</Button></>}>
        <div className="flex flex-col gap-3">
          <Field label="Company"><input className={inputCls} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} aria-label="Company" /></Field>
          <div className="flex items-center gap-3">
            <span className="text-[12px] text-muted">Board</span>
            <Segmented label="Board" value={f.board} options={["Mainboard", "SME"] as const} onChange={(b) => setF({ ...f, board: b, platform: "" })} />
          </div>
          <Field label="Platform"><input className={inputCls} value={platform} onChange={(e) => setF({ ...f, platform: e.target.value })} aria-label="Platform" /></Field>
          <div className="grid grid-cols-3 gap-3">
            <Field label="Price band low"><input type="number" min={0} className={inputCls} value={f.price_low} onChange={(e) => setF({ ...f, price_low: e.target.value })} /></Field>
            <Field label="Price band high"><input type="number" min={0} className={inputCls} value={f.price_high} onChange={(e) => setF({ ...f, price_high: e.target.value })} /></Field>
            <Field label="Lot size"><input type="number" min={1} className={inputCls} value={f.lot} onChange={(e) => setF({ ...f, lot: e.target.value })} /></Field>
          </div>
          <Field label="RHP link (opens in the Document Desk)"><input className={inputCls} value={f.rhp_link} onChange={(e) => setF({ ...f, rhp_link: e.target.value })} /></Field>
          {add.isError && <p className="text-[13px] text-bear">{errText(add.error)}</p>}
          <p className="text-[12px] text-muted">After adding, fill the figures from the RHP digest.</p>
        </div>
      </Dialog>
    </>
  );
}

/* ================================================================ RHP digest */
interface Rhp { tiles: Record<string, string>; quotes: Record<string, string>; rows: Row[]; facts: string[] }

function RhpTab({ x }: { x: Issue }) {
  const toast = useToast();
  const run = useMutation({ mutationFn: () => post<Rhp>(`${P}/rhp`, { name: x.name }) });
  const accept = useMutation({
    mutationFn: () => post(`${P}/rhp/accept`, { name: x.name }),
    onSuccess: () => toast("Saved the digest to the IPO's record"),
    onError: (e) => toast(errText(e), "danger"),
  });
  const [tile, setTile] = useState<string>("");
  const d = run.data;
  const tiles = d ? Object.entries(d.tiles) : [];
  const shown = tile && d?.tiles[tile] ? tile : tiles[0]?.[0] ?? "";
  const cols: Column<Row>[] = [
    { key: "Item", header: "Item", width: "30%", render: (r) => <span className="font-medium">{String(r.Item)}</span> },
    { key: "Quote", header: "Quote", render: (r) => r.status === "found"
      ? <span className="font-serif text-[14px]">“{String(r.Quote)}”</span> : <span className="text-muted">not found</span> },
    { key: "Page", header: "Page", render: (r) => <PageChip cite={String(r.Page)} /> },
  ];
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
      <div className="flex min-w-0 flex-col gap-5">
        <Panel>
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="primary" onClick={() => run.mutate()} disabled={run.isPending}>{run.isPending ? "Extracting…" : "Extract to table"}</Button>
            <span className="text-[13px] text-muted">Runs the RHP digest template in the Document Desk: eight items as quotes with page chips; tiles computed in code.</span>
          </div>
          {run.isError && <div className="mt-3"><Callout tone="danger" title="Could not extract">{errText(run.error)}</Callout></div>}
        </Panel>
        {d ? (
          <>
            {tiles.length ? (
              <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-3">
                {tiles.map(([k, v], i) => (
                  <button key={k} type="button" onClick={() => setTile(k)} aria-pressed={shown === k} title="Show the quote behind this tile"
                    className={cn("h-full rounded-[var(--radius-tile)] text-left [&>div]:h-full", shown === k && "ring-2 ring-indigo/50")}>
                    <FactTile label={k} value={<span className={i === 0 ? "" : "text-[17px]"}>{v}</span>} big={i === 0} />
                  </button>
                ))}
              </div>
            ) : (
              <EmptyState>No figures yet for {x.name}. A newly added IPO has no RHP numbers; open its RHP in the Document Desk and fill them in.</EmptyState>
            )}
            {tiles.length > 0 && (
              <Panel title="See the quote behind a tile">
                <Select value={shown} onChange={(e) => setTile(e.target.value)} className="max-w-[320px]" aria-label="See the quote behind a tile">
                  {tiles.map(([k]) => <option key={k}>{k}</option>)}
                </Select>
                <p className="mt-3 font-serif text-[15px] leading-[1.6]">{d.quotes[shown]}</p>
              </Panel>
            )}
            <Panel title="RHP digest, quoted">
              <DataTable rows={d.rows} columns={cols} empty="No RHP loaded for this issue. Add its RHP link, then extract again." />
              <p className="mt-2 text-[12px] text-muted">Open every page chip in the risk factors that names a customer, a related party or a lawsuit, and read the paragraph yourself.</p>
            </Panel>
          </>
        ) : <EmptyState>Click Extract to table to digest the RHP. Each figure comes back as a quote with its page; missing items say "not found".</EmptyState>}
      </div>
      <div className="flex flex-col gap-3">
        {d && <ExplainPanel key={d.facts.join("|")} facts={d.facts} section="Research" onAccept={() => accept.mutate()} />}
        {d && <p className="text-[12px] text-muted">Accept saves the digest to the IPO's record.</p>}
      </div>
    </div>
  );
}

/* ================================================================ Subscription */
interface Sub { rows: Row[]; by_day: Record<string, Row[]>; source: string }
interface Odds {
  category: string; p: number; at_least_one: number; money_blocked: number; lots_available: number;
  applications: number; is_estimate: boolean; applicants: number; facts: string[];
}

function SubscriptionTab({ x }: { x: Issue }) {
  const [day, setDay] = useState<"1" | "2" | "3">("3");
  const sub = useQuery({
    queryKey: ["rb-sub", x.name, day], queryFn: () => post<Sub>(`${P}/subscription`, { name: x.name, day: Number(day) }),
    placeholderData: keepPreviousData,
  });
  const [oddsOn, setOddsOn] = useState(false);
  const [apps, setApps] = useState("0");
  const [n, setN] = useState("1");
  const body = { name: x.name, applications: Number(useDebounced(apps)) || 0, applicants: Math.min(20, Math.max(1, Number(useDebounced(n)) || 1)) };
  const odds = useQuery({ queryKey: ["rb-odds", body], queryFn: () => post<Odds>(`${P}/odds`, body), enabled: oddsOn, placeholderData: keepPreviousData });
  const o = odds.data;

  const chart = useMemo(() => {
    if (!sub.data) return null;
    const t = chartTokens();
    const cats = sub.data.by_day["1"].filter((r) => !String(r.Category).startsWith("Overall") && !String(r.Category).startsWith("Anchors")).map((r) => String(r.Category));
    const shades = [t.indigo, t.muted, t.ink];
    return {
      grid: { left: 48, right: 64, top: 28, bottom: 28 },
      legend: { top: 0, textStyle: { color: t.muted } },
      tooltip: { trigger: "axis", backgroundColor: t.panel, borderColor: t.line, textStyle: { color: t.ink }, valueFormatter: (v: number) => `${v}×` },
      xAxis: { type: "category", data: ["Day 1", "Day 2", "Day 3 (final)"], axisLabel: { color: t.muted }, axisLine: { lineStyle: { color: t.line } } },
      yAxis: { type: "log", min: 0.5, axisLabel: { color: t.muted, formatter: "{value}×" }, splitLine: { lineStyle: { color: t.line } } },
      series: cats.map((c, i) => ({
        name: c, type: "bar", barMaxWidth: 26, itemStyle: { color: shades[i % 3], opacity: i === 1 ? 0.55 : 1 },
        data: ["1", "2", "3"].map((d) => Number(sub.data!.by_day[d].find((r) => r.Category === c)?.Times ?? 0)),
        ...(i === 0 ? { markLine: { symbol: "none", silent: true, lineStyle: { color: t.muted, type: "dashed" }, label: { formatter: "1×, fully\nsubscribed", color: t.muted, position: "end", fontSize: 11 }, data: [{ yAxis: 1 }] } } : {}),
      })),
    };
  }, [sub.data]);

  const cols: Column<Row>[] = [
    { key: "Category", header: "Category", render: (r) => (
      <span className={cn(String(r.Category).startsWith("Overall") && "font-medium", String(r.Category).startsWith("Anchors") && "text-muted")}>{String(r.Category)}</span>) },
    { key: "Shares offered", header: "Shares offered", align: "right", render: (r) => Number(r["Shares offered"]).toLocaleString("en-IN") },
    { key: "Shares bid", header: "Shares bid", align: "right", render: (r) => Number(r["Shares bid"]).toLocaleString("en-IN") },
    { key: "Times", header: "Times", align: "right", render: (r) => (r.Times === null ? <span className="text-muted">excluded</span> : <span className="font-medium">{Number(r.Times).toFixed(2)}×</span>) },
  ];
  const overall = sub.data?.rows.find((r) => String(r.Category).startsWith("Overall"));

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
      <div className="flex min-w-0 flex-col gap-5">
        <Panel title="Bids by category" action={<Segmented label="Day" value={day} options={[{ value: "1", label: "Day 1" }, { value: "2", label: "Day 2" }, { value: "3", label: "Day 3" }]} onChange={setDay} />}>
          <p className="mb-3 text-[12px] text-muted">Source: fictional sample bids. Anchors are shown on their own line and excluded from the multiples.</p>
          {sub.data ? <DataTable rows={sub.data.rows} columns={cols} /> : <Placeholder height={180} />}
        </Panel>
        <Panel title="How each category filled" action={<span className="text-[12px] text-muted">Log scale</span>}>
          {chart ? <EChart option={chart} height={240} /> : <Placeholder height={240} />}
          <p className="mt-1 text-[12px] text-muted">Read categories, not the overall number. Institutions often bid on the final day.</p>
        </Panel>
        <Panel title="Allotment odds" action={!oddsOn && <Button size="sm" variant="primary" onClick={() => setOddsOn(true)}>Allotment odds</Button>}>
          {oddsOn ? (
            <div className="flex flex-col gap-4">
              <div className="grid gap-3 md:grid-cols-2">
                <Field label="Valid applications (0 = use the lab's estimate)">
                  <input type="number" min={0} step={10000} className={inputCls} value={apps} onChange={(e) => setApps(e.target.value)} aria-label="Valid applications" />
                </Field>
                <Field label="Applicants" hint="Genuinely separate investors, each with their own PAN and demat.">
                  <input type="number" min={1} max={20} className={inputCls} value={n} onChange={(e) => setN(e.target.value)} aria-label="Applicants" />
                </Field>
              </div>
              {odds.isError && <Callout tone="danger" title="Could not compute the odds">{errText(odds.error)}</Callout>}
              {o ? (
                <div className="grid grid-cols-1 gap-2.5 md:grid-cols-3">
                  <FactTile label={`At least one of ${o.applicants}`} value={`${(o.at_least_one * 100).toFixed(2)}%`} big tone="indigo"
                    sub="1 − (1 − p)^n, draws treated as independent" />
                  <FactTile label="Chance of one lot per application" value={`${(o.p * 100).toFixed(2)}%`}
                    sub={`Chance of a lot${o.is_estimate ? " (estimate)" : ""}, ${o.category}`} />
                  <FactTile label="Money blocked in total" value={inr(o.money_blocked)} sub="Money blocked, released if not allotted" />
                  <FactTile label="Lots available" value={Math.round(o.lots_available).toLocaleString("en-IN")} />
                  <FactTile label={o.is_estimate ? "Valid applications (estimate)" : "Valid applications"} value={Math.round(o.applications).toLocaleString("en-IN")} />
                </div>
              ) : <Placeholder height={120} />}
            </div>
          ) : <p className="text-[13px] text-muted">After the issue closes, click Allotment odds. Type the valid applications from the exchange or registrar data, or leave the lab's labelled estimate.</p>}
        </Panel>
      </div>
      <div className="flex flex-col gap-3">
        <FactTile label="Overall (excl. anchors)" value={overall ? `${Number(overall.Times).toFixed(2)}×` : "—"} sub={`Day ${day}, a weighted average of the categories`} />
        {o && <ExplainPanel key={o.facts.join("|")} facts={o.facts} section="Research"
          question="Explain why more lots do not mean better odds, quoting the numbers. Do not suggest how to apply." />}
      </div>
    </div>
  );
}

/* ================================================================ GMP · unofficial */
interface Gmp { spread: number | null; note: string }

function GmpTab() {
  const [show, setShow] = useState(false);
  const [rows, setRows] = useState<{ source: string; gmp: string }[]>([
    { source: "Site A", gmp: "22" }, { source: "Site B", gmp: "35" }, { source: "Forwarded message", gmp: "48" },
  ]);
  const figures = Object.fromEntries(rows.filter((r) => r.source.trim() && r.gmp !== "" && !Number.isNaN(Number(r.gmp))).map((r) => [r.source.trim(), Number(r.gmp)]));
  const dFig = useDebounced(figures);
  const g = useQuery({ queryKey: ["rb-gmp", dFig], queryFn: () => post<Gmp>(`${P}/gmp`, { figures: dFig }), enabled: show, placeholderData: keepPreviousData });
  const set = (i: number, k: "source" | "gmp", v: string) => setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  return (
    <div className="flex max-w-[860px] flex-col gap-5">
      <div role="alert" className="rounded-[var(--radius-panel)] border-2 border-bear/60 bg-bear-soft px-4 py-3.5">
        <div className="flex items-center gap-2 text-[16px] font-semibold text-bear"><MessageSquareWarning size={18} /> Unofficial, unregulated, not a forecast</div>
        <p className="mt-1.5 text-[14px]">
          The grey market is not an exchange: no regulator, no visible order book, no settlement guarantee and no investor protection.
          Sites quote different figures for the same issue on the same day. These numbers are excluded from every tile, plan and odds calculation, and the AI is told never to use them.
        </p>
      </div>
      <Panel title="Grey-market figures" action={<Button size="sm" onClick={() => setShow((s) => !s)}>{show ? "Hide grey-market figures" : "Show grey-market figures"}</Button>}>
        {show ? (
          <div className="flex flex-col gap-4">
            <table className="w-full text-[14px]">
              <thead><tr className="border-b border-line text-left text-[12px] text-muted"><th className="pb-2 font-normal">Source</th><th className="w-[160px] pb-2 text-right font-normal">GMP (₹)</th><th className="w-10" /></tr></thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i} className="border-b border-line last:border-0">
                    <td className="py-1.5 pr-3"><input className={cn(inputCls, "h-8 font-sans")} value={r.source} onChange={(e) => set(i, "source", e.target.value)} aria-label={`Source ${i + 1}`} /></td>
                    <td className="py-1.5"><input type="number" className={cn(inputCls, "h-8 text-right")} value={r.gmp} onChange={(e) => set(i, "gmp", e.target.value)} aria-label={`GMP ${i + 1}`} /></td>
                    <td className="py-1.5 text-right"><button type="button" className="text-muted hover:text-bear" aria-label="Remove row" onClick={() => setRows(rows.filter((_, j) => j !== i))}><Trash2 size={15} /></button></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div><Button size="sm" variant="quiet" onClick={() => setRows([...rows, { source: "", gmp: "" }])}><Plus size={14} /> Add row</Button></div>
            <div className="grid max-w-[520px] grid-cols-2 items-start gap-3">
              <div className="rounded-[var(--radius-tile)] border border-dashed border-line-strong px-3 py-2.5">
                <div className="text-[12px] text-muted">Spread between sources</div>
                <div className="num mt-0.5 text-[20px] font-semibold">{g.data?.spread != null ? inr(g.data.spread) : "—"}</div>
                <div className="text-[12px] text-muted">Not a fact tile: never cited</div>
              </div>
              <p className="text-[13px] text-muted">{g.data?.note} The AI is told never to use it.</p>
            </div>
          </div>
        ) : <p className="text-[13px] text-muted">Hidden by default. If you open them, compare the sources side by side; the spread is usually the most honest number here.</p>}
      </Panel>
    </div>
  );
}

/* ================================================================ SME checker */
interface SmeInfo { sme: boolean; platform?: string; lot?: number; rules_as_of?: string; source?: string; has_doc?: boolean; liquidity?: Record<string, string> | null }
interface SmeRun { checks: (Row & { searched: string[] })[]; facts: string[] }

function SmeTab({ x }: { x: Issue }) {
  const toast = useToast();
  const info = useQuery({ queryKey: ["rb-sme", x.name], queryFn: () => post<SmeInfo>(`${P}/sme`, { name: x.name }) });
  const run = useMutation({ mutationFn: () => post<SmeRun>(`${P}/sme/run`, { name: x.name }) });
  const accept = useMutation({
    mutationFn: () => post(`${P}/sme/accept`, { name: x.name }),
    onSuccess: () => toast("Saved the check with the IPO record"),
    onError: (e) => toast(errText(e), "danger"),
  });
  const i = info.data;
  if (!i) return <Placeholder height={200} />;
  if (!i.sme) return <EmptyState>Pick an SME issue (NSE Emerge / BSE SME) from IPOs open, or Add IPO with the SME board.</EmptyState>;
  const icon = (s: string) => s === "meets" ? <CheckCircle2 size={16} className="text-bull" /> : s === "does not meet" ? <XCircle size={16} className="text-bear" /> : <HelpCircle size={16} className="text-saffron" />;
  const cols: Column<Row>[] = [
    { key: "Rule", header: "Rule", width: "30%" },
    { key: "Quoted figure", header: "Quoted figure", render: (r) => r["Quoted figure"] === "—" ? <span className="text-muted">—</span> : <span className="font-serif">“{String(r["Quoted figure"])}”</span> },
    { key: "Page", header: "Page", render: (r) => <PageChip cite={String(r.Page)} /> },
    { key: "Status", header: "Status", render: (r) => <span className="flex items-center gap-1.5 whitespace-nowrap">{icon(String(r.Status))}{String(r.Status)}</span> },
  ];
  const nf = run.data?.checks.filter((c) => c.Status === "not found") ?? [];
  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
      <div className="flex min-w-0 flex-col gap-5">
        <Panel>
          <MetaList items={[["Platform", i.platform], ["Lot", i.lot], ["Rules as of", i.rules_as_of], ["Source", i.source]]} />
          {i.has_doc ? (
            <div className="mt-4 flex items-center gap-3">
              <Button variant="primary" onClick={() => run.mutate()} disabled={run.isPending}>{run.isPending ? "Checking…" : "Run checks"}</Button>
              <span className="text-[13px] text-muted">Each dated rule becomes a row: the quoted RHP figure, its page and a status.</span>
            </div>
          ) : <div className="mt-4"><Callout tone="info" title="No RHP loaded">Load this issue's RHP in the Document Desk first.</Callout></div>}
          {run.isError && <div className="mt-3"><Callout tone="danger" title="Could not run the checks">{errText(run.error)}</Callout></div>}
        </Panel>
        {run.data && (
          <Panel title="Checks">
            <DataTable rows={run.data.checks} columns={cols} />
            {nf.map((c) => (
              <p key={String(c.Rule)} className="mt-2 text-[13px] text-muted">{String(c.Rule)}: pages searched {c.searched.join(", ") || "none"}</p>
            ))}
          </Panel>
        )}
        {i.liquidity && (
          <Panel title="Liquidity">
            <dl className="grid gap-x-4 gap-y-2 text-[14px] md:grid-cols-[180px_minmax(0,1fr)]">
              {Object.entries(i.liquidity).map(([k, v]) => (
                <div key={k} className="contents"><dt className="text-muted">{k}</dt><dd className={cn(v.startsWith("“") && "font-serif")}>{v}</dd></div>
              ))}
            </dl>
          </Panel>
        )}
      </div>
      <div className="flex flex-col gap-3">
        {run.data ? (
          <>
            {(() => {
              const c = run.data!.checks;
              const k = (st: string) => c.filter((x) => x.Status === st).length;
              return (
                <FactTile label="Rules met" value={`${k("meets")} of ${c.length}`} big tone={k("does not meet") ? "bear" : undefined}
                  sub={`${k("does not meet")} do not meet, ${k("not found")} not found`} />
              );
            })()}
            <ExplainPanel key={run.data.facts.join("|")} facts={run.data.facts} section="Research" onAccept={() => accept.mutate()} />
            <p className="text-[12px] text-muted">Accept saves the check with the IPO record.</p>
          </>
        ) : <p className="text-[13px] text-muted">Run checks to see how many dated rules the RHP meets.</p>}
      </div>
    </div>
  );
}

/* ================================================================ Listing-day plan */
interface PlanOut { shares: number; issue_price: number; listing_date: string | null; plan: Row[] }

function PlanTab({ x, scenarios }: { x: Issue; scenarios: number[] }) {
  const toast = useToast();
  const [shares, setShares] = useState(String(x.lot * (x.board === "SME" ? 2 : 1)));
  const [rows, setRows] = useState(() => scenarios.map((s) => ({ pct: String(s), action: "" })));
  useEffect(() => { setRows(scenarios.map((s) => ({ pct: String(s), action: "" }))); }, [scenarios]);
  const body = {
    name: x.name, shares: Math.max(0, Math.floor(Number(useDebounced(shares)) || 0)),
    scenarios: useDebounced(rows).map((r) => Number(r.pct) || 0), actions: rows.map((r) => r.action),
  };
  const plan = useQuery({ queryKey: ["rb-plan", body.name, body.shares, body.scenarios], queryFn: () => post<PlanOut>(`${P}/plan`, body), placeholderData: keepPreviousData });
  const critique = useMutation({ mutationFn: () => post<{ text: string }>(`${P}/plan/critique`, body) });
  const lock = useMutation({
    mutationFn: () => post<{ rows: Row[]; alerts: number }>(`${P}/plan/lockin`, { name: x.name }),
    onSuccess: (r) => toast(`Added ${r.alerts} lock-in dates to Alerts`),
    onError: (e) => toast(errText(e), "danger"),
  });
  const save = useMutation({
    mutationFn: () => post(`${P}/plan/save`, body),
    onSuccess: () => toast("Saved to journal"),
    onError: (e) => toast(errText(e), "danger"),
  });
  const p = plan.data;
  const set = (i: number, k: "pct" | "action", v: string) => setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const worst = p?.plan.reduce((m, r) => Math.min(m, Number(r.Change)), 0) ?? 0;

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
      <div className="flex min-w-0 flex-col gap-5">
        <Panel title="Scenarios" action={<Hypothetical />}>
          <div className="mb-4 flex flex-wrap items-end gap-4">
            <Field label="Shares allotted">
              <input type="number" min={0} className={cn(inputCls, "w-[160px]")} value={shares} onChange={(e) => setShares(e.target.value)} aria-label="Shares allotted" />
            </Field>
            <MetaList items={[["Issue price", inr(x.price_high)], ["Listing date", x.listing_date || "not set"]]} />
          </div>
          <div className="scroll-thin overflow-x-auto">
            <table className="w-full text-[14px]">
              <thead>
                <tr className="border-b border-line text-left text-[12px] text-muted">
                  <th className="w-[120px] pb-2 pr-3 font-normal">Opening vs issue price, %</th>
                  <th className="pb-2 pr-3 text-right font-normal">Price</th>
                  <th className="pb-2 pr-3 text-right font-normal">Value</th>
                  <th className="pb-2 pr-3 text-right font-normal">Change</th>
                  <th className="pb-2 font-normal">Your action</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => {
                  const c = p?.plan[i];
                  const ch = Number(c?.Change ?? 0);
                  return (
                    <tr key={i} className="border-b border-line last:border-0">
                      <td className="py-1.5 pr-3"><input type="number" step={1} className={cn(inputCls, "h-8 w-[88px]")} value={r.pct} onChange={(e) => set(i, "pct", e.target.value)} aria-label={`Opening vs issue price, row ${i + 1}`} /></td>
                      <td className="num whitespace-nowrap py-1.5 pr-3 text-right">{c ? inr(Number(c.Price), 2) : "—"}</td>
                      <td className="num whitespace-nowrap py-1.5 pr-3 text-right">{c ? inr(Number(c.Value)) : "—"}</td>
                      <td className={cn("num whitespace-nowrap py-1.5 pr-3 text-right font-medium", ch > 0 && "text-bull", ch < 0 && "text-bear")}>{c ? `${ch > 0 ? "+" : ""}${inr(ch)}` : "—"}</td>
                      <td className="py-1.5"><input className={cn(inputCls, "h-8 min-w-[240px] font-sans")} placeholder="Your written rule for this opening" value={r.action} onChange={(e) => set(i, "action", e.target.value)} aria-label={`Your action, row ${i + 1}`} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[12px] text-muted">Values before brokerage, charges and tax. Your actions are your written rules.</p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button onClick={() => critique.mutate()} disabled={critique.isPending}>{critique.isPending ? "Critiquing…" : "Critique"}</Button>
            <Button onClick={() => lock.mutate()} disabled={lock.isPending}><CalendarClock size={15} /> Lock-in calendar</Button>
            <Button onClick={() => save.mutate()} disabled={save.isPending || !p}><BookmarkPlus size={15} /> Save to journal</Button>
          </div>
          {save.isSuccess && <p className="mt-2 text-[13px] text-muted">Saved. A Post-listing review reminder is set for day 30.</p>}
        </Panel>
        {critique.data && (
          <Panel title="Critique">
            <p className="whitespace-pre-line font-serif text-[15px] leading-[1.6]">{critique.data.text}</p>
            <p className="mt-2 text-[12px] text-muted">Checks in code come first; the sceptic reads your plan against your Rule Card and never recommends buying or selling.</p>
          </Panel>
        )}
        {critique.isError && <Callout tone="danger" title="Critique failed">{errText(critique.error)}</Callout>}
        {lock.data && (
          <Panel title="Lock-in calendar">
            <DataTable rows={lock.data.rows} columns={[
              { key: "Holder", header: "Holder" },
              { key: "Unlocks", header: "Unlocks", render: (r) => <span className="num whitespace-nowrap">{String(r.Unlocks)}</span> },
              { key: "Day", header: "Day", align: "right" },
              { key: "Shares", header: "Shares", align: "right", render: (r) => Number(r.Shares).toLocaleString("en-IN") },
              { key: "% of all shares", header: "% of all shares", align: "right", render: (r) => `${Number(r["% of all shares"]).toFixed(1)}%` },
            ]} empty="No lock-in pools for this issue (no anchors or pre-IPO holders recorded)." />
            <p className="mt-2 text-[12px] text-muted">Unlock dates added to your plan and proposed in Paper Trading, Alerts. Nothing is active until you click Accept there.</p>
          </Panel>
        )}
      </div>
      <div className="flex flex-col gap-3">
        <FactTile label="Worst scenario" value={p ? inr(worst) : "—"} tone={worst < 0 ? "bear" : undefined} big
          sub={p ? `on ${p.shares.toLocaleString("en-IN")} shares at ${inr(p.issue_price)}` : undefined} />
        <FactTile label="Position at issue price" value={p ? inr(p.shares * p.issue_price) : "—"} />
        <p className="text-[13px] text-muted">Write the plan the evening allotment arrives. On listing day it opens beside the pre-open price.</p>
      </div>
    </div>
  );
}
