"""India: four buckets, ICAI turnover, audit check, carry-forward, advance tax, AIS, ITR CSV.

Every rate and threshold comes from ``tax.rates`` (the dated reference). Rows the rules
cannot place are marked ASK CA, never guessed. Every output is a *Draft for your CA / CPA*.
"""

from __future__ import annotations

import csv
import io
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

import polars as pl

from ..journal.detectors import simulated_mask
from ..store import default as store
from . import rates
from .reconcile import Reconciliation, normalise, reconcile

DRAFT = "Draft for your CA / CPA"
ASK_CA = "ASK CA"
SPECULATIVE, NON_SPECULATIVE, STCG, LTCG, VDA = ("SPECULATIVE", "NON_SPECULATIVE", "STCG",
                                                 "LTCG", "VDA")
BUCKET_NAMES = {SPECULATIVE: "Speculative business (intraday equity)",
                NON_SPECULATIVE: "Non-speculative business (F&O)", STCG: "STCG", LTCG: "LTCG",
                VDA: "Virtual digital asset (VDA)", ASK_CA: ASK_CA}

#: What it covers → (1961 Act, FY 2025-26 returns) → (Income-tax Act 2025, tax year 2026-27 on).
#: As printed in Chapter 32 (Sep 2026); cross-check against the bare Act.
SECTION_MAP: tuple[tuple[str, str, str], ...] = (
    ("STCG on listed equity, STT paid", "s.111A", "s.196"),
    ("LTCG on listed equity, STT paid", "s.112A", "s.198"),
    ("Speculation business kept separate", "s.28 Expl. 2, s.43(5)", "s.26(3); s.66(31), (33)"),
    ("Speculation loss set-off, carry-forward", "s.73", "s.113"),
    ("Business loss carry-forward", "s.72", "s.112"),
    ("Capital loss carry-forward", "s.74", "s.111"),
    ("Presumptive taxation", "s.44AD", "s.58"),
    ("Tax audit", "s.44AB", "s.63"),
    ("VDA income", "s.115BBH", "s.194(1), Table Sl. 4"),
    ("TDS on VDA transfer", "s.194S", "s.393(1), Table Sl. 8(vi)"),
    ("Advance tax instalments", "s.211", "s.408"),
    ("Return due dates", "s.139(1)", "s.263(1)"),
)
_BUCKET_SECTIONS = {
    SPECULATIVE: ("s.43(5); loss s.73", "s.66(31), s.26(3); loss s.113"),
    NON_SPECULATIVE: ("loss s.72", "loss s.112"),
    STCG: ("s.111A", "s.196"), LTCG: ("s.112A", "s.198"),
    VDA: ("s.115BBH", "s.194(1)"), ASK_CA: ("", ""),
}


def section_map() -> pl.DataFrame:
    """The old ↔ new section-number table (Chapter 32)."""
    return pl.DataFrame(list(SECTION_MAP), schema=["What it covers", "1961 Act (FY 2025-26)",
                                                   "2025 Act (tax year 2026-27 on)"], orient="row")


def translate(section: str) -> list[tuple[str, str, str]]:
    """Look up an old or new section number (e.g. '44AD' or 's.58') in the map."""
    key = section.lower().replace("section", "").replace("s.", "").strip()
    return [row for row in SECTION_MAP
            if any(key == part.strip().lower().replace("s.", "").split(" ")[0]
                   for col in row[1:] for part in col.replace(";", ",").split(","))]


def fy_of(d: date | datetime | str) -> str:
    """Indian tax year label (April–March), e.g. 2026-02-10 → '2025-26'."""
    d = date.fromisoformat(str(d)[:10])
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def _add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    day = min(d.day, [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28, 31, 30, 31,
                      30, 31, 31, 30, 31, 30, 31][m - 1])
    return date(y, m, day)


def _rule(r: dict) -> tuple[str, str]:
    """(bucket, reason) for one round trip."""
    inst = (r.get("instrument") or "").upper()
    if (r.get("market") or "IN") != "IN":
        return ASK_CA, "foreign market row: the Indian buckets need a CA's view"
    if inst == "CRYPTO":
        return VDA, "crypto / token → virtual digital asset"
    if inst in ("FUT", "CE", "PE"):
        return NON_SPECULATIVE, "exchange-traded derivative (F&O) → non-speculative business"
    if inst == "EQ":
        d_in, d_out = r["entry_time"].date(), r["exit_time"].date()
        if d_in == d_out:
            return SPECULATIVE, "same-day equity, no delivery → speculative business"
        if r.get("side") == "SHORT":
            return ASK_CA, "equity short held overnight: unusual, rules cannot place it"
        months = int(rates.get("india.tax.ltcg_months"))
        if d_out <= _add_months(d_in, months):
            return STCG, f"delivery equity held {(d_out - d_in).days} days (≤ {months} months)"
        return LTCG, f"delivery equity held {(d_out - d_in).days} days (> {months} months)"
    return ASK_CA, f"instrument {inst or 'unknown'}: the rules cannot place this row"


