import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Code2, Pin, SendHorizontal } from "lucide-react";
import { get, post, type Market } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button, Panel } from "@/components/ui";
import { Badge, EmptyState, Textarea, useToast } from "@/components/kit";
import { useMarket } from "@/components/shell";
import { LocalExplainPanel, LocalFactsProvider, LocalOnly } from "@/components/journal/local";
import { QueryBlock, RowsTable } from "@/components/journal/common";

interface Answer { i: number; question: string; label: string; via: string; text: string; table: Record<string, unknown>[]; rows: number[]; sql: string; facts: string[] }
interface Meta { examples: string[]; label: string; kind: "journal" | "sample" | "empty"; sample: string }

const HEAD: Record<string, string> = { grp: "Group", tod_bucket: "Time of day", total_r: "Total R", mean_r: "Mean R", median_hold_min: "Median hold (min)" };

function AnswerCard({ a, m, last }: { a: Answer; m: Market; last: boolean }) {
  const toast = useToast();
  const [showQ, setShowQ] = useState(false);
  const pin = useMutation({
    mutationFn: () => post("/api/journal/ask/pin", { market: m, index: a.i }),
    onSuccess: () => toast("Pinned: it will run every week in the Weekly Review"),
  });
  const understood = a.via !== "none";
  return (
    <div className="flex flex-col gap-3">
      <div className="ml-auto max-w-[80%] rounded-[var(--radius-tile)] bg-indigo-soft px-3.5 py-2.5 text-[14px] text-ink">{a.question}</div>
      <div className="rounded-[var(--radius-panel)] border border-line bg-panel">
        {understood && (
          <div className="flex flex-wrap items-center gap-2 border-b border-line bg-panel-2 px-4 py-2 text-[13px]">
            <span className="text-muted">The lab runs:</span>
            <span className="font-medium text-ink">{a.label}</span>
            <Badge className="ml-auto">via {a.via}</Badge>
          </div>
        )}
        <div className="flex flex-col gap-3 p-4">
          <p className="font-serif text-[15px] leading-[1.6]">{a.text}</p>
          {a.table.length > 0 && (
            <div role="button" tabIndex={0} title="Click a number to see the query and the rows"
              onClick={() => setShowQ(true)} onKeyDown={(e) => e.key === "Enter" && setShowQ(true)}
              className="cursor-pointer rounded-[var(--radius-tile)] outline-none focus-visible:ring-2 focus-visible:ring-indigo">
              <RowsTable rows={a.table} headers={HEAD} />
            </div>
          )}
          {a.rows.length > 0 && <p className="num text-[12px] text-muted">Rows: {a.rows.join(", ")}</p>}
          {understood && (
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" onClick={() => setShowQ((s) => !s)} aria-pressed={showQ}><Code2 size={14} /> Show query</Button>
              <Button size="sm" onClick={() => pin.mutate()} disabled={pin.isPending || pin.isSuccess} title="Pin this question to the Weekly Review">
                <Pin size={14} /> Accept
              </Button>
              <span className="text-[12px] text-muted">{pin.isSuccess ? "Pinned to the Weekly Review" : "Accept pins this question to the Weekly Review"}</span>
            </div>
          )}
          {showQ && <QueryBlock sql={a.sql} />}
          {pin.error && <p className="text-[13px] text-bear">{(pin.error as Error).message}</p>}
          {last && understood && <LocalExplainPanel facts={a.facts} section="Journal" />}
        </div>
      </div>
    </div>
  );
}

export default function AskJournal() {
  const [m] = useMarket();
  const qc = useQueryClient();
  const toast = useToast();
  const [q, setQ] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const { data: meta } = useQuery({ queryKey: ["journal-meta", m], queryFn: () => get<Meta>(`/api/journal/meta?market=${m}`) });
  const { data: hist } = useQuery({ queryKey: ["journal-ask", m], queryFn: () => get<{ history: Answer[] }>(`/api/journal/ask?market=${m}`) });
  const ask = useMutation({
    mutationFn: (question: string) => post<{ history: Answer[] }>("/api/journal/ask", { market: m, question }),
    onSuccess: (d) => { qc.setQueryData(["journal-ask", m], d); setQ(""); },
  });
  const clear = useMutation({ mutationFn: () => post<{ history: Answer[] }>(`/api/journal/ask/clear?market=${m}`), onSuccess: (d) => qc.setQueryData(["journal-ask", m], d) });
  const sample = useMutation({ mutationFn: () => post(`/api/journal/sample?market=${m}`), onSuccess: () => { qc.invalidateQueries({ queryKey: ["journal-meta", m] }); toast("Lesson 14 sample loaded"); } });
  const history = hist?.history ?? [];
  useEffect(() => { end.current?.scrollIntoView({ block: "nearest" }); }, [history.length]);
  const submit = () => q.trim() && ask.mutate(q.trim());

  if (meta && meta.kind === "empty") {
    return (
      <Panel title="Ask My Journal" className="max-w-[720px]">
        <EmptyState action={<Button onClick={() => sample.mutate()} disabled={sample.isPending}>Load lesson 14 sample ({meta.sample}, synthetic)</Button>}>
          No journal rows yet. Import a tradebook in Journal › Trades, or load the lesson sample.
        </EmptyState>
      </Panel>
    );
  }
  return (
    <LocalFactsProvider>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex min-w-0 flex-col gap-5">
          {history.length === 0 && (
            <EmptyState>Ask a question in plain English. The lab turns it into a query, runs it on your journal, and shows the query line before the answer.</EmptyState>
          )}
          {history.map((a, i) => <AnswerCard key={a.i} a={a} m={m} last={i === history.length - 1} />)}
          <div ref={end} />
          <div className="sticky bottom-0 -mx-1 rounded-[var(--radius-panel)] border border-line bg-panel p-3 shadow-sm">
            <div className="flex items-end gap-2">
              <Textarea aria-label="Ask a question about your journal" rows={2} className="min-h-[44px]" value={q} placeholder="Ask a question about your journal"
                onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }} />
              <Button variant="primary" onClick={submit} disabled={!q.trim() || ask.isPending}><SendHorizontal size={14} /> {ask.isPending ? "Asking…" : "Ask"}</Button>
            </div>
            {ask.error && <p className="mt-2 text-[13px] text-bear">{(ask.error as Error).message}</p>}
            {history.length > 0 && <p className="mt-2 text-[12px] text-muted">Follow-ups start from the previous query, for example "Which of those broke a Rule Card line?"</p>}
          </div>
        </div>
        <div className="flex flex-col gap-4">
          <Panel title="Asking">
            <div className="flex flex-col gap-2 text-[13px]">
              <span>{meta?.label || "your journal"}</span>
              <span className="flex flex-wrap items-center gap-2 text-muted"><LocalOnly>Local model</LocalOnly> Read the query line before the answer.</span>
            </div>
          </Panel>
          <Panel title="Examples">
            <ul className="flex flex-col gap-1">
              {(meta?.examples ?? []).map((ex) => (
                <li key={ex}>
                  <button type="button" onClick={() => setQ(ex)} className={cn("w-full rounded-[6px] px-2 py-1.5 text-left text-[13px] hover:bg-panel-2 hover:text-indigo")}>{ex}</button>
                </li>
              ))}
            </ul>
          </Panel>
          {history.length > 0 && <Button variant="quiet" className="self-start" onClick={() => clear.mutate()}>Clear chat</Button>}
        </div>
      </div>
    </LocalFactsProvider>
  );
}
