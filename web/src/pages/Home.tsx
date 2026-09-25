import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { get, type Market } from "@/lib/api";
import { money, pct } from "@/lib/format";
import { cn } from "@/lib/cn";
import { Panel, MarketChip } from "@/components/ui";
import { Sparkline } from "@/components/charts";

interface Session { time: string; tz: string; open: string; close: string; state: string }
interface Row { symbol: string; last: number; change: number; spark: number[]; source: string }

/** The hero: two markets, one day. Where each session is right now. */
function SessionBar({ m, s }: { m: Market; s?: Session }) {
  const toMin = (t?: string) => (t ? Number(t.slice(0, 2)) * 60 + Number(t.slice(3, 5)) : 0);
  const open = toMin(s?.open), close = toMin(s?.close), now = toMin(s?.time);
  const dayStart = open - 120, dayEnd = close + 180;
  const x = (v: number) => `${Math.min(100, Math.max(0, ((v - dayStart) / (dayEnd - dayStart)) * 100))}%`;
  return (
    <div className="flex items-center gap-5">
      <div className="w-40">
        <div className="flex items-center gap-2"><MarketChip m={m} /><span className="text-[13px] text-muted">{m === "IN" ? "NSE and BSE" : "NYSE and Nasdaq"}</span></div>
        <div className="num mt-1 text-[34px] font-semibold leading-none tracking-tight">{s?.time ?? "--:--"}</div>
        <div className={cn("mt-1 text-[13px]", s?.state === "open" ? "text-bull" : "text-muted")}>
          {s?.state === "open" ? "Session open" : s?.state === "pre-open" ? `Opens at ${s.open}` : `Closed, opens at ${s?.open ?? ""}`}
        </div>
      </div>
      <div className="relative h-9 flex-1">
        <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-line-strong" />
        <div className={cn("absolute top-1/2 h-2.5 -translate-y-1/2 rounded-full", m === "IN" ? "bg-saffron/70" : "bg-navy/70")}
          style={{ left: x(open), width: `calc(${x(close)} - ${x(open)})` }} />
        <div className="absolute top-0 h-full w-0.5 bg-ink" style={{ left: x(now) }} aria-label="now" />
        <div className="num absolute -bottom-4 text-[11px] text-muted" style={{ left: x(open) }}>{s?.open}</div>
        <div className="num absolute -bottom-4 -translate-x-full text-[11px] text-muted" style={{ left: x(close) }}>{s?.close}</div>
      </div>
    </div>
  );
}

function Watchlist({ m }: { m: Market }) {
  const { data = [] } = useQuery({ queryKey: ["watch", m], queryFn: () => get<Row[]>(`/api/watchlist?market=${m}`) });
  return (
    <table className="w-full text-[14px]">
      <tbody>
        {data.map((r) => (
          <tr key={r.symbol} className="border-b border-line last:border-0">
            <td className="py-2.5 font-medium">{r.symbol}</td>
            <td className="py-2.5"><Sparkline values={r.spark} /></td>
            <td className="num py-2.5 text-right">{money(r.last, m, 2)}</td>
            <td className={cn("num w-20 py-2.5 text-right", r.change >= 0 ? "text-bull" : "text-bear")}>{pct(r.change)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const NEXT = [
  { to: "/briefing", title: "Generate this morning's briefing", body: "Watchlist moves, events and questions, every line with its source." },
  { to: "/options", title: "Price an option before you buy it", body: "Breakeven, maximum loss, the move you need and the move the market expects." },
  { to: "/backtest-report", title: "Test a rule you already trade", body: "Plain English in, a graded Report Card out, costs included." },
  { to: "/paper-desk", title: "Practise it on paper", body: "Replay a session at 5× with the same fills and costs as the backtest." },
];

export default function Home() {
  const { data: clock } = useQuery({ queryKey: ["clock"], queryFn: () => get<Record<Market, Session>>("/api/clock"), refetchInterval: 30_000 });
  return (
    <div className="mx-auto flex max-w-[1180px] flex-col gap-5">
      <section className="rounded-[var(--radius-panel)] border border-line bg-panel px-6 pb-8 pt-5">
        <h2 className="mb-5 text-[15px] font-semibold">Your two markets today</h2>
        <div className="flex flex-col gap-9">
          <SessionBar m="IN" s={clock?.IN} />
          <SessionBar m="US" s={clock?.US} />
        </div>
      </section>
      <div className="grid gap-5 lg:grid-cols-[1fr_1fr_1.1fr]">
        <Panel title="India watchlist"><Watchlist m="IN" /></Panel>
        <Panel title="US watchlist"><Watchlist m="US" /></Panel>
        <Panel title="Pick up where you left off">
          <ul className="flex flex-col">
            {NEXT.map((n) => (
              <li key={n.to} className="border-b border-line last:border-0">
                <Link to={n.to} className="group block py-2.5">
                  <div className="font-medium group-hover:text-indigo">{n.title}</div>
                  <div className="text-[13px] text-muted">{n.body}</div>
                </Link>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
      <p className="text-[12px] text-muted">Prices shown are synthetic sample data until you connect a free source in Settings › Data Sources.</p>
    </div>
  );
}
