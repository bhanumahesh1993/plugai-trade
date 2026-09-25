import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, AlertTriangle, Circle, CircleDashed, Terminal, RotateCcw, Database } from "lucide-react";
import { get, post } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button, Panel, Field, inputCls } from "@/components/ui";
import { Badge, Callout, DataTable, Select, useToast } from "@/components/kit";
import { CiteTarget, ExplainPanel, FactTile, FactsProvider } from "@/components/facts";
import { useMarket } from "@/components/shell";
import { ErrorLine, Meta, ScreenLink, Tick, type ScreenLinkT } from "@/components/settings/common";

type BadgeT = "Not started" | "In progress" | "Done";
interface Row { n: number; title: string; levels: string[]; badge: BadgeT; command: string }
interface CheckT { key: string; text: string; kind: "number" | "tick" | "state"; unit: string }
interface Lesson extends Row {
  goal: string; market: string; steps: { text: string; screen?: ScreenLinkT }[]; checks: CheckT[];
  progress: Record<string, boolean>; samples: string[];
  exercise: { title: string; facts: string[]; table: { columns: string[]; rows: Record<string, unknown>[] } | null } | null;
  exercise_error: string | null;
}
interface Result { key: string; text: string; passed: boolean; detail: string }

function ProgressBadge({ b }: { b: BadgeT }) {
  const Icon = b === "Done" ? CheckCircle2 : b === "In progress" ? CircleDashed : Circle;
  return <Badge tone={b === "Not started" ? "neutral" : "indigo"} className="gap-1"><Icon size={12} /> {b}</Badge>;
}

