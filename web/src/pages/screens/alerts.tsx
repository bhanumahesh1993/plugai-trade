import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellPlus, Send, Pause, Play, Check as CheckIcon, X, Save, ChevronDown, ChevronRight } from "lucide-react";
import { get, post } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button, Panel, Field, inputCls } from "@/components/ui";
import { Badge, Callout, DataTable, EmptyState, Segmented, Select, useToast } from "@/components/kit";
import { FactTile, FactsProvider } from "@/components/facts";
import { useMarket } from "@/components/shell";
import { Check, ErrorLine, NumField, TextField } from "@/components/planning/common";

interface Alert {
  id: number | null; name: string; symbol: string; market: string; kind: string; condition: string; level: number | null;
  level2: number | null; indicator: string | null; bar_size: string; plan_id: number | null; plan_name: string; expires: string;
  channels: string[]; attach_paper_order: boolean; order_draft: Record<string, unknown> | null; breakthrough: boolean;
  ai_note: boolean; status: string; describe: string; when: string;
}
interface LogRow { id: number; at: string; event: string; name: string; bar?: string; delivered?: string[]; message: string }
interface State {
  alerts: Alert[]; proposed: Alert[]; log: LogRow[]; plans: { id: number; name: string; symbol: string }[];
  crypto_positions: { key: string; label: string }[]; in_quiet_hours: boolean;
  channels: { quiet_hours: string; telegram_chat_id: string; telegram_token: string; email_to: string; smtp_host: string; smtp_port: number };
  options: { channels: string[]; bar_sizes: string[]; conditions: string[]; indicators: string[] };
}
type Source = "From plan" | "From Crypto Monitor" | "Blank";

