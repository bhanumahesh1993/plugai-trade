import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "@/lib/api";
import { Button } from "@/components/ui";
import { Badge, Callout, useToast } from "@/components/kit";
import { useMarket } from "@/components/shell";
import { LocalFactsProvider, LocalOnly } from "@/components/journal/local";
import { Disclosure, ImportForm, RowsTable, type ImportArgs } from "@/components/journal/common";
import { IndiaTax } from "@/components/journal/tax-india";
import { UsTax } from "@/components/journal/tax-us";

interface State {
  market: "IN" | "US"; rows: number; draft: string; as_of: string; reference_as_of: string; brokers: string[]; samples: string[];
  account_default: string; preview: Record<string, unknown>[]; classified: boolean; fys: string[]; accounts: Record<string, string>;
  account_types: string[]; crypto_default: boolean; loss_buckets: string[]; account_names: string[];
}
interface Meta { generic_fields: string[]; generic_required: string[] }

export default function TaxExport() {
  const [m] = useMarket();
  const qc = useQueryClient();
  const toast = useToast();
  const [version, setVersion] = useState(0);
  const { data: st } = useQuery({ queryKey: ["tax-state", m], queryFn: () => get<State>(`/api/tax/state?market=${m}`) });
  const { data: meta } = useQuery({ queryKey: ["journal-meta", m], queryFn: () => get<Meta>(`/api/journal/meta?market=${m}`) });
  const changed = (s: State, msg: string) => {
    qc.setQueryData(["tax-state", m], s);
    for (const k of ["tax-classified", "tax-turnover", "tax-8949", "tax-1256"]) qc.removeQueries({ queryKey: [k] });
    setVersion((v) => v + 1);
    toast(msg);
  };
  const imp = useMutation({
    mutationFn: (a: ImportArgs) => post<{ added: number; broker: string; state: State }>("/api/tax/import", { market: m, ...a }),
    onSuccess: (d) => changed(d.state, `${d.added} round trips added from ${d.broker}`),
  });
  const useJournal = useMutation({ mutationFn: () => post<State>(`/api/tax/use-journal?market=${m}`), onSuccess: (s) => changed(s, `Using ${s.rows} Journal › Trades rows`) });
  const sample = useMutation({ mutationFn: (name: string) => post<State>("/api/tax/sample", { market: m, name }), onSuccess: (s) => changed(s, `Lesson sample loaded: ${s.rows} round trips`) });
  const clear = useMutation({ mutationFn: () => post<State>(`/api/tax/clear?market=${m}`), onSuccess: (s) => changed(s, "Rows cleared") });
  const err = (imp.error || useJournal.error || sample.error || clear.error) as Error | null;

  return (
    <LocalFactsProvider>
      <div className="flex flex-col gap-5">
        <Callout tone="warn" title="Draft for your CA / CPA">
          PlugAI-Trade sorts and adds up; it does not tell you how to file. Rows marked ASK CA are never guessed.
        </Callout>

        <Disclosure key={`${m}-${st?.rows ? "has" : "none"}`} defaultOpen={!st?.rows} summary={
          <span className="flex flex-wrap items-center gap-2"><span className="font-semibold">Import tradebook</span>
            {st && <span className="num text-[13px] text-muted">{st.rows} round trips loaded</span>}</span>}>
          <div className="flex flex-col gap-4">
            {st && meta && (
              <ImportForm key={m} brokers={st.brokers} brokerLabel="Broker or exchange" accountDefault={st.account_default}
                fileLabel="Tradebook / trade history CSV" fields={meta.generic_fields} required={meta.generic_required}
                pending={imp.isPending} onImport={(a) => imp.mutate(a)} />
            )}
            <div className="flex flex-wrap gap-2 border-t border-line pt-4">
              <Button onClick={() => useJournal.mutate()} disabled={useJournal.isPending}>Use Journal › Trades rows</Button>
              {st?.samples.map((s) => (
                <Button key={s} onClick={() => sample.mutate(s)} disabled={sample.isPending}>Load lesson sample ({s}, synthetic)</Button>
              ))}
              {!!st?.rows && <Button variant="danger" onClick={() => clear.mutate()}>Clear rows</Button>}
            </div>
            {!!st?.preview.length && (
              <Disclosure summary={`Loaded rows (${st.rows})`}>
                <div className="max-h-[300px] overflow-y-auto scroll-thin"><RowsTable rows={st.preview} headers={{ trade_id: "Row" }} /></div>
              </Disclosure>
            )}
          </div>
        </Disclosure>
        {err && <p className="text-[13px] text-bear">{err.message}</p>}

        {st && (
          <div className="flex flex-wrap items-center gap-2 text-[13px] text-muted">
            <Badge tone={m === "IN" ? "in" : "us"}>{m === "IN" ? "India" : "US"}</Badge>
            <span className="num">{st.rows} round trips loaded; rates and rules from the dated table, as of {st.as_of}.</span>
            <LocalOnly />
            <span>As of {st.reference_as_of}; live values in Derivatives › Contract Table.</span>
          </div>
        )}

        <section className="rounded-[var(--radius-panel)] border border-line bg-panel p-4">
          {m === "IN" ? <IndiaTax key={version} st={st} /> : <UsTax key={version} st={st} />}
        </section>
        <p className="text-[13px] text-muted">Every sheet is a {st?.draft ?? "Draft for your CA / CPA"}.</p>
      </div>
    </LocalFactsProvider>
  );
}
