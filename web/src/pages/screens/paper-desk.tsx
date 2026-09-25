import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { OctagonX, Play, FastForward } from "lucide-react";
import { get, post, type Market } from "@/lib/api";
import { money, num } from "@/lib/format";
import { cn } from "@/lib/cn";
import { Button, Panel, Field, inputCls } from "@/components/ui";
import { FactTile, FactsProvider } from "@/components/facts";
import { CandleChart } from "@/components/charts";
import { useMarket } from "@/components/shell";

interface Pos { id: number; symbol: string; side: string; qty: number; entry: number; last: number; open_pnl: number; unplanned: boolean; stop: number | null }
interface DeskState {
  market: Market; symbol: string; mode: string; now: string; cash: number; equity: number; day_pnl: number; killed: boolean;
  guardrails: Record<string, unknown>; positions: Pos[]; trades: Record<string, unknown>[];
  tape: { time: string; open: number; high: number; low: number; close: number }[];
  last_bar?: { close: number };
}

export default function PaperDesk() {
  const [market] = useMarket();
  const qc = useQueryClient();
  const key = ["paper", market];
  const { data: s } = useQuery({ queryKey: key, queryFn: () => get<DeskState>(`/api/paper/state?market=${market}`) });
  const set = (d: DeskState) => qc.setQueryData(key, d);
  const step = useMutation({ mutationFn: (n: number) => post<DeskState>(`/api/paper/step?market=${market}&n=${n}`), onSuccess: set });
  const kill = useMutation({ mutationFn: () => post<DeskState>(`/api/paper/kill?market=${market}`), onSuccess: set });
  const lot = market === "IN" ? 65 : 1;
  const [ticket, setTicket] = useState({ side: "buy", qty: lot, kind: "market", stop: "" });
  const place = useMutation({
    mutationFn: () => post<DeskState>("/api/paper/order", {
      market, symbol: s?.symbol, side: ticket.side, qty: Number(ticket.qty), kind: ticket.kind,
      stop: ticket.stop ? Number(ticket.stop) : null,
    }),
    onSuccess: (d) => { set(d); step.mutate(1); },
  });
  const m = market;
  const last = s?.tape.at(-1)?.close;

  return (
    <FactsProvider>
      <div className="flex flex-col gap-5">
        <div className="flex flex-wrap items-center gap-3 rounded-[var(--radius-panel)] border border-line bg-panel px-4 py-2.5">
          <span className="rounded-[4px] bg-indigo-soft px-2 py-0.5 text-[13px] font-semibold text-indigo">Replay</span>
          <span className="num text-[14px]">{s?.now.replace("T", " ") ?? "…"}</span>
          <span className="text-[13px] text-muted">{s?.symbol} on the last synthetic session</span>
          <div className="ml-auto flex gap-2">
            <Button size="sm" onClick={() => step.mutate(1)} disabled={step.isPending}><Play size={14} /> Next minute</Button>
            <Button size="sm" onClick={() => step.mutate(5)} disabled={step.isPending}><FastForward size={14} /> 5×</Button>
            <Button size="sm" onClick={() => step.mutate(20)} disabled={step.isPending}><FastForward size={14} /> 20×</Button>
            <Button size="sm" variant="danger" onClick={() => kill.mutate()} disabled={s?.killed}><OctagonX size={14} /> Kill switch</Button>
          </div>
        </div>

        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
          <div className="flex min-w-0 flex-col gap-5">
            <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
              <FactTile label="Equity" value={money(s?.equity, m)} big />
              <FactTile label="Day P&L" value={money(s?.day_pnl, m)} tone={(s?.day_pnl ?? 0) >= 0 ? "bull" : "bear"} />
              <FactTile label="Cash" value={money(s?.cash, m)} />
              <FactTile label="Last" value={last ? num(last, m) : "—"} />
            </div>
            <Panel title={`${s?.symbol ?? ""} one-minute tape`}>
              {s && <CandleChart bars={s.tape} height={300} />}
            </Panel>
            <Panel title="Positions">
              {s?.positions.length ? (
                <table className="w-full text-[14px]">
                  <thead className="text-left text-[12px] text-muted">
                    <tr><th className="pb-2 font-normal">Symbol</th><th className="pb-2 font-normal">Side</th><th className="pb-2 text-right font-normal">Qty</th>
                      <th className="pb-2 text-right font-normal">Entry</th><th className="pb-2 text-right font-normal">Last</th><th className="pb-2 text-right font-normal">Open P&L</th></tr>
                  </thead>
                  <tbody>
                    {s.positions.map((p) => (
                      <tr key={p.id} className="border-t border-line">
                        <td className="py-2">{p.symbol}{p.unplanned && <span className="ml-2 rounded-[4px] bg-bear-soft px-1.5 text-[11px] text-bear">No plan</span>}</td>
                        <td className="py-2 capitalize">{p.side}</td>
                        <td className="num py-2 text-right">{p.qty}</td>
                        <td className="num py-2 text-right">{num(p.entry, m)}</td>
                        <td className="num py-2 text-right">{num(p.last, m)}</td>
                        <td className={cn("num py-2 text-right font-medium", p.open_pnl >= 0 ? "text-bull" : "text-bear")}>{money(p.open_pnl, m)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : <p className="text-muted">No open paper positions. Place a paper order from the ticket.</p>}
            </Panel>
          </div>

          <Panel title="Paper order ticket" className="self-start">
            <div className="-mx-4 -mt-4 mb-4 border-b border-line bg-indigo-soft px-4 py-2 text-[13px] text-indigo">
              Simulated fills only. Nothing is sent to a broker.
            </div>
            <div className="flex flex-col gap-3">
              <div className="grid grid-cols-2 overflow-hidden rounded-[6px] border border-line-strong">
                {(["buy", "sell"] as const).map((sd) => (
                  <button key={sd} onClick={() => setTicket({ ...ticket, side: sd })}
                    className={cn("h-9 text-[14px] font-medium capitalize",
                      ticket.side === sd ? (sd === "buy" ? "bg-bull text-white" : "bg-bear text-white") : "text-muted")}>{sd}</button>
                ))}
              </div>
              <Field label={market === "IN" ? `Quantity (units; 1 lot = ${lot})` : "Quantity (shares)"}>
                <input className={inputCls} type="number" min={1} value={ticket.qty} onChange={(e) => setTicket({ ...ticket, qty: Number(e.target.value) })} />
              </Field>
              <Field label="Order type">
                <select className={inputCls} value={ticket.kind} onChange={(e) => setTicket({ ...ticket, kind: e.target.value })}>
                  <option value="market">Market (fills at the next minute's open)</option>
                  <option value="limit">Limit</option>
                </select>
              </Field>
              <Field label="Stop (optional)" hint="Every paper order without a plan is flagged in the journal.">
                <input className={inputCls} type="number" value={ticket.stop} onChange={(e) => setTicket({ ...ticket, stop: e.target.value })} />
              </Field>
              <Button variant="primary" onClick={() => place.mutate()} disabled={!s || s.killed || place.isPending}>Place paper order</Button>
              {place.error && <p className="text-[13px] text-bear">{(place.error as Error).message}</p>}
              {s?.killed && <p className="text-[13px] text-bear">Kill switch is on for this session. New paper orders are blocked.</p>}
            </div>
          </Panel>
        </div>
      </div>
    </FactsProvider>
  );
}
