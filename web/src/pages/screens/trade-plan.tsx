import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient, keepPreviousData } from "@tanstack/react-query";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { FilePlus2, Save, Scale, BookmarkCheck, Send } from "lucide-react";
import { get, post, type Explanation, type Market } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button, Panel, Field } from "@/components/ui";
import { Callout, DataTable, EmptyState, Segmented, Select, Textarea, useToast } from "@/components/kit";
import { FactsProvider } from "@/components/facts";
import { useMarket } from "@/components/shell";
import { CitedPanel, ErrorLine, LocalFacts, LocalTile, NumField, OwnerChip, TextField, useDebounced, useLit } from "@/components/planning/common";

interface PlanOut {
  id: number; name: string; template: string; market: Market; symbol: string; side: "long" | "short";
  entry: number | null; stop: number | null; target: number | null; qty: number | null; risk_money: number | null;
  trigger_expiry: string; fields: Record<string, string>; version: number; owners: Record<string, string>;
  versions: { version: number; saved: string; entry: number | null; stop: number | null; qty: number | null; fields: Record<string, string> }[];
  facts: string[]; check: { missing: string[]; vague: string[]; contradictions: string[] };
}
interface PlanRow { id: number; name: string; symbol: string; version: number; template: string }
interface Draft { name: string; side: "long" | "short"; entry: number | null; stop: number | null; trigger_expiry: string; fields: Record<string, string> }

const draftOf = (p: PlanOut): Draft => ({ name: p.name, side: p.side, entry: p.entry, stop: p.stop, trigger_expiry: p.trigger_expiry ?? "", fields: { ...p.fields } });

function FieldRow({ name, owner, value, onChange }: { name: string; owner: string; value: string; onChange: (v: string) => void }) {
  const lit = useLit(name);
  return (
    <div className={cn("tile grid gap-2 rounded-[var(--radius-tile)] p-1 sm:grid-cols-[140px_minmax(0,1fr)]", lit && "tile-lit")}>
      <div className="flex items-start justify-between gap-2 pt-2 sm:flex-col sm:justify-start">
        <span className="text-[14px] font-medium">{name}</span>
        <OwnerChip owner={owner} />
      </div>
      <Textarea aria-label={name} value={value} onChange={(e) => onChange(e.target.value)} rows={2}
        className="min-h-[60px] font-serif text-[15px]"
        placeholder={owner === "YOU" ? "Missing: write this in your own words" : owner === "CODE" ? "Filled by code; you may edit" : "From the lab calendar; add any it missed"} />
    </div>
  );
}