const STATUS_TONE: Record<string, "indigo" | "neutral" | "warn"> = { active: "indigo", fired: "neutral", expired: "neutral", paused: "warn" };
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/* ------------------------------------------------------------ New alert */
function NewAlert({ s, market, onProposed }: { s: State; market: string; onProposed: (a: Alert[]) => void }) {
  const [src, setSrc] = useState<Source>("From plan");
  const [picked, setPicked] = useState<number[]>([]);
  useEffect(() => setPicked(s.plans.slice(0, 1).map((p) => p.id)), [s.plans.length, market]); // eslint-disable-line react-hooks/exhaustive-deps
  const [pos, setPos] = useState("");
  const [lev, setLev] = useState(5);
  const [b, setB] = useState({ symbol: market === "IN" ? "NIFTY FUT" : "SPY", kind: "price", condition: "touch above", level: null as number | null, indicator: "sma_20" });
  const propose = useMutation({
    mutationFn: () => post<Alert[]>("/api/planning/alerts/propose", {
      source: src, market, plan_ids: picked, position_key: pos || s.crypto_positions[0]?.key, leverage: lev, ...b,
    }),
    onSuccess: onProposed,
  });
  return (
    <Panel title="New alert">
      <div className="flex flex-col gap-4">
        <Field label="Start from"><Segmented label="Start from" value={src} options={["From plan", "From Crypto Monitor", "Blank"] as const} onChange={setSrc} /></Field>
        {src === "From plan" && (s.plans.length ? (
          <div className="flex flex-col gap-2">
            <span className="text-[12px] text-muted">Plans</span>
            <div className="flex flex-wrap gap-x-5">
              {s.plans.map((p) => (
                <Check key={p.id} checked={picked.includes(p.id)} onChange={(v) => setPicked(v ? [...picked, p.id] : picked.filter((x) => x !== p.id))}>#{p.id} {p.name} ({p.symbol})</Check>
              ))}
            </div>
            <div><Button variant="primary" onClick={() => propose.mutate()} disabled={!picked.length || propose.isPending}>Propose alerts</Button></div>
          </div>
        ) : <EmptyState>No saved plans for this market yet. Write one in Plan & Risk › Trade Plan, then come back.</EmptyState>)}
        {src === "From Crypto Monitor" && (s.crypto_positions.length ? (
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Paper position">
              <Select className="w-72 font-sans" value={pos || s.crypto_positions[0].key} onChange={(e) => setPos(e.target.value)}>
                {s.crypto_positions.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
              </Select>
            </Field>
            <div className="w-32"><NumField label="Leverage" value={lev} step={1} min={1} max={125} onChange={(v) => setLev(v ?? 1)} /></div>
            <Button variant="primary" onClick={() => propose.mutate()} disabled={propose.isPending}>Propose alerts</Button>
          </div>
        ) : <EmptyState>No paper perpetual positions yet. Open one on the Paper Desk and click Send to Crypto Monitor.</EmptyState>)}
        {src === "Blank" && (
          <div className="flex flex-col gap-3">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <TextField label="Symbol" value={b.symbol} onChange={(v) => setB({ ...b, symbol: v.toUpperCase() })} />
              <Field label="Type"><Select className="font-sans" value={b.kind} onChange={(e) => setB({ ...b, kind: e.target.value })}>{["price", "indicator", "event"].map((k) => <option key={k} value={k}>{cap(k)}</option>)}</Select></Field>
              <Field label="Condition"><Select className="font-sans" value={b.condition} onChange={(e) => setB({ ...b, condition: e.target.value })} disabled={b.kind === "event"}>{s.options.conditions.map((c) => <option key={c} value={c}>{cap(c)}</option>)}</Select></Field>
              {b.kind === "indicator"
                ? <Field label="Indicator"><Select className="font-sans" value={b.indicator} onChange={(e) => setB({ ...b, indicator: e.target.value })}>{s.options.indicators.map((c) => <option key={c}>{c}</option>)}</Select></Field>
                : <NumField label="Level" value={b.level} disabled={b.kind === "event"} onChange={(v) => setB({ ...b, level: v })} />}
            </div>
            <div><Button variant="primary" onClick={() => propose.mutate()} disabled={propose.isPending}>Propose alert</Button></div>
          </div>
        )}
        <ErrorLine error={propose.error} />
      </div>
    </Panel>
  );
}

/* ------------------------------------------------------------ Review proposals */
function ProposalCard({ a, s, onChange }: { a: Alert; s: State; onChange: (a: Alert) => void }) {
  const editableLevel = a.level !== null && ["price", "loss_limit", "funding"].includes(a.kind);
  return (
    <div className="rounded-[var(--radius-tile)] border border-line bg-panel-2 p-3.5">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="font-medium">{a.name}</span>
        <span className="text-[13px] text-muted">{a.describe}</span>
        {a.plan_name && <Badge>{a.plan_id ? `Plan #${a.plan_id}` : a.plan_name}</Badge>}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Field label="Bar size"><Select className="font-sans" value={a.bar_size} onChange={(e) => onChange({ ...a, bar_size: e.target.value })}>{s.options.bar_sizes.map((x) => <option key={x}>{x}</option>)}</Select></Field>
        {editableLevel ? <NumField label="Level" value={a.level} onChange={(v) => onChange({ ...a, level: v })} /> : <Field label="Condition"><span className="flex h-9 items-center text-[14px]">{cap(a.condition)}</span></Field>}
        <Field label="Expiry (date)"><input type="text" className={cn(inputCls, "font-sans")} placeholder="none" value={a.expires} onChange={(e) => onChange({ ...a, expires: e.target.value })} /></Field>
        <Field label="Channels">
          <div className="flex h-9 items-center gap-3">
            {s.options.channels.map((c) => (
              <label key={c} className="flex items-center gap-1.5 text-[14px]">
                <input type="checkbox" className="h-4 w-4 accent-[var(--indigo)]" checked={a.channels.includes(c)}
                  onChange={(e) => onChange({ ...a, channels: e.target.checked ? [...a.channels, c] : a.channels.filter((x) => x !== c) })} />{c}
              </label>
            ))}
          </div>
        </Field>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-6">
        <Check checked={a.breakthrough} onChange={(v) => onChange({ ...a, breakthrough: v })}>May break through quiet hours</Check>
        <Check checked={a.ai_note} onChange={(v) => onChange({ ...a, ai_note: v })}>AI note (one sentence of context)</Check>
        {a.order_draft && (
          <Check checked={a.attach_paper_order} onChange={(v) => onChange({ ...a, attach_paper_order: v })}
            hint="Creates a pending paper order on the Paper Desk; it still waits for your Accept">Attach paper order</Check>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ Channels */
function Channels({ s }: { s: State }) {
  const toast = useToast();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [c, setC] = useState({ ...s.channels, telegram_token: "" });
  useEffect(() => setC({ ...s.channels, telegram_token: "" }), [s.channels]);
  const save = useMutation({
    mutationFn: () => post("/api/planning/alerts/channels", c),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["alerts"] }); toast("Saved channels. Send /start to your bot, then click Send test on an alert"); },
  });
  return (
    <section className="rounded-[var(--radius-panel)] border border-line bg-panel">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-[14px] font-semibold">
        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />} Channels and quiet hours
        <span className="ml-auto text-[13px] font-normal text-muted">{s.channels.quiet_hours ? `Quiet hours ${s.channels.quiet_hours}` : "No quiet hours set"}</span>
      </button>
      {open && (
        <div className="flex flex-col gap-3 border-t border-line p-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
            <TextField label="Quiet hours" placeholder="23:00-06:00" value={c.quiet_hours} onChange={(v) => setC({ ...c, quiet_hours: v })} />
            <TextField label="Telegram chat id" value={c.telegram_chat_id} onChange={(v) => setC({ ...c, telegram_chat_id: v })} />
            <Field label="Telegram bot token" hint="Stored in the OS keychain (Settings › Keys)"><span className="num flex h-9 items-center text-[14px]">{s.channels.telegram_token || "not set"}</span></Field>
            <TextField label="Email address" value={c.email_to} onChange={(v) => setC({ ...c, email_to: v })} />
            <TextField label="SMTP server" value={c.smtp_host} onChange={(v) => setC({ ...c, smtp_host: v })} />
            <NumField label="SMTP port" value={c.smtp_port} step={1} onChange={(v) => setC({ ...c, smtp_port: v ?? 587 })} />
          </div>
          <Field label="Paste BotFather token (stored in the OS keychain)">
            <input type="password" autoComplete="off" className={inputCls} value={c.telegram_token} onChange={(e) => setC({ ...c, telegram_token: e.target.value })} />
          </Field>
          <div><Button variant="primary" onClick={() => save.mutate()} disabled={save.isPending}><Save size={15} /> Save channels</Button></div>
          <ErrorLine error={save.error} />
          <p className="text-[13px] text-muted">Channels: Desktop (this lab), Email and Telegram. Every message starts with SIMULATED.</p>
        </div>
      )}
    </section>
  );
}

/* ------------------------------------------------------------ screen */
export default function Alerts() {
  const [market] = useMarket();
  const qc = useQueryClient();
  const toast = useToast();
  const key = ["alerts", market];
  const { data: s } = useQuery({ queryKey: key, queryFn: () => get<State>(`/api/planning/alerts?market=${market}`) });
  const refresh = () => qc.invalidateQueries({ queryKey: ["alerts"] });
  const [open, setOpen] = useState(false);
  const [props, setProps] = useState<Alert[]>([]);
  const [test, setTest] = useState<{ id: number; message: string; delivered: string[] } | null>(null);
  const [logOpen, setLogOpen] = useState(false);

  const acceptAll = useMutation({
    mutationFn: () => post<{ accepted: number }>("/api/planning/alerts/accept", { alerts: props }),
    onSuccess: (r) => { setProps([]); refresh(); toast(`Accepted: ${r.accepted} alert${r.accepted === 1 ? "" : "s"} active`); },
  });
  const act = useMutation({
    mutationFn: ({ id, action }: { id: number; action: "accept" | "discard" | "pause" | "resume" }) => post(`/api/planning/alerts/${id}/${action}`),
    onSuccess: (_d, v) => { refresh(); toast({ accept: "Accepted: alert active", discard: "Discarded the proposed alert", pause: "Paused the alert", resume: "Resumed the alert" }[v.action]); },
  });
  const sendTest = useMutation({
    mutationFn: (id: number) => post<{ message: string; delivered: string[] }>(`/api/planning/alerts/${id}/test`),
    onSuccess: (r, id) => { setTest({ id, ...r }); refresh(); toast(r.delivered.length ? `Sent test to ${r.delivered.join(", ")}` : "Test not delivered: see the alert log", r.delivered.length ? "ok" : "danger"); },
  });

  const active = s?.alerts.filter((a) => a.status === "active").length ?? 0;
  const fired = s?.alerts.filter((a) => a.status === "fired").length ?? 0;
  const held = s?.log.filter((l) => l.event === "held").length ?? 0;
  const waiting = (s?.proposed.length ?? 0) + props.length;

  return (
    <FactsProvider>
      <div className="flex flex-col gap-5">
        <div className="flex flex-wrap items-center gap-3 rounded-[var(--radius-panel)] border border-line bg-panel px-4 py-2.5">
          <Badge tone="indigo">Simulated</Badge>
          <span className="text-[13px] text-muted">Rules checked in code on completed bars. Every message says SIMULATED; paper only, no real orders.</span>
          {s?.in_quiet_hours && <Badge tone="warn">Quiet hours now</Badge>}
          <Button variant="primary" className="ml-auto" onClick={() => setOpen(true)}><BellPlus size={15} /> New alert</Button>
        </div>

        <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
          <FactTile big label="Active alerts" value={active} sub="Evaluated by the Scheduler on completed bars" />
          <FactTile label="Waiting for Accept" value={waiting} sub="Inactive until you click Accept" />
          <FactTile label="Fired" value={fired} />
          <FactTile label="Held in quiet hours" value={held} />
        </div>

        {open && s && <NewAlert s={s} market={market} onProposed={(a) => { setProps(a); toast(`Proposed ${a.length} alert${a.length === 1 ? "" : "s"}: review, then Accept`); }} />}

        {props.length > 0 && s && (
          <Panel title="Proposed alerts" action={<span className="text-[13px] text-muted">Check bar size and condition; nothing is active until Accept</span>}>
            <div className="flex flex-col gap-3">
              {props.map((a, i) => <ProposalCard key={i} a={a} s={s} onChange={(n) => setProps(props.map((x, j) => (j === i ? n : x)))} />)}
            </div>
            <div className="mt-4 flex gap-2">
              <Button variant="primary" onClick={() => acceptAll.mutate()} disabled={acceptAll.isPending}><CheckIcon size={15} /> Accept</Button>
              <Button onClick={() => setProps([])}>Discard proposals</Button>
            </div>
            <ErrorLine error={acceptAll.error} />
          </Panel>
        )}

        {s && s.proposed.length > 0 && (
          <Panel title="Proposed by other screens" action={<span className="text-[13px] text-muted">Inactive until Accept</span>}>
            <ul className="divide-y divide-line">
              {s.proposed.map((a) => (
                <li key={a.id} className="flex flex-wrap items-center gap-3 py-2">
                  <span className="flex-1"><span className="font-medium">#{a.id} {a.name}</span> <span className="text-[13px] text-muted">{a.describe}</span></span>
                  <Button size="sm" variant="primary" onClick={() => act.mutate({ id: a.id!, action: "accept" })}>Accept</Button>
                  <Button size="sm" variant="quiet" onClick={() => act.mutate({ id: a.id!, action: "discard" })}><X size={14} /> Discard</Button>
                </li>
              ))}
            </ul>
          </Panel>
        )}

        <Panel title="Alerts">
          {!s ? <div className="h-16" /> : s.alerts.length === 0 ? (
            <EmptyState action={<Button variant="primary" onClick={() => setOpen(true)}><BellPlus size={15} /> New alert</Button>}>
              No alerts yet. Click New alert and start from a saved Trade Plan: the lab proposes the entry trigger, stop, exit and loss-limit alerts.
            </EmptyState>
          ) : (
            <DataTable rows={s.alerts as unknown as Record<string, unknown>[]} rowKey={(r) => r.id as number} columns={[
              { key: "id", header: "#", align: "right", width: "48px" },
              { key: "status", header: "Status", render: (r) => <Badge tone={STATUS_TONE[r.status as string] ?? "neutral"}>{cap(r.status as string)}</Badge> },
              { key: "name", header: "Alert", render: (r) => (
                <div><div className="font-medium">{r.name as string}</div>
                  <div className="text-[13px] text-muted">{r.describe as string}{r.expires ? `, expires ${r.expires}` : ""}{r.attach_paper_order ? ", paper order attached" : ""}</div></div>) },
              { key: "channels", header: "Channels", render: (r) => (r.channels as string[]).join(", ") },
              { key: "actions", header: "", render: (r) => (
                <div className="flex justify-end gap-1.5">
                  <Button size="sm" onClick={() => sendTest.mutate(r.id as number)} disabled={sendTest.isPending}><Send size={13} /> Send test</Button>
                  {r.status === "active" && <Button size="sm" variant="quiet" onClick={() => act.mutate({ id: r.id as number, action: "pause" })}><Pause size={13} /> Pause</Button>}
                  {r.status === "paused" && <Button size="sm" variant="quiet" onClick={() => act.mutate({ id: r.id as number, action: "resume" })}><Play size={13} /> Resume</Button>}
                </div>) },
            ]} />
          )}
          {test && (
            <div className="mt-3">
              <Callout tone={test.delivered.length ? "info" : "warn"} title={`Test message for alert #${test.id}`}>
                <span className="block font-serif text-ink">{test.message}</span>
                <span className="mt-1 block">Delivered: {test.delivered.join(", ") || "none (see the alert log)"}</span>
              </Callout>
            </div>
          )}
          <ErrorLine error={act.error ?? sendTest.error} />
        </Panel>

        {s && <Channels s={s} />}

        <section className="rounded-[var(--radius-panel)] border border-line bg-panel">
          <button type="button" onClick={() => setLogOpen((o) => !o)} aria-expanded={logOpen} className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-[14px] font-semibold">
            {logOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />} Alert log
            <span className="ml-auto text-[13px] font-normal text-muted">{s?.log.length ?? 0} entries</span>
          </button>
          {logOpen && (
            <div className="border-t border-line p-4">
              <DataTable rows={(s?.log ?? []) as unknown as Record<string, unknown>[]} empty="Every firing, test, hold and expiry appears here." columns={[
                { key: "at", header: "When", render: (r) => String(r.at ?? "").replace("T", " ").slice(0, 16) },
                { key: "event", header: "Event", render: (r) => cap(String(r.event ?? "")) },
                { key: "name", header: "Alert" },
                { key: "bar", header: "Bar", render: (r) => String(r.bar ?? "—") },
                { key: "delivered", header: "Delivered", render: (r) => ((r.delivered as string[] | undefined) ?? []).join(", ") || "—" },
                { key: "message", header: "Message", render: (r) => <span className="text-[13px]">{r.message as string}</span> },
              ]} />
            </div>
          )}
        </section>
      </div>
    </FactsProvider>
  );
}
