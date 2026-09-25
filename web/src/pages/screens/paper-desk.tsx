import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { OctagonX, Play, SkipForward, RotateCw, Radio, Send } from "lucide-react";
import { get, post } from "@/lib/api";
import { money, num } from "@/lib/format";
import { cn } from "@/lib/cn";
import { Button, Panel, Field, inputCls } from "@/components/ui";
import { Badge, Callout, DataTable, Dialog, Hypothetical, Segmented, Select, useToast } from "@/components/kit";
import { FactTile, FactsProvider } from "@/components/facts";
import { CandleChart } from "@/components/charts";
import { useMarket } from "@/components/shell";
import { ErrorLine, NumField } from "@/components/planning/common";
import { CompareWithBacktest, PaperTicket, PendingOrders, type DeskState, type Fill, type Position } from "@/components/planning/paper";

const SPEEDS = [{ value: "1", label: "1×" }, { value: "5", label: "5×" }, { value: "20", label: "20×" }];

/* ------------------------------------------------------------ one open position */
function PositionRow({ p, s, onState }: { p: Position; s: DeskState; onState: (d: DeskState) => void }) {
  const m = s.market;
  const toast = useToast();
  const [stop, setStop] = useState<number | null>(p.stop ?? p.entry);
  const [reason, setReason] = useState("");
  const [rate, setRate] = useState<number | null>(p.funding_rate != null ? Math.round(p.funding_rate * 1e6) / 1e4 : null);
  const move = useMutation({
    mutationFn: () => post<DeskState>(`/api/paper/positions/${p.id}/move-stop`, { market: m, stop, reason }),
    onSuccess: (d) => { onState(d); setReason(""); toast(`Moved stop on #${p.id}; the reason is in the journal`); },
  });
  const close = useMutation({ mutationFn: () => post<DeskState>(`/api/paper/positions/${p.id}/close?market=${m}`), onSuccess: (d) => { onState(d); toast(`Closing #${p.id} at the next bar's open`); } });
  const fund = useMutation({ mutationFn: () => post<DeskState>(`/api/paper/positions/${p.id}/funding`, { market: m, rate_pct: rate ?? 0 }), onSuccess: (d) => { onState(d); toast("Set funding per 8 h"); } });
  const cm = useMutation({ mutationFn: () => post<DeskState>(`/api/paper/positions/${p.id}/crypto-monitor?market=${m}`), onSuccess: (d) => { onState(d); toast("Sent to Crypto Monitor. Alerts › From Crypto Monitor can use it"); } });
  const perp = p.symbol.endsWith("-PERP");
  return (
    <div className="border-b border-line py-3 last:border-0">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className="num text-muted">#{p.id}</span>
        <span className="font-medium"><span className="capitalize">{p.side}</span> {p.qty} {p.symbol}</span>
        <span className="num text-[13px] text-muted">entry {num(p.entry, m)}, last {num(p.last, m)}, stop {p.stop != null ? num(p.stop, m) : "—"}</span>
        {p.unplanned && <Badge tone="warn">No plan</Badge>}
        {p.rule_breaks.includes("stop moved away") && <Badge tone="warn">Stop moved away</Badge>}
        {p.closing && <Badge tone="indigo">Closing at next bar</Badge>}
        {perp && <span className="num text-[13px] text-muted">funding {money(p.funding, m, 2)}</span>}
        <span className={cn("num ml-auto font-semibold", p.open_pnl >= 0 ? "text-bull" : "text-bear")}>{money(p.open_pnl, m, 2)}</span>
      </div>
      <div className="mt-2 flex flex-wrap items-end gap-2">
        <div className="w-32"><NumField label="New stop" value={stop} onChange={setStop} /></div>
        <label className="flex min-w-[200px] flex-1 flex-col gap-1">
          <span className="text-[12px] text-muted">Reason (required)</span>
          <input className={cn(inputCls, "font-sans")} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why the stop moves" />
        </label>
        <Button size="sm" className="h-9" onClick={() => move.mutate()} disabled={move.isPending || stop === null}>Move stop</Button>
        <Button size="sm" className="h-9" onClick={() => close.mutate()} disabled={p.closing || close.isPending}>Close at next bar</Button>
      </div>
      {perp && (
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <div className="w-44"><NumField label="Funding per 8 h (%)" value={rate} step={0.001} onChange={setRate} /></div>
          <Button size="sm" className="h-9" onClick={() => fund.mutate()} disabled={fund.isPending}>Set funding</Button>
          <Button size="sm" className="h-9" onClick={() => cm.mutate()} disabled={cm.isPending}><Send size={13} /> Send to Crypto Monitor</Button>
          <span className="pb-2 text-[12px] text-muted">Funding posts to the paper account at each funding time on daily bars.</span>
        </div>
      )}
      <ErrorLine error={move.error ?? close.error ?? fund.error ?? cm.error} />
    </div>
  );
}

