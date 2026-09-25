"""Income tab: dividend Safety (payout, cash cover), Yield vs price, After-tax income,
Holding-period check. Rates come from the dated tax table or from the user's own
profile (slab / bracket), never from the AI.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .. import reference


def payout_ratio(dps: float, eps: float) -> float:
    """Dividend per share ÷ earnings per share (inf when earnings are ≤ 0)."""
    return dps / eps if eps > 0 else float("inf")


def cash_cover(fcf_per_share: float, dps: float) -> float:
    """Free cash flow per share ÷ dividend per share."""
    return fcf_per_share / dps if dps > 0 else float("inf")


def safety(dps: float, eps: float, fcf_per_share: float) -> dict[str, object]:
    """The Safety column: amber when payout > 100 % or cover < 1."""
    p, c = payout_ratio(dps, eps), cash_cover(fcf_per_share, dps)
    flags = []
    if p > 1:
        flags.append("payout above 100%")
    if c < 1:
        flags.append("cash cover below 1")
    return {"payout": p, "cover": c, "flag": bool(flags), "why": ", ".join(flags)}


def trailing_yield(annual_dividend: float, price: float) -> float:
    """Last annual dividend ÷ price."""
    return annual_dividend / price


# ------------------------------------------------------------------ tax
def after_tax_india(gross: float, slab: float, cess: float) -> float:
    """India: dividends are taxed at your slab rate plus cess (surcharge ignored)."""
    return gross * (1 - slab * (1 + cess))


def after_tax_us(gross: float, bracket: float, qualified: bool, qualified_rate: float = 0.15,
                 niit: bool = False) -> float:
    """US federal: ordinary dividends at your bracket; qualified at 0/15/20 % (+3.8 % NIIT)."""
    if qualified and qualified_rate not in reference.lookup("us.tax.long_term", []):
        raise ValueError("qualified rate must be one of the dated long-term rates")
    rate = qualified_rate if qualified else bracket
    if niit:
        rate += float(reference.lookup("us.tax.niit"))
    return gross * (1 - rate)


def days_held_in_window(bought: date, ex_date: date, sold: date | None = None) -> int:
    """Days held inside the 121-day window starting 60 days before the ex-date.

    The purchase day is not counted; the sale day is.
    """
    start, end = ex_date - timedelta(days=60), ex_date + timedelta(days=60)
    first = max(bought + timedelta(days=1), start)
    last = min(sold or end, end)
    return max(0, (last - first).days + 1)


def qualifies(bought: date, ex_date: date, sold: date | None = None) -> bool:
    """US holding-period test: more than 60 days in the window."""
    return days_held_in_window(bought, ex_date, sold) > 60


@dataclass
class IncomeHolding:
    """One income holding with the figures the Safety column needs."""

    name: str
    shares: float
    price: float
    dps: float  # last 12 months
    eps: float
    fcf_ps: float
    ex_date: date
    bought: date
    sold: date | None = None

    @property
    def gross(self) -> float:
        """Dividends over the last 12 months."""
        return self.shares * self.dps

    def row(self, check_holding_period: bool = False) -> dict:
        """Row for the Income table."""
        s = safety(self.dps, self.eps, self.fcf_ps)
        row = {"Holding": self.name, "Shares": self.shares, "Price": self.price,
               "Dividend (12m)": self.dps, "Yield %": round(trailing_yield(self.dps, self.price) * 100, 2),
               "Ex-date": self.ex_date.isoformat(), "Gross income": round(self.gross, 2),
               "Payout %": round(s["payout"] * 100, 1), "Cash cover": round(s["cover"], 2),
               "Safety": ("⚠ " + s["why"]) if s["flag"] else "ok"}
        if check_holding_period:
            row["Treated as"] = ("qualified" if qualifies(self.bought, self.ex_date, self.sold)
                                 else "ordinary (≤ 60 days)")
        return row


@dataclass
class IncomeSummary:
    """After-tax income tile plus the facts behind it."""

    gross: float
    net: float
    flagged: list[str]
    profile: str
    currency: str

    def facts(self) -> list[str]:
        """Facts for Explain."""
        c = self.currency
        return [f"Gross dividends, last 12 months: {c}{self.gross:,.0f}",
                f"After-tax income ({self.profile}): {c}{self.net:,.0f}",
                f"Expected next quarter, if unchanged: {c}{self.net / 4:,.0f}",
                f"Safety flags: {', '.join(self.flagged) or 'none'}"]


def summarise(holdings: list[IncomeHolding], market: str, slab: float = 0.30, cess: float = 0.0,
              bracket: float = 0.22, qualified: bool = True, qualified_rate: float = 0.15,
              niit: bool = False, check_holding_period: bool = False) -> IncomeSummary:
    """After-tax income across holdings for one tax profile."""
    gross = sum(h.gross for h in holdings)
    flagged = [h.name for h in holdings if safety(h.dps, h.eps, h.fcf_ps)["flag"]]
    if market == "IN":
        net = after_tax_india(gross, slab, cess)
        profile = f"slab {slab:.0%} + cess {cess:.0%}"
    else:
        net = 0.0
        for h in holdings:
            q = qualified and (not check_holding_period or qualifies(h.bought, h.ex_date, h.sold))
            net += after_tax_us(h.gross, bracket, q, qualified_rate, niit)
        profile = (f"bracket {bracket:.0%}, qualified at {qualified_rate:.0%}" if qualified
                   else f"bracket {bracket:.0%}, ordinary") + (" + NIIT" if niit else "")
    return IncomeSummary(gross, net, flagged, profile, "₹" if market == "IN" else "$")


# ------------------------------------------------------------------ samples
# Chapter 16's yield trap: price path (₹), dividend ₹20 until the cut to ₹8 at month 30.
TRAP_PRICES = (400, 377, 372, 375, 361, 339, 331, 328, 332, 313, 294, 293, 291, 298, 300, 293,
               284, 300, 290, 277, 262, 257, 252, 244, 238, 235, 234, 237, 233, 216, 190, 181,
               179, 170, 170, 165, 166)
TRAP_CUT_MONTH = 30


def yield_trap_series() -> list[dict]:
    """Month, price, trailing yield and whether the yield rose only because the price fell."""
    rows, prev = [], None
    for m, p in enumerate(TRAP_PRICES):
        div = 20.0 if m < TRAP_CUT_MONTH else 8.0
        y = trailing_yield(div, p)
        price_driven = prev is not None and y > prev[1] and div == prev[0]
        rows.append({"month": m, "price": p, "yield_pct": round(y * 100, 2),
                     "price_driven": price_driven})
        prev = (div, y)
    return rows


def sample_income(market: str, today: date | None = None) -> list[IncomeHolding]:
    """Synthetic income holdings (one looks like a yield trap)."""
    t = today or date.today()
    def mk(name: str, shares: float, price: float, dps: float, eps: float, fcf: float,
           ex_in: int, held: int) -> IncomeHolding:
        return IncomeHolding(name, shares, price, dps, eps, fcf, t + timedelta(days=ex_in),
                             t - timedelta(days=held))

    if market == "IN":
        return [mk("Steady Utilities (synthetic)", 400, 500, 18, 40, 30, 20, 400),
                mk("High-Yield Metals (synthetic)", 300, 216, 20, 18.2, 15, 35, 200),
                mk("Bank Dividend Co (synthetic)", 250, 820, 16, 70, 55, 50, 900)]
    return [mk("SYN Consumer Staples", 120, 64, 2.4, 3.6, 3.1, 12, 30),
            mk("SYN Telecom", 200, 21.6, 2.0, 1.82, 1.5, 40, 500),
            mk("SYN Dividend ETF", 80, 88, 3.1, 4.4, 4.0, 25, 700)]