@dataclass
class Classified:
    """Round trips with a bucket, the rule that put them there, and section numbers."""

    rows: pl.DataFrame
    excluded_simulated: int = 0

    def counts(self) -> dict[str, int]:
        return {b: int(n) for b, n in self.rows.group_by("bucket").len().iter_rows()} \
            if self.rows.height else {}

    def facts(self) -> list[str]:
        out = [f"Rows classified: {self.rows.height}",
               f"Simulated rows left out (PAPER / REPLAY / BLOCKED): {self.excluded_simulated}"]
        for b, n in sorted(self.counts().items()):
            out.append(f"{BUCKET_NAMES.get(b, b)}: {n} rows")
        return out + [f"Stamp: {DRAFT}"]


def classify(trades: pl.DataFrame) -> Classified:
    """Classify: speculative / non-speculative F&O / STCG / LTCG / VDA, or ASK CA."""
    if trades.is_empty():
        return Classified(trades.with_columns(
            [pl.lit(None, pl.Utf8).alias(c) for c in ("bucket", "rule", "section_old",
                                                     "section_new", "fy")]
            + [pl.lit(None, pl.Boolean).alias("ask_ca")]))
    sim = trades.filter(simulated_mask()).height
    real = trades.filter(~simulated_mask())
    buckets, reasons = [], []
    for r in real.iter_rows(named=True):
        b, why = _rule(r)
        buckets.append(b)
        reasons.append(why)
    out = real.with_columns(bucket=pl.Series(buckets, dtype=pl.Utf8),
                            rule=pl.Series(reasons, dtype=pl.Utf8))
    return Classified(out.with_columns(
        section_old=pl.col("bucket").replace_strict(
            {k: v[0] for k, v in _BUCKET_SECTIONS.items()}, default=""),
        section_new=pl.col("bucket").replace_strict(
            {k: v[1] for k, v in _BUCKET_SECTIONS.items()}, default=""),
        ask_ca=pl.col("bucket") == ASK_CA,
        fy=pl.col("exit_time").dt.strftime("%Y-%m-%d").map_elements(fy_of, return_dtype=pl.Utf8),
    ), sim)


# ------------------------------------------------------------------ turnover
@dataclass
class Turnover:
    """ICAI turnover (Σ |P&L| per trade) with the per-contract view and the wrong answers."""

    per_trade: pl.DataFrame
    fo: dict[str, float]
    speculative: dict[str, float]
    per_contract_fo: float
    old_method_fo: float
    notional_fo: float
    presumptive_rate: float

    @property
    def deemed_profit(self) -> float:
        """Presumptive (s.44AD / s.58) deemed profit on the F&O turnover."""
        return round(self.fo["turnover"] * self.presumptive_rate, 2)

    def annualised(self, months: int = 12) -> float:
        return round(self.fo["turnover"] * months, 2)

    def facts(self) -> list[str]:
        f, s = self.fo, self.speculative
        return [
            f"F&O round trips: {int(f['trades'])}; net result ₹{f['net']:,.2f}",
            f"F&O gains ₹{f['gains']:,.2f}; losses ₹{f['losses']:,.2f}",
            f"F&O turnover (ICAI, Σ |P&L| per trade): ₹{f['turnover']:,.2f}",
            f"Per-contract view: ₹{self.per_contract_fo:,.2f}",
            f"Pre-2022 method (adds premium received on option sales): ₹{self.old_method_fo:,.2f}",
            f"Notional contract value (NOT turnover): ₹{self.notional_fo:,.2f}",
            f"Speculative (intraday equity) turnover, kept separate: ₹{s['turnover']:,.2f}",
            f"{self.presumptive_rate * 100:g}% of F&O turnover (s.44AD / s.58 deemed profit): "
            f"₹{self.deemed_profit:,.2f}",
        ]


