"""Every tax rate, threshold and date the Tax Export uses, read from the dated reference.

A few values the book prints are not in ``reference/tables.yaml`` yet. They are read
from the table under the key shown in ``PENDING`` and fall back to the book's
Sep 2026 value only until ``plugai-trade update`` ships them; the Tax Export marks
such values "pending table" so the reader knows where each number came from.
"""

from __future__ import annotations

from typing import Any

from .. import reference

#: key in reference → (fallback printed in the book as of Sep 2026, what it is)
PENDING: dict[str, tuple[Any, str]] = {
    "india.tax.audit_threshold_inr": (10_000_000, "Tax audit: business turnover limit when "
                                                  "cash exceeds 5% (s.44AB → s.63)"),
    "india.tax.presumptive_rate_digital": (0.06, "Presumptive deemed profit on digitally "
                                                  "received turnover (s.44AD → s.58)"),
    "india.tax.presumptive_lock_in_years": (5, "Presumptive lock-in years (s.58(7))"),
    "india.tax.advance_tax_min_inr": (10_000, "Advance tax applies from this much tax a year"),
    "india.tax.ltcg_months": (12, "Listed equity held longer than this many months is LTCG"),
    "india.tax.vda_tds_threshold_inr": (10_000, "VDA TDS threshold a year (₹50,000 for "
                                                "specified persons)"),
    "us.tax.long_term_days": (365, "Held more than one year → long-term"),
    "us.tax.sec_1256_symbols": (["SPX", "NDX", "RUT", "VIX", "XSP", "DJX", "OEX", "MES", "MNQ",
                                 "ES", "NQ", "RTY", "YM", "CL", "GC", "ZN", "ZB"],
                                "Broad-based index options and regulated futures"),
    "us.tax.equity_option_symbols": (["SPY", "QQQ", "IWM", "DIA", "VOO", "IVV"],
                                     "ETF options: equity options, not 1256"),
}


def get(key: str) -> Any:
    """A dated value: from the reference table, else the pending fallback."""
    v = reference.lookup(key)
    if v is not None:
        return v
    if key in PENDING:
        return PENDING[key][0]
    raise KeyError(f"No dated value for {key}")


def source(key: str) -> str:
    """'table' if the reference has it, 'pending table' if a book fallback is used."""
    return "table" if reference.lookup(key) is not None else "pending table"


def as_of() -> str:
    return reference.as_of()


def india() -> dict[str, Any]:
    return reference.lookup("india.tax") or {}


def us() -> dict[str, Any]:
    return reference.lookup("us.tax") or {}


def carry_forward_years(bucket: str) -> int | None:
    """Years a loss may be carried forward; None when it may not be carried (VDA)."""
    table = india().get("carry_forward_years", {})
    key = {"SPECULATIVE": "speculative", "NON_SPECULATIVE": "non_speculative",
           "STCL": "capital", "LTCL": "capital"}.get(bucket)
    return int(table[key]) if key and key in table else None


def advance_tax_schedule() -> list[tuple[str, float]]:
    """[(MM-DD, cumulative share)] from the dated table."""
    return [(str(d), float(s)) for d, s in india().get("advance_tax", [])]


def wash_days() -> int:
    return int(us().get("wash_sale_days", 30))


def split_1256() -> tuple[float, float]:
    lt, st = us().get("sec_1256_split", [0.6, 0.4])
    return float(lt), float(st)
