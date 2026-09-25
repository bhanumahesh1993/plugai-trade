/* The four editable rule cards of the Strategy Builder (Chapter 11):
 * ENTRY, EXIT, FILL, SIZE · COST. Amber "assumed" marks show every choice the
 * lab made for you; changing a field (or confirming it) clears its mark. */
import type { ReactNode } from "react";
import { Check } from "lucide-react";
import { cn } from "@/lib/cn";
import { inputCls } from "@/components/ui";
import { Badge, Callout, Select } from "@/components/kit";
import type { RuleCard } from "./shared";

export interface Operand { kind: string; n: number | null; value: number | null }
export interface Condition { op: string; left: Operand; right: Operand }
export interface Spec {
  text: string; mode: string; entry: Condition[]; exit: Condition[]; time_stop: number | null; stop_loss_pct: number | null;
  fill: string; check: string;
  size: { method: string; capital: number | null; target_vol: number; buffer: number; cap: number; borrowing: boolean; vol_lookback: number };
  cost: { profile: string | null; slippage_pct: number | null };
  universe: string[]; lookback_months: number; top_n: number; assumed: string[]; notes: string[];
  origin: string; family: string | null; market: string | null;
}

const KINDS: [string, string][] = [["Close", "close"], ["Simple average", "sma"], ["Exponential average", "ema"],
  ["Prior N-day high", "high_n"], ["Prior N-day low", "low_n"], ["RSI", "rsi"], ["Close N sessions ago", "close_ago"], ["Number", "value"]];
const OPS: [string, string][] = [["is above", "above"], ["is below", "below"], ["first moves above", "cross_above"], ["first moves below", "cross_below"]];
export const CHECKS: [string, string][] = [["Every session", "daily"], ["Weekly (Fridays)", "weekly"], ["Monthly", "monthly"]];
const SIZES: [string, string][] = [["All capital, whole units", "all_capital"], ["Volatility target", "vol_target"]];

/* ------------------------------------------------------------ labels with the amber mark */
function FieldLabel({ text, flags, assumed, onConfirm }: { text: string; flags: string[]; assumed: string[]; onConfirm: (f: string[]) => void }) {
  const on = flags.some((f) => assumed.includes(f));
  return (
    <span className="flex min-h-5 items-center gap-1.5 text-[12px] text-muted">
      {text}
      {on && (
        <>
          <Badge tone="warn">assumed</Badge>
          <button type="button" onClick={() => onConfirm(flags)} title="Keep this value and clear the assumed mark"
            className="inline-flex h-5 items-center gap-0.5 rounded-[4px] px-1 text-[12px] text-indigo hover:bg-indigo-soft">
            <Check size={12} /> Keep
          </button>
        </>
      )}
    </span>
  );
}

function Row({ label, children }: { label: ReactNode; children: ReactNode }) {
  return <div className="flex flex-col gap-1">{label}{children}</div>;
}

function NumberBox({ value, onChange, min, max, step, label }: { value: number | null; onChange: (v: number) => void; min?: number; max?: number; step?: number; label: string }) {
  return (
    <input aria-label={label} type="number" className={inputCls} value={value ?? ""} min={min} max={max} step={step}
      onChange={(e) => onChange(e.target.value === "" ? NaN : Number(e.target.value))} />
  );
}

/* ------------------------------------------------------------ one condition */
function OperandEditor({ op, onChange, flags, assumed, confirm, side }: {
  op: Operand; onChange: (o: Operand) => void; flags: string[]; assumed: string[]; confirm: (f: string[]) => void; side: string;
}) {
  return (
    <>
      <Row label={<FieldLabel text="Measure" flags={flags} assumed={assumed} onConfirm={confirm} />}>
        <Select aria-label={`${side} measure`} value={op.kind} onChange={(e) => {
          const kind = e.target.value;
          onChange(kind === "value" ? { kind, n: null, value: op.value ?? 50 }
            : kind === "close" ? { kind, n: null, value: null } : { kind, n: op.n ?? 20, value: null });
        }}>
          {KINDS.map(([l, v]) => <option key={v} value={v}>{l}</option>)}
        </Select>
      </Row>
      {op.kind === "value" && (
        <Row label={<span className="text-[12px] text-muted">Number</span>}>
          <NumberBox label={`${side} number`} value={op.value} step={1} onChange={(v) => onChange({ ...op, value: v })} />
        </Row>
      )}
      {op.kind !== "value" && op.kind !== "close" && (
        <Row label={<span className="text-[12px] text-muted">Length (sessions)</span>}>
          <NumberBox label={`${side} length`} value={op.n} min={1} max={2000} step={1} onChange={(v) => onChange({ ...op, n: v })} />
        </Row>
      )}
    </>
  );
}

