import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Plus, RefreshCw, Save, ClipboardList, Play } from "lucide-react";
import { get, post, type Market } from "@/lib/api";
import { money } from "@/lib/format";
import { cn } from "@/lib/cn";
import { Button, Panel, Field, Tabs, TabList, Tab, TabPanel, inputCls } from "@/components/ui";
import { Badge, Callout, DataTable, EmptyState, Segmented, Select, Textarea, useToast } from "@/components/kit";
import { FactTile, FactsProvider, ExplainPanel } from "@/components/facts";
import { useMarket } from "@/components/shell";
import { Check, ErrorLine, NumField, TextField, useDebounced } from "@/components/planning/common";

const SECTION = "Plan & Risk";
interface Rule { group: string; text: string; status: "accepted" | "suggested" }
interface Card {
  version: number; account: Record<Market, number>; risk_pct: number; position_cap_pct: number; open_risk_cap_r: number;
  group_cap_r: number; daily_limit_r: number; weekly_limit_r: number; max_trades_day: number; cooldown_min: number;
  window: Record<Market, string>; event_lockout_min: number; event_types: string[]; events: { when: string; name: string }[];
  rules: Rule[]; checklist: { text: string; ticked: boolean }[]; pass_marks: Record<string, number>; note: string; written: string;
}
type Limits = Record<Market, { one_r: number; daily: number; weekly: number; position_cap: number }>;
interface CardOut { card: Card; facts: string[]; limits: Limits; groups: string[]; event_types: string[]; synced_version: number | null }
interface Measure { name: string; pass_mark: string; value: string; passed: boolean; rows: (number | string)[] }
interface GoNoGo { verdict: string; go: boolean; measures: Measure[]; facts: string[] }
interface Audit { month: string; items: { item: string; hint: string; done: boolean }[] }

const iso = (d: Date) => d.toISOString().slice(0, 10);
const daysAgo = (n: number) => iso(new Date(Date.now() - n * 864e5));
const eventsText = (c: Card) => c.events.map((e) => `${e.when} ${e.name}`).join("\n");
const parseEvents = (t: string) => t.split("\n").filter((l) => l.trim()).map((l) => {
  const [when, ...rest] = l.trim().split(" ");
  return { when, name: rest.join(" ") || "event" };
});

