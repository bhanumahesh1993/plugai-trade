import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Search, Send, Save, Trash2, PencilLine, ShieldAlert } from "lucide-react";
import { get, post } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button, Field, inputCls } from "@/components/ui";
import { Badge, EmptyState, Textarea, useToast } from "@/components/kit";
import { FactTile, FactsProvider } from "@/components/facts";
import { useMarket } from "@/components/shell";
import { CopyButton, ErrorLine } from "@/components/settings/common";

interface Ph { name: string; paste: boolean }
interface Prompt {
  kid: string; id: string; title: string; chapter: number; chapter_title: string; use: string; works_with: string;
  group: string; chips: string[]; text: string; mine: boolean; note_id: number | null; placeholders: Ph[];
}
interface Found { chips: string[]; count: number; total: number; prompts: Prompt[] }
interface Filled { filled: string; left: string[]; placeholders: Ph[]; untrusted: boolean }

function useDebounced<T>(v: T, ms = 250) {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t); }, [v, ms]);
  return d;
}

/** Hand the prompt (and any pasted source) to Research › Document Desk. */
function useSendToDesk() {
  const navigate = useNavigate();
  const [market] = useMarket();
  const toast = useToast();
  return useMutation({
    mutationFn: async ({ p, text, values }: { p: Prompt; text: string; values: Record<string, string> }) => {
      const pasted = Object.entries(values).filter(([k, v]) => p.placeholders.some((x) => x.name === k && x.paste) && v.trim());
      // Pasted text goes to the desk as its own (UNTRUSTED) document; the question names it instead.
      const vals = Object.fromEntries(Object.entries(values).filter(([k]) => !pasted.some(([pk]) => pk === k)));
      const name = `${p.title} (pasted)`;
      if (pasted.length) await post("/api/research/documents/text", { text: pasted.map(([, v]) => v).join("\n\n"), name, market });
      let q = (await post<Filled>("/api/prompts/fill", { text, values: vals })).filled;
      for (const [k] of pasted) q = q.split(`[${k}]`).join(`(the document "${name}" on the desk)`);
      return { q, pasted: pasted.length > 0 };
    },
    onSuccess: ({ q, pasted }) => {
      toast(pasted ? "Sent to Document Desk with your pasted text loaded as a document" : "Sent to Document Desk");
      navigate(`/documents?q=${encodeURIComponent(q)}`);
    },
  });
}

function FillPanel({ p, onSaved }: { p: Prompt; onSaved: () => void }) {
  const toast = useToast();
  const [text, setText] = useState(p.text);
  const [values, setValues] = useState<Record<string, string>>({});
  const dText = useDebounced(text), dValues = useDebounced(values);
  const { data: f } = useQuery({
    queryKey: ["prompt-fill", p.kid, dText, dValues], placeholderData: keepPreviousData,
    queryFn: () => post<Filled>("/api/prompts/fill", { text: dText, values: dValues }),
  });
  const send = useSendToDesk();
  const save = useMutation({
    mutationFn: () => post(`/api/prompts/${p.id}/my-version`, { text }),
    onSuccess: () => { toast("Saved my version. It now sits above the book's version, tagged MY VERSION."); onSaved(); },
  });
  const phs = f?.placeholders ?? p.placeholders;
  return (
    <div className="mt-3 flex flex-col gap-4 border-t border-line pt-4">
      <Field label="Prompt (edit it to make it yours)">
        <Textarea className="min-h-[200px] text-[14px] leading-[1.5]" value={text} onChange={(e) => setText(e.target.value)} />
      </Field>
      {phs.length > 0 && (
        <div className="grid gap-3 md:grid-cols-2">
          {phs.map((ph) => ph.paste ? (
            <Field key={ph.name} label={ph.name} hint="Pasted text is fenced as UNTRUSTED automatically.">
              <Textarea className="min-h-[110px]" value={values[ph.name] ?? ""} onChange={(e) => setValues({ ...values, [ph.name]: e.target.value })} />
            </Field>
          ) : (
            <Field key={ph.name} label={ph.name}>
              <input className={cn(inputCls, "font-sans")} value={values[ph.name] ?? ""} onChange={(e) => setValues({ ...values, [ph.name]: e.target.value })} />
            </Field>
          ))}
        </div>
      )}
      <div>
        <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
          <span className="text-[13px] font-medium">Ready to paste{f && f.left.length > 0 && <span className="font-normal text-muted">, {f.left.length} placeholder{f.left.length > 1 ? "s" : ""} still to fill</span>}</span>
          <CopyButton text={f?.filled ?? text} label="Copy prompt" done="Copied the filled prompt" />
        </div>
        <pre className="font-sans scroll-thin max-h-[320px] overflow-auto whitespace-pre-wrap rounded-[var(--radius-tile)] border border-line bg-panel-2 p-3 text-[13px] leading-[1.5]">{f?.filled ?? text}</pre>
        {f?.untrusted && <p className="mt-1.5 flex items-center gap-1.5 text-[13px] text-muted"><ShieldAlert size={14} className="text-saffron" /> Pasted text is fenced as UNTRUSTED, so instructions inside it are not followed.</p>}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" onClick={() => send.mutate({ p, text, values })} disabled={send.isPending}><Send size={14} /> Send to Document Desk</Button>
        <Button onClick={() => save.mutate()} disabled={save.isPending || !text.trim()}><Save size={14} /> Save my version</Button>
      </div>
      <ErrorLine error={send.error ?? save.error} />
    </div>
  );
}

