"""Match two lists of tax rows (broker P&L vs AIS / 26AS, lab vs 1099-B) in code.

Rows match on date + security with amounts within a tolerance (₹1 by default).
Every unmatched row gets one *possible* reason, never a conclusion; the model can
explain a row (Explain) but the matching is done here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from ..journal.importers import _key, _num, parse_time, read_rows

COLS = {"date": ("date", "transaction date", "trade date", "date of sale", "date sold",
                 "sale date", "date of transaction"),
        "security": ("security", "security name", "name of security", "symbol", "scrip",
                     "instrument", "description", "information description"),
        "amount": ("amount", "value", "sale value", "sale consideration", "proceeds",
                   "amount paid/credited", "reported value", "tds", "tds deducted"),
        "type": ("type", "information category", "category", "nature", "transaction type")}


def normalise(source: str | Path | bytes | pl.DataFrame, us: bool = False) -> pl.DataFrame:
    """Any broker / AIS / 26AS / 1099 CSV → date, security, amount, type."""
    if isinstance(source, pl.DataFrame):
        rows = [{_key(k): ("" if v is None else str(v)) for k, v in r.items()}
                for r in source.iter_rows(named=True)]
    else:
        rows, _ = read_rows(source)
    out = []
    for r in rows:
        rec = {}
        for field, names in COLS.items():
            rec[field] = next((r[_key(n)] for n in names if r.get(_key(n))), "")
        if not rec["date"] or rec["amount"] == "":
            continue
        out.append({"date": parse_time(rec["date"], us=us).strftime("%Y-%m-%d"),
                    "security": rec["security"].strip().upper(),
                    "amount": _num(rec["amount"]) or 0.0, "type": rec["type"].strip()})
    return pl.DataFrame(out, schema={"date": pl.Utf8, "security": pl.Utf8,
                                     "amount": pl.Float64, "type": pl.Utf8})


def _reason(side: str, security: str, kind: str, near: float | None) -> str:
    text = f"{security} {kind}".lower()
    if near is not None:
        return "same date and security, different amount: gross vs net value, or charges"
    if re.search(r"dividend", text):
        return "dividend: perhaps paid to a second bank account, or not in the broker P&L"
    if re.search(r"buy ?back", text):
        return "buyback: its tax treatment changed from 1 April 2026"
    if re.search(r"off[- ]market|transfer|gift", text):
        return "off-market transfer"
    if side == "other only" and re.search(r"vda|crypto|194s|btc|eth", text):
        return "crypto exchange or VDA TDS you may have forgotten"
    if side == "other only":
        return "another broker or account you used"
    return "not reported (yet) by the other side, or under a different date or name"


@dataclass
class Reconciliation:
    """Matched rows and mismatches (amber) with a suggested reason each."""

    matched: pl.DataFrame
    mismatches: pl.DataFrame
    left_name: str = "Broker"
    right_name: str = "AIS"

    def facts(self) -> list[str]:
        out = [f"Rows matched: {self.matched.height}", f"Mismatches: {self.mismatches.height}"]
        for r in self.mismatches.head(12).iter_rows(named=True):
            out.append(f"{r['side']}: {r['date']} {r['security']} {r['amount']:,.2f} — "
                       f"{r['reason']}")
        return out


def reconcile(left: pl.DataFrame, right: pl.DataFrame, tol: float = 1.0,
              left_name: str = "Broker", right_name: str = "AIS") -> Reconciliation:
    """Match rows by date + security within ``tol``; list every unmatched row with a reason."""
    used: set[int] = set()
    matched, lonely = [], []
    right_rows = list(right.iter_rows(named=True))
    for lr in left.iter_rows(named=True):
        hit = next((i for i, rr in enumerate(right_rows) if i not in used
                    and rr["date"] == lr["date"] and rr["security"] == lr["security"]
                    and abs(rr["amount"] - lr["amount"]) <= tol), None)
        if hit is None:
            lonely.append(lr)
            continue
        used.add(hit)
        matched.append({"date": lr["date"], "security": lr["security"],
                        "amount": lr["amount"], "other_amount": right_rows[hit]["amount"]})
    mism = []
    for lr in lonely:
        near = next((rr["amount"] for i, rr in enumerate(right_rows) if i not in used
                     and rr["date"] == lr["date"] and rr["security"] == lr["security"]), None)
        mism.append({"side": f"{left_name} only", "date": lr["date"], "security": lr["security"],
                     "amount": lr["amount"], "other_amount": near,
                     "reason": _reason("left only", lr["security"], lr.get("type", ""), near)})
    for i, rr in enumerate(right_rows):
        if i in used:
            continue
        near = next((lr["amount"] for lr in lonely if lr["date"] == rr["date"]
                     and lr["security"] == rr["security"]), None)
        mism.append({"side": f"{right_name} only", "date": rr["date"],
                     "security": rr["security"], "amount": rr["amount"], "other_amount": near,
                     "reason": _reason("other only", rr["security"], rr.get("type", ""), near)})
    mschema = {"side": pl.Utf8, "date": pl.Utf8, "security": pl.Utf8, "amount": pl.Float64,
               "other_amount": pl.Float64, "reason": pl.Utf8}
    return Reconciliation(
        pl.DataFrame(matched, schema={"date": pl.Utf8, "security": pl.Utf8,
                                      "amount": pl.Float64, "other_amount": pl.Float64}),
        pl.DataFrame(mism, schema=mschema).sort("date"), left_name, right_name)
