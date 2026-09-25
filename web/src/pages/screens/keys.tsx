import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Plus, ShieldCheck, Trash2, Ban } from "lucide-react";
import { get, post } from "@/lib/api";
import { Button, Field, Panel } from "@/components/ui";
import { Callout, DataTable, Dialog, EmptyState, Select, useToast } from "@/components/kit";
import { FactTile, FactsProvider } from "@/components/facts";
import { ErrorLine, Tick, TextInput } from "@/components/settings/common";

interface KeysState { keychain_ok: boolean; keys: { name: string; masked: string }[]; known: string[]; permissions: string[] }
const OTHER = "Other…";
const KEY = ["keys"];

function AddForm({ s, onDone }: { s: KeysState; onDone: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [choice, setChoice] = useState(s.known[0]);
  const [custom, setCustom] = useState("");
  const [value, setValue] = useState("");
  const [perms, setPerms] = useState<string[]>(["read"]);
  const name = choice === OTHER ? custom.trim().toLowerCase().replace(/ /g, "_") : choice;
  const save = useMutation({
    mutationFn: () => post<{ name: string; masked: string }>("/api/settings/keys", { name, value, permissions: perms }),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: KEY }); qc.invalidateQueries({ queryKey: ["ai-models"] }); qc.invalidateQueries({ queryKey: ["data-sources"] }); toast(`Saved ${r.name} ${r.masked} to the OS keychain`); onDone(); },
  });
  const risky = perms.filter((p) => p !== "read");
  return (
    <Panel title="Add key">
      <div className="flex max-w-[640px] flex-col gap-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Key"><Select className="font-sans" value={choice} onChange={(e) => setChoice(e.target.value)}>{[...s.known, OTHER].map((k) => <option key={k}>{k}</option>)}</Select></Field>
          {choice === OTHER && <TextInput label="Key name" value={custom} onChange={setCustom} placeholder="my_provider_api_key" />}
        </div>
        <TextInput label="Value" type="password" value={value} onChange={setValue} hint="Paste it here only, never into a chatbot or a file." />
        <fieldset>
          <legend className="text-[12px] text-muted">Permissions this key has (for exchange keys, tick exactly what the provider's page shows)</legend>
          <div className="mt-1 flex flex-wrap gap-x-5">
            {s.permissions.map((p) => <Tick key={p} checked={perms.includes(p)} onChange={(v) => setPerms(v ? [...perms, p] : perms.filter((x) => x !== p))}><span className="capitalize">{p}</span></Tick>)}
          </div>
        </fieldset>
        {risky.length > 0 && (
          <Callout tone="danger" title="This key will be refused">
            It allows {risky.join(", ")}. PlugAI-Trade only needs read-only keys. Create a read-only key on the provider's site instead.
          </Callout>
        )}
        <div className="flex gap-2">
          <Button variant="primary" onClick={() => save.mutate()} disabled={save.isPending || !name || !value.trim()}><KeyRound size={14} /> Save</Button>
          <Button variant="quiet" onClick={onDone}>Cancel</Button>
        </div>
        <ErrorLine error={save.error} />
      </div>
    </Panel>
  );
}

export default function Keys() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: s, error } = useQuery({ queryKey: KEY, queryFn: () => get<KeysState>("/api/settings/keys") });
  const [adding, setAdding] = useState(false);
  const [confirm, setConfirm] = useState<string | null>(null);
  const rm = useMutation({
    mutationFn: (n: string) => post(`/api/settings/keys/${encodeURIComponent(n)}/remove`),
    onSuccess: (_r, n) => { setConfirm(null); qc.invalidateQueries({ queryKey: KEY }); toast(`Removed ${n} from the keychain`); },
  });
  if (error) return <Callout tone="danger" title="Keys could not load">{(error as Error).message}</Callout>;
  return (
    <FactsProvider>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex min-w-0 flex-col gap-5">
          {s && !s.keychain_ok && <Callout tone="danger" title="No OS keychain found">Keys cannot be saved on this machine. On Linux, install and unlock GNOME Keyring or KWallet, then restart the lab.</Callout>}
          <Panel title="Stored keys" action={!adding && <Button size="sm" variant="primary" onClick={() => setAdding(true)}><Plus size={14} /> Add key</Button>}>
            {s && (s.keys.length === 0 ? (
              <EmptyState action={!adding && <Button size="sm" onClick={() => setAdding(true)}><Plus size={14} /> Add key</Button>}>No keys saved yet. Everything in the lab works without them.</EmptyState>
            ) : (
              <DataTable rows={s.keys} rowKey={(r) => r.name} columns={[
                { key: "name", header: "Key", render: (r) => <span className="font-medium">{r.name}</span> },
                { key: "masked", header: "Value", render: (r) => <span className="num text-muted">{r.masked}</span> },
                { key: "x", header: "", align: "right", render: (r) => <Button size="sm" variant="quiet" onClick={() => setConfirm(r.name)}><Trash2 size={13} /> Remove</Button> },
              ]} />
            ))}
          </Panel>
          {adding && s && <AddForm s={s} onDone={() => setAdding(false)} />}
        </div>
        <div className="flex flex-col gap-4">
          <FactTile big label="Keys in the keychain" value={s ? s.keys.length : "—"} sub="only the last four characters are shown" />
          <div className="flex flex-col gap-3 rounded-[var(--radius-tile)] border border-line bg-panel p-3.5 text-[13px] leading-[1.5]">
            <p className="flex gap-2"><ShieldCheck size={16} className="mt-0.5 shrink-0 text-indigo" />Stored in your operating system's keychain (Keychain on macOS, Credential Manager on Windows, Secret Service on Linux), never in files or chats. Backups never include keys.</p>
            <p className="flex gap-2"><Ban size={16} className="mt-0.5 shrink-0 text-bear" />Exchange keys with trade, withdraw or transfer permission are refused: PlugAI-Trade only reads.</p>
          </div>
        </div>
      </div>
      <Dialog open={confirm !== null} onOpenChange={(v) => !v && setConfirm(null)} title={`Remove ${confirm}?`}
        footer={<><Button onClick={() => setConfirm(null)}>Keep the key</Button><Button variant="danger" onClick={() => confirm && rm.mutate(confirm)} disabled={rm.isPending}><Trash2 size={14} /> Remove from keychain</Button></>}>
        <p>The key is deleted from your OS keychain. Screens that use it fall back to the next source or the local model.</p>
        <ErrorLine error={rm.error} />
      </Dialog>
    </FactsProvider>
  );
}
