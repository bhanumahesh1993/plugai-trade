import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Eye, LayoutTemplate } from "lucide-react";
import { get, post } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button, Field, Panel, inputCls } from "@/components/ui";
import { Badge, Callout, Segmented, Select, useToast } from "@/components/kit";
import { FactTile, FactsProvider } from "@/components/facts";
import { useMarket } from "@/components/shell";
import { DownloadButton, ErrorLine } from "@/components/settings/common";

interface Pv { style: string; markets: string[]; accepted: string[]; groups: { name: string; lines: string[] }[]; facts: string[] }
interface WS {
  styles: string[]; markets: string[]; market_parts: Record<string, string[]>; groups: string[]; briefing_at: Record<string, string>;
  pinned: string[]; template: string | null; preview: Pv | null;
}
const KEY = ["workspace"];
const ZONE: Record<string, string> = { IN: "IST, NSE trading days", US: "ET, NYSE trading days" };
const NOTE: Record<string, string> = {
  "Pinned screens": "Pinned on Home, above the quick links.",
  "Scheduler jobs": "The Scheduler already knows each exchange's holidays.",
  "Rule Card lines": "They arrive as suggestions on Plan & Risk › Rule Card; none is active until you accept it there.",
  "Rhythm reminders": "They appear under Questions for you on the Daily Briefing.",
};