def _sums(df: pl.DataFrame) -> dict[str, float]:
    if df.is_empty():
        return {"trades": 0, "gains": 0.0, "losses": 0.0, "net": 0.0, "turnover": 0.0}
    p = df["pnl"]
    return {"trades": df.height, "gains": round(float(p.filter(p > 0).sum()), 2),
            "losses": round(float(-p.filter(p < 0).sum()), 2), "net": round(float(p.sum()), 2),
            "turnover": round(float(p.abs().sum()), 2)}


def turnover(classified: Classified | pl.DataFrame, use: str = "gross") -> Turnover:
    """Turnover calculator. ``use='gross'`` (before charges, as the book's example) or 'net'."""
    rows = classified.rows if isinstance(classified, Classified) else classify(classified).rows
    t = rows.filter(pl.col("bucket").is_in([NON_SPECULATIVE, SPECULATIVE])).with_columns(
        pnl=pl.col(use), abs_pnl=pl.col(use).abs(),
        premium_received=pl.when((pl.col("side") == "SHORT")
                                 & pl.col("instrument").is_in(["CE", "PE"]))
        .then(pl.col("entry_price") * pl.col("qty") * pl.col("multiplier")).otherwise(0.0),
        notional=(pl.col("entry_price") + pl.col("exit_price")) * pl.col("qty")
        * pl.col("multiplier"),
    ) if rows.height else pl.DataFrame(schema={"bucket": pl.Utf8, "pnl": pl.Float64})
    fo = t.filter(pl.col("bucket") == NON_SPECULATIVE) if t.height else t
    spec = t.filter(pl.col("bucket") == SPECULATIVE) if t.height else t
    fo_s = _sums(fo)
    per_contract = round(float(fo.group_by("symbol").agg(pl.col("pnl").sum())["pnl"].abs().sum()),
                         2) if fo.height else 0.0
    old = round(fo_s["turnover"] + (float(fo["premium_received"].sum()) if fo.height else 0.0), 2)
    notional = round(float(fo["notional"].sum()), 2) if fo.height else 0.0
    per_trade = t.select("trade_id", "date", "symbol", "side", "qty", "entry_price",
                         "exit_price", "bucket", "pnl", "abs_pnl") if t.height else t
    return Turnover(per_trade, fo_s, _sums(spec), per_contract, old, notional,
                    float(rates.get("india.tax.presumptive_rate_digital")))


# ------------------------------------------------------------------ audit & presumptive
@dataclass
class AuditCheck:
    turnover: float
    status: str
    detail: str
    lock_in: str

    def facts(self) -> list[str]:
        return [f"Turnover tested: ₹{self.turnover:,.2f}", f"Audit check: {self.status}",
                self.detail, f"s.58 / 44AD: {self.lock_in}", f"Stamp: {DRAFT}"]


def audit_check(turnover_inr: float, cash_share_ok: bool = True,
                presumptive_opted_fy: str | None = None, current_fy: str | None = None,
                declared_profit: float | None = None, deemed_profit: float | None = None
                ) -> AuditCheck:
    """Turnover test against the dated thresholds, plus the presumptive lock-in note."""
    low = float(rates.get("india.tax.audit_threshold_inr"))
    high = float(rates.get("india.tax.audit_threshold_digital_inr"))
    if turnover_inr <= low:
        status, detail = "Below limit", f"≤ ₹{low:,.0f}: no audit on turnover grounds"
    elif turnover_inr <= high and cash_share_ok:
        status, detail = "Below limit", (f"≤ ₹{high:,.0f} with cash ≤ 5% (online trading): "
                                         "no audit on turnover grounds")
    else:
        status, detail = "Audit likely", "above the turnover limits: talk to your CA"
    lock = "Not opted"
    if presumptive_opted_fy:
        years = int(rates.get("india.tax.presumptive_lock_in_years"))
        start = int(presumptive_opted_fy[:4])
        cur = int((current_fy or fy_of(date.today()))[:4])
        if cur - start <= years:
            lock = f"opted in FY {presumptive_opted_fy}: locked in for {years} years"
            if declared_profit is not None and deemed_profit is not None \
                    and declared_profit < deemed_profit:
                lock += (" — declaring below the deemed profit now exits the scheme for "
                         f"{years} years, with an audit if income is above the exemption "
                         "limit (ASK CA)")
                status = "Audit likely (lock-in)"
        else:
            lock = f"opted in FY {presumptive_opted_fy}: lock-in window has passed"
    return AuditCheck(turnover_inr, status, detail, lock)


