import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { GitCompareArrows, ChevronDown, ChevronRight } from "lucide-react";
import { get } from "@/lib/api";
import { Button, Panel } from "@/components/ui";
import { Callout } from "@/components/kit";
import { FactTile, FactsProvider } from "@/components/facts";
import { useMarket } from "@/components/shell";
import { StatusDot } from "@/components/settings/common";
import { AddKey, CompareSources, FallbackStrip, SourceCard, type DS } from "@/components/settings/data-sources";

export default function DataSources() {
  const [market] = useMarket();
  const [params, setParams] = useSearchParams();
  const view = params.get("view") === "compare" ? "compare" : "sources";
  const setView = (v: string) => setParams(v === "compare" ? { view: "compare" } : {});
  const { data: d, error } = useQuery({ queryKey: ["data-sources", market], queryFn: () => get<DS>(`/api/settings/data-sources?market=${market}`) });
  const [licence, setLicence] = useState(false);

  if (error) return <Callout tone="danger" title="Data Sources could not load">{(error as Error).message}</Callout>;
  if (!d) return <div className="min-h-[60vh]" aria-busy="true" />;
  if (view === "compare") return <FactsProvider><CompareSources d={d} market={market} onBack={() => setView("sources")} /></FactsProvider>;

  return (
    <FactsProvider>
      <div className="flex flex-col gap-5">
        <div className="grid gap-4 lg:grid-cols-[240px_1fr_auto] lg:items-center">
          <FactTile big label="Sources working" value={`${d.working} of ${d.total}`} sub="filled dot = working" />
          <p className="text-[13px] text-muted">
            <span className="mr-3 inline-flex items-center gap-1.5 align-middle"><StatusDot on /> working</span>
            <span className="mr-3 inline-flex items-center gap-1.5 align-middle"><StatusDot on={false} /> not set up</span>
            Synthetic always works offline; the no-signup sources for your market are added automatically. Every bar is tagged with the source that answered.
          </p>
          <Button onClick={() => setView("compare")}><GitCompareArrows size={15} /> Compare sources</Button>
        </div>

        <div className="grid gap-4 lg:grid-cols-3">
          {d.tiers.map((t) => (
            <section key={t.tier} className="flex flex-col gap-2 rounded-[var(--radius-panel)] border border-line bg-panel-2/60 p-3" aria-label={t.tier}>
              <h2 className="px-1 text-[14px] font-semibold">{t.tier}</h2>
              {t.sources.map((s) => <SourceCard key={s.name} s={s} d={d} market={market} />)}
              {t.tier === "Free key" && <AddKey known={d.known_keys} />}
              {t.tier === "Your broker" && (
                <p className="flex items-center gap-2 px-1 pt-1 text-[13px] text-muted"><StatusDot on={false} label="Paid" /> {d.paid_brokers}: paid data plans</p>
              )}
            </section>
          ))}
        </div>

        <Panel title="Fallback strip" action={<span className="text-[12px] text-muted">Drag a source to reorder, or focus it and use the arrow keys</span>}>
          <p className="mb-1 text-[13px] text-muted">The router tries each source from left to right and tags every bar with the one that answered. Dashed sources are not set up yet and are skipped. Indian intraday never falls back to scraping the NSE site.</p>
          {d.strips.map((s) => <FallbackStrip key={s.key} strip={s} />)}
        </Panel>

        <section className="rounded-[var(--radius-panel)] border border-line bg-panel">
          <button type="button" aria-expanded={licence} onClick={() => setLicence(!licence)} className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-[14px] font-semibold">
            {licence ? <ChevronDown size={15} /> : <ChevronRight size={15} />} Provenance and licences
          </button>
          {licence && (
            <div className="flex flex-col gap-2 border-t border-line px-4 py-3 font-serif text-[15px] leading-[1.6]">
              <p><span className="font-semibold">Provenance.</span> {d.licence_note[0]}</p>
              <p><span className="font-semibold">Licences.</span> {d.licence_note[1]}</p>
            </div>
          )}
        </section>
      </div>
    </FactsProvider>
  );
}
