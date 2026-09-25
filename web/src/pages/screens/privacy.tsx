import { useEffect, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, AlertTriangle, ChevronDown, ChevronRight } from "lucide-react";
import { get, post } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button, Field, Panel, inputCls } from "@/components/ui";
import { Badge, Callout, Switch, Textarea, useToast } from "@/components/kit";
import { FactTile, FactsProvider } from "@/components/facts";
import { ErrorLine } from "@/components/settings/common";

interface Priv {
  toggles: { name: string; label: string; on: boolean; default: boolean }[]; defaults_on: boolean; lag: number; min_lag: number; default_lag: number;
  local_only_sections: string[];
}
const KEY = ["privacy"];

function useDebounced<T>(v: T, ms = 300) {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t); }, [v, ms]);
  return d;
}

function Preview() {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const dt = useDebounced(text);
  const { data } = useQuery({
    queryKey: ["privacy-preview", dt], enabled: dt.trim().length > 0, placeholderData: keepPreviousData,
    queryFn: () => post<{ found: string[]; payload: string; stripping: boolean }>("/api/settings/privacy/preview", { text: dt }),
  });
  return (
    <section className="rounded-[var(--radius-panel)] border border-line bg-panel">
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-[14px] font-semibold">
        {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />} See what a cloud call would send
      </button>
      {open && (
        <div className="grid gap-4 border-t border-line p-4 md:grid-cols-2">
          <Field label="Paste text"><Textarea className="min-h-[140px]" value={text} onChange={(e) => setText(e.target.value)} placeholder="Contract note line, client code, PAN, SSN…" /></Field>
          <div className="flex flex-col gap-1">
            <span className="text-[12px] text-muted">What would leave your computer</span>
            <pre className="min-h-[140px] font-sans whitespace-pre-wrap rounded-[6px] border border-line bg-panel-2 p-2.5 text-[14px]">{dt.trim() ? data?.payload ?? "" : <span className="text-muted">Paste text on the left to preview it.</span>}</pre>
            {dt.trim() && data && (
              <span className="flex flex-wrap items-center gap-1.5 text-[13px]">
                Found: {data.found.length ? data.found.map((k) => <Badge key={k} tone="warn">{k}</Badge>) : <span className="text-muted">no identifiers</span>}
                {!data.stripping && data.found.length > 0 && <span className="text-bear">Removal is off, so these would be sent.</span>}
              </span>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

export default function Privacy() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: p, error } = useQuery({ queryKey: KEY, queryFn: () => get<Priv>("/api/settings/privacy") });
  const [lag, setLag] = useState("");
  useEffect(() => { if (p) setLag(String(p.lag)); }, [p?.lag]); // eslint-disable-line react-hooks/exhaustive-deps
  const toggle = useMutation({
    mutationFn: (b: { name: string; on: boolean; label: string }) => post<Priv>("/api/settings/privacy/toggle", { name: b.name, on: b.on }),
    onSuccess: (d, b) => { qc.setQueryData(KEY, d); qc.invalidateQueries({ queryKey: ["ai-models"] }); toast(`${b.on ? "Switched on" : "Switched off"}: ${b.label}`); },
  });
  const saveLag = useMutation({
    mutationFn: () => post<Priv & { raised: boolean }>("/api/settings/privacy/lag", { days: Number(lag) }),
    onSuccess: (d) => { qc.setQueryData(KEY, d); setLag(String(d.lag)); toast(d.raised ? `Set the Education lag to the minimum, ${d.lag} days` : `Set the Education lag to ${d.lag} days`); },
  });
  if (error) return <Callout tone="danger" title="Privacy could not load">{(error as Error).message}</Callout>;
  if (!p) return <div className="min-h-[60vh]" aria-busy="true" />;
  const lagN = Number(lag);
  return (
    <FactsProvider>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex min-w-0 flex-col gap-5">
          <p className="text-[13px] text-muted">What may leave your computer. The defaults are strict, and they are what the book assumes.</p>
          <Panel title="What may leave your computer">
            <div className="flex flex-col divide-y divide-line">
              {p.toggles.map((t) => (
                <div key={t.name} className="py-1.5">
                  <Switch checked={t.on} onChange={(on) => toggle.mutate({ name: t.name, on, label: t.label })} label={t.label}
                    hint={t.on !== t.default ? `Changed from the book's default (${t.default ? "on" : "off"})` : undefined} />
                </div>
              ))}
            </div>
            <p className={cn("mt-3 flex items-center gap-1.5 text-[13px]", p.defaults_on ? "text-bull" : "text-ink")}>
              {p.defaults_on ? <CheckCircle2 size={15} /> : <AlertTriangle size={15} className="text-saffron" />}
              {p.defaults_on ? "The book's defaults are on." : "You changed a default. The book assumes the strict defaults."}
            </p>
            <ErrorLine error={toggle.error} />
          </Panel>
          <Preview />
          <Panel title="Education lag">
            <div className="flex flex-wrap items-end gap-2">
              <Field label="Days of lag for named Indian securities in lessons and AI explanations">
                <input type="number" min={p.min_lag} max={3650} step={1} className={cn(inputCls, "w-32")} value={lag} onChange={(e) => setLag(e.target.value)} />
              </Field>
              <Button onClick={() => saveLag.mutate()} disabled={saveLag.isPending || lag === "" || lagN === p.lag}>Save lag</Button>
            </div>
            {lag !== "" && lagN < p.min_lag && <p className="mt-1.5 text-[13px] text-saffron">The minimum is {p.min_lag} days; saving raises it to {p.min_lag}.</p>}
            <p className="mt-2 text-[13px] text-muted">Default {p.default_lag} days (minimum {p.min_lag}). Indices (NIFTY, BANKNIFTY, SENSEX), synthetic data and your own tradebook are not affected.</p>
            <ErrorLine error={saveLag.error} />
          </Panel>
        </div>
        <div className="flex flex-col gap-4">
          <FactTile big label="Education lag" value={`${p.lag} days`} sub={`minimum ${p.min_lag}, default ${p.default_lag}`} />
          <FactTile label="Local-only sections" value={p.local_only_sections.length ? p.local_only_sections.join(", ") : "None"} sub="forced by the toggles above" />
        </div>
      </div>
    </FactsProvider>
  );
}
