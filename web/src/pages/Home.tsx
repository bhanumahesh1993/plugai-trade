import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { CheckCircle2, AlertTriangle } from "lucide-react";
import { get, post, type Market } from "@/lib/api";
import { money, pct } from "@/lib/format";
import { cn } from "@/lib/cn";
import { Panel, MarketChip } from "@/components/ui";
import { Sparkline } from "@/components/charts";
import { Button } from "@/components/ui";
import { useToast } from "@/components/kit";
import { FirstRunWizard, type WizardState } from "@/components/settings/wizard";
import type { ScreenLinkT } from "@/components/settings/common";

interface HomeExtras { pinned: ScreenLinkT[]; quick: ScreenLinkT[]; self_test: { passed: boolean; failed: string[] } | null }
const REDIRECT_KEY = "plugai-start-redirect-done";

/** `?lesson=N`, then PLUGAI_TRADE_LESSON / PLUGAI_TRADE_START_PAGE: redirect once per session. */
function useStartRedirect() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  useEffect(() => {
    const lesson = params.get("lesson");
    if (lesson) { navigate(`/lessons?lesson=${encodeURIComponent(lesson)}`, { replace: true }); return; }
    const page = params.get("page");
    if (page) { navigate(`/${page.replace(/^\/+/, "")}`, { replace: true }); return; }
    try {
      if (sessionStorage.getItem(REDIRECT_KEY)) return;
      sessionStorage.setItem(REDIRECT_KEY, "1");
    } catch { return; }
    get<{ target: string | null; lesson: number | null }>("/api/wizard/start").then((s) => {
      if (s.target === "lessons") navigate(`/lessons${s.lesson ? `?lesson=${s.lesson}` : ""}`, { replace: true });
      else if (s.target) navigate(`/${s.target}`, { replace: true });
    }).catch(() => { /* no redirect: stay on Home */ });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
}

function LinkList({ items }: { items: ScreenLinkT[] }) {
  return (
    <ul className="flex flex-wrap gap-1.5">
      {items.map((s) => (
        <li key={s.slug}>
          <Link to={`/${s.slug}`} className="inline-flex h-7 items-center rounded-[6px] border border-line bg-panel-2 px-2.5 text-[13px] hover:border-indigo hover:text-indigo">{s.title}</Link>
        </li>
      ))}
    </ul>
  );
}

function YourLab() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data } = useQuery({ queryKey: ["wizard-home"], queryFn: () => get<HomeExtras>("/api/wizard/home") });
  const again = useMutation({
    mutationFn: () => post("/api/wizard/done", { done: false }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["wizard"] }); toast("Opened the first-run wizard again at screen 1"); },
  });
  const t = data?.self_test;
  return (
    <Panel title="Your lab">
      <div className="grid gap-5 md:grid-cols-[1fr_1fr_auto]">
        <div>
          <h3 className="mb-2 text-[13px] font-medium text-muted">Pinned screens</h3>
          {data?.pinned.length ? <LinkList items={data.pinned} />
            : <p className="text-[13px] text-muted">None yet. <Link to="/workspace" className="font-medium text-indigo hover:underline">Settings › Workspace</Link> pins the screens for your style when you accept a template.</p>}
        </div>
        <div>
          <h3 className="mb-2 text-[13px] font-medium text-muted">Quick links</h3>
          {data && <LinkList items={data.quick} />}
        </div>
        <div className="flex flex-col items-start gap-2">
          <h3 className="text-[13px] font-medium text-muted">Self-test</h3>
          {t ? (
            <span className={cn("flex items-center gap-1.5 text-[14px]", t.passed ? "text-bull" : "text-ink")}>
              {t.passed ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} className="text-saffron" />}
              {t.passed ? "Passed" : `Failed: ${t.failed.join(", ")}`}
            </span>
          ) : <span className="text-[13px] text-muted">Not run yet</span>}
          <Button size="sm" onClick={() => again.mutate()} disabled={again.isPending}>Run the first-run wizard again</Button>
        </div>
      </div>
    </Panel>
  );
}

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
            <td className="py-2.5 pr-3 font-medium">{r.symbol}</td>
            <td className="py-2.5"><Sparkline values={r.spark} /></td>
            <td className="num py-2.5 pl-3 text-right">{money(r.last, m, 2)}</td>
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
  useStartRedirect();
  const { data: wiz } = useQuery({ queryKey: ["wizard"], queryFn: () => get<WizardState>("/api/wizard/state") });
  if (!wiz) return <div className="min-h-[60vh]" aria-busy="true" />;
  if (!wiz.done) return <FirstRunWizard w={wiz} />;
  return <Dashboard />;
}

function Dashboard() {
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
      <YourLab />
      <p className="text-[12px] text-muted">Prices shown are synthetic sample data until you connect a free source in Settings › Data Sources.</p>
    </div>
  );
}
