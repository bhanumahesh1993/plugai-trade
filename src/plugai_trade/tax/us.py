"""US: short / long term, wash sales across accounts, Section 1256, Form 8949 CSV.

The wash-sale check scans ±30 days (dated table) across every tagged account —
Taxable, IRA and Spouse — links options to their underlying, and never covers crypto
unless the Crypto wash-sale check switch is on (default off as of Sep 2026).
"Substantially identical" pairs are only ever warnings. Draft for your CA / CPA.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, timedelta

import polars as pl

from .. import reference
from ..journal.detectors import simulated_mask
from ..store import default as store
from . import rates
from .reconcile import Reconciliation, normalise, reconcile

DRAFT = "Draft for your CA / CPA"
ASK_CA = "ASK CA"
ACCOUNT_TYPES = ("Taxable", "IRA", "Spouse")


# ------------------------------------------------------------------ accounts
def add_account(name: str, kind: str) -> int:
    """Add account: tag an imported account as Taxable, IRA or Spouse."""
    if kind not in ACCOUNT_TYPES:
        raise ValueError(f"Account type must be one of {ACCOUNT_TYPES}")
    for r in store().all("tax_accounts"):
        if r.get("name") == name:
            store().update("tax_accounts", r["id"], {"name": name, "type": kind}, tag=kind)
            return r["id"]
    return store().add("tax_accounts", {"name": name, "type": kind}, tag=kind)


def account_types() -> dict[str, str]:
    """{account name: Taxable | IRA | Spouse} from the store."""
    return {r["name"]: r["type"] for r in store().all("tax_accounts") if r.get("name")}


# ------------------------------------------------------------------ 1256
def tag_1256(underlying: str, instrument: str) -> tuple[bool | None, str, bool]:
    """(is 1256?, reason, ask CA?) for one instrument, with the reason printed in the book."""
    u, inst = (underlying or "").upper(), (instrument or "").upper()
    confirm = " · confirm against your 1099-B"
    if inst == "CRYPTO":
        return False, "digital asset → property → Form 8949 boxes G–L", False
    if inst == "EQ":
        return False, "shares → not a 1256 contract", False
    row = reference.lookup(f"us.contracts.{u}") or {}
    flag = row.get("sec_1256")
    if flag is None:
        if u in rates.get("us.tax.sec_1256_symbols"):
            flag = True
        elif u in rates.get("us.tax.equity_option_symbols"):
            flag = False
    if inst == "FUT":
        if flag is False:
            return False, "security future → not 1256" + confirm, True
        return True, "regulated futures contract → 1256" + confirm, flag is None
    if flag is True:
        return True, "broad-based index option → nonequity option → 1256" + confirm, False
    if flag is False:
        return False, "option on an ETF's shares → equity option → not 1256" + confirm, False
    return False, "option on a stock → equity option → not 1256" + confirm, False


def split_1256(gain: float) -> tuple[float, float]:
    """60 / 40: (long-term part, short-term part), however long it was held."""
    lt, st = rates.split_1256()
    return round(gain * lt, 2), round(gain * st, 2)


def last_business_day(year: int) -> date:
    d = date(year, 12, 31)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def mark_to_market(open_positions: pl.DataFrame, prices: dict[str, float],
                   year: int) -> pl.DataFrame:
    """Year-end MTM for open 1256 positions: treated as sold on the last business day."""
    day = last_business_day(year)
    recs = []
    for r in open_positions.iter_rows(named=True):
        is_1256, why, _ = tag_1256(r["underlying"], r["instrument"])
        if not is_1256 or r["symbol"] not in prices:
            continue
        sign = 1 if r["side"] in ("BUY", "LONG") else -1
        gain = round((prices[r["symbol"]] - r["price"]) * r["qty"] * (r["multiplier"] or 1)
                     * sign, 2)
        lt, st = split_1256(gain)
        recs.append({"symbol": r["symbol"], "marked_on": day.isoformat(),
                     "mark": prices[r["symbol"]], "gain": gain, "long_term_60": lt,
                     "short_term_40": st, "reason": why})
    return pl.DataFrame(recs)


# ------------------------------------------------------------------ wash sales
@dataclass
class WashSaleResult:
    """Hits (loss sale → replacement), adjusted rows, and declared-pair warnings."""

    hits: pl.DataFrame
    rows: pl.DataFrame
    warnings: pl.DataFrame
    crypto_checked: bool = False

    def facts(self) -> list[str]:
        out = [f"Wash-sale hits: {self.hits.height}",
               f"Crypto wash-sale check: {'on' if self.crypto_checked else 'off (default)'}"]
        for h in self.hits.iter_rows(named=True):
            out.append(
                f"Row {h['loss_row']} sold {h['sale_date']} at a loss of ${h['loss']:,.2f}; window "
                f"{h['window_start']} – {h['window_end']}; replacement row {h['replacement_row']}"
                f" ({h['replacement_account']}, {h['days_from_sale']:+d} days): "
                f"${h['disallowed']:,.2f}"
                f" disallowed" + (" permanently (IRA)" if h["permanent"] else
                                  f"; new basis ${h['new_basis']:,.2f}"))
        for w in self.warnings.iter_rows(named=True):
            out.append(f"Substantially identical? {w['pair']}: {w['note']}")
        return out + [f"Stamp: {DRAFT}"]


def _basis_proceeds(r: dict) -> tuple[float, float]:
    """(cost basis, proceeds) with charges split half to each side."""
    v_in = r["entry_price"] * r["qty"] * r["multiplier"]
    v_out = r["exit_price"] * r["qty"] * r["multiplier"]
    half = (r["charges"] or 0.0) / 2
    if r["side"] == "LONG":
        return v_in + half, v_out - half
    return v_out + half, v_in - half


def _replaces(loss: dict, cand: dict) -> bool:
    """Is ``cand``'s purchase a replacement for ``loss``? Same stock, or an option to buy it."""
    if cand["side"] != "LONG":
        return False
    if loss["instrument"] in ("CALL", "PUT"):
        return cand["symbol"] == loss["symbol"]
    if cand["underlying"] != loss["underlying"]:
        return False
    return cand["instrument"] in ("EQ", "CALL", "CRYPTO")


