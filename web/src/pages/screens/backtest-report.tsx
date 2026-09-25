import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, AlertTriangle, XCircle } from "lucide-react";
import { post } from "@/lib/api";
import { money, pct } from "@/lib/format";
import { cn } from "@/lib/cn";
import { Button, Panel } from "@/components/ui";
import { FactTile, FactsProvider, ExplainPanel } from "@/components/facts";
import { EquityChart } from "@/components/charts";
import { useMarket } from "@/components/shell";

interface Check { name: string; status: "pass" | "fail" | "warn" | string; measured: string; why: string }
interface Run {
  read_back: string; stats: Record<string, number>; dates: string[]; equity: number[]; benchmark: number[];
  drawdown: number[]; card: { grade: string; reason: string; trials: number; deflated_sharpe: number; checks: Check[]; warnings: string[] };
  facts: string[]; trials: number;
}

const EXAMPLE = "Buy at the next open on the first close above the 50-day average; sell at the next open when the close is below the 20-day average";

const GRADE_STYLE: Record<string, string> = {
  Robust: "text-bull", Fragile: "text-saffron", "Likely overfit": "text-bear",
};

export default function BacktestReport() {
  const [market] = useMarket();
  const [idea, setIdea] = useState(EXAMPLE);
  const run = useMutation({
    mutationFn: () => post<Run>("/api/backtest/run", { idea, market, symbol: market === "IN" ? "NIFTY" : "SPY" }),
  });
  const r = run.data;
  const s = r?.stats;
  return (
    <FactsProvider>
      <div className="flex flex-col gap-5">
        <Panel title="Your rule, in plain English">
          <div className="flex flex-col gap-3 md:flex-row">
            <textarea value={idea} onChange={(e) => setIdea(e.target.value)} rows={2}
              className="min-h-[64px] flex-1 resize-y rounded-[6px] border border-line-strong bg-panel p-2.5 font-serif text-[15px] outline-none focus:border-indigo" />
            <Button variant="primary" className="self-start" onClick={() => run.mutate()} disabled={run.isPending}>
              {run.isPending ? "Running…" : "Backtest"}
            </Button>
          </div>
          {r && <p className="mt-3 text-[14px]"><span className="text-muted">Read back: </span>{r.read_back}</p>}
          {run.error && <p className="mt-3 text-bear">{(run.error as Error).message}</p>}
        </Panel>

        {r && s && (
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
            <div className="flex min-w-0 flex-col gap-5">
              <div className="grid grid-cols-2 gap-2.5 md:grid-cols-5">
                <FactTile label="Total return" value={pct(s.total_return, 1)} tone={s.total_return >= 0 ? "bull" : "bear"} big />
                <FactTile label="Buy and hold" value={pct(s.bh_return, 1)} />
                <FactTile label="Max drawdown" value={pct(s.max_drawdown, 1)} tone="bear" />
                <FactTile label="Round trips" value={s.round_trips} sub={`${s.winners} winners`} />
                <FactTile label="Charges" value={money(s.charges, market)} sub="included" />
              </div>
              <Panel title="Equity and drawdown" action={<span className="text-[12px] font-semibold text-muted">Hypothetical</span>}>
                <EquityChart dates={r.dates} equity={r.equity} benchmark={r.benchmark} drawdown={r.drawdown} />
              </Panel>
            </div>

            <div className="flex flex-col gap-4">
              <section className="rounded-[var(--radius-panel)] border border-line bg-panel p-4">
                <div className="text-[13px] text-muted">Report Card</div>
                <div className={cn("mt-1 text-[34px] font-semibold leading-none", GRADE_STYLE[r.card.grade])}>{r.card.grade}</div>
                <p className="mt-2 text-[14px]">{r.card.reason}</p>
                <div className="num mt-2 text-[13px] text-muted">Trials: {r.card.trials}, deflated Sharpe {r.card.deflated_sharpe.toFixed(2)}</div>
                <ul className="mt-4 flex flex-col gap-2.5">
                  {r.card.checks.map((c) => (
                    <li key={c.name} className="flex gap-2.5">
                      {c.status === "pass" ? <CheckCircle2 size={17} className="mt-0.5 shrink-0 text-bull" />
                        : c.status === "fail" ? <XCircle size={17} className="mt-0.5 shrink-0 text-bear" />
                          : <AlertTriangle size={17} className="mt-0.5 shrink-0 text-saffron" />}
                      <div>
                        <div className="font-medium">{c.name}</div>
                        <div className="text-[13px] text-muted">{c.measured}</div>
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
              <ExplainPanel facts={r.facts} section="Strategy" />
            </div>
          </div>
        )}
        {!r && !run.isPending && (
          <p className="text-muted">Write a rule the way you would say it, then press Backtest. Costs are always included, and every change you test counts as a trial.</p>
        )}
      </div>
    </FactsProvider>
  );
}