const label = (fact: string) => fact.split(":")[0].trim();
/** `code` spans in lesson text render as code, never as raw backticks. */
function Prose({ text }: { text: string }) {
  return <>{text.split(/(`[^`]+`)/g).map((p, i) => p.startsWith("`") ? <code key={i} className="rounded-[4px] bg-panel-2 px-1 text-[13px]">{p.slice(1, -1)}</code> : <span key={i}>{p}</span>)}</>;
}

function CheckMyWork({ les, market, onBadge }: { les: Lesson; market: string; onBadge: () => void }) {
  const toast = useToast();
  const [answers, setAnswers] = useState<Record<string, string | boolean>>({});
  const [results, setResults] = useState<Result[] | null>(null);
  const check = useMutation({
    mutationFn: () => post<{ results: Result[]; badge: BadgeT }>(`/api/lessons/${les.n}/check`, { market, answers }),
    onSuccess: (r) => { setResults(r.results); onBadge(); toast(`Checked your work: ${r.results.filter((x) => x.passed).length} of ${r.results.length} match the lab`); },
  });
  const reset = useMutation({
    mutationFn: () => post<{ removed: number }>(`/api/lessons/${les.n}/reset`),
    onSuccess: () => { setAnswers({}); setResults(null); onBadge(); toast(`Reset lesson ${les.n}: progress cleared`); },
  });
  const res = Object.fromEntries((results ?? []).map((r) => [r.key, r]));
  return (
    <Panel title="Check my work" action={<ProgressBadge b={les.badge} />}>
      <ul className="flex flex-col divide-y divide-line">
        {les.checks.map((c) => {
          const r = res[c.key];
          return (
            <li key={c.key} className="flex flex-col gap-1.5 py-2.5 first:pt-0">
              {c.kind === "number" && (
                <Field label={c.text}>
                  <input className={cn(inputCls, "max-w-[260px]")} inputMode="decimal" placeholder="Type your number"
                    value={String(answers[c.key] ?? "")} onChange={(e) => setAnswers({ ...answers, [c.key]: e.target.value })} />
                </Field>
              )}
              {c.kind === "tick" && <Tick checked={Boolean(answers[c.key])} onChange={(v) => setAnswers({ ...answers, [c.key]: v })}>{c.text}</Tick>}
              {c.kind === "state" && (
                <div className="flex items-start gap-2.5 py-1"><Database size={15} className="mt-0.5 shrink-0 text-muted" /><span>{c.text}<span className="block text-[13px] text-muted">The lab checks this itself.</span></span></div>
              )}
              {r && (
                <p className={cn("flex items-start gap-1.5 text-[13px]", r.passed ? "text-bull" : "text-ink")}>
                  {r.passed ? <CheckCircle2 size={15} className="mt-0.5 shrink-0" /> : <AlertTriangle size={15} className="mt-0.5 shrink-0 text-saffron" />}
                  <span>{r.detail}</span>
                </p>
              )}
            </li>
          );
        })}
      </ul>
      <div className="mt-3 flex flex-wrap gap-2 border-t border-line pt-3">
        <Button variant="primary" onClick={() => check.mutate()} disabled={check.isPending}>Check my work</Button>
        <Button onClick={() => reset.mutate()} disabled={reset.isPending}><RotateCcw size={14} /> Reset lesson</Button>
      </div>
      <ErrorLine error={check.error ?? reset.error} />
    </Panel>
  );
}

function HandsOn({ les, market }: { les: Lesson; market: string }) {
  const toast = useToast();
  const load = useMutation({
    mutationFn: () => post<{ lines: string[] }>(`/api/lessons/${les.n}/load-sample`, { market }),
    onSuccess: () => toast("Loaded the lesson sample"),
  });
  const ex = les.exercise;
  return (
    <Panel title="Hands-on" action={<span className="text-[12px] text-muted">Synthetic data, computed in code</span>}>
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => load.mutate()} disabled={load.isPending}>Load lesson sample</Button>
          {!load.data && <span className="text-[13px] text-muted">Loads the sample watchlist{les.samples.length ? ` and ${les.samples.join(", ")}` : ""} for {market}.</span>}
        </div>
        {load.data && (
          <ul className="flex flex-col gap-1 text-[13px]">
            {load.data.lines.map((l) => <li key={l} className="flex items-start gap-1.5"><CheckCircle2 size={14} className="mt-0.5 shrink-0 text-bull" />{l}</li>)}
          </ul>
        )}
        <ErrorLine error={load.error} />
        {les.exercise_error && <Callout tone="info">{les.exercise_error}</Callout>}
        {ex && (
          <div className="flex flex-col gap-3">
            <h3 className="text-[14px] font-semibold">{ex.title}</h3>
            <ul className="flex flex-col gap-1">
              {ex.facts.map((f) => <li key={f}><CiteTarget label={label(f)} className="px-2 py-1 num">{f}</CiteTarget></li>)}
            </ul>
            {ex.table && (
              <DataTable rows={ex.table.rows} columns={ex.table.columns.map((c) => ({
                key: c, header: c, align: typeof ex.table!.rows[0]?.[c] === "number" ? "right" as const : "left" as const,
                render: (r: Record<string, unknown>) => {
                  const v = r[c];
                  return typeof v === "number" ? v.toLocaleString(market === "IN" ? "en-IN" : "en-US", { maximumFractionDigits: 2 }) : String(v ?? "—");
                },
              }))} />
            )}
          </div>
        )}
      </div>
    </Panel>
  );
}

export default function Lessons() {
  const [market] = useMarket();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const { data: list } = useQuery({ queryKey: ["lessons"], queryFn: () => get<{ lessons: Row[]; from_env: number | null }>("/api/lessons") });
  const fromUrl = Number(params.get("lesson"));
  const n = fromUrl >= 1 && fromUrl <= 34 ? fromUrl : list?.from_env ?? 1;
  const pick = (k: number) => setParams({ lesson: String(k) }, { replace: false });
  const { data: les, error } = useQuery({ queryKey: ["lesson", n, market], queryFn: () => get<Lesson>(`/api/lessons/${n}?market=${market}`) });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["lessons"] }); qc.invalidateQueries({ queryKey: ["lesson", n] }); };
  const [showAll, setShowAll] = useState(false);
  useEffect(() => { document.getElementById("main-lesson-top")?.scrollIntoView?.({ block: "start" }); }, [n]);

  const passed = les ? les.checks.filter((c) => les.progress[c.key]).length : 0;
  const counts = useMemo(() => {
    const c = { Done: 0, "In progress": 0, "Not started": 0 } as Record<BadgeT, number>;
    list?.lessons.forEach((l) => { c[l.badge] += 1; });
    return c;
  }, [list]);

  return (
    <FactsProvider>
      <div className="flex flex-col gap-5" id="main-lesson-top">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Lesson">
            <Select className="w-[min(520px,80vw)] font-sans" value={n} onChange={(e) => pick(Number(e.target.value))}>
              {list?.lessons.map((l) => <option key={l.n} value={l.n}>Chapter {l.n}: {l.title} ({l.badge})</option>)}
            </Select>
          </Field>
          <Button onClick={() => pick(Math.max(1, n - 1))} disabled={n <= 1}>Previous lesson</Button>
          <Button onClick={() => pick(Math.min(34, n + 1))} disabled={n >= 34}>Next lesson</Button>
          <span className="ml-auto text-[13px] text-muted">One lesson per chapter. Synthetic data, so your numbers match the book.</span>
        </div>
        <ErrorLine error={error} />

        {les && (
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
            <div className="flex min-w-0 flex-col gap-5">
              <section className="rounded-[var(--radius-panel)] border border-line bg-panel px-5 py-4">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-[20px] font-semibold leading-tight">Chapter {les.n}: {les.title}</h2>
                  <ProgressBadge b={les.badge} />
                </div>
                <p className="mt-2 font-serif text-[16px] leading-[1.55]"><span className="font-semibold">Goal.</span> {les.goal}</p>
                <div className="mt-3">
                  <Meta items={[["Levels", les.levels.join(", ")], ["Market", les.market],
                    ["Terminal", <span key="t" className="inline-flex items-center gap-1"><Terminal size={13} className="text-muted" /><code className="text-[13px]">{les.command}</code></span>]]} />
                </div>
              </section>

              <Panel title="Steps">
                <ol className="flex flex-col divide-y divide-line">
                  {les.steps.map((s, i) => (
                    <li key={i} className="flex flex-wrap items-start gap-x-4 gap-y-2 py-2.5 first:pt-0 last:pb-0">
                      <span className="num mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-indigo-soft text-[12px] font-semibold text-indigo">{i + 1}</span>
                      <span className="min-w-0 flex-1 basis-[280px] font-serif text-[15px] leading-[1.55]"><Prose text={s.text} /></span>
                      {s.screen && <ScreenLink s={s.screen} className="ml-10 sm:ml-0" />}
                    </li>
                  ))}
                </ol>
              </Panel>

              <HandsOn key={`${les.n}-${market}`} les={les} market={market} />
            </div>

            <div className="flex flex-col gap-4">
              <div className="grid grid-cols-2 gap-2.5">
                <FactTile big label="Checks passed" value={`${passed} of ${les.checks.length}`} sub="your latest results" />
                <FactTile label="Lessons done" value={`${counts.Done} of 34`} sub={`${counts["In progress"]} in progress`} />
              </div>
              <CheckMyWork key={`${les.n}-${market}`} les={les} market={market} onBadge={refresh} />
              {les.exercise && (
                <Panel title="Explain the exercise">
                  <ExplainPanel facts={les.exercise.facts} section="Research" />
                </Panel>
              )}
            </div>
          </div>
        )}

        <Panel title="All lessons and your progress" action={<Button size="sm" variant="quiet" onClick={() => setShowAll((x) => !x)}>{showAll ? "Hide the list" : "Show all 34"}</Button>}>
          {showAll ? (
            <DataTable rows={(list?.lessons ?? []) as unknown as Record<string, unknown>[]} rowKey={(r) => Number(r.n)} onRowClick={(r) => pick(Number(r.n))} columns={[
              { key: "n", header: "Chapter", align: "right", width: "70px" },
              { key: "title", header: "Lesson", render: (r) => <span className={cn(Number(r.n) === n && "font-medium text-indigo")}>{String(r.title)}</span> },
              { key: "levels", header: "Levels", render: (r) => (r.levels as string[]).join(", ") },
              { key: "badge", header: "Progress", render: (r) => <ProgressBadge b={r.badge as BadgeT} /> },
              { key: "command", header: "Command", render: (r) => <code className="text-[13px]">{String(r.command)}</code> },
            ]} />
          ) : (
            <div className="flex flex-wrap gap-1" aria-label="Lesson progress">
              {list?.lessons.map((l) => (
                <button key={l.n} type="button" onClick={() => pick(l.n)} title={`Chapter ${l.n}: ${l.title} (${l.badge})`}
                  className={cn("num flex h-8 w-8 items-center justify-center rounded-[6px] border text-[13px]",
                    l.badge === "Done" ? "border-indigo bg-indigo text-white dark:text-[#0f1a2b]" : l.badge === "In progress" ? "border-indigo bg-indigo-soft text-indigo" : "border-line text-muted hover:border-indigo",
                    l.n === n && "ring-2 ring-indigo ring-offset-1 ring-offset-[var(--panel)]")}>{l.n}</button>
              ))}
            </div>
          )}
        </Panel>
        <p className="text-[12px] text-muted">Paper only. PlugAI-Trade never places real orders.</p>
      </div>
    </FactsProvider>
  );
}
