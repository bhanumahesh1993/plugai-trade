import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, GitCompareArrows, Play, Save } from "lucide-react";
import { get, post, type Market } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button, Field, Panel, Tabs, TabList, Tab, TabPanel, inputCls } from "@/components/ui";
import { Badge, Callout, DataTable, EChart, EmptyState, Hypothetical, Segmented, Select, chartTokens, useToast, type Column } from "@/components/kit";
import { ExplainPanel, FactTile, FactsProvider } from "@/components/facts";
import { useMarket } from "@/components/shell";
import { Check, ErrorLine, Note, NumField, Radio, TextField } from "@/components/automate/common";

/* ------------------------------------------------------------ types */
interface Head extends Record<string, unknown> {
  id: string; source: string; symbol: string; headline: string; original: string; lang: string;
  published: string; seen: string; tradable_from: string;
}
interface Scorer { key: string; name: string; used: string; labels: string[]; paths: string[] }
interface Compare {
  n: number; agreement: number; opposite: number; disagreements_n: number; name_a: string; name_b: string;
  table_columns: string[]; table: Record<string, string | number>[]; disagreements: Record<string, unknown>[]; facts: string[];
}
interface Study {
  n: number; day0: number; trials: number; drift: number; drift_lo: number; drift_hi: number; after_20: number; preset_bps: number;
  benchmark: string; costs: string; entry: string; window: [number, number]; side: string;
  path: { day: number; mean_ar: number; car: number; lo: number; hi: number }[];
  cost_table: Record<string, string | number>[]; skipped: string[]; facts: string[];
}
interface NewsState {
  market: Market; sources: { key: string; label: string; market: string }[]; watchlist: string[];
  edgar_contact_set: boolean; finbert_available: boolean; indexes: string[]; cost_presets: string[]; rules: string[];
  gdelt_interval: number; status: Record<string, string>; fetched: boolean; range: [string, string] | null;
  heads: Head[]; tray: Record<string, string>[]; scored: { rows: Head[]; scorers: Scorer[] } | null;
  compare: Compare | null; study: Study | null; rule_saved: { id: number; rule: string } | null;
}

const iso = (d: Date) => d.toISOString().slice(0, 10);
const LABEL_TONE: Record<string, "neutral" | "indigo" | "warn"> = { positive: "indigo", negative: "warn", neutral: "neutral", unclear: "neutral" };
const signed = (x: number, d = 1) => `${x >= 0 ? "+" : "−"}${Math.abs(x).toFixed(d)}`;

/** "2025-01-01 07:08 IST" → date over time, so three clocks fit side by side. */
function Clock({ v, strong }: { v: string; strong?: boolean }) {
  const [d, ...rest] = String(v ?? "").split(" ");
  return <span className={cn("num block whitespace-nowrap leading-tight", strong && "font-medium")}>{d}<span className="block text-[13px] text-muted">{rest.join(" ")}</span></span>;
}
/** "nse-rss (synthetic sample)" → "nse-rss" with a quiet synthetic mark. */
function SourceCell({ v }: { v: string }) {
  const m = String(v).match(/^(.*?)\s*\((.+)\)$/);
  return <span className="block whitespace-nowrap text-[13px] leading-tight">{m ? m[1] : v}{m && <span className="block text-muted">{m[2]}</span>}</span>;
}

function LabelBadge({ l }: { l: string }) {
  return <Badge tone={LABEL_TONE[l] ?? "neutral"}>{l}</Badge>;
}

function HeadlineCell({ r }: { r: Head }) {
  return (
    <div className="min-w-[220px]">
      <div>{r.headline}</div>
      {r.original && r.lang !== "en" && r.original !== r.headline && <div className="mt-0.5 text-[13px] text-muted" lang="hi">Original (Hindi): {r.original}</div>}
    </div>
  );
}

