import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Moon, Sun, Database, Bot, Wallet } from "lucide-react";
import { get, post, type Market, type Status } from "@/lib/api";
import { cn } from "@/lib/cn";
import { MarketSwitch } from "./ui";
import { useTheme } from "./theme";
import { SCREENS, SECTIONS, isReady } from "@/screens";

export function useMarket(): [Market, (m: Market) => void] {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["status"], queryFn: () => get<Status>("/api/status") });
  const set = useMutation({
    mutationFn: (m: Market) => post("/api/market", { market: m }),
    onSuccess: () => qc.invalidateQueries(),
  });
  return [data?.market ?? "IN", (m) => set.mutate(m)];
}

function Sidebar() {
  return (
    <nav className="scroll-thin flex h-full w-[232px] shrink-0 flex-col overflow-y-auto border-r border-line bg-panel px-3 py-4" aria-label="Screens">
      <NavLink to="/" className="mb-5 flex items-center gap-2 px-2">
        <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden><rect width="32" height="32" rx="8" fill="var(--indigo)" /><path d="M8 21l5-6 4 3 7-9" stroke="var(--panel)" strokeWidth="2.6" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
        <span className="text-[16px] font-semibold tracking-tight">PlugAI-Trade</span>
      </NavLink>
      {SECTIONS.map((sec) => (
        <div key={sec} className="mb-3">
          <div className="px-2 pb-1 text-[12px] font-medium text-muted">{sec}</div>
          {SCREENS.filter((s) => s.section === sec).map((s) => (
            <NavLink
              key={s.slug}
              to={`/${s.slug}`}
              className={({ isActive }) => cn(
                "flex h-8 items-center justify-between rounded-[6px] px-2 text-[14px] text-ink/80 hover:bg-panel-2 hover:text-ink",
                isActive && "bg-indigo-soft text-indigo font-medium hover:bg-indigo-soft hover:text-indigo",
              )}
            >
              {s.title}
              {isReady(s.slug) && <span className="h-1.5 w-1.5 rounded-full bg-indigo" aria-label="new design" />}
            </NavLink>
          ))}
        </div>
      ))}
      <p className="mt-auto px-2 pt-4 text-[12px] leading-snug text-muted">Paper only. PlugAI-Trade never places real orders.</p>
    </nav>
  );
}

function TopBar() {
  const { pathname } = useLocation();
  const screen = SCREENS.find((s) => `/${s.slug}` === pathname);
  const { data } = useQuery({ queryKey: ["status"], queryFn: () => get<Status>("/api/status"), refetchInterval: 30_000 });
  const [market, setMarket] = useMarket();
  const { theme, setTheme } = useTheme();
  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b border-line bg-panel px-5">
      <div className="min-w-0 flex-1">
        <div className="text-[12px] text-muted">{screen?.section ?? "Today"}</div>
        <h1 className="truncate text-[17px] font-semibold leading-tight">{screen?.title ?? "Home"}</h1>
      </div>
      <MarketSwitch value={market} onChange={setMarket} />
      <div className="hidden items-center gap-4 text-[13px] text-muted lg:flex">
        <span className="flex items-center gap-1.5" title="Where the numbers on this screen come from">
          <Database size={14} /> {data?.data.source ?? "…"}, {data?.data.age}
        </span>
        <span className="flex items-center gap-1.5" title="Your AI model">
          <Bot size={14} />
          <span className={cn("h-2 w-2 rounded-full", data?.ai.reachable ? "bg-bull" : "bg-line-strong")} />
          {data?.ai.reachable ? data.ai.model : "No model connected"}
        </span>
        <span className="flex items-center gap-1.5 num" title="Cloud AI spend this month">
          <Wallet size={14} /> ${data?.ai.spend_this_month.toFixed(2) ?? "0.00"} of ${data?.ai.budget ?? 5}
        </span>
      </div>
      <button
        type="button"
        onClick={() => setTheme(theme === "book" ? "desk" : "book")}
        className="flex h-8 w-8 items-center justify-center rounded-[6px] border border-line-strong text-muted hover:text-ink"
        aria-label={theme === "book" ? "Switch to the Desk (dark) theme" : "Switch to the Book (light) theme"}
      >
        {theme === "book" ? <Moon size={15} /> : <Sun size={15} />}
      </button>
    </header>
  );
}

export function AppShell() {
  return (
    <div className="flex h-full">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="scroll-thin flex-1 overflow-y-auto p-5"><Outlet /></main>
      </div>
    </div>
  );
}