export default function PaperDesk() {
  const [market] = useMarket();
  const m = market;
  const qc = useQueryClient();
  const toast = useToast();
  const key = ["paper", market];
  const { data: s, error } = useQuery({ queryKey: key, queryFn: () => get<DeskState>(`/api/paper/state?market=${market}`) });
  const set = (d: DeskState) => qc.setQueryData(key, d);

  // Replay controls (the classic page's Symbol / Session / Bars / Speed / Replay row).
  const [rp, setRp] = useState({ symbol: "", day: "", interval: "5m" });
  useEffect(() => { if (s) setRp({ symbol: s.replay.symbol, day: s.replay.day, interval: s.replay.interval }); }, [s?.replay.symbol, s?.replay.day, s?.replay.interval, market]); // eslint-disable-line react-hooks/exhaustive-deps
  const session = useMutation({ mutationFn: (v: string) => post<DeskState>("/api/paper/session", { market, session: v }), onSuccess: set });
  const load = useMutation({ mutationFn: () => post<DeskState>("/api/paper/replay", { market, ...rp, speed: s?.replay.speed ?? 1 }), onSuccess: (d) => { set(d); toast(`Replay loaded: ${d.replay.symbol}, ${d.replay.day}`); } });
  const speed = useMutation({ mutationFn: (n: number) => post<DeskState>(`/api/paper/speed?market=${market}&speed=${n}`), onSuccess: set });
  const step = useMutation({ mutationFn: (toEnd: boolean) => post<DeskState>(`/api/paper/step?market=${market}${toEnd ? "&to_end=true" : ""}`), onSuccess: set });
  const [killOpen, setKillOpen] = useState(false);
  const kill = useMutation({
    mutationFn: () => post<DeskState & { kill: { cancelled: number; closing: number } }>(`/api/paper/kill?market=${market}`),
    onSuccess: (d) => { set(d); setKillOpen(false); toast(`Kill switch: ${d.kill.cancelled} paper orders cancelled, ${d.kill.closing} positions close at the next bar's open`); },
  });
  // Journal › Trades › Replay hands a session over: open it here in Replay at 5×, tagged REPLAY.
  const { data: ho } = useQuery({
    queryKey: ["journal-handoff", market],
    queryFn: () => get<{ handoff: { day: string; market: string; speed: number; fills: Fill[] } | null }>(`/api/journal/replay/handoff?market=${market}`).catch(() => ({ handoff: null })),
  });
  const openHandoff = useMutation({
    mutationFn: (h: { day: string; speed: number; fills: Fill[] }) => post<DeskState>("/api/paper/replay", {
      market, symbol: h.fills[0]?.symbol ?? s?.symbols[0] ?? "", day: h.day, interval: "5m", speed: h.speed || 5,
      fills: h.fills, source: "Journal › Trades",
    }),
    onSuccess: (d) => { set(d); toast(`Opened the ${d.replay.day} session from Journal › Trades in Replay at ${d.replay.speed}×`); },
  });
  const h = ho?.handoff;
  useEffect(() => {
    if (!s || !h || openHandoff.isPending || openHandoff.isError) return;
    const same = s.handoff && s.handoff.day === h.day && JSON.stringify(s.handoff.fills) === JSON.stringify(h.fills);
    if (!same) openHandoff.mutate(h);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [h, s?.handoff, market]);

  const cancel = useMutation({ mutationFn: (id: number) => post<DeskState>(`/api/paper/orders/${id}/cancel?market=${market}`), onSuccess: (d) => { set(d); toast("Cancelled the paper order"); } });

  if (error) return <Callout tone="danger" title="The Paper Desk could not load">{(error as Error).message}</Callout>;
  const g = s?.guardrails;
  const last = s?.tape.at(-1)?.close;
  const isLive = s?.session === "LIVE";
  const sp = s?.replay.speed ?? 1;

  return (
    <FactsProvider>
      <div className="flex flex-col gap-5">
        {/* session strip */}
        <div className="flex flex-col gap-3 rounded-[var(--radius-panel)] border border-line bg-panel px-4 py-3">
          <div className="flex flex-wrap items-center gap-3">
            <Segmented label="Session" value={isLive ? "LIVE" : "Replay"} options={[{ value: "LIVE", label: "Live" }, { value: "Replay", label: "Replay" }]}
              onChange={(v) => session.mutate(v)} />
            {isLive ? <Badge tone="indigo"><Radio size={12} className="mr-1" /> Live, {s?.live.source}</Badge>
              : <Badge tone="indigo">Replay</Badge>}
            <span className="text-[13px] text-muted">
              {isLive ? "Round trips are tagged PAPER in the journal." : s?.live.ok ? "Replayed trades are tagged REPLAY in the journal, never PAPER."
                : `Live unavailable: ${s?.live.source ?? "…"}. Replay feeds a recorded or synthetic session bar by bar.`}
            </span>
            <span className="num ml-auto text-[14px]">{s?.now ? s.now.replace("T", " ") : "no bar fed yet"}</span>
          </div>
          <ErrorLine error={session.error} />
          {!isLive && s && (
            <div className="flex flex-wrap items-end gap-3 border-t border-line pt-3">
              <Field label="Symbol"><Select className="w-44 font-sans" value={rp.symbol} onChange={(e) => setRp({ ...rp, symbol: e.target.value })}>{s.symbols.map((x) => <option key={x}>{x}</option>)}</Select></Field>
              <Field label="Session"><input type="date" className={cn(inputCls, "w-40")} value={rp.day} onChange={(e) => setRp({ ...rp, day: e.target.value })} /></Field>
              <Field label="Bars"><Select className="w-24 font-sans" value={rp.interval} onChange={(e) => setRp({ ...rp, interval: e.target.value })}>{["5m", "1m", "15m", "1d"].map((x) => <option key={x}>{x}</option>)}</Select></Field>
              <Field label="Speed"><Segmented label="Speed" value={String(sp)} options={SPEEDS} onChange={(v) => speed.mutate(Number(v))} /></Field>
              <Button variant="primary" onClick={() => load.mutate()} disabled={load.isPending}><RotateCw size={14} /> Replay</Button>
              <div className="ml-auto flex items-center gap-2">
                <span className="num text-[13px] text-muted">{s.replay.symbol}: bar {s.replay.cursor} of {s.replay.total}</span>
                <Button onClick={() => step.mutate(false)} disabled={step.isPending || s.replay.done}><Play size={14} /> Next {sp} bar{sp > 1 ? "s" : ""}</Button>
                <Button onClick={() => step.mutate(true)} disabled={step.isPending || s.replay.done}><SkipForward size={14} /> To session end</Button>
              </div>
            </div>
          )}
          <ErrorLine error={load.error ?? step.error ?? speed.error ?? openHandoff.error} />
        </div>

        {/* guardrail strip */}
        <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3 xl:grid-cols-6">
          <FactTile label="Trades left" value={g?.trades_left ?? "—"} sub={s?.limits.max_trades_per_day ? `of ${s.limits.max_trades_per_day} a day` : "No daily maximum synced"} />
          <FactTile label="Cooldown" value={`${g?.cooldown_min ?? 0} min`} />
          <FactTile label="Day result" value={g?.day_r == null ? "—" : `${g.day_r >= 0 ? "+" : "−"}${Math.abs(g.day_r).toFixed(2)}R`}
            sub={g ? money(g.day_pnl, m, 2) : undefined} tone={g?.day_r == null ? undefined : g.day_r >= 0 ? "bull" : "bear"} />
          <FactTile label="Daily loss limit" value={g?.daily_loss_limit ? money(g.daily_loss_limit, m) : "Not set"} sub="From Rule Card › Sync limits. No override." />
          <FactTile label="Next lockout" value={g?.next_lockout ?? "—"} />
          <div className="flex flex-col justify-center gap-1.5 rounded-[var(--radius-tile)] border border-bear/30 px-3 py-2.5">
            <Button variant="danger" onClick={() => setKillOpen(true)} disabled={!s || s.killed}><OctagonX size={15} /> Kill switch</Button>
            <span className="text-[12px] text-muted">{s?.killed ? "On for this session" : "Cancels, closes, blocks"}</span>
          </div>
        </div>
        {s?.blocked_now && (
          <Callout tone="danger" title={`Blocked: ${s.blocked_now}`}>New paper orders are blocked. Change rules on the Rule Card in the evening, where the change is dated.</Callout>
        )}

        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="flex min-w-0 flex-col gap-5">
            <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
              <FactTile label="Equity" value={money(s?.equity, m)} big sub={s ? `starting ${money(s.starting_balance, m)}` : undefined} />
              <FactTile label="Day P&L" value={money(s?.day_pnl, m)} tone={(s?.day_pnl ?? 0) >= 0 ? "bull" : "bear"} />
              <FactTile label="Realised" value={money(s?.realised, m)} tone={(s?.realised ?? 0) >= 0 ? "bull" : "bear"} />
              <FactTile label="Last" value={last ? num(last, m) : "—"} sub={s?.replay.symbol} />
            </div>
            <Panel title={`${s?.replay.symbol ?? ""} ${s?.replay.interval === "1d" ? "daily" : s?.replay.interval ?? ""} bars fed so far`} action={<Hypothetical />}>
              <div className="h-[300px]">
                {s && s.tape.length > 0 ? <CandleChart bars={s.tape} height={300} marks={((s.trades ?? []) as unknown as Record<string, unknown>[]).flatMap((t) => [
                    t.entry_time ? { at: String(t.entry_time), side: (t.side === "short" ? "sell" : "buy") as "buy" | "sell", text: "In" } : null,
                    t.exit_time ? { at: String(t.exit_time), side: (t.side === "short" ? "buy" : "sell") as "buy" | "sell", text: "Out" } : null,
                  ].filter((x): x is { at: string; side: "buy" | "sell"; text: string } => x !== null))} />
                  : <p className="pt-10 text-center text-muted">No bar fed yet. Click Next bar to start the replay.</p>}
              </div>
              <p className="mt-2 text-[12px] text-muted">Only bars already fed to the paper engine are shown; a paper order placed now fills on a later bar, never the current one.</p>
            </Panel>

            {s?.handoff && (
              <Panel title={`Your fills on ${s.handoff.day}`} action={<Badge tone="indigo">From {s.handoff.source}</Badge>}>
                <DataTable rows={s.handoff.fills as unknown as Record<string, unknown>[]} empty="No fills recorded for this session."
                  columns={[
                    { key: "time", header: "Time", render: (f) => String(f.time).replace("T", " ").slice(0, 16) },
                    { key: "kind", header: "Fill", render: (f) => <span className="capitalize">{f.kind as string}</span> },
                    { key: "symbol", header: "Contract" },
                    { key: "side", header: "Side", render: (f) => <span className="capitalize">{f.side as string}</span> },
                    { key: "price", header: "Price", align: "right", render: (f) => num(f.price as number, m) },
                  ]} />
                <p className="mt-2 text-[12px] text-muted">Step the replay to each fill time and compare the bar with your price: that gap is your slippage.</p>
              </Panel>
            )}

            {s && <PendingOrders s={s} onState={set} />}

            {s && s.working.length > 0 && (
              <Panel title="Working paper orders">
                <DataTable rows={s.working as unknown as Record<string, unknown>[]} columns={[
                  { key: "id", header: "#", align: "right", width: "44px" },
                  { key: "symbol", header: "Contract" },
                  { key: "side", header: "Side", render: (o) => <span className="capitalize">{o.side as string}</span> },
                  { key: "qty", header: "Qty", align: "right" },
                  { key: "kind", header: "Type", render: (o) => (o.purpose === "close" ? "Close" : o.kind === "stop" ? "Stop-entry" : String(o.kind).replace(/^./, (c) => c.toUpperCase())) },
                  { key: "price", header: "Price", align: "right", render: (o) => (o.price != null ? num(o.price as number, m) : "—") },
                  { key: "stop", header: "Stop", align: "right", render: (o) => (o.stop != null ? num(o.stop as number, m) : "—") },
                  { key: "status", header: "Status", render: (o) => <span className="flex items-center gap-1.5"><Badge tone="indigo">Working</Badge>{o.unplanned ? <Badge tone="warn">No plan</Badge> : null}</span> },
                  { key: "filled_qty", header: "Filled", align: "right" },
                  { key: "x", header: "", render: (o) => (o.purpose === "open" ? <Button size="sm" variant="quiet" onClick={() => cancel.mutate(o.id as number)}>Cancel #{o.id as number}</Button> : null) },
                ]} />
              </Panel>
            )}

            <Panel title="Positions">
              {s?.positions.length ? s.positions.map((p) => <PositionRow key={`${p.id}-${p.stop}-${p.closing}`} p={p} s={s} onState={set} />)
                : <p className="text-muted">No open paper positions. Place a paper order from the ticket, then feed the next bar.</p>}
            </Panel>

            <Panel title="Closed this session" action={<Hypothetical />}>
              <DataTable rows={(s?.trades ?? []) as unknown as Record<string, unknown>[]} empty="No round trips yet. Each closed paper trade lands here and in Journal › Trades, with every cost itemised."
                columns={[
                  { key: "symbol", header: "Contract" },
                  { key: "side", header: "Side", render: (t) => <span className="capitalize">{t.side as string}</span> },
                  { key: "qty", header: "Qty", align: "right" },
                  { key: "entry", header: "Entry", align: "right", render: (t) => num(t.entry as number, m) },
                  { key: "exit", header: "Exit", align: "right", render: (t) => num(t.exit as number, m) },
                  { key: "exit_reason", header: "Exit reason", render: (t) => String(t.exit_reason).replace(/^./, (c) => c.toUpperCase()) },
                  { key: "slippage", header: "Slippage", align: "right", render: (t) => money(t.slippage as number, m, 2) },
                  { key: "costs_total", header: "Charges", align: "right", render: (t) => money(t.costs_total as number, m, 2) },
                  { key: "net", header: "Net", align: "right", render: (t) => <span className={(t.net as number) >= 0 ? "text-bull" : "text-bear"}>{money(t.net as number, m, 2)}</span> },
                  { key: "r", header: "R", align: "right", render: (t) => (t.r == null ? "—" : (t.r as number).toFixed(2)) },
                  { key: "mode", header: "Tag", render: (t) => <Badge>{String(t.mode) === "PAPER" ? "Paper" : "Replay"}</Badge> },
                ]} />
            </Panel>

            {s && s.blocked.length > 0 && (
              <Panel title={`Blocked paper orders (${s.blocked.length})`}>
                <DataTable rows={s.blocked} columns={[
                  { key: "at", header: "At", render: (b) => String(b.at ?? "").replace("T", " ") },
                  { key: "symbol", header: "Contract" },
                  { key: "side", header: "Side", render: (b) => <span className="capitalize">{b.side as string}</span> },
                  { key: "qty", header: "Qty", align: "right" },
                  { key: "reason", header: "Reason" },
                ]} />
                <p className="mt-2 text-[13px] text-muted">Each block is logged in Journal › Trades, tagged BLOCKED.</p>
              </Panel>
            )}
          </div>

          {s ? <PaperTicket key={`${market}-${s.ticket?.id ?? "none"}`} s={s} onState={set} /> : <div />}
        </div>

        {s && <CompareWithBacktest key={market} s={s} onDrift={() => qc.invalidateQueries({ queryKey: key })} />}
        <p className="text-[12px] text-muted">Paper only. PlugAI-Trade never places real orders; nothing here can reach a broker.</p>
      </div>

      <Dialog open={killOpen} onOpenChange={setKillOpen} title="Press the kill switch?"
        footer={<><Button onClick={() => setKillOpen(false)}>Keep trading on paper</Button><Button variant="danger" onClick={() => kill.mutate()} disabled={kill.isPending}><OctagonX size={15} /> Press kill switch</Button></>}>
        <ul className="list-disc pl-5 text-[14px]">
          <li>Every working and pending paper order is cancelled.</li>
          <li>Every paper position closes at the next bar's open.</li>
          <li>New paper orders are blocked for the rest of this session. There is no override.</li>
        </ul>
        <ErrorLine error={kill.error} />
      </Dialog>
    </FactsProvider>
  );
}
