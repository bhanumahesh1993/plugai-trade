"""Portfolio › Portfolio Reviewer: holdings, overlap, costs, concentration, allocation,
ETF check, income, SIP planner and thesis tracker.

    from plugai_trade import portfolio
    portfolio.sip.future_value(10_000, 20, 0.08)          # ₹57.3 lakh (illustrative)
    funds = portfolio.funds.sample_funds_in()[:5]
    portfolio.funds.overlap_matrix(funds)                 # A↔E 57 %

Holdings, tax and thesis data are private: every AI call from this screen is
made with ``sensitive=True`` so it stays on the local model.
"""

from __future__ import annotations

from . import allocation, etf, funds, holdings, income, sip, thesis
from .. import reference

__all__ = ["allocation", "etf", "funds", "holdings", "income", "sip", "thesis", "cess_rate", "money"]


def cess_rate() -> float | None:
    """Indian health & education cess from the dated table, or None if the table lacks it."""
    v = reference.lookup("india.tax.cess")
    return None if v is None else float(v)


def money(x: float | None, currency: str = "₹", decimals: int = 0) -> str:
    """Format money: Indian digit grouping (12,34,567) for ₹, western for $."""
    if x is None:
        return "—"
    sign = "−" if x < 0 else ""
    x = abs(x)
    whole, _, frac = f"{x:.{decimals}f}".partition(".")
    if currency == "₹" and len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    elif currency != "₹":
        whole = f"{int(whole):,}"
    return f"{sign}{currency}{whole}" + (f".{frac}" if decimals else "")