def wash_sales(trades: pl.DataFrame, accounts: dict[str, str] | None = None,
               crypto: bool | None = None,
               identical_pairs: list[tuple[str, str]] | None = None) -> WashSaleResult:
    """Wash-sale check across all tagged accounts (Taxable / IRA / Spouse)."""
    accounts = accounts if accounts is not None else account_types()
    crypto = bool(rates.us().get("wash_sale_covers_crypto", False)) if crypto is None else crypto
    days = rates.wash_days()
    t = trades.filter(~simulated_mask()) if trades.height else trades
    t = t.sort("exit_time")
    recs = list(t.iter_rows(named=True))
    kind = lambda r: accounts.get(r["account"], "Taxable")  # noqa: E731
    covered = lambda r: not tag_1256(r["underlying"], r["instrument"])[0] and (  # noqa: E731
        r["instrument"] != "CRYPTO" or crypto) and r["instrument"] != "FUT"
    adj_basis = {r["trade_id"]: 0.0 for r in recs}
    tack_days = {r["trade_id"]: 0 for r in recs}
    disallowed = {r["trade_id"]: 0.0 for r in recs}
    used_qty = {r["trade_id"]: 0.0 for r in recs}
    hits = []
    for r in recs:
        if r["side"] != "LONG" or kind(r) == "IRA" or not covered(r):
            continue
        basis, proceeds = _basis_proceeds(r)
        loss = proceeds - (basis + adj_basis[r["trade_id"]])
        if loss >= 0:
            continue
        sale = r["exit_time"].date()
        lo, hi = sale - timedelta(days=days), sale + timedelta(days=days)
        left_qty = r["qty"]
        for c in sorted(recs, key=lambda x: x["entry_time"]):
            if left_qty <= 1e-9:
                break
            if c["trade_id"] == r["trade_id"] or not _replaces(r, c):
                continue
            if c["account"] == r["account"] and c["entry_time"] == r["entry_time"]:
                continue  # same purchase lot, split by a partial exit
            if not (lo <= c["entry_time"].date() <= hi):
                continue
            avail = c["qty"] - used_qty[c["trade_id"]]
            if avail <= 1e-9:
                continue
            take = min(avail, left_qty)
            amount = round(-loss * take / r["qty"], 2)
            used_qty[c["trade_id"]] += take
            left_qty -= take
            disallowed[r["trade_id"]] += amount
            permanent = kind(c) == "IRA"
            if not permanent:
                adj_basis[c["trade_id"]] += amount
                tack_days[c["trade_id"]] += (sale - r["entry_time"].date()).days
            c_basis = _basis_proceeds(c)[0]
            hits.append({
                "loss_row": r["trade_id"], "symbol": r["symbol"], "loss_account": r["account"],
                "sale_date": sale.isoformat(), "loss": round(-loss, 2),
                "window_start": lo.isoformat(), "window_end": hi.isoformat(),
                "replacement_row": c["trade_id"], "replacement_account": c["account"],
                "replacement_type": kind(c), "replacement_date": c["entry_time"].date().isoformat(),
                "days_from_sale": (c["entry_time"].date() - sale).days,
                "disallowed": amount, "permanent": permanent,
                "new_basis": round(c_basis + (0.0 if permanent else adj_basis[c["trade_id"]]), 2),
            })
    rows = []
    for r in recs:
        basis, proceeds = _basis_proceeds(r)
        basis += adj_basis[r["trade_id"]]
        held = (r["exit_time"].date() - r["entry_time"].date()).days + tack_days[r["trade_id"]]
        w = round(disallowed[r["trade_id"]], 2)
        rows.append({**r, "account_type": kind(r), "cost_basis": round(basis, 2),
                     "proceeds": round(proceeds, 2), "wash_disallowed": w,
                     "code": "W" if w else "", "holding_days": held,
                     "gain": round(proceeds - basis + w, 2)})
    hit_schema = {"loss_row": pl.Int64, "symbol": pl.Utf8, "loss_account": pl.Utf8,
                  "sale_date": pl.Utf8, "loss": pl.Float64, "window_start": pl.Utf8,
                  "window_end": pl.Utf8, "replacement_row": pl.Int64,
                  "replacement_account": pl.Utf8, "replacement_type": pl.Utf8,
                  "replacement_date": pl.Utf8, "days_from_sale": pl.Int64,
                  "disallowed": pl.Float64, "permanent": pl.Boolean, "new_basis": pl.Float64}
    return WashSaleResult(pl.DataFrame(hits, schema=hit_schema),
                          pl.DataFrame(rows) if rows else pl.DataFrame(),
                          identical_warnings(t, identical_pairs or [], days), crypto)