function ConditionEditor({ c, onChange, side, assumed, clear }: {
  c: Condition; onChange: (c: Condition, answered: string[]) => void; side: "entry" | "exit"; assumed: string[]; clear: (f: string[]) => void;
}) {
  const leftFlags = [`${side}.basis`];
  const rightFlags = [`${side}.average`, `${side}.rsi_length`];
  return (
    <div className="flex flex-col gap-2.5">
      <OperandEditor side={`${side} left`} op={c.left} flags={leftFlags} assumed={assumed} confirm={clear}
        onChange={(o) => onChange({ ...c, left: o }, leftFlags)} />
      <Row label={<span className="text-[12px] text-muted">Comparison</span>}>
        <Select aria-label={`${side} comparison`} value={c.op} onChange={(e) => onChange({ ...c, op: e.target.value }, [])}>
          {OPS.map(([l, v]) => <option key={v} value={v}>{l}</option>)}
        </Select>
      </Row>
      <OperandEditor side={`${side} right`} op={c.right} flags={rightFlags} assumed={assumed} confirm={clear}
        onChange={(o) => onChange({ ...c, right: o }, rightFlags)} />
    </div>
  );
}

/* ------------------------------------------------------------ the four cards */
function Card({ title, tag, children }: { title: string; tag?: ReactNode; children: ReactNode }) {
  return (
    <section className="flex min-w-0 flex-col rounded-[var(--radius-panel)] border border-line bg-panel">
      <header className="flex items-center gap-2 border-b border-line px-3.5 py-2.5">
        <h3 className="text-[14px] font-semibold tracking-wide">{title}</h3>
        {tag}
      </header>
      <div className="flex flex-col gap-2.5 p-3.5">{children}</div>
    </section>
  );
}