def presumptive_note(t: Turnover) -> str:
    """The Chapter 32 trap, in numbers computed here."""
    return (f"Opting in would mean declaring a profit of ₹{t.deemed_profit:,.2f} "
            f"({t.presumptive_rate * 100:g}% of turnover) on a result of ₹{t.fo['net']:,.2f}. "
            "Whether s.44AD / s.58 suits you is a question for your CA.")


# ------------------------------------------------------------------ carry-forward
LOSS_BUCKETS = (SPECULATIVE, NON_SPECULATIVE, "STCL", "LTCL")
_ABSORBS = {SPECULATIVE: (SPECULATIVE, NON_SPECULATIVE), NON_SPECULATIVE: (NON_SPECULATIVE,),
            STCG: ("STCL",), LTCG: ("LTCL", "STCL")}


@dataclass
class LossEntry:
    fy: str
    bucket: str
    amount: float
    used: float = 0.0
    filed_on_time: bool = True

    @property
    def expires(self) -> str:
        years = rates.carry_forward_years(self.bucket) or 0
        start = int(self.fy[:4]) + years
        return f"{start}-{str(start + 1)[-2:]}"

    @property
    def left(self) -> float:
        return round(self.amount - self.used, 2)


@dataclass
class CarryForwardLedger:
    """One line per year per bucket: amount, expiry year, amount used since."""

    entries: list[LossEntry] = field(default_factory=list)

    def add(self, fy: str, bucket: str, amount: float, filed_on_time: bool = True) -> LossEntry:
        if bucket == VDA:
            raise ValueError("A VDA loss cannot be set off or carried forward.")
        if bucket not in LOSS_BUCKETS:
            raise ValueError(f"Bucket must be one of {LOSS_BUCKETS}")
        e = LossEntry(fy, bucket, round(abs(amount), 2), 0.0, filed_on_time)
        self.entries.append(e)
        return e

    def apply(self, fy: str, profit_bucket: str, profit: float) -> list[tuple[LossEntry, float]]:
        """Set brought-forward losses against a profit, oldest first; returns what was used."""
        used, remaining = [], profit
        for e in sorted(self.entries, key=lambda x: x.fy):
            if remaining <= 0:
                break
            if e.bucket not in _ABSORBS.get(profit_bucket, ()) or not e.filed_on_time:
                continue
            if not (e.fy < fy <= e.expires) or e.left <= 0:
                continue
            take = min(e.left, remaining)
            e.used = round(e.used + take, 2)
            remaining -= take
            used.append((e, take))
        return used

    def rows(self) -> pl.DataFrame:
        recs = [{"fy": e.fy, "bucket": e.bucket, "amount": e.amount, "used": e.used,
                 "left": e.left, "expires_after_fy": e.expires,
                 "note": "" if e.filed_on_time else f"{ASK_CA}: return filed late — the loss may "
                                                    "not carry forward"} for e in self.entries]
        return pl.DataFrame(recs, schema={"fy": pl.Utf8, "bucket": pl.Utf8, "amount": pl.Float64,
                                          "used": pl.Float64, "left": pl.Float64,
                                          "expires_after_fy": pl.Utf8, "note": pl.Utf8})

    def facts(self) -> list[str]:
        return [f"{e.fy} {e.bucket}: ₹{e.amount:,.2f}, used ₹{e.used:,.2f}, carries to FY "
                f"{e.expires}" for e in self.entries] + ["VDA losses: never carried forward"]

    def save(self) -> None:
        for r in store().all("notes", tag="carry_forward"):
            store().delete("notes", r["id"])
        store().add("notes", {"entries": [asdict(e) for e in self.entries]}, tag="carry_forward")

    @classmethod
    def load(cls) -> "CarryForwardLedger":
        rows = store().all("notes", tag="carry_forward", limit=1)
        if not rows:
            return cls()
        return cls([LossEntry(**e) for e in rows[0].get("entries", [])])


def losses_from(classified: Classified) -> list[tuple[str, str, float]]:
    """(fy, bucket, loss) per year from classified rows: candidates for the ledger."""
    rows = classified.rows
    if rows.is_empty():
        return []
    b = rows.with_columns(lb=pl.col("bucket").replace({STCG: "STCL", LTCG: "LTCL"}))
    net = b.filter(pl.col("lb").is_in(list(LOSS_BUCKETS))).group_by("fy", "lb").agg(
        pl.col("net").sum())
    return [(fy, lb, round(-v, 2)) for fy, lb, v in net.sort("fy", "lb").iter_rows() if v < 0]


