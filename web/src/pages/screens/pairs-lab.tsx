import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { Link2, Search, Send } from "lucide-react";
import { get, post } from "@/lib/api";
import { money } from "@/lib/format";
import { cn } from "@/lib/cn";
import { Button, Panel, inputCls } from "@/components/ui";
import { FactTile, FactsProvider, ExplainPanel } from "@/components/facts";
import { useMarket } from "@/components/shell";
import { Badge, Callout, DataTable, EmptyState, Hypothetical, Select, Textarea, useToast, type Column } from "@/components/kit";
import { ErrorText, Labelled, PaperOnlyNote, useSessionState } from "@/components/strategy/shared";
import { PairTradesTable, ZChart, type PairRule, type PairTrade } from "@/components/strategy/pairs";

interface Universe { name: string; symbols: string[] }
interface Candidate { a: string; b: string; correlation: number; adf_t: number; critical_5: number; passes: boolean; half_life: number; beta: number }
interface Fit {
  a: string; b: string; formation: number; beta: number; half_life: number; adf_t: number; critical_5: number; cointegrated: boolean;
  sd: number; correlation: number; z: number[]; default_time_stop: number; rule: PairRule; trades: PairTrade[];
  suspended: number | null; latest_z: number; facts: string[]; lots: { a: number | null; b: number | null };
}
interface SizeOut {
  market: "IN" | "US"; lots_a?: number; lots_b?: number; shares_a?: number; shares_b?: number; value_a: number; value_b: number;
  target_lots_b?: number; error: number; achieved: number; borrow_fee?: number; qty_a: number; qty_b: number;
  near?: { lots_a: number; lots_b: number; gross: number } | null; facts: string[];
}
interface Link { text: string; rating: string | null; where: string; model: string }

const TYPE = "Type symbols";
const hl = (x: number) => (x > 1e5 ? "∞" : x.toFixed(1));

function Num({ label, value, onChange, step = 0.1, min, max, hint }: { label: string; value: number; onChange: (v: number) => void; step?: number; min?: number; max?: number; hint?: string }) {
  return (
    <Labelled label={label}>
      <input className={inputCls} type="number" value={Number.isFinite(value) ? value : ""} step={step} min={min} max={max} title={hint}
        onChange={(e) => onChange(Number(e.target.value))} />
    </Labelled>
  );
}