export default function Workspace() {
  const qc = useQueryClient();
  const toast = useToast();
  const [top] = useMarket();
  const { data: w, error } = useQuery({ queryKey: KEY, queryFn: () => get<WS>("/api/settings/workspace") });
  const [style, setStyle] = useState("Swing");
  const [mkt, setMkt] = useState<string>(top);
  const [times, setTimes] = useState<Record<string, string>>({});
  const [show, setShow] = useState(false);
  useEffect(() => { if (w) setTimes(w.briefing_at); }, [w?.briefing_at]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => setMkt(top), [top]);

  const apply = useMutation({
    mutationFn: () => post<Pv>("/api/settings/workspace/preview", { style, market: mkt, times: Object.fromEntries((w?.market_parts[mkt] ?? []).map((m) => [m, times[m]])) }),
    onSuccess: (pv) => { setShow(false); qc.setQueryData<WS>(KEY, (x) => x && { ...x, preview: pv }); toast(`Applied the ${pv.style} template as a preview. Nothing changes until you Accept each group.`); },
  });
  const accept = useMutation({
    mutationFn: (group: string) => post<Pv & { message: string; pinned: string[] }>("/api/settings/workspace/accept", { group }),
    onSuccess: (r) => {
      qc.setQueryData<WS>(KEY, (x) => x && { ...x, preview: r, pinned: r.pinned, template: r.style });
      qc.invalidateQueries({ queryKey: ["wizard-home"] });
      toast(r.message);
    },
  });
  if (error) return <Callout tone="danger" title="Workspace could not load">{(error as Error).message}</Callout>;
  if (!w) return <div className="min-h-[60vh]" aria-busy="true" />;
  const pv = w.preview;
  const count = (g: string) => pv?.groups.find((x) => x.name === g)?.lines.length ?? 0;
  return (
    <FactsProvider>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex min-w-0 flex-col gap-5">
          <p className="text-[13px] text-muted">One reviewed pass from a style template. Nothing changes until you Accept each group.</p>
          <Panel title="Template">
            <div className="flex flex-col gap-4">
              <div className="flex flex-wrap items-end gap-3">
                <Field label="Template"><Select className="w-44 font-sans" value={style} onChange={(e) => setStyle(e.target.value)}>{w.styles.map((s) => <option key={s}>{s}</option>)}</Select></Field>
                <Field label="Market"><Segmented label="Market" value={mkt} options={w.markets.map((m) => ({ value: m, label: m === "IN" ? "India" : m === "US" ? "US" : "Both" }))} onChange={setMkt} /></Field>
              </div>
              <div className="flex flex-wrap gap-3">
                {(w.market_parts[mkt] ?? []).map((m) => (
                  <Field key={m} label={`Daily Briefing time (${ZONE[m]})`}>
                    <input type="time" className={cn(inputCls, "w-36")} value={times[m] ?? ""} onChange={(e) => setTimes({ ...times, [m]: e.target.value })} />
                  </Field>
                ))}
              </div>
              <div className="flex flex-wrap gap-2">
                <Button variant="primary" onClick={() => apply.mutate()} disabled={apply.isPending}><LayoutTemplate size={15} /> Apply template</Button>
                <Button onClick={() => setShow(true)} disabled={!pv || show}><Eye size={15} /> Preview changes</Button>
              </div>
              <ErrorLine error={apply.error} />
            </div>
          </Panel>

          {!pv && <p className="text-muted">Choose a template and click Apply template. Nothing changes until you Accept each group.</p>}
          {pv && !show && <Callout tone="info" title={`${pv.style} template for ${pv.markets.join(" and ")} ready`}>Click Preview changes to see it.</Callout>}
          {pv && show && (
            <div className="grid gap-4 md:grid-cols-2">
              {pv.groups.map((g) => {
                const done = pv.accepted.includes(g.name);
                return (
                  <section key={g.name} className={cn("flex flex-col rounded-[var(--radius-panel)] border bg-panel", done ? "border-indigo/50" : "border-line")}>
                    <header className="flex items-center gap-2 border-b border-line px-4 py-2.5">
                      <h2 className="text-[14px] font-semibold">{g.name}</h2>
                      <span className="num text-[13px] text-muted">{g.lines.length}</span>
                      {done && <Badge tone="indigo" className="ml-auto gap-1"><CheckCircle2 size={12} /> Accepted</Badge>}
                    </header>
                    <ul className="flex-1 list-disc px-4 py-3 pl-8 text-[14px] leading-[1.5]">{g.lines.map((l) => <li key={l}>{l}</li>)}</ul>
                    <div className="flex flex-wrap items-center gap-3 border-t border-line px-4 py-2.5">
                      <Button size="sm" variant={done ? "outline" : "primary"} onClick={() => accept.mutate(g.name)} disabled={done || accept.isPending}>{done ? "Accepted" : "Accept"}</Button>
                      <span className="text-[12px] text-muted">{NOTE[g.name]}</span>
                    </div>
                  </section>
                );
              })}
            </div>
          )}
          <ErrorLine error={accept.error} />

          <Panel title="Export workspace">
            <div className="flex flex-wrap items-center gap-3">
              <DownloadButton path="/api/settings/workspace/export" name="plugai-trade-workspace.json" type="application/json" label="Export workspace" done="Exported the workspace as plugai-trade-workspace.json" />
              <span className="text-[13px] text-muted">Holds settings, schedules and pins: not keys and not your journal. Keep the file with your backups.</span>
            </div>
          </Panel>
        </div>
        <div className="flex flex-col gap-4">
          <FactTile big label="Pinned on Home" value={w.pinned.length} sub={w.template ? `from the ${w.template} template` : "no template accepted yet"} />
          {pv && (
            <div className="grid grid-cols-2 gap-2.5">
              <FactTile label="Scheduler jobs" value={count("Scheduler jobs")} sub="in this preview" />
              <FactTile label="Rule Card lines" value={count("Rule Card lines")} sub="as suggestions" />
            </div>
          )}
          {w.pinned.length > 0 && (
            <div className="rounded-[var(--radius-tile)] border border-line bg-panel p-3.5">
              <div className="mb-2 text-[12px] text-muted">Pinned on Home</div>
              <ul className="flex flex-wrap gap-1.5">{w.pinned.map((p) => <li key={p}><Badge>{p}</Badge></li>)}</ul>
              <Link to="/" className="mt-2 inline-block text-[13px] font-medium text-indigo hover:underline">Open Home</Link>
            </div>
          )}
        </div>
      </div>
    </FactsProvider>
  );
}