/* ------------------------------------------------------------ Written rules */
function Written({ card, set, out, market }: { card: Card; set: (c: Card) => void; out?: CardOut; market: Market }) {
  const toast = useToast();
  const qc = useQueryClient();
  const [guardOpen, setGuardOpen] = useState(false);
  const [paste, setPaste] = useState("");
  const [group, setGroup] = useState("Behaviour");
  const [note, setNote] = useState("");
  const [evText, setEvText] = useState(eventsText(card));
  useEffect(() => setEvText(eventsText(card)), [card.version]); // eslint-disable-line react-hooks/exhaustive-deps

  const suggest = useMutation({
    mutationFn: () => post<CardOut>("/api/planning/rulecard/suggest", { card, lines: paste.split("\n"), group }),
    onSuccess: (r) => { set(r.card); setPaste(""); toast("Added as suggestions: click Accept on each one you will follow"); },
  });
  const newVersion = useMutation({
    mutationFn: () => post<CardOut>("/api/planning/rulecard/new-version", { card, note }),
    onSuccess: (r) => { set(r.card); setNote(""); qc.invalidateQueries({ queryKey: ["rc-history"] }); qc.setQueryData(["rulecard"], r); toast(`Saved Rule Card version ${r.card.version}`); },
  });
  const sync = useMutation({
    mutationFn: () => post<{ values: Record<string, unknown>; version: number }>("/api/planning/rulecard/sync", { card }),
    onSuccess: (r) => {
      const by = r.values["paper.daily_loss_limit_by_market"] as Record<Market, number>;
      qc.invalidateQueries({ queryKey: ["paper"] });
      toast(`Synced limits: Position Sizer caps and the Paper Desk daily loss limit (${money(by[market], market)}) now match version ${r.version}`);
    },
  });
  const { data: adh } = useQuery({ queryKey: ["rc-adherence"], queryFn: () => get<{ decisions: number; followed: number; score: number | null; broken_rows: number[] }>("/api/planning/rulecard/adherence") });
  const { data: hist = [] } = useQuery({ queryKey: ["rc-history"], queryFn: () => get<{ id: number; version: number; written: string; note: string }[]>("/api/planning/rulecard/history") });

  const lim = out?.limits;
  const setRule = (i: number, r: Rule | null) => set({ ...card, rules: r ? card.rules.map((x, j) => (j === i ? r : x)) : card.rules.filter((_, j) => j !== i) });
  const groups = out?.groups ?? ["Size & risk", "Limits", "Behaviour"];
  const extra = [...new Set(card.rules.map((r) => r.group))].filter((g) => !groups.includes(g));

  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
        <FactTile big label="Daily loss limit" value={lim ? money(lim[market].daily, market) : "…"} sub={`${card.daily_limit_r}R, stop for the day`} />
        <FactTile label="1R" value={lim ? money(lim[market].one_r, market) : "…"} sub={`${(card.risk_pct * 100).toFixed(2)}% of account`} />
        <FactTile label="Weekly loss limit" value={lim ? money(lim[market].weekly, market) : "…"} sub={`${card.weekly_limit_r}R`} />
        <FactTile label="Largest position" value={lim ? money(lim[market].position_cap, market) : "…"} sub={`${(card.position_cap_pct * 100).toFixed(0)}% of account`} />
      </div>

      <Panel title="Size & risk, and limits">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <NumField label="Account (IN, ₹)" value={card.account.IN} step={10000} onChange={(v) => set({ ...card, account: { ...card.account, IN: v ?? 0 } })} />
          <NumField label="Account (US, $)" value={card.account.US} step={1000} onChange={(v) => set({ ...card, account: { ...card.account, US: v ?? 0 } })} />
          <NumField label="1R (% of account)" value={Math.round(card.risk_pct * 10000) / 100} step={0.05} onChange={(v) => set({ ...card, risk_pct: (v ?? 0) / 100 })} />
          <NumField label="Largest position (% of account)" value={Math.round(card.position_cap_pct * 10000) / 100} step={1} onChange={(v) => set({ ...card, position_cap_pct: (v ?? 0) / 100 })} />
          <NumField label="Open risk cap (R)" value={card.open_risk_cap_r} step={0.5} onChange={(v) => set({ ...card, open_risk_cap_r: v ?? 0 })} />
          <NumField label="One correlated group (R)" value={card.group_cap_r} step={0.5} onChange={(v) => set({ ...card, group_cap_r: v ?? 0 })} />
          <NumField label="Daily loss limit (R)" value={card.daily_limit_r} step={0.5} onChange={(v) => set({ ...card, daily_limit_r: v ?? 0 })} />
          <NumField label="Weekly loss limit (R)" value={card.weekly_limit_r} step={0.5} onChange={(v) => set({ ...card, weekly_limit_r: v ?? 0 })} />
        </div>
        <div className="mt-4">
          <DataTable rows={(["IN", "US"] as Market[]).map((m) => ({ m, ...(lim?.[m] ?? { one_r: 0, daily: 0, weekly: 0, position_cap: 0 }) }))} columns={[
            { key: "m", header: "Market", render: (r) => <Badge tone={r.m === "IN" ? "in" : "us"}>{r.m}</Badge> },
            { key: "one_r", header: "1R", align: "right", render: (r) => money(r.one_r, r.m) },
            { key: "daily", header: "Daily limit", align: "right", render: (r) => money(r.daily, r.m) },
            { key: "weekly", header: "Weekly limit", align: "right", render: (r) => money(r.weekly, r.m) },
            { key: "position_cap", header: "Largest position", align: "right", render: (r) => money(r.position_cap, r.m) },
          ]} />
        </div>
      </Panel>

      <section className="rounded-[var(--radius-panel)] border border-line bg-panel">
        <button type="button" onClick={() => setGuardOpen((o) => !o)} aria-expanded={guardOpen}
          className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-[14px] font-semibold">
          {guardOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />} Intraday guardrails
          <span className="ml-auto text-[13px] font-normal text-muted">max {card.max_trades_day} trades a day, cooldown {card.cooldown_min} min, lockout {card.event_lockout_min} min</span>
        </button>
        {guardOpen && (
          <div className="flex flex-col gap-4 border-t border-line p-4">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <NumField label="Max trades a day" value={card.max_trades_day} step={1} onChange={(v) => set({ ...card, max_trades_day: Math.round(v ?? 0) })} />
              <NumField label="Cooldown after a loss (min)" value={card.cooldown_min} step={5} onChange={(v) => set({ ...card, cooldown_min: Math.round(v ?? 0) })} />
              <TextField label="Trading window IST" value={card.window.IN ?? ""} placeholder="09:30-15:00" onChange={(v) => set({ ...card, window: { ...card.window, IN: v } })} />
              <TextField label="Trading window ET" value={card.window.US ?? ""} placeholder="09:45-15:30" onChange={(v) => set({ ...card, window: { ...card.window, US: v } })} />
            </div>
            <div className="grid gap-4 md:grid-cols-[220px_minmax(0,1fr)]">
              <NumField label="Event lockout (min before and after)" value={card.event_lockout_min} step={5} onChange={(v) => set({ ...card, event_lockout_min: Math.round(v ?? 0) })} />
              <Field label="Event types to lock out">
                <div className="flex flex-wrap gap-x-5">
                  {(out?.event_types ?? []).map((t) => (
                    <Check key={t} checked={card.event_types.includes(t)}
                      onChange={(v) => set({ ...card, event_types: v ? [...card.event_types, t] : card.event_types.filter((x) => x !== t) })}>{t}</Check>
                  ))}
                </div>
              </Field>
            </div>
            <Field label="Events" hint="Dates come from your calendar; one per line, as YYYY-MM-DDTHH:MM name">
              <Textarea value={evText} rows={3} placeholder="2026-10-08T10:00 RBI policy"
                onChange={(e) => { setEvText(e.target.value); set({ ...card, events: parseEvents(e.target.value) }); }} />
            </Field>
          </div>
        )}
      </section>

      <Panel title="Your written rules">
        <div className="flex flex-col gap-4">
          {[...groups, ...extra].map((g) => {
            const rows = card.rules.map((r, i) => ({ r, i })).filter(({ r }) => r.group === g);
            if (!rows.length) return null;
            return (
              <div key={g}>
                <div className="mb-1 text-[13px] font-medium text-muted">{g}</div>
                <ul className="divide-y divide-line rounded-[var(--radius-tile)] border border-line">
                  {rows.map(({ r, i }) => (
                    <li key={i} className="flex items-center gap-3 px-3 py-2">
                      <span className={cn("flex-1 text-[14px]", r.status === "suggested" && "italic text-muted")}>{r.text}</span>
                      {r.status === "suggested" && <Badge tone="indigo">Suggestion</Badge>}
                      {r.status === "suggested"
                        ? <Button size="sm" variant="primary" onClick={() => setRule(i, { ...r, status: "accepted" })}>Accept</Button>
                        : <Button size="sm" variant="quiet" onClick={() => setRule(i, null)}>Delete</Button>}
                      {r.status === "suggested" && <Button size="sm" variant="quiet" onClick={() => setRule(i, null)}>Discard</Button>}
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
          <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_200px]">
            <Field label="Paste rule lines (one per line); they arrive as suggestions">
              <Textarea value={paste} onChange={(e) => setPaste(e.target.value)} rows={3} placeholder="No new trade after two losses in a day" />
            </Field>
            <div className="flex flex-col gap-2">
              <Field label="Group"><Select className="font-sans" value={group} onChange={(e) => setGroup(e.target.value)}>{groups.map((g) => <option key={g}>{g}</option>)}</Select></Field>
              <Button onClick={() => suggest.mutate()} disabled={!paste.trim() || suggest.isPending}><Plus size={15} /> Add as suggestions</Button>
            </div>
          </div>
        </div>
      </Panel>

      <Panel>
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[260px] flex-1"><TextField label="What changed (dated in the history)" value={note} onChange={setNote} placeholder="Daily limit from 3R to 2R" /></div>
          <Button variant="primary" onClick={() => newVersion.mutate()} disabled={newVersion.isPending}><Save size={15} /> New version</Button>
          <Button onClick={() => sync.mutate()} disabled={sync.isPending}><RefreshCw size={15} /> Sync limits</Button>
        </div>
        <p className="mt-2 text-[13px] text-muted">
          New version saves a dated copy. Sync limits pushes these numbers to the Position Sizer caps and the Paper Desk's daily loss limit and guardrails
          {out?.synced_version ? `; last synced from version ${out.synced_version}` : ""}.
        </p>
        <ErrorLine error={newVersion.error ?? sync.error ?? suggest.error} />
      </Panel>

      <div className="grid gap-5 lg:grid-cols-[280px_minmax(0,1fr)]">
        <div className="flex flex-col gap-2">
          <FactTile label="Adherence score" value={adh?.score != null ? `${(adh.score * 100).toFixed(1)}%` : "—"}
            sub={adh?.score != null ? `${adh.followed} of ${adh.decisions} decisions followed the rules` : "No paper, replay or pilot trades in the journal yet"} />
          {adh && adh.broken_rows.length > 0 && <p className="text-[13px] text-muted">Journal rows that broke a rule: {adh.broken_rows.slice(0, 20).map((r) => `#${r}`).join(", ")}</p>}
          <p className="text-[13px] text-muted">That score, not profit, is the first number to improve.</p>
        </div>
        <Panel title="Version history">
          <DataTable rows={hist} empty="No saved versions yet: you are looking at the template. Click New version to save it."
            columns={[
              { key: "version", header: "Version", align: "right", width: "80px" },
              { key: "written", header: "Written", render: (r) => String(r.written ?? "").replace("T", " ").slice(0, 16) },
              { key: "note", header: "What changed", render: (r) => r.note || <span className="text-muted">—</span> },
            ]} />
        </Panel>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ Checklist */
function Checklist({ card, set }: { card: Card; set: (c: Card) => void }) {
  const [item, setItem] = useState("");
  return (
    <Panel title="Pre-market checklist" className="max-w-[760px]">
      <p className="mb-3 text-[13px] text-muted">Ticked items appear in the Daily Briefing's Questions for you.</p>
      <div className="flex flex-col">
        {card.checklist.map((c, i) => (
          <Check key={i} checked={c.ticked} onChange={(v) => set({ ...card, checklist: card.checklist.map((x, j) => (j === i ? { ...x, ticked: v } : x)) })}>{c.text}</Check>
        ))}
      </div>
      <div className="mt-4 flex items-end gap-2">
        <div className="flex-1"><TextField label="Add a checklist item" value={item} onChange={setItem} placeholder="Checked the overnight gap?" /></div>
        <Button onClick={() => { set({ ...card, checklist: [...card.checklist, { text: item.trim(), ticked: true }] }); setItem(""); }} disabled={!item.trim()}><Plus size={15} /> Add item</Button>
      </div>
      <p className="mt-3 text-[13px] text-muted">Click New version on the Written rules tab to save checklist changes.</p>
    </Panel>
  );
}

/* ------------------------------------------------------------ Go / no-go */
function GoNoGoTab({ out, market }: { out?: CardOut; market: Market }) {
  const toast = useToast();
  const [account, setAccount] = useState<"Paper" | "Pilot">("Paper");
  const [from, setFrom] = useState(daysAgo(60));
  const [to, setTo] = useState(iso(new Date()));
  const run = useMutation({ mutationFn: () => post<GoNoGo>("/api/planning/rulecard/gonogo", { account, start: from, end: to }) });
  const g = run.data;
  const oneR = out?.limits[market].one_r ?? 0;
  const [pilot, setPilot] = useState({ budget: 3 * oneR, trades: 1, review: iso(new Date(Date.now() + 42 * 864e5)), size: "",
    stops: "Pilot budget used up → stop\nDaily loss limit hit → stop for the day\nA stop moved away from entry → back to paper" });
  useEffect(() => setPilot((p) => ({ ...p, budget: 3 * oneR })), [oneR]);
  const [pilotOpen, setPilotOpen] = useState(false);
  useEffect(() => { if (g?.go) setPilotOpen(true); }, [g?.go]);
  const save = useMutation({
    mutationFn: () => post<{ id: number }>("/api/planning/rulecard/pilot", { market, budget: pilot.budget, trades_per_day: pilot.trades,
      review_date: pilot.review, stop_conditions: pilot.stops.split("\n"), size: pilot.size }),
    onSuccess: (r) => toast(`Saved pilot plan #${r.id}. The lab sends nothing to your broker`),
  });
  return (
      <div className="flex flex-col gap-5">
        <Panel>
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Account"><Segmented label="Account" value={account} options={["Paper", "Pilot"] as const} onChange={setAccount} /></Field>
            <Field label="From"><input type="date" className={cn(inputCls, "w-44")} value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
            <Field label="To"><input type="date" className={cn(inputCls, "w-44")} value={to} onChange={(e) => setTo(e.target.value)} /></Field>
            <Button variant="primary" onClick={() => run.mutate()} disabled={run.isPending}><Play size={15} /> {run.isPending ? "Checking…" : "Run check"}</Button>
          </div>
          <p className="mt-3 text-[13px] text-muted">Each measure is computed in code from Journal › Trades, against the pass marks on your Rule Card.</p>
          <ErrorLine error={run.error} />
        </Panel>
        {!g ? (
          <EmptyState>Choose the account and the period, then click <b className="text-ink">Run check</b>. Process measures only; profit is deliberately not on the list.</EmptyState>
        ) : (
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
            <div className="flex min-w-0 flex-col gap-4">
              <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3">
                <div className="col-span-2 md:col-span-3">
                  <FactTile big label="Verdict" value={g.go ? g.verdict.replace("GO", "Go") : "Not yet"} tone={g.go ? "indigo" : undefined}
                    sub={`${g.measures.filter((m) => m.passed).length} of ${g.measures.length} measures pass`} />
                </div>
                {g.measures.map((m) => (
                  <FactTile key={m.name} label={m.name} value={m.value}
                    sub={<span className="flex items-center gap-1.5">{m.passed ? <Badge tone="indigo">Pass</Badge> : <Badge tone="warn">Not yet</Badge>} pass mark {m.pass_mark}</span>} />
                ))}
              </div>
              <Panel title="Measures and their rows">
                <DataTable rows={g.measures as unknown as Record<string, unknown>[]} columns={[
                  { key: "name", header: "Measure" },
                  { key: "pass_mark", header: "Pass mark", align: "right" },
                  { key: "value", header: "Value", align: "right" },
                  { key: "passed", header: "Result", render: (m) => (m.passed ? <Badge tone="indigo">Pass</Badge> : <Badge tone="warn">Not yet</Badge>) },
                  { key: "rows", header: "Journal rows", render: (m) => ((m.rows as unknown[]).length ? (m.rows as unknown[]).slice(0, 10).map((r) => `#${r}`).join(", ") : <span className="text-muted">—</span>) },
                ]} />
                <p className="mt-3 text-[13px] text-muted">Process measures only. Profit is deliberately not on this list.</p>
              </Panel>
            </div>
            <Panel title="Explain the measures">
              <ExplainPanel facts={g.facts} section={SECTION} sensitive />
              <p className="mt-2 text-[12px] text-muted">Sensitive: explained by your local model only.</p>
            </Panel>
          </div>
        )}

        <section className="rounded-[var(--radius-panel)] border border-line bg-panel">
          <button type="button" onClick={() => setPilotOpen((o) => !o)} aria-expanded={pilotOpen} className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-[14px] font-semibold">
            {pilotOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />} Save pilot plan
            <span className="ml-auto text-[13px] font-normal text-muted">Small, capped and dated</span>
          </button>
          {pilotOpen && (
            <div className="flex flex-col gap-3 border-t border-line p-4">
              <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
                <NumField label="Pilot budget" value={pilot.budget} step={100} onChange={(v) => setPilot({ ...pilot, budget: v ?? 0 })} hint={`3 × 1R is ${money(3 * oneR, market)}`} />
                <NumField label="Trades a day" value={pilot.trades} step={1} min={1} max={20} onChange={(v) => setPilot({ ...pilot, trades: Math.round(v ?? 0) })} />
                <Field label="Review date"><input type="date" className={inputCls} value={pilot.review} onChange={(e) => setPilot({ ...pilot, review: e.target.value })} /></Field>
              </div>
              <TextField label="Pilot size (from the Position Sizer › Use in plan)" value={pilot.size} onChange={(v) => setPilot({ ...pilot, size: v })} placeholder="1 lot, risk ₹10,950" />
              <Field label="Stop conditions (one per line)"><Textarea rows={3} value={pilot.stops} onChange={(e) => setPilot({ ...pilot, stops: e.target.value })} /></Field>
              <div><Button variant="primary" onClick={() => save.mutate()} disabled={save.isPending}><Save size={15} /> Save pilot plan</Button></div>
              <ErrorLine error={save.error} />
              {save.isSuccess && <p className="text-[13px] text-muted">Real trades imported during the pilot are tagged PILOT in Journal › Trades. The lab sends nothing to your broker.</p>}
            </div>
          )}
        </section>
      </div>
  );
}

/* ------------------------------------------------------------ Monthly audit */
function AuditTab() {
  const toast = useToast();
  const [a, setA] = useState<Audit | null>(null);
  const start = useMutation({ mutationFn: () => post<Audit>("/api/planning/rulecard/audit/start"), onSuccess: setA });
  const save = useMutation({ mutationFn: () => post<{ id: number }>("/api/planning/rulecard/audit/save", a), onSuccess: () => toast("Audit saved to your reviews") });
  const done = a?.items.filter((i) => i.done).length ?? 0;
  return (
    <div className="flex max-w-[860px] flex-col gap-4">
      <div className="flex items-center gap-3">
        <Button variant="primary" onClick={() => start.mutate()} disabled={start.isPending}><ClipboardList size={15} /> Start audit</Button>
        {a && <span className="text-[13px] text-muted">Monthly audit for {a.month}</span>}
      </div>
      <ErrorLine error={start.error ?? save.error} />
      {!a ? (
        <EmptyState>First weekend of the month, about 45 minutes. Start with <code>plugai-trade update</code> and <code>plugai-trade doctor</code>, then click Start audit.</EmptyState>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3">
            <FactTile big label="Audit items done" value={`${done} of ${a.items.length}`} />
          </div>
          <Panel>
            <div className="flex flex-col">
              {a.items.map((it, i) => (
                <Check key={it.item} checked={it.done} hint={it.hint}
                  onChange={(v) => setA({ ...a, items: a.items.map((x, j) => (j === i ? { ...x, done: v } : x)) })}>
                  <span className="font-medium">{it.item}</span>
                </Check>
              ))}
            </div>
            <div className="mt-4"><Button onClick={() => save.mutate()} disabled={save.isPending}><Save size={15} /> Save audit</Button></div>
          </Panel>
        </>
      )}
    </div>
  );
}

/* ------------------------------------------------------------ screen */
export default function RuleCard() {
  const [market] = useMarket();
  const [tab, setTab] = useState("written");
  const { data: saved, error } = useQuery({ queryKey: ["rulecard"], queryFn: () => get<CardOut>("/api/planning/rulecard") });
  const [card, setCard] = useState<Card | null>(null);
  useEffect(() => { if (saved && !card) setCard(saved.card); }, [saved, card]);
  const dc = useDebounced(card, 250);
  const { data: out } = useQuery({
    queryKey: ["rulecard-preview", dc], enabled: !!dc, placeholderData: keepPreviousData,
    queryFn: () => post<CardOut>("/api/planning/rulecard/preview", { card: dc }),
  });
  const view = out ?? saved;
  return (
    <FactsProvider>
      <div className="flex flex-col gap-5">
        <div className="flex flex-wrap items-baseline gap-3">
          <span className="text-[14px] font-semibold">Version {card?.version ?? "…"}</span>
          <span className="text-[13px] text-muted">{card?.written ? `written ${card.written.slice(0, 10)}` : "template, not saved yet"}</span>
          <span className="text-[13px] text-muted">Short, specific, checkable rules, read every morning.</span>
        </div>
        {error && <Callout tone="danger" title="The Rule Card could not be loaded">{(error as Error).message}</Callout>}
        {card && (
          <Tabs value={tab} onValueChange={setTab}>
            <TabList>
              <Tab value="written">Written rules</Tab>
              <Tab value="checklist">Checklist</Tab>
              <Tab value="gonogo">Go / no-go</Tab>
              <Tab value="audit">Monthly audit</Tab>
            </TabList>
            <TabPanel value="written" className="pt-5"><Written card={card} set={setCard} out={view} market={market} /></TabPanel>
            <TabPanel value="checklist" className="pt-5"><Checklist card={card} set={setCard} /></TabPanel>
            <TabPanel value="gonogo" className="pt-5"><GoNoGoTab out={view} market={market} /></TabPanel>
            <TabPanel value="audit" className="pt-5"><AuditTab /></TabPanel>
          </Tabs>
        )}
      </div>
    </FactsProvider>
  );
}
