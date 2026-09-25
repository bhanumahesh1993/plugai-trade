/* Building blocks shared by the Journal and Tax screens. */
import { useId, useState, type ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";
import { ChevronRight, Download, Upload } from "lucide-react";
import { get, post } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button, Field, inputCls } from "@/components/ui";
import { Badge, DataTable, Select, type Column } from "@/components/kit";

/* ------------------------------------------------------------ files */
export function readB64(file: File): Promise<string> {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(String(r.result).split(",", 2)[1] ?? "");
    r.onerror = () => rej(new Error("The file could not be read. Choose it again."));
    r.readAsDataURL(file);
  });
}

export function downloadText(name: string, text: string, type = "text/csv") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** A labelled CSV picker that shows the chosen file name. */
export function FilePick({ label, file, onFile, hint }: { label: string; file: File | null; onFile: (f: File | null) => void; hint?: string }) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-[12px] text-muted">{label}</label>
      <div className="flex items-center gap-2">
        <label htmlFor={id} className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-[6px] border border-line-strong bg-panel px-3 text-[14px] font-medium hover:border-indigo hover:text-indigo focus-within:border-indigo">
          <Upload size={14} /> Choose CSV
        </label>
        <input id={id} type="file" accept=".csv,text/csv" className="sr-only" onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
        <span className={cn("min-w-0 truncate text-[13px]", file ? "text-ink" : "text-muted")}>{file ? file.name : "No file chosen"}</span>
      </div>
      {hint && <span className="text-[12px] text-muted">{hint}</span>}
    </div>
  );
}

/* ------------------------------------------------------------ format */
export const hhmm = (iso?: unknown) => (typeof iso === "string" && iso.length >= 16 ? iso.slice(11, 16) : "—");
export const rStr = (x: unknown, digits = 2) =>
  typeof x === "number" ? `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x).toFixed(digits)}R` : "—";
export const plain = (x: unknown, digits = 2) =>
  typeof x === "number" ? x.toLocaleString("en-US", { maximumFractionDigits: digits }).replace(/^-/, "−") : x === null || x === undefined || x === "" ? "—" : String(x);
export const toneOf = (x: unknown) => (typeof x === "number" ? (x > 0 ? "text-bull" : x < 0 ? "text-bear" : "") : "");

/* ------------------------------------------------------------ tags */
const TAG_TONE: Record<string, "indigo" | "warn" | "neutral" | "bear"> = { PAPER: "indigo", REPLAY: "indigo", PILOT: "warn", BLOCKED: "bear", REAL: "neutral" };
export function TagChips({ tags }: { tags?: unknown }) {
  const list = Array.isArray(tags) ? (tags as string[]) : [];
  if (!list.length) return <span className="text-muted">—</span>;
  return <span className="flex flex-wrap gap-1">{list.map((t) => <Badge key={t} tone={TAG_TONE[t] ?? "neutral"}>{t}</Badge>)}</span>;
}
export const splitTags = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

/* ------------------------------------------------------------ disclosure */
export function Disclosure({ summary, children, defaultOpen = false }: { summary: ReactNode; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-[var(--radius-tile)] border border-line">
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-[14px] hover:bg-panel-2">
        <ChevronRight size={15} className={cn("shrink-0 text-muted transition-transform", open && "rotate-90")} />
        <span className="min-w-0 flex-1">{summary}</span>
      </button>
      {open && <div className="border-t border-line p-3">{children}</div>}
    </div>
  );
}

export function QueryBlock({ sql }: { sql: string }) {
  return <pre className="scroll-thin num overflow-x-auto whitespace-pre-wrap rounded-[var(--radius-tile)] border border-line bg-panel-2 p-3 text-[12.5px] leading-relaxed">{sql}</pre>;
}

/* ------------------------------------------------------------ generic rows table */
/** Any engine table (list of dicts) with sentence-case headers; numbers right-aligned. */
export function RowsTable({ rows, empty, cols, headers, amber }: {
  rows: Record<string, unknown>[]; empty?: ReactNode; cols?: string[]; headers?: Record<string, string>; amber?: boolean;
}) {
  const keys = cols ?? Object.keys(rows[0] ?? {});
  const columns: Column<Record<string, unknown>>[] = keys.map((k) => {
    const numeric = rows.some((r) => typeof r[k] === "number");
    return {
      key: k, header: headers?.[k] ?? k.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase()), align: numeric ? "right" : "left",
      render: (r) => {
        const v = r[k];
        if (k === "tags") return <TagChips tags={v} />;
        if (typeof v === "boolean") return v ? "Yes" : "No";
        if (Array.isArray(v)) return v.join(", ");
        return typeof v === "string" && v.length <= 14 ? <span className="whitespace-nowrap">{v}</span> : plain(v);
      },
    };
  });
  return (
    <div className={cn(amber && rows.length > 0 && "rounded-[var(--radius-tile)] border border-saffron/40 bg-saffron/10 p-2")}>
      <DataTable rows={rows} columns={columns} empty={empty} />
    </div>
  );
}