def identical_warnings(t: pl.DataFrame, pairs: list[tuple[str, str]],
                       days: int | None = None) -> pl.DataFrame:
    """Substantially identical warnings: declared pairs, loss sale of one, buy of the other."""
    days = days or rates.wash_days()
    out = []
    recs = list(t.iter_rows(named=True)) if t.height else []
    for a, b in pairs:
        for x, y in ((a, b), (b, a)):
            for r in recs:
                if r["underlying"] != x or r["side"] != "LONG" or (r["net"] or 0) >= 0:
                    continue
                sale = r["exit_time"].date()
                for c in recs:
                    if c["underlying"] == y and c["side"] == "LONG" and \
                            abs((c["entry_time"].date() - sale).days) <= days:
                        out.append({"pair": f"{x} / {y}", "loss_row": r["trade_id"],
                                    "replacement_row": c["trade_id"],
                                    "note": "QUESTION FOR CPA — a warning, not a determination",
                                    "flag": ASK_CA})
    return pl.DataFrame(out, schema={"pair": pl.Utf8, "loss_row": pl.Int64,
                                     "replacement_row": pl.Int64, "note": pl.Utf8,
                                     "flag": pl.Utf8})


# ------------------------------------------------------------------ 8949 / 6781
def term(holding_days: int) -> str:
    return "long" if holding_days > int(rates.get("us.tax.long_term_days")) else "short"


def box_letter(is_short: bool, digital: bool, basis_reported: bool | None) -> str:
    """Form 8949 box: A–F securities, G–L digital assets (reported / not reported / no form)."""
    idx = 0 if basis_reported else (1 if basis_reported is False else 2)
    letters = ("GHI" if is_short else "JKL") if digital else ("ABC" if is_short else "DEF")
    return letters[idx]


@dataclass
class Form8949:
    rows: pl.DataFrame
    form_6781: pl.DataFrame
    excluded_ira: int = 0
    flags: list[str] = field(default_factory=list)

    def facts(self) -> list[str]:
        st = self.rows.filter(pl.col("part") == "I") if self.rows.height else self.rows
        lt = self.rows.filter(pl.col("part") == "II") if self.rows.height else self.rows
        s = lambda d: float(d["gain"].sum()) if d.height else 0.0  # noqa: E731
        out = [f"Form 8949 rows: {self.rows.height} (short-term {st.height}, long-term "
               f"{lt.height})", f"Short-term total: ${s(st):,.2f}",
               f"Long-term total: ${s(lt):,.2f}",
               f"Section 1256 rows (Form 6781): {self.form_6781.height}",
               f"IRA rows left out: {self.excluded_ira}"]
        if self.form_6781.height:
            out.append(f"1256 net: ${float(self.form_6781['gain'].sum()):,.2f} = "
                       f"${float(self.form_6781['long_term_60'].sum()):,.2f} long-term + "
                       f"${float(self.form_6781['short_term_40'].sum()):,.2f} short-term")
        return out + self.flags + [f"Stamp: {DRAFT}"]