export default function TradePlan() {
  const [market] = useMarket();
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const planId = params.get("plan") ? Number(params.get("plan")) : null;
  const setPlanId = (id: number | null) => setParams(id ? { plan: String(id) } : {}, { replace: true });

  const { data: tpl } = useQuery({ queryKey: ["plan-templates"], queryFn: () => get<{ templates: Record<string, { field: string; owner: string }[]> }>("/api/planning/templates") });
  const { data: saved = [] } = useQuery({ queryKey: ["plans", market], queryFn: () => get<PlanRow[]>(`/api/planning/plans?market=${market}`) });
  const [template, setTemplate] = useState("Seven-field plan");
  const [symbolBy, setSymbolBy] = useState<Record<Market, string>>({ IN: "NIFTY FUT", US: "SPY" });

  const { data: plan, error: planErr } = useQuery({
    queryKey: ["plan", planId], enabled: planId !== null,
    queryFn: () => get<PlanOut>(`/api/planning/plans/${planId}`),
  });
  // A plan from the other market does not belong on this screen after a market switch.
  useEffect(() => { if (plan && plan.market !== market) setPlanId(null); /* eslint-disable-next-line */ }, [market, plan?.market]);

  const [draft, setDraft] = useState<Draft | null>(null);
  useEffect(() => { if (plan) setDraft(draftOf(plan)); }, [plan]);
  const dd = useDebounced(draft, 350);
  const { data: live } = useQuery({
    queryKey: ["plan-check", planId, dd], enabled: !!dd && planId !== null, placeholderData: keepPreviousData,
    queryFn: () => post<PlanOut>(`/api/planning/plans/${planId}/check`, dd),
  });
  const cur = live ?? plan;

  const refresh = (p?: PlanOut) => {
    if (p) qc.setQueryData(["plan", p.id], p);
    qc.invalidateQueries({ queryKey: ["plans", market] });
  };
  const create = useMutation({
    mutationFn: () => post<PlanOut>("/api/planning/plans", { template, market, symbol: symbolBy[market] }),
    onSuccess: (p) => { refresh(p); setPlanId(p.id); toast(`Opened plan #${p.id}`); },
  });
  const save = useMutation({
    mutationFn: () => post<PlanOut>(`/api/planning/plans/${planId}/save`, { ...draft, note: "edited" }),
    onSuccess: (p) => { refresh(p); toast(`Saved version ${p.version}`); },
  });
  const sizeIt = useMutation({
    mutationFn: () => post<PlanOut>(`/api/planning/plans/${planId}/save`, { ...draft, note: "sent to sizer" }),
    onSuccess: (p) => { refresh(p); navigate(`/position-sizer?plan=${p.id}`); },
  });
  const journal = useMutation({
    mutationFn: () => post<{ row: number; plan: PlanOut }>(`/api/planning/plans/${planId}/journal`, draft),
    onSuccess: (r) => { refresh(r.plan); toast(`Saved to journal (row ${r.row}), timestamped before the trade`); },
  });
  const paper = useMutation({
    mutationFn: () => post<{ ticket: number; plan: PlanOut }>(`/api/planning/plans/${planId}/paper`, draft),
    onSuccess: (r) => { refresh(r.plan); qc.invalidateQueries({ queryKey: ["paper"] }); toast("Sent to Paper Desk: the ticket is filled in"); },
  });
  const anyErr = create.error ?? save.error ?? sizeIt.error ?? journal.error ?? paper.error;

  const owners = cur?.owners ?? {};
  const check = cur?.check;
  const facts = useMemo(() => cur?.facts ?? [], [cur]);
  const set = (patch: Partial<Draft>) => setDraft((d) => (d ? { ...d, ...patch } : d));

  return (
    <FactsProvider>
      <LocalFacts>
        <div className="flex flex-col gap-5">
          <Panel>
            <div className="flex flex-wrap items-end gap-3">
              <Field label="Plan template">
                <Select value={template} onChange={(e) => setTemplate(e.target.value)} className="w-56 font-sans">
                  {Object.keys(tpl?.templates ?? { "Seven-field plan": [] }).map((t) => <option key={t}>{t}</option>)}
                </Select>
              </Field>
              <TextField label="Symbol" value={symbolBy[market]} className="w-40" onChange={(v) => setSymbolBy((s) => ({ ...s, [market]: v }))} />
              <Button variant="primary" onClick={() => create.mutate()} disabled={create.isPending}><FilePlus2 size={15} /> New plan</Button>
              <div className="ml-auto">
                <Field label="Saved plans">
                  <Select value={planId ?? ""} onChange={(e) => setPlanId(e.target.value ? Number(e.target.value) : null)} className="w-72 font-sans" disabled={!saved.length}>
                    <option value="">{saved.length ? "Choose a saved plan" : "No saved plans yet"}</option>
                    {saved.map((p) => <option key={p.id} value={p.id}>#{p.id} {p.name}, version {p.version}</option>)}
                  </Select>
                </Field>
              </div>
            </div>
            <p className="mt-3 text-[13px] text-muted">A plan is decisions made while the market is closed.</p>
          </Panel>

          {!planId || !draft || !cur ? (
            planErr ? <Callout tone="warn" title="That plan could not be opened">{(planErr as Error).message}</Callout> :
            <EmptyState action={<Button variant="primary" onClick={() => create.mutate()} disabled={create.isPending}><FilePlus2 size={15} /> New plan</Button>}>
              Click <b className="text-ink">New plan</b> to open the plan template. Fill the fields marked <i>You</i> in your own words; leave
              Size empty, because the Position Sizer fills it. Or pick one from Saved plans.
            </EmptyState>
          ) : (
            <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
              <div className="flex min-w-0 flex-col gap-5">
                <Panel title={`Plan #${cur.id}`} action={<span className="text-[13px] text-muted">{cur.template}, {cur.symbol}, version {cur.version}</span>}>
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    <TextField label="Plan name" value={draft.name} onChange={(v) => set({ name: v })} />
                    <Field label="Side">
                      <Segmented label="Side" value={draft.side} options={[{ value: "long", label: "Long" }, { value: "short", label: "Short" }]} onChange={(v) => set({ side: v })} />
                    </Field>
                    <NumField label="Entry / trigger price" value={draft.entry} onChange={(v) => set({ entry: v })} />
                    <NumField label="Stop price" value={draft.stop} onChange={(v) => set({ stop: v })} />
                  </div>
                  {cur.template === "Weekend swing plan" && (
                    <div className="mt-3 max-w-xs">
                      <TextField label="Trigger valid until (date)" placeholder="2026-06-03" value={draft.trigger_expiry} onChange={(v) => set({ trigger_expiry: v })} />
                    </div>
                  )}
                  <div className="mt-4 flex flex-col gap-2">
                    {Object.entries(owners).map(([f, o]) => (
                      <FieldRow key={f} name={f} owner={o} value={draft.fields[f] ?? ""} onChange={(v) => set({ fields: { ...draft.fields, [f]: v } })} />
                    ))}
                  </div>
                  <div className="mt-4 flex flex-wrap gap-2 border-t border-line pt-4">
                    <Button variant="primary" onClick={() => save.mutate()} disabled={save.isPending}><Save size={15} /> Save</Button>
                    <Button onClick={() => sizeIt.mutate()} disabled={sizeIt.isPending}><Scale size={15} /> Size it</Button>
                    <Button onClick={() => journal.mutate()} disabled={journal.isPending}><BookmarkCheck size={15} /> Save to journal</Button>
                    <Button onClick={() => paper.mutate()} disabled={paper.isPending}><Send size={15} /> Send to Paper Desk</Button>
                  </div>
                  <div className="mt-2 min-h-[20px]">
                    <ErrorLine error={anyErr} />
                    {paper.isSuccess && <p className="text-[13px] text-muted">The <Link className="text-indigo underline" to="/paper-desk">Paper Desk</Link> ticket is filled in from this plan. Click Place paper order there; nothing is placed until you do.</p>}
                  </div>
                </Panel>

                <Panel title="Plan version history" action={<span className="text-[13px] text-muted">{cur.versions.length} earlier</span>}>
                  <DataTable
                    rows={[...cur.versions].reverse() as unknown as Record<string, unknown>[]}
                    empty="No earlier versions. Every Save keeps the previous version here."
                    columns={[
                      { key: "version", header: "Version", align: "right", width: "72px" },
                      { key: "saved", header: "Saved", render: (v) => String(v.saved ?? "").replace("T", " ").slice(0, 16) },
                      { key: "entry", header: "Entry", align: "right", render: (v) => (v.entry as number | null)?.toLocaleString() ?? "—" },
                      { key: "stop", header: "Stop", align: "right", render: (v) => (v.stop as number | null)?.toLocaleString() ?? "—" },
                      { key: "qty", header: "Qty", align: "right", render: (v) => String(v.qty ?? "—") },
                      { key: "fields", header: "Fields", render: (v) => (
                        <span className="text-[13px] text-muted">
                          {Object.entries((v.fields as Record<string, string>) ?? {}).filter(([, t]) => t).map(([k, t]) => `${k}: ${t.slice(0, 40)}`).join("; ") || "empty"}
                        </span>) },
                    ]} />
                </Panel>
              </div>

              <div className="flex flex-col gap-4">
                <div className="grid grid-cols-2 gap-2.5">
                  <div className="col-span-2">
                    <LocalTile big label="Missing fields" value={check?.missing.length ?? 0}
                      sub={check?.missing.length ? check.missing.join(", ") : "Every field has words in it"} />
                  </div>
                  <LocalTile label="Vague words" value={check?.vague.length ?? 0} />
                  <LocalTile label="Contradictions" value={check?.contradictions.length ?? 0} />
                  <LocalTile label="Size" value={cur.qty ?? "—"} sub={cur.qty ? "units, from the Position Sizer" : "Click Size it"} />
                  <LocalTile label="Version" value={cur.version} sub={cur.template} />
                </div>
                {check && (check.vague.length > 0 || check.contradictions.length > 0) && (
                  <Callout tone="warn" title="The checklist found">
                    <ul className="list-disc pl-4">
                      {check.contradictions.map((c) => <li key={c}>{c}</li>)}
                      {check.vague.map((v) => <li key={v}>Vague: {v}</li>)}
                    </ul>
                  </Callout>
                )}
                <Panel title="AI sceptic">
                  <p className="mb-3 text-[13px] text-muted">Critique lists gaps, contradictions, unmentioned failure modes and yes/no questions. It reads only this plan's fields; Show sources proves it. It never grades the idea or sizes it.</p>
                  <CitedPanel key={planId} facts={facts} label="Critique" pendingLabel="Critiquing…"
                    run={() => post<Explanation>(`/api/planning/plans/${planId}/critique`, draft)}
                    second={(text) => post<Explanation>(`/api/planning/plans/${planId}/second-opinion`, { ...draft, text })}
                    note="Reads only this plan's fields" />
                </Panel>
                <ul className="flex flex-col gap-1.5 text-[13px] text-muted">
                  <li className="flex items-center gap-2"><OwnerChip owner="YOU" /> You write it, in your own words.</li>
                  <li className="flex items-center gap-2"><OwnerChip owner="CODE" /> The Position Sizer or Alerts fills it.</li>
                  <li className="flex items-center gap-2"><OwnerChip owner="CALENDAR" /> The lab calendar fills it.</li>
                </ul>
              </div>
            </div>
          )}
        </div>
      </LocalFacts>
    </FactsProvider>
  );
}
