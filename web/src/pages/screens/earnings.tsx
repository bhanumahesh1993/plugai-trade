import { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { BellPlus, BookmarkPlus, ExternalLink, Sparkles } from "lucide-react";
import { get, post, type Market } from "@/lib/api";
import { num } from "@/lib/format";
import { cn } from "@/lib/cn";
import { Button, Panel, Field, Slider, Tabs, TabList, Tab, TabPanel, inputCls } from "@/components/ui";
import { FactTile, FactsProvider, ExplainPanel } from "@/components/facts";
import {
  Badge, Callout, DataTable, EmptyState, Hypothetical, Select, Switch, chartTokens, useToast, type Column,
} from "@/components/kit";
import { useMarket } from "@/components/shell";
import { ClickChart } from "@/components/research-b/ClickChart";
import { ChipPicker, Disclosure, FileDrop, MetaList, PageChip, Placeholder, errText, useDebounced } from "@/components/research-b/common";

const P = "/api/research-b/earnings";
type Row = Record<string, string | number | null>;

interface Setup {
  watchlists: { name: string; symbols: string[] }[]; positions: string[]; sample: string[]; samples: string[];
  move_default: string; actual_moves_filled: number; today: string;
}

export default function EarningsDesk() {
  const [market] = useMarket();
  const setup = useQuery({ queryKey: ["rb-earn-setup", market], queryFn: () => get<Setup>(`${P}/setup?market=${market}`) });
  return (
    <FactsProvider>
      <div className="flex flex-col gap-4">
        <p className="text-[13px] text-muted">Dates with sources, digests with page chips, moves computed in code.</p>
        <Tabs defaultValue="calendar">
          <TabList>
            <Tab value="calendar">Results calendar</Tab>
            <Tab value="digest">Results digest</Tab>
            <Tab value="move">Implied vs historical move</Tab>
          </TabList>
          <TabPanel value="calendar" className="pt-5 outline-none"><CalendarTab market={market} setup={setup.data} /></TabPanel>
          <TabPanel value="digest" className="pt-5 outline-none"><DigestTab market={market} setup={setup.data} /></TabPanel>
          <TabPanel value="move" className="pt-5 outline-none"><MoveTab market={market} setup={setup.data} /></TabPanel>
        </Tabs>
      </div>
    </FactsProvider>
  );
}

/* ================================================================ Results calendar */
interface CalOut { rows: Row[]; facts: string[] }

function CalendarTab({ market, setup }: { market: Market; setup?: Setup }) {
  const toast = useToast();
  const [picks, setPicks] = useState<string[]>([]);
  const [namesBy, setNamesBy] = useState<Partial<Record<Market, string>>>({});
  const names = namesBy[market] ?? setup?.sample.join(", ") ?? "";
  const setNames = (v: string) => setNamesBy((x) => ({ ...x, [market]: v }));
  const [macro, setMacro] = useState(false);
  const [start, setStart] = useState(() => new Date().toISOString().slice(0, 10));
  const [days, setDays] = useState(7);
  useEffect(() => setPicks([]), [market]);

  const dNames = useDebounced(names);
  const dDays = useDebounced(days, 250);
  const symbols = dNames.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean);
  const body = { market, symbols, start, days: dDays, macro };
  const cal = useQuery({
    queryKey: ["rb-cal", body], queryFn: () => post<CalOut>(`${P}/calendar`, body),
    placeholderData: keepPreviousData, enabled: !!setup,
  });
  const imp = useMutation({
    mutationFn: () => post<{ symbols: string[] }>(`${P}/import`, { market, watchlists: picks }),
    onSuccess: (r) => { setNames(r.symbols.join(", ")); toast("Imported watchlist"); },
    onError: (e) => toast(errText(e), "danger"),
  });
  const send = useMutation({
    mutationFn: () => post<{ ids: number[] }>(`${P}/alerts`, body),
    onSuccess: (r) => toast(`Sent ${r.ids.length} simulated alerts to Alerts`),
    onError: (e) => toast(errText(e), "danger"),
  });

  const rows = cal.data?.rows ?? [];
  const overlaps = rows.filter((r) => r.Overlap).length;
  const estimated = rows.filter((r) => r.Status === "estimated").length;
  const cols: Column<Row>[] = [
    { key: "Date", header: "Date", render: (r) => <span className="num whitespace-nowrap">{String(r.Date)}</span> },
    { key: "Time", header: "Time", render: (r) => <span className="num whitespace-nowrap">{String(r.Time)}</span> },
    { key: "Event", header: "Event", render: (r) => <span className="font-medium">{String(r.Event)}</span> },
    { key: "Symbol", header: "Symbol" },
    { key: "Kind", header: "Kind", render: (r) => <span className="text-muted">{String(r.Kind)}</span> },
    { key: "Status", header: "Status", render: (r) => <Badge tone={r.Status === "estimated" ? "warn" : "neutral"}>{String(r.Status)}</Badge> },
    { key: "Source", header: "Source", render: (r) => <span className="text-[13px] text-muted">{String(r.Source)}</span> },
    { key: "Stamped", header: "Stamped", render: (r) => <span className="num whitespace-nowrap text-[13px] text-muted">{String(r.Stamped)}</span> },
    { key: "Overlap", header: "Overlap", render: (r) => (r.Overlap ? <span className="text-[13px] font-medium text-saffron">{String(r.Overlap)}</span> : "") },
  ];

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
      <div className="flex min-w-0 flex-col gap-5">
        <Panel title="Names and window">
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <span className="text-[12px] text-muted">Watchlists</span>
              <div className="flex flex-wrap items-center gap-3">
                {setup?.watchlists.length
                  ? <ChipPicker label="Watchlists" options={setup.watchlists.map((w) => w.name)} value={picks} onChange={setPicks} />
                  : <span className="text-[13px] text-muted">No saved watchlists yet. Save one from the Screener; Import watchlist then adds your open paper positions{setup?.positions.length ? "" : ", or the sample names"}.</span>}
                <Button size="sm" onClick={() => imp.mutate()} disabled={imp.isPending}>Import watchlist</Button>
              </div>
            </div>
            <Field label="Names" hint="Comma-separated symbols. Open paper positions are always checked for overlaps.">
              <input className={inputCls} value={names} onChange={(e) => setNames(e.target.value)} aria-label="Names" />
            </Field>
            <div className="grid items-end gap-4 md:grid-cols-[auto_180px_minmax(0,1fr)]">
              <div className="min-w-[180px]"><Switch checked={macro} onChange={setMacro} label="Macro events" /></div>
              <Field label="From">
                <input type="date" className={inputCls} value={start} onChange={(e) => e.target.value && setStart(e.target.value)} aria-label="From" />
              </Field>
              <div className="flex flex-col gap-1">
                <span className="text-[12px] text-muted">Days</span>
                <div className="flex h-9 items-center gap-3">
                  <Slider label="Days" min={5} max={60} value={days} onChange={setDays} />
                  <span className="num w-8 text-right font-medium">{days}</span>
                </div>
              </div>
            </div>
          </div>
        </Panel>

        <Panel title="Calendar" action={cal.isFetching && <span className="text-[12px] text-muted">Updating…</span>}>
          {cal.isError && <Callout tone="danger" title="Could not build the calendar">{errText(cal.error)}</Callout>}
          {!cal.data && !cal.isError && <Placeholder height={220} />}
          {cal.data && (rows.length ? (
            <div className="scroll-thin overflow-x-auto">
              <table className="w-full text-[14px]">
                <thead>
                  <tr className="border-b border-line text-left text-[12px] text-muted">
                    {cols.map((c) => <th key={c.key} className="pb-2 pr-3 font-normal">{c.header}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => (
                    <tr key={i} className={cn("border-b border-line last:border-0", r.Overlap && "bg-saffron/10")}>
                      {cols.map((c) => <td key={c.key} className="py-2 pr-3 align-top">{c.render ? c.render(r) : String(r[c.key] ?? "—")}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <EmptyState>No events in this window. Widen Days, switch on Macro events, or add names.</EmptyState>)}
          <p className="mt-3 text-[12px] text-muted">Estimated rows are not confirmed by the company. Sample calendar rules offline. Amber rows overlap an open paper position or a plan's holding window.</p>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Button onClick={() => send.mutate()} disabled={!rows.length || send.isPending}><BellPlus size={15} /> Send to Alerts</Button>
            {send.isSuccess && <span className="text-[13px] text-muted">{send.data.ids.length} simulated alerts proposed in Paper Trading, Alerts. Nothing is active until you click Accept there.</span>}
          </div>
        </Panel>
      </div>

      <div className="flex flex-col gap-3">
        <h2 className="text-[14px] font-semibold">This window</h2>
        <div className="grid grid-cols-2 gap-2.5">
          <FactTile label="Rows" value={cal.data ? rows.length : "—"} big sub={`${days} days from ${start}`} />
          <FactTile label="Overlaps" value={cal.data ? overlaps : "—"} sub="touch open positions" />
          <FactTile label="Estimated" value={cal.data ? estimated : "—"} sub="not yet confirmed" />
          <FactTile label="Open positions" value={setup ? setup.positions.length : "—"} sub="paper" />
        </div>
        {cal.data && rows.length > 0 && (
          <div className="mt-2">
            <ExplainPanel key={cal.data.facts.join("|")} facts={cal.data.facts} section="Research"
              question="Summarise the week in plain English. Cite each row; add no dates." />
          </div>
        )}
      </div>
    </div>
  );
}

/* ================================================================ Results digest */
interface Digest {
  company: string; rows: Row[]; guidance_now: string; guidance_cite: string; guidance_before: string;
  guidance_before_cite: string; chip: string; consensus: Row[];
}
interface DigestOut { digest: Digest; facts: string[] }

function DigestTab({ market, setup }: { market: Market; setup?: Setup }) {
  const toast = useToast();
  const [company, setCompany] = useState("Kaveri Pumps (fictional)");
  const [file, setFile] = useState<{ name: string; base64: string } | null>(null);
  const [sample, setSample] = useState("");
  const [out, setOut] = useState<DigestOut | null>(null);
  const sampleName = sample || setup?.samples[0] || "";
  const gen = useMutation({
    mutationFn: () => post<DigestOut>(`${P}/digest`, {
      market, company, sample: sampleName, pdf_base64: file?.base64 ?? null, pdf_name: file?.name ?? null,
    }),
    onSuccess: (d) => setOut(d),
  });
  const accept = useMutation({
    mutationFn: () => post<{ id: number }>(`${P}/digest/accept`, { digest: out!.digest, market }),
    onSuccess: () => { toast("Saved to the Thesis tracker"); hist.refetch(); },
    onError: (e) => toast(errText(e), "danger"),
  });
  const hist = useQuery({
    queryKey: ["rb-hist", out?.digest.company],
    queryFn: () => get<{ rows: { created: string; guidance: string; cite: string; chip: string }[] }>(`${P}/history?company=${encodeURIComponent(out!.digest.company)}`),
    enabled: !!out,
  });
  const d = out?.digest;
  const cols: Column<Row>[] = [
    { key: "Item", header: "Item", render: (r) => <span className="font-medium">{String(r.Item)}</span> },
    { key: "This quarter", header: "This quarter", align: "right" },
    { key: "Comparison", header: "Comparison", align: "right" },
    { key: "Change", header: "Change", align: "right", render: (r) => <span className="font-medium">{String(r.Change)}</span> },
    { key: "Page", header: "Page", render: (r) => <PageChip cite={String(r.Page)} /> },
  ];

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
      <div className="flex min-w-0 flex-col gap-5">
        <Panel title="Results set">
          <div className="grid gap-4 md:grid-cols-2">
            <Field label="Company">
              <input className={inputCls} value={company} onChange={(e) => setCompany(e.target.value)} aria-label="Company" />
            </Field>
            <Field label="Or use a sample filing">
              <Select value={sampleName} onChange={(e) => setSample(e.target.value)} disabled={!!file}>
                {setup?.samples.map((s) => <option key={s}>{s}</option>)}
              </Select>
            </Field>
          </div>
          <div className="mt-4"><FileDrop file={file} onFile={setFile} /></div>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Button variant="primary" onClick={() => gen.mutate()} disabled={gen.isPending || !company.trim()}>
              {gen.isPending ? "Generating…" : "Generate digest"}
            </Button>
            <span className="text-[13px] text-muted">The desk runs the quote-first template, then computes Change in code.</span>
          </div>
          {gen.isError && <div className="mt-3"><Callout tone="danger" title="Could not generate the digest">{errText(gen.error)}</Callout></div>}
        </Panel>

        {d ? (
          <>
            <Panel title={`${d.company}, results digest`}>
              <DataTable rows={d.rows} columns={cols} />
              <p className="mt-2 text-[12px] text-muted">Change is computed in code from the quoted figures: % for money, percentage points for margins, a difference for days.</p>
            </Panel>
            <Panel title="Guidance · word for word" action={<ChipBadge chip={d.chip} />}>
              <div className="flex flex-col gap-3 font-serif text-[15px] leading-[1.6]">
                {d.guidance_before && (
                  <p><span className="mr-2 font-sans text-[13px] text-muted">Before</span>“{d.guidance_before}” <PageChip cite={d.guidance_before_cite} /></p>
                )}
                <p><span className="mr-2 font-sans text-[13px] text-muted">Now</span>“{d.guidance_now}” <PageChip cite={d.guidance_cite} /></p>
              </div>
              <p className="mt-3 text-[12px] text-muted">The chip compares words added or dropped: unchanged, wording softer or wording firmer.</p>
            </Panel>
            <Consensus digest={d} onChange={setOut} />
            <Disclosure title="History" hint={hist.data ? `${hist.data.rows.length} saved` : undefined}>
              {hist.data?.rows.length ? (
                <ul className="flex flex-col gap-2">
                  {hist.data.rows.map((h, i) => (
                    <li key={i} className="flex flex-wrap items-baseline gap-2 text-[14px]">
                      <span className="num text-muted">{h.created}</span>
                      <span className="font-serif">“{h.guidance}”</span>
                      <ChipBadge chip={h.chip} />
                    </li>
                  ))}
                </ul>
              ) : <p className="text-[13px] text-muted">No saved digests for {d.company} yet. Click Accept to save this one; next quarter's guidance comparison starts from it.</p>}
            </Disclosure>
          </>
        ) : (
          <EmptyState>Drop the results PDF or pick the sample filing, then click Generate digest. Every figure comes back as a quote with its page.</EmptyState>
        )}
      </div>

      <div className="flex flex-col gap-3">
        <h2 className="text-[14px] font-semibold">From the filing</h2>
        {d ? (
          <div className="grid grid-cols-2 gap-2.5">
            {d.rows.map((r, i) => (
              <FactTile key={String(r.Item)} label={String(r.Item)} value={String(r["This quarter"])} big={i === 0}
                sub={`${r.Change} vs ${r.Comparison}`} />
            ))}
            <FactTile label="Guidance chip" value={<span className="text-[16px]">{d.chip}</span>} />
          </div>
        ) : <Placeholder height={200}>Tiles appear after Generate digest.</Placeholder>}
        {out && (
          <div className="mt-2">
            <ExplainPanel key={out.facts.join("|")} facts={out.facts} section="Research" onAccept={() => accept.mutate()} />
            <p className="mt-2 text-[12px] text-muted">Accept saves the digest to the Thesis tracker.</p>
          </div>
        )}
      </div>
    </div>
  );
}

function ChipBadge({ chip }: { chip: string }) {
  return <Badge tone={chip === "wording softer" ? "warn" : chip === "wording firmer" ? "indigo" : "neutral"}>{chip}</Badge>;
}

function Consensus({ digest, onChange }: { digest: Digest; onChange: (d: DigestOut) => void }) {
  const toast = useToast();
  const items = digest.rows.map((r) => String(r.Item));
  const [item, setItem] = useState(items[0] ?? "");
  const [value, setValue] = useState("0");
  const [source, setSource] = useState("");
  const [asOf, setAsOf] = useState(() => new Date().toISOString().slice(0, 10));
  const add = useMutation({
    mutationFn: () => post<DigestOut>(`${P}/consensus`, { digest, item, value: Number(value), source, as_of: asOf }),
    onSuccess: (d) => { onChange(d); toast("Added consensus"); },
  });
  const cols: Column<Row>[] = [
    { key: "Item", header: "Item" },
    { key: "Consensus", header: "Consensus", align: "right" },
    { key: "Source", header: "Source", render: (r) => <span className="text-muted">{String(r.Source)}</span> },
    { key: "Difference", header: "Difference", align: "right", render: (r) => <span className="font-medium">{String(r.Difference)}</span> },
  ];
  return (
    <Disclosure title="Consensus (you fill it in)" hint={digest.consensus.length ? `${digest.consensus.length} added` : undefined}>
      <div className="grid items-end gap-3 md:grid-cols-[minmax(0,1fr)_120px_minmax(0,1fr)_150px_auto]">
        <Field label="Item">
          <Select value={item} onChange={(e) => setItem(e.target.value)}>{items.map((i) => <option key={i}>{i}</option>)}</Select>
        </Field>
        <Field label="Consensus figure">
          <input type="number" className={inputCls} value={value} onChange={(e) => setValue(e.target.value)} aria-label="Consensus figure" />
        </Field>
        <Field label="Source">
          <input className={inputCls} value={source} placeholder="Where you copied it" onChange={(e) => setSource(e.target.value)} aria-label="Source" />
        </Field>
        <Field label="Date">
          <input type="date" className={inputCls} value={asOf} onChange={(e) => setAsOf(e.target.value)} aria-label="Date" />
        </Field>
        <Button onClick={() => add.mutate()} disabled={!source.trim() || add.isPending}>Add consensus</Button>
      </div>
      {add.isError && <p className="mt-2 text-[13px] text-bear">{errText(add.error)}</p>}
      {digest.consensus.length > 0 && <div className="mt-4"><DataTable rows={digest.consensus} columns={cols} /></div>}
      <p className="mt-3 text-[12px] text-muted">The desk only subtracts; it never fetches or guesses consensus.</p>
    </Disclosure>
  );
}

/* ================================================================ Implied vs historical move */
interface Move { event: string; time: string; close_before: number; close_after: number; move_pct: number; from: string; to: string }
interface MoveOut {
  available: boolean; symbol: string; event: string; moves: Move[]; market?: Market; event_title?: string;
  event_date?: string; expiry?: string; spot?: number; strike?: number; call?: number; put?: number; straddle?: number;
  implied_move_pct?: number; chain_source?: string; tiles?: Record<string, string>; scenarios?: Row[];
  split?: Record<string, number>; facts?: string[];
}

function MoveTab({ market, setup }: { market: Market; setup?: Setup }) {
  const toast = useToast();
  const [symBy, setSymBy] = useState<Partial<Record<Market, string>>>({});
  const symbol = symBy[market] ?? setup?.move_default ?? "";
  const [draft, setDraft] = useState(symbol);
  useEffect(() => setDraft(symbol), [symbol]);
  const commit = () => { const s = draft.trim().toUpperCase(); if (s && s !== symbol) setSymBy((x) => ({ ...x, [market]: s })); };
  const [event, setEvent] = useState<string | null>(null);
  const [split, setSplit] = useState(false);
  const [quiet, setQuiet] = useState("0");
  const dQuiet = useDebounced(quiet);
  const [picked, setPicked] = useState<Move | null>(null);

  const evs = useQuery({
    queryKey: ["rb-evs", symbol, market],
    queryFn: () => get<{ events: string[] }>(`${P}/move/events?symbol=${encodeURIComponent(symbol)}&market=${market}`),
    enabled: !!symbol,
  });
  useEffect(() => { setEvent(null); setPicked(null); }, [symbol, market]);
  const ev = event && evs.data?.events.includes(event) ? event : evs.data?.events[0] ?? null;
  const body = { symbol, market, event: ev, quiet_pct: Number(dQuiet) || 0 };
  const mv = useQuery({
    queryKey: ["rb-move", body], queryFn: () => post<MoveOut>(`${P}/move`, body),
    enabled: !!ev, placeholderData: keepPreviousData,
  });
  const openOB = useMutation({
    mutationFn: () => post<{ strike: number; expiry: string }>(`${P}/move/options-builder`, body),
    onSuccess: () => toast("Opened a draft straddle in Options Strategy Builder"),
    onError: (e) => toast(errText(e), "danger"),
  });
  const journal = useMutation({
    mutationFn: () => post<{ id: number }>(`${P}/move/journal`, body),
    onSuccess: () => toast("Saved to journal"),
    onError: (e) => toast(errText(e), "danger"),
  });
  const m = mv.data;

  const chart = useMemo(() => {
    if (!m?.moves.length) return null;
    const t = chartTokens();
    return {
      grid: { left: 48, right: 12, top: 16, bottom: 36 },
      tooltip: { trigger: "axis", backgroundColor: t.panel, borderColor: t.line, textStyle: { color: t.ink },
        formatter: (ps: { dataIndex: number }[]) => {
          const x = m.moves[ps[0].dataIndex];
          return `${x.event} ${x.time}<br/>${x.close_before} to ${x.close_after}: ${x.move_pct > 0 ? "+" : ""}${x.move_pct}%`;
        } },
      xAxis: { type: "category", data: m.moves.map((x) => x.event), axisLabel: { color: t.muted }, axisLine: { lineStyle: { color: t.line } } },
      yAxis: { type: "value", name: "Move, %", nameTextStyle: { color: t.muted }, axisLabel: { color: t.muted, formatter: "{value}%" }, splitLine: { lineStyle: { color: t.line } } },
      series: [{ type: "bar", barMaxWidth: 34, cursor: "pointer",
        data: m.moves.map((x) => ({ value: x.move_pct, itemStyle: { color: x.move_pct >= 0 ? t.bull : t.bear, borderRadius: 2 } })) }],
    };
  }, [m]);

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
      <div className="flex min-w-0 flex-col gap-5">
        <Panel>
          <div className="grid items-end gap-4 md:grid-cols-[200px_minmax(0,1fr)]">
            <Field label="Symbol">
              <input className={inputCls} value={draft} aria-label="Symbol" onChange={(e) => setDraft(e.target.value.toUpperCase())}
                onBlur={commit} onKeyDown={(e) => e.key === "Enter" && commit()} />
            </Field>
            <Field label="Calendar row">
              <Select value={ev ?? ""} onChange={(e) => setEvent(e.target.value)} disabled={!evs.data?.events.length}>
                {evs.data?.events.map((e) => <option key={e}>{e}</option>)}
              </Select>
            </Field>
          </div>
          {evs.data && !evs.data.events.length && <p className="mt-3 text-[13px] text-muted">No scheduled event for this symbol in the next months. Try another symbol.</p>}
          {m?.available && (
            <div className="mt-4">
              <MetaList items={[["Expiry", m.expiry], ["ATM", num(m.strike, market)], ["Call", num(m.call, market)], ["Put", num(m.put, market)], ["Spot", num(m.spot, market)], ["Chain", m.chain_source]]} />
            </div>
          )}
        </Panel>

        {mv.isError && <Callout tone="danger" title="Could not price the move">{errText(mv.error)}</Callout>}
        {m && !m.available && (
          <>
            <Callout tone="info" title="Implied move: n/a (not in the F&O list)">The history of results-day moves is below.</Callout>
            <Panel title="Results-day moves" action={<Hypothetical />}>
              <MovesTable moves={m.moves} market={market} />
            </Panel>
          </>
        )}
        {m?.available && (
          <>
            <Panel title="Results-day moves, last 8" action={<Hypothetical />}>
              {chart ? (
                <>
                  <ClickChart option={chart} onPick={(i) => setPicked(m.moves[i])} />
                  {picked ? (
                    <div className="mt-2 rounded-[var(--radius-tile)] border border-line bg-panel-2 px-3 py-2">
                      <MetaList items={[["Announcement", `${picked.event} ${picked.time}`], ["Close before", `${num(picked.close_before, market)} (${picked.from})`],
                        ["Close after", `${num(picked.close_after, market)} (${picked.to})`], ["Move", `${picked.move_pct > 0 ? "+" : ""}${picked.move_pct.toFixed(2)}%`]]} />
                    </div>
                  ) : <p className="mt-1 text-[12px] text-muted">Click a bar to see the filing time and the two closes used. Moves use the last close before the announcement time, not the date.</p>}
                </>
              ) : <EmptyState>No results-day history for this row (macro events and indices have none). The tiles use realised volatility instead.</EmptyState>}
            </Panel>

            <Panel title="Event split" action={<Switch checked={split} onChange={setSplit} label={<span className="sr-only">Event split</span>} />}>
              {split && m.split ? (
                <>
                  <Field label="Normal-day move from a quiet week, % (0 = use realised vol)">
                    <input type="number" min={0} max={10} step={0.05} className={cn(inputCls, "max-w-[160px]")} value={quiet}
                      onChange={(e) => setQuiet(e.target.value)} aria-label="Normal-day move from a quiet week, %" />
                  </Field>
                  <div className="mt-4 grid grid-cols-3 gap-2.5">
                    <FactTile label="Sessions to expiry" value={m.split["sessions to expiry"]} />
                    <FactTile label="Normal-day move" value={`${m.split["normal-day move %"].toFixed(2)}%`} />
                    <FactTile label="Event-day move" value={`${m.split["event-day move %"].toFixed(2)}%`} tone="indigo" />
                  </div>
                  <p className="mt-2 text-[12px] text-muted">Approximate: total implied variance minus the normal days' share.</p>
                </>
              ) : <p className="text-[13px] text-muted">Switch on Event split to separate the event day from the normal days priced into the straddle.</p>}
            </Panel>

            <Disclosure title="Scenarios" hint="after an IV crush">
              <div className="mb-3 flex items-center gap-2"><Hypothetical /><span className="text-[12px] text-muted">Straddle value one day later after an IV crush to the normal level.</span></div>
              <DataTable rows={m.scenarios ?? []} columns={[
                { key: "Move", header: "Move" },
                { key: "Spot", header: "Spot", align: "right", render: (r) => num(Number(r.Spot), market) },
                { key: "Straddle after IV crush", header: "Straddle after IV crush", align: "right", render: (r) => num(Number(r["Straddle after IV crush"]), market) },
                { key: "Change", header: "Change", align: "right", render: (r) => (
                  <span className={cn("font-medium", Number(r.Change) >= 0 ? "text-bull" : "text-bear")}>{Number(r.Change) > 0 ? "+" : ""}{num(Number(r.Change), market)}</span>) },
              ]} />
            </Disclosure>

            <div className="flex flex-wrap gap-2">
              <Button onClick={() => openOB.mutate()} disabled={openOB.isPending}><ExternalLink size={15} /> Open in Options Strategy Builder</Button>
              <Button onClick={() => journal.mutate()} disabled={journal.isPending}><BookmarkPlus size={15} /> Save to journal</Button>
            </div>
            {openOB.isSuccess && <p className="text-[13px] text-muted">Draft straddle sent to Derivatives, Options Strategy Builder. Test it there with the Days left slider.</p>}
            {journal.isSuccess && <p className="text-[13px] text-muted">Logged before the event; the actual move is added after it.</p>}
          </>
        )}
      </div>

      <div className="flex flex-col gap-3">
        <h2 className="text-[14px] font-semibold">What the options are pricing</h2>
        {m?.available && m.tiles ? (
          <div className="grid grid-cols-2 gap-2.5">
            {Object.entries(m.tiles).map(([k, v]) => (
              <FactTile key={k} label={k} value={v} big={k === "Implied move"} tone={k === "Implied move" ? "indigo" : undefined} />
            ))}
          </div>
        ) : m && !m.available ? (
          <EmptyState>No listed options for {m.symbol}, so there is no straddle. The history table shows past results-day moves.</EmptyState>
        ) : <Placeholder height={200} />}
        {m?.available && m.facts && (
          <div className="mt-2">
            <ExplainPanel key={m.facts.join("|")} facts={m.facts} section="Research"
              question="Narrate the tiles and cite each one. Do not suggest a strike, a direction or a trade." />
          </div>
        )}
        {setup && setup.actual_moves_filled > 0 && (
          <p className="flex items-center gap-1.5 text-[12px] text-muted"><Sparkles size={13} /> Added the actual move to {setup.actual_moves_filled} saved journal rows.</p>
        )}
      </div>
    </div>
  );
}

function MovesTable({ moves, market }: { moves: Move[]; market: Market }) {
  return (
    <DataTable rows={moves as unknown as Row[]} columns={[
      { key: "event", header: "Announcement" },
      { key: "time", header: "Time" },
      { key: "close_before", header: "Close before", align: "right", render: (r) => num(Number(r.close_before), market) },
      { key: "close_after", header: "Close after", align: "right", render: (r) => num(Number(r.close_after), market) },
      { key: "move_pct", header: "Move", align: "right", render: (r) => (
        <span className={cn("font-medium", Number(r.move_pct) >= 0 ? "text-bull" : "text-bear")}>{Number(r.move_pct) > 0 ? "+" : ""}{Number(r.move_pct).toFixed(2)}%</span>) },
    ]} />
  );
}