def form_8949(wash: WashSaleResult, basis_reported: bool | None = True) -> Form8949:
    """8949-shaped rows (box letters A–L, code W) and 1256 rows for Form 6781."""
    rows, r1256, flags = [], [], []
    ira = 0
    for r in wash.rows.iter_rows(named=True) if wash.rows.height else []:
        if r["account_type"] == "IRA":
            ira += 1
            continue
        is_1256, why, ask = tag_1256(r["underlying"], r["instrument"])
        if is_1256:
            lt, st = split_1256(r["gain"])
            r1256.append({"row": r["trade_id"], "description": f"{r['qty']:g} {r['symbol']}",
                          "gain": r["gain"], "long_term_60": lt, "short_term_40": st,
                          "reason": why, "flag": ASK_CA if ask else ""})
            continue
        digital = r["instrument"] == "CRYPTO"
        reported = basis_reported
        flag = ""
        if digital:
            reported = r["entry_time"].date() >= date(2026, 1, 1) and basis_reported is not None
            if not reported:
                flag = f"{ASK_CA}: basis not reported (pre-2026 or transferred coin) — add records"
        short = term(r["holding_days"]) == "short"
        rows.append({
            "stamp": DRAFT, "part": "I" if short else "II",
            "box": box_letter(short, digital, reported), "row": r["trade_id"],
            "description": f"{r['qty']:g} {r['symbol']}",
            "date_acquired": f"{r['entry_time']:%m/%d/%Y}",
            "date_sold": f"{r['exit_time']:%m/%d/%Y}",
            "proceeds": r["proceeds"], "cost_basis": r["cost_basis"], "code": r["code"],
            "adjustment": r["wash_disallowed"] or 0.0, "gain": r["gain"],
            "account": r["account"], "flag": flag})
        if flag:
            flags.append(f"Row {r['trade_id']}: {flag}")
    for w in wash.warnings.iter_rows(named=True):
        flags.append(f"Rows {w['loss_row']}/{w['replacement_row']} {w['pair']}: {w['note']}")
    return Form8949(pl.DataFrame(rows), pl.DataFrame(r1256), ira, flags)


def export_8949_csv(f: Form8949) -> str:
    """8949-shaped CSV with the draft stamp on the header and every row; 6781 rows after."""
    buf = io.StringIO()
    buf.write(f"# {DRAFT.upper()} — PlugAI-Trade, not tax advice. Rules as of {rates.as_of()}.\n")
    w = csv.writer(buf)
    cols = ["stamp", "part", "box", "row", "description", "date_acquired", "date_sold",
            "proceeds", "cost_basis", "code", "adjustment", "gain", "account", "flag"]
    w.writerow(cols)
    for r in f.rows.iter_rows(named=True) if f.rows.height else []:
        w.writerow([r[c] if not isinstance(r[c], float) else f"{r[c]:.2f}" for c in cols])
    if f.form_6781.height:
        buf.write("# Form 6781 (Section 1256) — 60% long-term / 40% short-term\n")
        w.writerow(["stamp", "row", "description", "gain", "long_term_60", "short_term_40",
                    "reason", "flag"])
        for r in f.form_6781.iter_rows(named=True):
            w.writerow([DRAFT, r["row"], r["description"], f"{r['gain']:.2f}",
                        f"{r['long_term_60']:.2f}", f"{r['short_term_40']:.2f}", r["reason"],
                        r["flag"]])
    return buf.getvalue()


def compare_1099b(f: Form8949, form_1099b: pl.DataFrame | str | bytes,
                  tol: float = 1.0) -> Reconciliation:
    """Lab 8949 rows vs the broker's 1099-B, matched on date sold, security and proceeds."""
    left = f.rows.select(
        date=pl.col("date_sold").str.to_date("%m/%d/%Y").dt.strftime("%Y-%m-%d"),
        security=pl.col("description").str.split(" ").list.get(1).str.to_uppercase(),
        amount="proceeds", type=pl.col("code")) if f.rows.height else \
        pl.DataFrame(schema={"date": pl.Utf8, "security": pl.Utf8, "amount": pl.Float64,
                             "type": pl.Utf8})
    return reconcile(left, normalise(form_1099b, us=True), tol, "Lab", "1099-B")