export default function PairsLab() {
  const [market] = useMarket();
  const toast = useToast();
  const navigate = useNavigate();
  const [formation, setFormation] = useSessionState("pl-formation", 250);
  const [uniName, setUniName] = useSessionState("pl-universe", "");
  const [typed, setTyped] = useSessionState("pl-typed", "SYN-A, SYN-B, SYN-C, SYN-D");
  const [pair, setPair] = useSessionState("pl-pair", "SYN-A / SYN-B");
  const [rule, setRule] = useSessionState<{ entry: number; exit: number; stop: number; time_stop: number | null }>("pl-rule", { entry: 2, exit: 0.5, stop: 3.5, time_stop: null });
  const [events, setEvents] = useSessionState("pl-events", "");
  const [desc, setDesc] = useState("");
  const [sizeIn, setSizeIn] = useSessionState("pl-size", { pa: 1630, pb: 885, la: 0, lb: 0, cap: 10000, pa_us: 81.66, pb_us: 44.26, fee: 3, days: 16 });

  const { data: universes = [] } = useQuery({ queryKey: ["pl-universes"], queryFn: () => get<Universe[]>("/api/strategy/pairs/universes") });
  const uni = uniName || universes[0]?.name || "";
  const symbols = uni === TYPE ? typed.split(",").map((x) => x.trim().toUpperCase()).filter(Boolean)
    : universes.find((u) => u.name === uni)?.symbols ?? ["SYN-A", "SYN-B", "SYN-C", "SYN-D"];

  const [findSyms, setFindSyms] = useState<string[] | null>(null);
  const find = useQuery({
    queryKey: ["pl-find", market, formation, findSyms ?? ["SYN-A", "SYN-B", "SYN-C", "SYN-D"]],
    queryFn: () => post<Candidate[]>("/api/strategy/pairs/find", { symbols: findSyms ?? ["SYN-A", "SYN-B", "SYN-C", "SYN-D"], market, formation }),
    placeholderData: keepPreviousData, retry: false,
  });
  const cands = find.data ?? [];
  const labels = cands.map((c) => `${c.a} / ${c.b}`);
  const current = labels.includes(pair) ? pair : labels[0] ?? pair;
  const [a, b] = current.split(" / ");

  const fitBody = { a, b, market, formation, entry: rule.entry, exit: rule.exit, stop: rule.stop, time_stop: rule.time_stop };
  const fit = useQuery({
    queryKey: ["pl-fit", fitBody], queryFn: () => post<Fit>("/api/strategy/pairs/fit", fitBody),
    enabled: !!a && !!b, placeholderData: keepPreviousData, retry: false,
  });
  const f = fit.data;

  // Lot sizes come from the dated Contract Table when it has them.
  useEffect(() => {
    if (f && market === "IN" && (!sizeIn.la || !sizeIn.lb)) setSizeIn({ ...sizeIn, la: f.lots.a ?? 1000, lb: f.lots.b ?? 2000 });
  }, [f, market, sizeIn, setSizeIn]);
  const sizeBody = market === "IN"
    ? { market, beta: f?.beta, price_a: sizeIn.pa, price_b: sizeIn.pb, lot_a: sizeIn.la || 1000, lot_b: sizeIn.lb || 2000 }
    : { market, beta: f?.beta, price_a: sizeIn.pa_us, price_b: sizeIn.pb_us, capital: sizeIn.cap, borrow_pct: sizeIn.fee, days: sizeIn.days };
  const size = useQuery({
    queryKey: ["pl-size", sizeBody], queryFn: () => post<SizeOut>("/api/strategy/pairs/size", sizeBody),
    enabled: !!f, placeholderData: keepPreviousData, retry: false,
  });
  const sz = size.data;

  const [note, setNote] = useState<(Link & { pair: string }) | null>(null);
  const link = useMutation({
    mutationFn: () => post<Link>("/api/strategy/pairs/check-link", { a, b, description: desc, market }),
    onSuccess: (x) => setNote({ ...x, pair: current }),
  });
  const keep = useMutation({
    mutationFn: () => post<{ rating: string }>("/api/strategy/pairs/accept-link", { a, b, text: note!.text, rating: note!.rating }),
    onSuccess: (x) => toast(`Link note kept: ${x.rating}`),
    onError: (e) => toast((e as Error).message, "danger"),
  });
  const [sentId, setSentId] = useState<number | null>(null);
  const sendBt = useMutation({
    mutationFn: () => post<{ id: number; trials: number }>("/api/strategy/pairs/send-backtest", fitBody),
    onSuccess: (x) => { setSentId(x.id); toast(`Sent as backtest #${x.id}`); },
    onError: (e) => toast((e as Error).message, "danger"),
  });
  const sendPaper = useMutation({
    mutationFn: () => post<{ ids: number[] }>("/api/strategy/pairs/send-paper", { ...fitBody, qty_a: sz?.qty_a, qty_b: sz?.qty_b, events }),
    onSuccess: (x) => toast(`Two linked pending paper orders (#${x.ids[0]}, #${x.ids[1]}) drafted`),
    onError: (e) => toast((e as Error).message, "danger"),
  });
  const paperOk = !!f && f.cointegrated && !f.suspended && !!sz;

  const cols: Column<Candidate & Record<string, unknown>>[] = [
    { key: "pair", header: "Pair", render: (c) => <span className="font-medium">{c.a} / {c.b}</span> },
    { key: "correlation", header: "Correlation", align: "right", render: (c) => c.correlation.toFixed(2) },
    { key: "adf_t", header: "Cointegration t", align: "right", render: (c) => c.adf_t.toFixed(2) },
    { key: "critical_5", header: "5% critical", align: "right", render: (c) => c.critical_5.toFixed(2) },
    { key: "passes", header: "Test", render: (c) => c.passes ? <span className="font-medium">passes</span>
      : c.correlation >= 0.8 ? <Badge tone="warn">fails, high correlation</Badge> : <span className="text-muted">fails</span> },
    { key: "half_life", header: "Half-life", align: "right", render: (c) => hl(c.half_life) },
    { key: "beta", header: "Hedge ratio", align: "right", render: (c) => c.beta.toFixed(3) },
  ];

  return (
    <FactsProvider>
      <div className="flex flex-col gap-5">
        <div className="flex flex-wrap items-end gap-4">
          <div className="w-56"><Num label="Formation window (sessions)" value={formation} step={10} min={60} max={1000}
            onChange={(v) => setFormation(Math.min(1000, Math.max(60, Math.round(v) || 60)))} /></div>
          <p className="pb-2 text-[13px] text-muted">Hedge ratio, z-score and half-life are fitted on this frozen window; no later data leaks into them.</p>
        </div>

        {/* ------------------------------------------------ pair finder */}
        <Panel title="Pair finder">
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex w-[min(360px,100%)] flex-col gap-1">
              <span className="text-[12px] text-muted">Universe</span>
              <Select value={uni} onChange={(e) => setUniName(e.target.value)}>
                {universes.map((u) => <option key={u.name}>{u.name}</option>)}
                <option>{TYPE}</option>
              </Select>
            </label>
            {uni === TYPE && (
              <label className="flex min-w-[240px] flex-1 flex-col gap-1">
                <span className="text-[12px] text-muted">Symbols (comma-separated)</span>
                <input className={inputCls} value={typed} onChange={(e) => setTyped(e.target.value)} />
              </label>
            )}
            <Button variant="primary" onClick={() => setFindSyms(symbols)} disabled={find.isFetching}><Search size={15} /> {find.isFetching ? "Testing pairs…" : "Find pairs"}</Button>
          </div>
          <div className="mt-4">
            <ErrorText error={find.error} />
            {cands.length ? (
              <DataTable rows={cands as (Candidate & Record<string, unknown>)[]} columns={cols}
                rowKey={(c) => `${c.a}/${c.b}`} onRowClick={(c) => setPair(`${c.a} / ${c.b}`)} />
            ) : !find.isFetching && <EmptyState>No pairs could be tested (need at least two symbols with data). Choose another universe or type symbols.</EmptyState>}
            <p className="mt-2 text-[13px] text-muted">Amber: high correlation but no leash. Correlation is not cointegration. Click a row to pick it as the candidate.</p>
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
            <Labelled label="Candidate">
              <Select value={current} onChange={(e) => setPair(e.target.value)}>
                {(labels.length ? labels : [current]).map((l) => <option key={l}>{l}</option>)}
              </Select>
            </Labelled>
            <div className="flex flex-col gap-2">
              <Labelled label="Your two-line description of each business (optional)">
                <Textarea rows={2} value={desc} onChange={(e) => setDesc(e.target.value)} className="min-h-[56px]" />
              </Labelled>
              <div className="flex flex-wrap items-center gap-2">
                <Button onClick={() => link.mutate()} disabled={link.isPending || !a}><Link2 size={14} /> {link.isPending ? "Checking…" : "Check link"}</Button>
                <span className="text-[13px] text-muted">The AI writes a short economic-link note. Nothing is kept until you click Accept.</span>
              </div>
              <ErrorText error={link.error} />
              {note && note.pair === current && (
                <div className="rounded-[var(--radius-tile)] border border-line bg-panel-2 p-3.5">
                  <p className="whitespace-pre-line font-serif text-[15px] leading-[1.6]">{note.text}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-[13px] text-muted">
                    Link rating: <Badge tone={note.rating ? "indigo" : "neutral"}>{note.rating ?? "not rated"}</Badge>
                    <span>{note.where === "Fallback" ? "No model connected" : `${note.where} model ${note.model}`}</span>
                    <Button size="sm" variant="primary" className="ml-auto" disabled={!note.rating || keep.isPending} onClick={() => keep.mutate()}>Accept</Button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </Panel>

        {/* ------------------------------------------------ spread z-score */}
        <Panel title={`Spread z-score, ${current}`} action={<Hypothetical />}>
          <div className="grid gap-4 sm:grid-cols-4">
            <Num label="Entry |z|" value={rule.entry} min={0.5} max={5} onChange={(v) => setRule({ ...rule, entry: v })} />
            <Num label="Exit |z|" value={rule.exit} min={0} max={3} onChange={(v) => setRule({ ...rule, exit: v })} />
            <Num label="Stop |z|" value={rule.stop} min={1} max={10} onChange={(v) => setRule({ ...rule, stop: v })} />
            <Num label="Time stop (sessions)" value={rule.time_stop ?? f?.default_time_stop ?? 18} step={1} min={1} max={500}
              hint="Three half-lives is the book's rule of thumb." onChange={(v) => setRule({ ...rule, time_stop: Math.round(v) || null })} />
          </div>
          <p className="mt-1 text-[12px] text-muted">Time stop defaults to three half-lives, the book's rule of thumb.</p>
          <ErrorText error={fit.error} />
          {f && (
            <div className="mt-4 flex flex-col gap-4">
              <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
                <FactTile label="Half-life" value={`${hl(f.half_life)} sessions`} big />
                <FactTile label="Hedge ratio" value={f.beta.toFixed(3)} />
                <FactTile label="Cointegration t" value={f.adf_t.toFixed(2)} sub={`5% critical ${f.critical_5.toFixed(2)}`} tone={f.cointegrated ? undefined : "bear"} />
                <FactTile label="Spread width (sd)" value={`${(f.sd * 100).toFixed(2)}%`} />
              </div>
              {!f.cointegrated && <Callout tone="warn">This pair fails the cointegration test on the formation window.</Callout>}
              <Labelled label="Known event dates for both companies (results, meetings)">
                <input className={inputCls} value={events} onChange={(e) => setEvents(e.target.value)} placeholder="For example 2026-10-14 results A; 2026-10-21 AGM B" />
              </Labelled>
              <ZChart z={f.z} formation={f.formation} rule={f.rule} trades={f.trades} />
              <p className="text-[13px] text-muted">Formation = sessions 1 to {f.formation} (frozen), trading after. Latest z-score {f.latest_z.toFixed(2)}.</p>
              <PairTradesTable trades={f.trades} />
              {f.suspended && <Callout tone="warn">Stopped at session {f.suspended}: pair suspended. Only a new formation window after the event is an honest restart.</Callout>}
              <ExplainPanel facts={f.facts} section="Strategy" />
            </div>
          )}
        </Panel>

        {/* ------------------------------------------------ sizing */}
        <Panel title="Sizing">
          {market === "IN" ? (
            <div className="grid gap-4 sm:grid-cols-4">
              <Num label="Price A (₹)" value={sizeIn.pa} step={1} min={0} onChange={(v) => setSizeIn({ ...sizeIn, pa: v })} />
              <Num label="Price B (₹)" value={sizeIn.pb} step={1} min={0} onChange={(v) => setSizeIn({ ...sizeIn, pb: v })} />
              <Num label="Lot A" value={sizeIn.la || 1000} step={1} min={1} onChange={(v) => setSizeIn({ ...sizeIn, la: Math.round(v) })} />
              <Num label="Lot B" value={sizeIn.lb || 2000} step={1} min={1} onChange={(v) => setSizeIn({ ...sizeIn, lb: Math.round(v) })} />
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-5">
              <Num label="Capital for the long leg ($)" value={sizeIn.cap} step={100} min={0} onChange={(v) => setSizeIn({ ...sizeIn, cap: v })} />
              <Num label="Price A ($)" value={sizeIn.pa_us} step={0.01} min={0} onChange={(v) => setSizeIn({ ...sizeIn, pa_us: v })} />
              <Num label="Price B ($)" value={sizeIn.pb_us} step={0.01} min={0} onChange={(v) => setSizeIn({ ...sizeIn, pb_us: v })} />
              <Num label="Borrow fee (% a year)" value={sizeIn.fee} step={0.5} min={0} max={100} onChange={(v) => setSizeIn({ ...sizeIn, fee: v })} />
              <Num label="Days held (estimate)" value={sizeIn.days} step={1} min={1} max={365} onChange={(v) => setSizeIn({ ...sizeIn, days: Math.round(v) })} />
            </div>
          )}
          <ErrorText error={size.error} />
          {sz && (
            <div className="mt-4 flex flex-col gap-4">
              {sz.market === "IN" ? (
                <div className="grid grid-cols-1 gap-2.5 md:grid-cols-3">
                  <FactTile label="Long A" value={`${sz.lots_a} lot = ${money(sz.value_a, "IN")}`} />
                  <FactTile label="Short B (rounded)" value={`${sz.lots_b} lot = ${money(sz.value_b, "IN")}`} sub={`Target ${sz.target_lots_b?.toFixed(2)} lots`} />
                  <FactTile label="Hedge-ratio error" value={`${sz.error >= 0 ? "+" : "−"}${Math.abs(sz.error * 100).toFixed(1)}%`} sub={`Achieved ${sz.achieved.toFixed(3)}`} big />
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
                  <FactTile label="Long A" value={`${sz.shares_a} sh = ${money(sz.value_a, "US", 2)}`} />
                  <FactTile label="Short B" value={`${sz.shares_b} sh = ${money(sz.value_b, "US", 2)}`} />
                  <FactTile label="Hedge-ratio error" value={`${sz.error >= 0 ? "+" : "−"}${Math.abs(sz.error * 100).toFixed(1)}%`} sub={`Achieved ${sz.achieved.toFixed(3)}`} big />
                  <FactTile label="Borrow fee" value={money(sz.borrow_fee, "US", 2)} />
                </div>
              )}
              {sz.near && (
                <p className="text-[13px] text-muted">Lot mismatch: to get within 5% of target you need {sz.near.lots_a} lots A and {sz.near.lots_b} lots B, about ₹{(sz.near.gross / 1e7).toFixed(1)} crore gross. Overnight shorts need stock futures (whole lots) or SLB; margin on both legs.</p>
              )}
              <ExplainPanel facts={sz.facts} section="Strategy" />
            </div>
          )}
        </Panel>

        {/* ------------------------------------------------ hand-offs */}
        <Panel title="Hand-offs">
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={() => sendBt.mutate()} disabled={!f || sendBt.isPending}><Send size={14} /> Send to Backtest Report</Button>
            <Button onClick={() => sendPaper.mutate()} disabled={!paperOk || sendPaper.isPending}><Send size={14} /> Send to Paper Desk</Button>
            {sentId && <Button variant="quiet" size="sm" onClick={() => navigate(`/backtest-report?id=${sentId}`)}>Open Backtest Report</Button>}
          </div>
          <div className="mt-3 flex flex-col gap-1.5">
            <p className={cn("text-[13px]", paperOk ? "text-muted" : "text-bear")}>
              {paperOk ? "Send to Paper Desk drafts two linked pending paper orders with the hedge ratio, three exits and your event dates. Nothing fills until you click Accept."
                : "Send to Paper Desk needs a pair that passes the test and is not suspended."}
            </p>
            <p className="text-[13px] text-muted">Send to Backtest Report stores this run; the Trials counter counts every pair you tested.</p>
            <PaperOnlyNote />
          </div>
        </Panel>
      </div>
    </FactsProvider>
  );
}