/* ------------------------------------------------------------ Sources tab */
function SourcesTab({ s, onState }: { s: NewsState; onState: (d: NewsState) => void }) {
  const toast = useToast();
  const m = s.market;
  const [picked, setPicked] = useState<string[]>(s.sources.map((x) => x.key));
  const [rss, setRss] = useState("");
  const [watch, setWatch] = useState<string[]>(s.watchlist);
  const today = new Date();
  const [from, setFrom] = useState(s.range?.[0] ?? iso(new Date(today.getTime() - 30 * 864e5)));
  const [to, setTo] = useState(s.range?.[1] ?? iso(today));
  const [contact, setContact] = useState("");
  const [showTray, setShowTray] = useState(false);
  useEffect(() => { setPicked(s.sources.map((x) => x.key)); setWatch(s.watchlist); }, [m]); // eslint-disable-line react-hooks/exhaustive-deps

  const fetchNow = useMutation({
    mutationFn: () => post<NewsState>("/api/automate/news/fetch", { market: m, sources: picked, rss, watchlists: watch, start: from, end: to }),
    onSuccess: (d) => { onState(d); toast(`Fetched and stamped ${d.heads.length} headlines`); },
  });
  const save = useMutation({
    mutationFn: () => post("/api/automate/news/contact", { contact }),
    onSuccess: () => { onState({ ...s, edgar_contact_set: true }); toast("Saved contact. SEC EDGAR requests now carry it"); },
  });
  const needContact = picked.includes("sec-8k") && !s.edgar_contact_set;

  const cols: Column<Head>[] = [
    { key: "source", header: "Source", render: (r) => <SourceCell v={r.source} /> },
    { key: "symbol", header: "Symbol", render: (r) => r.symbol || <span className="text-muted">—</span> },
    { key: "headline", header: "Headline", render: (r) => <HeadlineCell r={r} /> },
    { key: "lang", header: "Lang" },
    { key: "published", header: "Published", render: (r) => <Clock v={r.published} /> },
    { key: "seen", header: "Seen", render: (r) => <Clock v={r.seen} /> },
    { key: "tradable_from", header: "Tradable from", render: (r) => <Clock v={r.tradable_from} strong /> },
  ];

  return (
    <div className="grid gap-5 xl:grid-cols-[290px_minmax(0,1fr)]">
      <Panel title="Feeds">
        <div className="flex flex-col gap-4">
          <Note>Tick the feeds you want. Stamping happens before scoring: every row gets Published, Seen and Tradable from, in {m === "IN" ? "IST" : "ET"}.</Note>
          <div>
            {s.sources.map((x) => (
              <Check key={x.key} checked={picked.includes(x.key)}
                onChange={(v) => setPicked((p) => (v ? [...p, x.key] : p.filter((k) => k !== x.key)))}
                hint={x.market === "ANY" ? "India and US" : undefined}>{x.label}</Check>
            ))}
          </div>
          {needContact && (
            <div className="flex flex-col gap-2 rounded-[var(--radius-tile)] border border-saffron/40 bg-saffron/10 p-3">
              <TextField label="EDGAR contact (name and email, sent in the User-Agent)" value={contact} onChange={setContact} placeholder="Asha Rao asha@example.com" />
              <div><Button size="sm" onClick={() => save.mutate()} disabled={!contact.includes("@") || save.isPending}><Save size={13} /> Save contact</Button></div>
              <Note>SEC EDGAR asks once for a contact. Without it, the 8-K feed is skipped.</Note>
              <ErrorLine error={save.error} />
            </div>
          )}
          <TextField label="Any other RSS feed (optional)" value={rss} onChange={setRss} placeholder="https://publisher.example/business.rss" />
          <div>
            <div className="mb-1 text-[12px] text-muted">Match watchlists</div>
            {s.watchlist.length === 0 ? <Note>No watchlist for {m} yet. Add symbols in Settings › Workspace.</Note> : (
              <div className="flex flex-wrap gap-1.5">
                {s.watchlist.map((w) => {
                  const on = watch.includes(w);
                  return (
                    <button key={w} type="button" aria-pressed={on} onClick={() => setWatch((p) => (on ? p.filter((x) => x !== w) : [...p, w]))}
                      className={cn("h-7 rounded-[4px] border px-2 text-[13px]", on ? "border-indigo bg-indigo-soft font-medium text-indigo" : "border-line-strong text-muted hover:text-ink")}>{w}</button>
                  );
                })}
              </div>
            )}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Field label="From"><input type="date" className={inputCls} value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
            <Field label="To"><input type="date" className={inputCls} value={to} onChange={(e) => setTo(e.target.value)} /></Field>
          </div>
          <Button variant="primary" onClick={() => fetchNow.mutate()} disabled={fetchNow.isPending || (picked.length === 0 && !rss.trim())}>
            <Download size={14} /> {fetchNow.isPending ? "Collecting and stamping…" : "Fetch now"}
          </Button>
          <ErrorLine error={fetchNow.error} />
          {Object.keys(s.status).length > 0 && (
            <ul className="flex flex-col gap-1 text-[13px] text-muted">
              {Object.entries(s.status).map(([k, v]) => <li key={k}><span className="font-medium text-ink">{k}</span>: {v}</li>)}
            </ul>
          )}
        </div>
      </Panel>

      <div className="flex min-w-0 flex-col gap-5">
        <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3">
          <FactTile big label="Stamped headlines" value={s.fetched ? s.heads.length : "—"} sub={s.range ? `${s.range[0]} to ${s.range[1]}` : "Nothing fetched yet"} />
          <FactTile label="Unstamped" value={s.fetched ? s.tray.length : "—"} sub="Never scored" />
          <FactTile label="Clock" value={m === "IN" ? "IST" : "ET"} sub="Tradable from = next session open after Seen" />
        </div>
        <Panel title="Stamped headlines" action={s.fetched ? <Button size="sm" onClick={() => setShowTray((v) => !v)} aria-expanded={showTray}>Unstamped ({s.tray.length})</Button> : undefined}>
          {!s.fetched ? (
            <EmptyState>Click Fetch now. Offline, the lab uses a bundled synthetic set of headlines about fictional companies (Kaveri Pumps, Lakeshore Devices and others), labelled as such.</EmptyState>
          ) : (
            <div className="scroll-thin max-h-[440px] overflow-y-auto">
              <DataTable rows={s.heads} columns={cols} rowKey={(r) => r.id} empty="No headlines for these dates. Widen From / To or tick more feeds." />
            </div>
          )}
        </Panel>
        {s.fetched && showTray && (
          <Panel title={`Unstamped tray, ${s.tray.length} rows (never scored)`}>
            <DataTable rows={s.tray} empty="Empty. Rows without a usable time, and same-story duplicates, land here." columns={[
              { key: "source", header: "Source" }, { key: "headline", header: "Headline" },
              { key: "published_raw", header: "Time as published" }, { key: "reason", header: "Reason" },
            ]} />
          </Panel>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ Score tab */
function ScoreTab({ s, onState }: { s: NewsState; onState: (d: NewsState) => void }) {
  const toast = useToast();
  const m = s.market;
  const [fb, setFb] = useState(true);
  const [llm, setLlm] = useState(true);
  const [rule, setRule] = useState(s.rules[0]);
  const [why, setWhy] = useState("");
  const score = useMutation({
    mutationFn: () => post<NewsState>("/api/automate/news/score", { market: m, finbert: fb, llm }),
    onSuccess: (d) => { onState(d); toast(`Scored ${d.heads.length} headlines`); },
  });
  const compare = useMutation({ mutationFn: () => post<NewsState>("/api/automate/news/compare", { market: m }), onSuccess: (d) => { onState(d); toast("Compared scorers"); } });
  const saveRule = useMutation({
    mutationFn: () => post<NewsState>("/api/automate/news/rule", { market: m, rule, note: why }),
    onSuccess: (d) => { onState(d); toast("Saved rule. Apply it to every headline, before any event study"); },
  });
  if (!s.fetched || s.heads.length === 0) return <EmptyState>Fetch headlines in the Sources tab first.</EmptyState>;

  const sc = s.scored;
  const rows = sc ? sc.rows.map((r, i) => {
    const o: Record<string, unknown> = { ...r };
    sc.scorers.forEach((x) => { o[x.name] = x.labels[i]; o[`${x.name} path`] = x.paths[i]; });
    return o;
  }) : [];
  const cmp = s.compare;
  const firstCol = cmp?.table_columns[0] ?? "";
  const labs = cmp ? cmp.table_columns.slice(1, -1) : [];

  return (
    <div className="flex flex-col gap-5">
      <Panel title="Scorers">
        <div className="flex flex-wrap items-start gap-x-10 gap-y-2">
          <Check checked={fb} onChange={setFb} hint={s.finbert_available ? "FinBERT (transformers)" : "transformers not installed: a Loughran–McDonald-style word list is used instead, and labelled"}>FinBERT</Check>
          <Check checked={llm} onChange={setLlm} hint="JSON labels at temperature 0; with no model reachable, phrase rules, labelled">Local model</Check>
          <div className="ml-auto flex gap-2">
            <Button variant="primary" onClick={() => score.mutate()} disabled={score.isPending || !(fb || llm)}><Play size={14} /> {score.isPending ? "Scoring…" : "Score"}</Button>
            <Button onClick={() => compare.mutate()} disabled={!sc || sc.scorers.length < 2 || compare.isPending}><GitCompareArrows size={14} /> Compare scorers</Button>
          </div>
        </div>
        {sc && <ul className="mt-2 text-[13px] text-muted">{sc.scorers.map((x) => <li key={x.key}>{x.name}: {x.used}</li>)}</ul>}
        {sc && sc.scorers.length < 2 && <Note className="mt-1">Tick both scorers and click Score to compare them.</Note>}
        <ErrorLine error={score.error ?? compare.error} />
      </Panel>

      {sc && (
        <Panel title={`Scored headlines (${rows.length})`}>
          <div className="scroll-thin max-h-[340px] overflow-y-auto">
            <DataTable rows={rows} columns={[
              { key: "symbol", header: "Symbol" },
              { key: "headline", header: "Headline", render: (r) => <HeadlineCell r={r as Head} /> },
              ...sc.scorers.flatMap((x) => [
                { key: x.name, header: x.name, render: (r: Record<string, unknown>) => <LabelBadge l={String(r[x.name])} /> },
                { key: `${x.name} path`, header: `${x.name} path`, render: (r: Record<string, unknown>) => <span className="text-[13px] text-muted">{String(r[`${x.name} path`])}</span> },
              ] as Column<Record<string, unknown>>[]),
            ]} />
          </div>
        </Panel>
      )}

      {cmp && (
        <>
          <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
            <FactTile big label="Agreement" value={`${Math.round(cmp.agreement * 100)}%`} sub={`${cmp.name_a} vs ${cmp.name_b}`} />
            <FactTile label="Headlines compared" value={cmp.n} />
            <FactTile label="Disagreements" value={cmp.disagreements_n} />
            <FactTile label="Opposite labels (positive vs negative)" value={cmp.opposite} sub="Read these first" />
          </div>
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
            <div className="flex min-w-0 flex-col gap-5">
              <Panel title="Agreement table">
                <table className="text-[14px]">
                  <thead>
                    <tr className="text-[12px] text-muted">
                      <th className="pb-2 pr-6 text-left font-normal">{cmp.name_a} (rows) \ {cmp.name_b} (columns)</th>
                      {labs.map((l) => <th key={l} className="pb-2 pr-6 text-right font-normal">{l}</th>)}
                      <th className="pb-2 text-right font-normal">Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cmp.table.map((r) => (
                      <tr key={String(r[firstCol])} className="border-t border-line">
                        <td className="py-2 pr-6">{String(r[firstCol])}</td>
                        {labs.map((l) => (
                          <td key={l} className={cn("num py-2 pr-6 text-right", l === r[firstCol] && "font-semibold text-indigo")}>{String(r[l])}</td>
                        ))}
                        <td className="num py-2 text-right text-muted">{String(r.total)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <Note className="mt-2">The diagonal (highlighted) is where both scorers agree. Diagonal ÷ total = agreement.</Note>
              </Panel>
              <Panel title={`Disagreements (${cmp.disagreements.length}), opposite labels first`}>
                <div className="scroll-thin max-h-[440px] overflow-y-auto"><DataTable rows={cmp.disagreements} empty="None. Both scorers gave every headline the same label." columns={[
                  { key: "opposite", header: "", render: (r) => (r.opposite ? <Badge tone="warn">Opposite</Badge> : null) },
                  { key: "symbol", header: "Symbol" },
                  { key: "headline", header: "Headline", render: (r) => <HeadlineCell r={r as unknown as Head} /> },
                  { key: "finbert", header: "FinBERT", render: (r) => <LabelBadge l={String(r.finbert)} /> },
                  { key: "llm", header: "Local model", render: (r) => <LabelBadge l={String(r.llm)} /> },
                  { key: "why", header: "Why (each scorer)", render: (r) => <span className="text-[13px] text-muted">{String(r.finbert_reason ?? "")}; {String(r.llm_reason ?? "")}</span> },
                ]} /></div>
              </Panel>
            </div>
            <div className="flex flex-col gap-5">
              <Panel title="Your rule for disagreements">
                <div role="radiogroup" aria-label="Your rule for disagreements">
                  {s.rules.map((r) => <Radio key={r} name="np-rule" checked={rule === r} onChange={() => setRule(r)}>{r}</Radio>)}
                </div>
                <div className="mt-2"><TextField label="Why (optional)" value={why} onChange={setWhy} /></div>
                <div className="mt-3 flex items-center gap-3">
                  <Button onClick={() => saveRule.mutate()} disabled={saveRule.isPending}><Save size={14} /> Save rule</Button>
                  {s.rule_saved && <span className="text-[13px] text-muted">Saved: {s.rule_saved.rule}</span>}
                </div>
                <ErrorLine error={saveRule.error} />
              </Panel>
              <Panel title="Explain">
                <ExplainPanel facts={cmp.facts} section="Automate" question="Explain what this agreement table says and which rows to read first." />
              </Panel>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------ Event study tab */
function StudyChart({ st }: { st: Study }) {
  const option = useMemo(() => {
    const t = chartTokens();
    const days = st.path.map((p) => p.day);
    const lo = st.path.map((p) => p.lo * 100);
    const band = st.path.map((p) => (p.hi - p.lo) * 100);
    return {
      grid: { left: 56, right: 16, top: 16, bottom: 40 },
      tooltip: { trigger: "axis", backgroundColor: t.panel, borderColor: t.line, textStyle: { color: t.ink },
        formatter: (ps: { dataIndex: number }[]) => {
          const p = st.path[ps[0].dataIndex];
          return `Day ${p.day >= 0 ? "+" : ""}${p.day}<br/>Average CAR ${signed(p.car * 100, 2)}%<br/>95% band ${signed(p.lo * 100, 2)}% to ${signed(p.hi * 100, 2)}%`;
        } },
      xAxis: { type: "category", data: days, name: "Sessions relative to day 0", nameLocation: "middle", nameGap: 26,
        nameTextStyle: { color: t.muted }, axisLine: { lineStyle: { color: t.line } }, axisLabel: { color: t.muted } },
      yAxis: { type: "value", axisLabel: { color: t.muted, formatter: (v: number) => `${v.toFixed(1)}%` }, splitLine: { lineStyle: { color: t.line } } },
      series: [
        { type: "line", data: lo, stack: "band", symbol: "none", lineStyle: { opacity: 0 }, silent: true },
        { type: "line", data: band, stack: "band", symbol: "none", lineStyle: { opacity: 0 }, areaStyle: { color: t.indigo, opacity: 0.14 }, silent: true },
        { name: "Average cumulative abnormal return", type: "line", data: st.path.map((p) => p.car * 100), symbolSize: 5,
          lineStyle: { width: 2.2, color: t.indigo }, itemStyle: { color: t.indigo },
          markLine: { symbol: "none", silent: true, data: [{ xAxis: String(0), lineStyle: { color: t.muted, type: "dashed" }, label: { formatter: "Day 0", color: t.muted } }] } },
      ],
    };
  }, [st]);
  return <EChart option={option} height={300} />;
}

function StudyTab({ s, onState }: { s: NewsState; onState: (d: NewsState) => void }) {
  const toast = useToast();
  const m = s.market;
  const [group, setGroup] = useState("Both agreed: positive");
  const [w0, setW0] = useState<number | null>(-5);
  const [w1, setW1] = useState<number | null>(10);
  const [bench, setBench] = useState(s.indexes[0]);
  const [preset, setPreset] = useState(s.cost_presets[0]);
  const [entry, setEntry] = useState<"tradable_from" | "published_date">("tradable_from");
  useEffect(() => { setBench(s.indexes[0]); setPreset(s.cost_presets[0]); }, [m]); // eslint-disable-line react-hooks/exhaustive-deps
  const run = useMutation({
    mutationFn: () => post<NewsState>("/api/automate/news/event-study", { market: m, group, window: [w0 ?? -5, w1 ?? 10], benchmark: bench, costs: preset, entry }),
    onSuccess: (d) => { onState(d); toast(`Ran event study: ${d.study?.n ?? 0} events, trial ${d.study?.trials ?? ""}`); },
  });
  if (!s.compare) return <EmptyState>Score with both scorers and click Compare scorers first: the event groups are the headlines both scorers agreed on.</EmptyState>;
  const st = s.study;
  return (
    <div className="flex flex-col gap-5">
      <Panel title="Study settings">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Event group"><Select className="w-56 font-sans" value={group} onChange={(e) => setGroup(e.target.value)}>
            <option>Both agreed: positive</option><option>Both agreed: negative</option></Select></Field>
          <div className="flex items-end gap-1.5">
            <div className="w-24"><NumField label="Window from" value={w0} min={-10} max={0} step={1} onChange={setW0} /></div>
            <span className="pb-2 text-muted">to</span>
            <div className="w-24"><NumField label="to (sessions)" value={w1} min={0} max={20} step={1} onChange={setW1} /></div>
          </div>
          <Field label="Index"><Select className="w-32 font-sans" value={bench} onChange={(e) => setBench(e.target.value)}>{s.indexes.map((x) => <option key={x}>{x}</option>)}</Select></Field>
          <Field label="Cost preset"><Select className="w-48 font-sans" value={preset} onChange={(e) => setPreset(e.target.value)}>{s.cost_presets.map((x) => <option key={x}>{x}</option>)}</Select></Field>
          <Field label="Day 0"><Segmented label="Day 0" value={entry} onChange={setEntry}
            options={[{ value: "tradable_from", label: "Tradable from" }, { value: "published_date", label: "Published date (date-only join)" }]} /></Field>
          <Button variant="primary" onClick={() => run.mutate()} disabled={run.isPending}><Play size={14} /> {run.isPending ? "Computing in code…" : "Run event study"}</Button>
        </div>
        <Note className="mt-2">Window from −10 to 0, to 0 to +20 sessions. Every distinct variant you run adds one trial.</Note>
        <ErrorLine error={run.error} />
      </Panel>

      {!st ? <EmptyState>Pick an event group, a window, the index and a cost preset, then click Run event study.</EmptyState> : (
        <>
          <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
            <FactTile big label="After 20 bps round-trip cost" value={`${signed(st.after_20)} bps`} tone={st.after_20 >= 0 ? "bull" : "bear"} sub="Per event, drift window" />
            <FactTile label="Events" value={st.n} sub={`${st.side} side`} />
            <FactTile label="Day 0 average abnormal move" value={`${signed(st.day0, 2)}%`} sub={`Benchmark ${st.benchmark}`} />
            <FactTile label="Trials in this family" value={st.trials} sub="Trials counter" tone="indigo" />
          </div>
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
            <div className="flex min-w-0 flex-col gap-5">
              <Panel title="Average cumulative abnormal return, with 95% band" action={<Hypothetical />}>
                <StudyChart st={st} />
                <Note>Stock minus {st.benchmark}, around day 0 = {st.entry === "tradable_from" ? "the first session tradable after the headline was seen" : "the published date (date-only join, the Exercise 3 mistake)"}.</Note>
              </Panel>
              <Panel title="Cost table" action={<Hypothetical />}>
                <DataTable rows={st.cost_table} columns={[
                  { key: "Round-trip cost assumed", header: "Round-trip cost assumed" },
                  { key: "Result per event (bps)", header: "Result per event (bps)", align: "right",
                    render: (r) => { const v = Number(r["Result per event (bps)"]); return <span className={v >= 0 ? "text-bull" : "text-bear"}>{signed(v)}</span>; } },
                ]} />
                <Note className="mt-2">Average drift-window result per event (day 0 close to day +2 close), before taxes. Gross {signed(st.drift)} bps, 95% range {signed(st.drift_lo)} to {signed(st.drift_hi)} bps.</Note>
                {st.skipped.length > 0 && <Note className="mt-1">Skipped: {st.skipped.join("; ")}</Note>}
              </Panel>
            </div>
            <Panel title="Explain" className="self-start">
              <ExplainPanel facts={st.facts} section="Automate" question="Explain this event study in plain English, quoting the table, and list how the result could still mislead." />
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------ screen */
export default function NewsPipeline() {
  const [market] = useMarket();
  const qc = useQueryClient();
  const key = ["automate", "news", market];
  const { data: s, error } = useQuery({ queryKey: key, queryFn: () => get<NewsState>(`/api/automate/news/state?market=${market}`) });
  const set = (d: NewsState) => qc.setQueryData(["automate", "news", d.market], d);
  const [tab, setTab] = useState("sources");
  if (error) return <Callout tone="danger" title="The News Pipeline could not load">{(error as Error).message} Restart the lab, then open this screen again.</Callout>;
  return (
    <FactsProvider>
      <div className="flex flex-col gap-5">
        <p className="text-[14px] text-muted">Collect, stamp, score, measure. The model never sees prices; nothing here places an order.</p>
        <Tabs value={tab} onValueChange={setTab}>
          <TabList>
            <Tab value="sources">Sources</Tab>
            <Tab value="score">Score</Tab>
            <Tab value="study">Event study</Tab>
          </TabList>
          <div className="pt-5">
            {!s ? <div className="h-[420px]" /> : (
              <>
                <TabPanel value="sources"><SourcesTab key={market} s={s} onState={set} /></TabPanel>
                <TabPanel value="score"><ScoreTab key={market} s={s} onState={set} /></TabPanel>
                <TabPanel value="study"><StudyTab key={market} s={s} onState={set} /></TabPanel>
              </>
            )}
          </div>
        </Tabs>
        <Note>GDELT: about one request every {s?.gdelt_interval ?? 5} s. The lab stores headline, time and link, not full articles.</Note>
      </div>
    </FactsProvider>
  );
}