export function RuleCardsEditor({ spec, cards, onChange, profiles, defaultSlippage }: {
  spec: Spec; cards?: RuleCard[]; onChange: (s: Spec) => void; profiles: string[]; defaultSlippage: number;
}) {
  const a = spec.assumed;
  const clear = (flags: string[]) => {
    if (flags.some((f) => a.includes(f))) onChange({ ...spec, assumed: a.filter((x) => !flags.includes(x)) });
  };
  /** Apply a change and clear the flags it answers, in one update. */
  const set = (patch: Partial<Spec>, flags: string[] = []) =>
    onChange({ ...spec, ...patch, assumed: spec.assumed.filter((x) => !flags.includes(x)) });
  const proposed = spec.origin === "agent" ? <Badge tone="indigo">PROPOSED</Badge> : null;
  const holdWhile = spec.mode === "hold_while";
  const exitEmpty = !spec.exit.length && !spec.time_stop && !spec.stop_loss_pct;
  const profile = spec.cost.profile && profiles.includes(spec.cost.profile) ? spec.cost.profile : profiles[0];

  return (
    <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-4">
      <Card title="ENTRY" tag={<>{holdWhile && <Badge>hold while</Badge>}{proposed}</>}>
        {spec.entry[0] && (
          <ConditionEditor side="entry" c={spec.entry[0]} assumed={a}
            clear={(f) => clear(f)}
            onChange={(c, f) => set({ entry: [c, ...spec.entry.slice(1)] }, f)} />
        )}
        {(cards?.[0]?.lines ?? []).slice(1, spec.entry.length).map(([t], i) => (
          <p key={i} className="text-[13px] text-muted">and {t}</p>
        ))}
      </Card>

      <Card title="EXIT" tag={proposed}>
        {holdWhile ? (
          <p className="text-[13px] text-muted">When the ENTRY condition stops being true.</p>
        ) : (
          <>
            {spec.exit[0] && (
              <ConditionEditor side="exit" c={spec.exit[0]} assumed={a} clear={(f) => clear(f)}
                onChange={(c, f) => set({ exit: [c, ...spec.exit.slice(1)] }, f)} />
            )}
            {(cards?.[1]?.lines ?? []).slice(1, spec.exit.length).map(([t], i) => (
              <p key={i} className="text-[13px] text-muted">or {t}</p>
            ))}
            <Row label={<span className="text-[12px] text-muted">Time stop (sessions, 0 = none)</span>}>
              <NumberBox label="Time stop" value={spec.time_stop ?? 0} min={0} max={2000} step={1}
                onChange={(v) => set({ time_stop: Number.isFinite(v) && v > 0 ? Math.round(v) : null })} />
            </Row>
            {exitEmpty && <Callout tone="warn">EXIT is empty: add a time stop or describe an exit.</Callout>}
          </>
        )}
      </Card>

      <Card title="FILL">
        <Row label={<FieldLabel text="Fill" flags={["fill"]} assumed={a} onConfirm={clear} />}>
          <Select aria-label="Fill" value="next_open" disabled title="A signal is known only after its bar has closed.">
            <option value="next_open">Next session's open</option>
          </Select>
          <span className="text-[12px] text-muted">Cannot be set earlier: a signal is known only after its bar has closed.</span>
        </Row>
        <Row label={<FieldLabel text="Check" flags={["check"]} assumed={a} onConfirm={clear} />}>
          <Select aria-label="Check" value={spec.check} onChange={(e) => set({ check: e.target.value }, ["check"])}>
            {CHECKS.map(([l, v]) => <option key={v} value={v}>{l}</option>)}
          </Select>
        </Row>
        {spec.notes.map((n, i) => <p key={i} className="text-[13px] text-muted">{n}</p>)}
      </Card>

      <Card title="SIZE · COST">
        <Row label={<FieldLabel text="Size" flags={["size.method"]} assumed={a} onConfirm={clear} />}>
          <Select aria-label="Size" value={spec.size.method === "vol_target" ? "vol_target" : "all_capital"}
            onChange={(e) => set({ size: { ...spec.size, method: e.target.value } }, ["size.method"])}>
            {SIZES.map(([l, v]) => <option key={v} value={v}>{l}</option>)}
          </Select>
        </Row>
        {spec.size.method === "vol_target" && (
          <div className="grid grid-cols-2 gap-2.5">
            <Row label={<FieldLabel text="Target volatility % a year" flags={["size.target_vol"]} assumed={a} onConfirm={clear} />}>
              <NumberBox label="Target volatility" value={+(spec.size.target_vol * 100).toFixed(2)} min={1} max={100} step={1}
                onChange={(v) => set({ size: { ...spec.size, target_vol: v / 100 } }, ["size.target_vol"])} />
            </Row>
            <Row label={<FieldLabel text="Buffer %" flags={["size.buffer"]} assumed={a} onConfirm={clear} />}>
              <NumberBox label="Buffer" value={+(spec.size.buffer * 100).toFixed(2)} min={0} max={50} step={1}
                onChange={(v) => set({ size: { ...spec.size, buffer: v / 100 } }, ["size.buffer"])} />
            </Row>
          </div>
        )}
        <Row label={<FieldLabel text="Cost profile" flags={["cost.profile"]} assumed={a} onConfirm={clear} />}>
          <Select aria-label="Cost profile" value={profile}
            onChange={(e) => set({ cost: { ...spec.cost, profile: e.target.value } }, ["cost.profile"])}>
            {profiles.map((p) => <option key={p} value={p}>{p}</option>)}
          </Select>
        </Row>
        <Row label={<FieldLabel text="Slippage % a side" flags={["cost.slippage"]} assumed={a} onConfirm={clear} />}>
          <NumberBox label="Slippage % a side" value={spec.cost.slippage_pct ?? defaultSlippage} min={0} max={2} step={0.01}
            onChange={(v) => set({ cost: { ...spec.cost, slippage_pct: v } }, ["cost.slippage"])} />
        </Row>
      </Card>
    </div>
  );
}

/** The read-only draft: each card's lines with the amber mark on assumed ones. */
export function DraftCards({ cards }: { cards: RuleCard[] }) {
  return (
    <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-4">
      {cards.map((c) => (
        <div key={c.title} className="rounded-[var(--radius-tile)] border border-line bg-panel-2 px-3 py-2.5">
          <div className="text-[13px] font-semibold tracking-wide">{c.title}</div>
          <ul className="mt-1.5 flex flex-col gap-1">
            {c.lines.map(([t, flag], i) => (
              <li key={i} className={cn("flex flex-wrap items-center gap-1.5 text-[14px]")}>
                <span>{t}</span>{flag && <Badge tone="warn">assumed</Badge>}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