# ------------------------------------------------------------------ advance tax
@dataclass
class AdvanceTaxPlan:
    estimated_tax: float
    fy: str
    rows: pl.DataFrame
    due: bool

    def facts(self) -> list[str]:
        out = [f"Estimated tax for FY {self.fy}: ₹{self.estimated_tax:,.2f}"]
        if not self.due:
            out.append(f"Below ₹{rates.get('india.tax.advance_tax_min_inr'):,} a year: advance "
                       "tax not due")
        for r in self.rows.iter_rows(named=True):
            out.append(f"By {r['due_date']}: {r['cumulative_pct']}% = ₹{r['cumulative']:,.2f} "
                       f"cumulative (₹{r['instalment']:,.2f} this instalment)")
        return out + [f"Stamp: {DRAFT}"]


def advance_tax(estimated_tax: float, fy: str, paid_so_far: float = 0.0) -> AdvanceTaxPlan:
    """Advance-tax planner: the four cumulative instalments from the dated schedule."""
    start = int(fy[:4])
    recs, prev = [], 0.0
    for mmdd, share in rates.advance_tax_schedule():
        year = start if int(mmdd[:2]) >= 4 else start + 1
        cum = round(estimated_tax * share, 2)
        recs.append({"due_date": f"{year}-{mmdd}", "cumulative_pct": round(share * 100),
                     "cumulative": cum, "instalment": round(cum - prev, 2),
                     "still_to_pay": round(max(cum - paid_so_far, 0.0), 2)})
        prev = cum
    due = estimated_tax >= float(rates.get("india.tax.advance_tax_min_inr"))
    return AdvanceTaxPlan(estimated_tax, fy, pl.DataFrame(recs), due)


# ------------------------------------------------------------------ AIS / 26AS / VDA
def reconcile_ais(broker: pl.DataFrame | str | bytes, ais: pl.DataFrame | str | bytes,
                  tol: float = 1.0) -> Reconciliation:
    """Reconcile AIS: broker tax P&L vs AIS / 26AS, matched in code (tolerance ₹1)."""
    return reconcile(normalise(broker), normalise(ais), tol, "Broker", "AIS")


def broker_rows(classified: Classified) -> pl.DataFrame:
    """The lab's own sale rows (date sold, security, sale value) for AIS matching."""
    r = classified.rows
    if r.is_empty():
        return pl.DataFrame(schema={"date": pl.Utf8, "security": pl.Utf8, "amount": pl.Float64,
                                    "type": pl.Utf8})
    return r.select(
        date=pl.col("exit_time").dt.strftime("%Y-%m-%d"),
        security=pl.col("underlying").str.to_uppercase(),
        amount=(pl.when(pl.col("side") == "LONG").then(pl.col("exit_price"))
                .otherwise(pl.col("entry_price")) * pl.col("qty") * pl.col("multiplier"))
        .round(2),
        type=pl.col("bucket"))


@dataclass
class VdaLedger:
    """India VDA ledger: gains and losses kept apart, never netted."""

    rows: pl.DataFrame
    gains: float
    losses: float
    tds: float
    tax_before_cess: float
    rate: float

    def facts(self) -> list[str]:
        return [f"VDA gains (taxable): ₹{self.gains:,.2f}",
                f"VDA losses (recorded, cannot be set off or carried): ₹{self.losses:,.2f}",
                f"Taxable VDA income: ₹{self.gains:,.2f}",
                f"Tax at {self.rate * 100:g}% before cess: ₹{self.tax_before_cess:,.2f}",
                f"TDS deducted (credit): ₹{self.tds:,.2f}", f"Stamp: {DRAFT}"]


def vda_ledger(classified: Classified) -> VdaLedger:
    """One row per VDA sale with gain / loss / 1% TDS; taxable income adds only the gains."""
    v = classified.rows.filter(pl.col("bucket") == VDA) if classified.rows.height else \
        classified.rows
    rate = float(rates.india().get("vda_rate", 0.0))
    tds_rate = float(rates.india().get("vda_tds", 0.0))
    if v.is_empty():
        return VdaLedger(pl.DataFrame(), 0.0, 0.0, 0.0, 0.0, rate)
    sale = (pl.col("exit_price") * pl.col("qty") * pl.col("multiplier"))
    total_sales = float(v.select(sale.sum()).item())
    tds_on = total_sales > float(rates.get("india.tax.vda_tds_threshold_inr"))
    rows = v.select(
        "trade_id", "symbol",
        bought=(pl.col("entry_price") * pl.col("qty") * pl.col("multiplier")).round(2),
        sold=sale.round(2),
        gain=pl.when(pl.col("gross") > 0).then(pl.col("gross")).otherwise(0.0),
        loss=pl.when(pl.col("gross") < 0).then(-pl.col("gross")).otherwise(0.0),
        tds=(sale * (tds_rate if tds_on else 0.0)).round(2),
        date=pl.col("exit_time").dt.strftime("%Y-%m-%d"))
    gains, losses = float(rows["gain"].sum()), float(rows["loss"].sum())
    return VdaLedger(rows, round(gains, 2), round(losses, 2), round(float(rows["tds"].sum()), 2),
                     round(gains * rate, 2), rate)