function Card({ p, open, onOpen, onChanged }: { p: Prompt; open: boolean; onOpen: (v: boolean) => void; onChanged: () => void }) {
  const toast = useToast();
  const send = useSendToDesk();
  const del = useMutation({
    mutationFn: () => post(`/api/prompts/my-version/${p.note_id}/delete`),
    onSuccess: () => { toast("Deleted my version. The book's version stays."); onChanged(); },
  });
  return (
    <article className={cn("rounded-[var(--radius-panel)] border bg-panel p-4", p.mine ? "border-indigo/50" : "border-line", open && "ring-1 ring-indigo/30")}>
      <header className="flex flex-wrap items-center gap-2">
        <h3 className="text-[15px] font-semibold">{p.title}</h3>
        {p.mine && <Badge tone="indigo">MY VERSION</Badge>}
        <div className="ml-auto flex flex-wrap gap-1">{p.chips.map((c) => <Badge key={c}>{c}</Badge>)}</div>
      </header>
      <p className="mt-1 text-[13px] text-muted">From Chapter {p.chapter}, {p.chapter_title}. Use it for {p.use}. Works with {p.works_with}.</p>
      {!open && <pre className="font-sans scroll-thin mt-3 max-h-[180px] overflow-auto whitespace-pre-wrap rounded-[var(--radius-tile)] border border-line bg-panel-2 p-3 text-[13px] leading-[1.5]">{p.text}</pre>}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" variant={open ? "primary" : "outline"} onClick={() => onOpen(!open)}><PencilLine size={13} /> {open ? "Close" : "Fill in"}</Button>
        {!open && <Button size="sm" onClick={() => send.mutate({ p, text: p.text, values: {} })} disabled={send.isPending}><Send size={13} /> Send to Document Desk</Button>}
        {!open && <Button size="sm" onClick={() => onOpen(true)}><Save size={13} /> Save my version</Button>}
        {p.mine && <Button size="sm" variant="danger" onClick={() => del.mutate()} disabled={del.isPending}><Trash2 size={13} /> Delete my version</Button>}
      </div>
      <ErrorLine error={send.error ?? del.error} />
      {open && <FillPanel p={p} onSaved={onChanged} />}
    </article>
  );
}

export default function PromptLibrary() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [chips, setChips] = useState<string[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const dq = useDebounced(q);
  const { data, error } = useQuery({
    queryKey: ["prompts", dq, chips], placeholderData: keepPreviousData,
    queryFn: () => get<Found>(`/api/prompts?q=${encodeURIComponent(dq)}&chips=${encodeURIComponent(chips.join(","))}`),
  });
  const refresh = () => { setOpen(null); qc.invalidateQueries({ queryKey: ["prompts"] }); };
  const toggle = (c: string) => setChips((x) => (x.includes(c) ? x.filter((y) => y !== c) : [...x, c]));
  const mine = data?.prompts.filter((p) => p.mine).length ?? 0;
  return (
    <FactsProvider>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_300px]">
        <div className="flex min-w-0 flex-col gap-4">
          <div className="flex flex-col gap-3 rounded-[var(--radius-panel)] border border-line bg-panel p-4">
            <label className="relative block">
              <span className="sr-only">Search</span>
              <Search size={15} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted" />
              <input className={cn(inputCls, "pl-8 font-sans")} placeholder="Search: concall, 10-K, plan, wash sale…" value={q} onChange={(e) => setQ(e.target.value)} />
            </label>
            <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filter">
              {data?.chips.map((c) => (
                <button key={c} type="button" aria-pressed={chips.includes(c)} onClick={() => toggle(c)}
                  className={cn("h-7 rounded-[4px] border px-2.5 text-[13px]", chips.includes(c) ? "border-indigo bg-indigo-soft font-medium text-indigo" : "border-line-strong text-muted hover:text-ink")}>{c}</button>
              ))}
              {chips.length > 0 && <Button size="sm" variant="quiet" onClick={() => setChips([])}>Clear filters</Button>}
            </div>
          </div>
          <ErrorLine error={error} />
          {data && data.prompts.length === 0 && (
            <EmptyState action={<Button size="sm" onClick={() => { setQ(""); setChips([]); }}>Show all prompts</Button>}>
              No prompt matches. Try one word such as concall or plan, or clear the filters.
            </EmptyState>
          )}
          {data?.prompts.map((p) => <Card key={p.kid} p={p} open={open === p.kid} onOpen={(v) => setOpen(v ? p.kid : null)} onChanged={refresh} />)}
        </div>
        <div className="flex flex-col gap-4 xl:sticky xl:top-0 xl:self-start">
          <FactTile big label="Prompts shown" value={data ? `${data.count} of ${data.total}` : "—"} sub={mine ? `${mine} of them are your versions` : "the book's prompts, Appendix B"} />
          <div className="rounded-[var(--radius-tile)] border border-line bg-panel p-3.5 text-[13px] leading-[1.5]">
            <p className="font-medium">How to use them</p>
            <p className="mt-1 text-muted">Text in [CAPITALS] is yours to replace. Keep the "Do NOT recommend" and "Do NOT do arithmetic" lines. Anything you paste is fenced as UNTRUSTED.</p>
          </div>
        </div>
      </div>
    </FactsProvider>
  );
}