/* ------------------------------------------------------------ import form */
interface Cols { columns: string[]; guess: Record<string, string> }
export interface ImportArgs { broker: string; account: string; file_b64: string; mapping?: Record<string, string> }

/** Broker, account, file and (for Generic CSV) the column mapper. Parent runs the import. */
export function ImportForm({ brokers, brokerLabel = "Broker", accountDefault, fileLabel, fields = [], required = [], onImport, pending, submitLabel = "Import tradebook", children, templateLink }: {
  brokers: string[]; brokerLabel?: string; accountDefault: string; fileLabel: string; fields?: string[]; required?: string[];
  onImport: (a: ImportArgs) => void; pending?: boolean; submitLabel?: string; children?: ReactNode; templateLink?: boolean;
}) {
  const [broker, setBroker] = useState(brokers[0] ?? "");
  const [account, setAccount] = useState(accountDefault);
  const [file, setFile] = useState<File | null>(null);
  const [b64, setB64] = useState("");
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const cols = useMutation({
    mutationFn: (file_b64: string) => post<Cols>("/api/journal/columns", { file_b64 }),
    onSuccess: (c) => setMapping(c.guess),
  });
  const pick = async (f: File | null) => {
    setFile(f);
    if (!f) { setB64(""); return; }
    const s = await readB64(f);
    setB64(s);
    if (broker === "Generic CSV") cols.mutate(s);
  };
  const generic = broker === "Generic CSV";
  return (
    <div className="flex max-w-[920px] flex-col gap-3.5">
      <div className="grid gap-3 md:grid-cols-2">
        <Field label={brokerLabel}>
          <Select value={broker} onChange={(e) => { setBroker(e.target.value); if (e.target.value === "Generic CSV" && b64) cols.mutate(b64); }}>
            {brokers.map((b) => <option key={b}>{b}</option>)}
          </Select>
        </Field>
        <Field label="Account name">
          <input className={inputCls} value={account} onChange={(e) => setAccount(e.target.value)} />
        </Field>
      </div>
      <FilePick label={fileLabel} file={file} onFile={pick} />
      {generic && b64 && cols.data && (
        <div className="rounded-[var(--radius-tile)] border border-line bg-panel-2 p-3">
          <p className="mb-2 text-[13px] text-muted">Generic CSV: map your columns ({required.join(", ")} are required).</p>
          <div className="grid grid-cols-2 gap-2.5 md:grid-cols-5">
            {fields.map((f) => (
              <Field key={f} label={required.includes(f) ? `${f} (required)` : f}>
                <Select value={mapping[f] ?? ""} onChange={(e) => setMapping({ ...mapping, [f]: e.target.value })}>
                  <option value="">—</option>
                  {cols.data.columns.map((c) => <option key={c}>{c}</option>)}
                </Select>
              </Field>
            ))}
          </div>
        </div>
      )}
      {cols.error && <p className="text-[13px] text-bear">{(cols.error as Error).message}</p>}
      {children}
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary" disabled={!b64 || pending}
          onClick={() => onImport({ broker, account, file_b64: b64, mapping: generic ? mapping : undefined })}>
          {pending ? "Importing…" : submitLabel}
        </Button>
        {templateLink && <TemplateButton />}
      </div>
    </div>
  );
}

export function TemplateButton() {
  const t = useMutation({
    mutationFn: () => get<{ filename: string; csv: string }>("/api/journal/template"),
    onSuccess: (d) => downloadText(d.filename, d.csv),
  });
  return <Button variant="quiet" onClick={() => t.mutate()}><Download size={14} /> Generic CSV template</Button>;
}

/* ------------------------------------------------------------ mismatches */
export interface Rec { matched: number; mismatches: Record<string, unknown>[]; facts: string[]; left: string; right: string }
export function MismatchTable({ rec, onExplain }: { rec: Rec; onExplain?: (row: Record<string, unknown>) => void }) {
  if (!rec.mismatches.length) return <p className="text-[14px] text-bull">All {rec.matched} rows matched.</p>;
  const cols = ["side", "date", "security", "amount", "other_amount", "reason"];
  const columns: Column<Record<string, unknown>>[] = [
    ...cols.map((k) => ({ key: k, header: k === "other_amount" ? "Other side" : k.replace(/^./, (c) => c.toUpperCase()),
      align: (k.includes("amount") ? "right" : "left") as "left" | "right", render: (r: Record<string, unknown>) => plain(r[k]) })),
    ...(onExplain ? [{ key: "_x", header: "", render: (r: Record<string, unknown>) => <Button size="sm" variant="quiet" onClick={() => onExplain(r)}>Explain</Button> }] : []),
  ];
  return (
    <div className="flex flex-col gap-2">
      <p className="text-[14px]"><span className="font-semibold text-saffron">{rec.mismatches.length} mismatches</span><span className="text-muted">, {rec.matched} matched</span></p>
      <div className="rounded-[var(--radius-tile)] border border-saffron/40 bg-saffron/10 p-2">
        <DataTable rows={rec.mismatches} columns={columns} />
      </div>
    </div>
  );
}