def reconcile_tds(ledger: VdaLedger, form26as: pl.DataFrame | str | bytes,
                  tol: float = 1.0) -> Reconciliation:
    """Reconcile TDS: every VDA sale's 1% TDS against Form 26AS / AIS rows."""
    left = ledger.rows.select("date", security=pl.col("symbol").str.to_uppercase(),
                              amount="tds", type=pl.lit("VDA TDS")) if ledger.rows.height else \
        pl.DataFrame(schema={"date": pl.Utf8, "security": pl.Utf8, "amount": pl.Float64,
                             "type": pl.Utf8})
    return reconcile(left, normalise(form26as), tol, "Ledger", "26AS")


# ------------------------------------------------------------------ export
_SCHEDULE = {SPECULATIVE: "BP · speculative (intraday equity)",
             NON_SPECULATIVE: "BP · non-speculative (F&O)",
             STCG: "CG · STCG (111A → 196)", LTCG: "CG · LTCG (112A → 198)",
             VDA: "VDA (115BBH → 194(1))", ASK_CA: ASK_CA}


def export_itr_csv(classified: Classified, fy: str | None = None) -> str:
    """ITR-schedule-shaped CSV. Every line and the header carry the draft stamp."""
    rows = classified.rows
    if fy and rows.height:
        rows = rows.filter(pl.col("fy") == fy)
    buf = io.StringIO()
    buf.write(f"# {DRAFT.upper()} — PlugAI-Trade, not tax advice. Rates as of {rates.as_of()}.\n")
    buf.write(f"# FY {fy or 'all'} · section numbers: 1961 Act (FY 2025-26) and 2025 Act\n")
    w = csv.writer(buf)
    w.writerow(["stamp", "schedule", "row", "fy", "date_in", "date_out", "instrument", "side",
                "qty", "buy_value", "sell_value", "pnl_gross", "charges", "pnl_net",
                "turnover_abs_pnl", "section_old", "section_new", "rule", "flag"])
    for r in rows.iter_rows(named=True):
        long = r["side"] == "LONG"
        v_in = r["entry_price"] * r["qty"] * r["multiplier"]
        v_out = r["exit_price"] * r["qty"] * r["multiplier"]
        w.writerow([DRAFT, _SCHEDULE[r["bucket"]], r["trade_id"], r["fy"],
                    f"{r['entry_time']:%Y-%m-%d}", f"{r['exit_time']:%Y-%m-%d}", r["symbol"],
                    r["side"], f"{r['qty']:g}", f"{v_in if long else v_out:.2f}",
                    f"{v_out if long else v_in:.2f}", f"{r['gross']:.2f}",
                    f"{r['charges']:.2f}", f"{r['net']:.2f}",
                    f"{abs(r['gross']):.2f}" if r["bucket"] in (SPECULATIVE, NON_SPECULATIVE)
                    else "", r["section_old"], r["section_new"], r["rule"],
                    ASK_CA if r["ask_ca"] else ""])
    if rows.height:
        tot = rows.group_by("bucket").agg(pl.len().alias("n"), pl.col("gross").sum(),
                                          pl.col("charges").sum(), pl.col("net").sum(),
                                          pl.col("gross").abs().sum().alias("turnover"))
        for r in tot.sort("bucket").iter_rows(named=True):
            w.writerow([DRAFT, _SCHEDULE[r["bucket"]] + " · TOTAL", r["n"], fy or "", "", "", "",
                        "", "", "", "", f"{r['gross']:.2f}", f"{r['charges']:.2f}",
                        f"{r['net']:.2f}", f"{r['turnover']:.2f}"
                        if r["bucket"] in (SPECULATIVE, NON_SPECULATIVE) else "", "", "",
                        "VDA: gains only are taxable; losses never netted"
                        if r["bucket"] == VDA else "", ""])
    return buf.getvalue()

