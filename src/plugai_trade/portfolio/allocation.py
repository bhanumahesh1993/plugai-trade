"""Allocation: target mix, band, drift and the Rebalance checklist.

Priya's 60/30/10 on ₹13.22 lakh (65.8/25.9/8.3 after two strong years) needs about
₹76,800 out of equity and ₹54,600 / ₹22,200 into debt / gold (Chapter 15).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .. import reference

CHECKLIST = (
    "Is the target mix still right for my goal, horizon and situation? (Decide target changes first, separately.)",
    "Which sleeves are outside their bands, and by how many points and rupees or dollars?",
    "Can new SIP or contribution money close the gap within a few months?",
    "If units must be sold: which lots are long-term, what gains would be realised, any exit loads?",
    "US: would a sale at a loss plus a repurchase in any account, IRA included, fall inside the wash-sale window?",
    "Record what you did, why and when (Journal).",
)


@dataclass(frozen=True)
class SleeveDrift:
    """One sleeve against its target."""

    sleeve: str
    value: float
    now: float  # fraction
    target: float  # fraction
    band: float  # fraction, e.g. 0.05 for ±5 points
    to_target: float  # money to add (+) or move out (−)
    months_new_money: float | None

    @property
    def drift(self) -> float:
        """Percentage points away from target (as a fraction)."""
        return self.now - self.target

    @property
    def outside(self) -> bool:
        """True when the sleeve has left its band."""
        return abs(self.drift) > self.band + 1e-12


@dataclass
class Allocation:
    """Drift for every sleeve, plus the facts Explain cites."""

    sleeves: list[SleeveDrift]
    currency: str = "₹"

    @property
    def total(self) -> float:
        """Portfolio value."""
        return sum(s.value for s in self.sleeves)

    def rows(self) -> list[dict]:
        """Table rows for the Allocation tab and the Rebalance checklist."""
        return [{"Sleeve": s.sleeve, "Value": round(s.value), "Now %": round(s.now * 100, 1),
                 "Target %": round(s.target * 100, 1), "Drift (pts)": round(s.drift * 100, 1),
                 "Band": f"±{s.band * 100:g}", "Status": "OUTSIDE BAND" if s.outside else "inside",
                 "To target": round(s.to_target),
                 "Months of new money": None if s.months_new_money is None
                 else round(s.months_new_money, 1)} for s in self.sleeves]

    def facts(self) -> list[str]:
        """Facts for Explain."""
        c = self.currency
        f = [f"Portfolio value: {c}{self.total:,.0f}"]
        for s in self.sleeves:
            f.append(f"{s.sleeve}: {s.now:.1%} now vs {s.target:.0%} target "
                     f"({s.drift * 100:+.1f} pts, {'outside' if s.outside else 'inside'} the "
                     f"±{s.band * 100:g} band); to target {c}{s.to_target:+,.0f}")
        return f


def drift(values: dict[str, float], target: dict[str, float], band: float = 0.05,
          monthly_new_money: float = 0.0, currency: str = "₹") -> Allocation:
    """Compare sleeve values with a target mix (fractions summing to 1)."""
    total = sum(values.values())
    if total <= 0:
        raise ValueError("no holdings")
    tsum = sum(target.values())
    if abs(tsum - 1) > 1e-6:
        raise ValueError(f"target adds up to {tsum:.1%}, not 100%")
    out = []
    for sleeve in target:
        v = values.get(sleeve, 0.0)
        t = target[sleeve]
        gap = t * total - v
        months = None
        if monthly_new_money > 0:
            if gap > 0:  # underweight: point new money here
                months = gap / monthly_new_money
            elif t > 0:  # overweight: dilute with new money going elsewhere
                months = (v / t - total) / monthly_new_money
        out.append(SleeveDrift(sleeve, v, v / total, t, band, gap, months))
    return Allocation(out, currency)


@dataclass(frozen=True)
class Lot:
    """A purchase lot for the sale estimate."""

    bought: date
    units: float
    cost: float  # per unit


def sale_lots(lots: list[Lot], units: float, price: float, today: date | None = None) -> list[dict]:
    """FIFO lots for selling ``units`` (India listed equity rules from the dated table).

    Estimated gains only: a *Draft for your CA / CPA*.
    """
    today = today or date.today()
    stcg = float(reference.lookup("india.tax.stcg_listed_equity"))
    ltcg = float(reference.lookup("india.tax.ltcg_listed_equity"))
    rows, left = [], units
    for lot in sorted(lots, key=lambda x: x.bought):
        if left <= 0:
            break
        take = min(left, lot.units)
        left -= take
        held = (today - lot.bought).days
        long_term = held > 365
        gain = take * (price - lot.cost)
        rows.append({"Bought": lot.bought.isoformat(), "Units": take, "Held (days)": held,
                     "Type": "LTCG" if long_term else "STCG", "Gain": round(gain, 2),
                     "Rate": ltcg if long_term else stcg,
                     "Note": "Draft for your CA / CPA (LTCG exemption applies per year)"})
    return rows
