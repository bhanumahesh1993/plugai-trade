"""SIP planner: projections under *assumed* returns, computed exactly in code.

Convention (the book's, Chapter 15): the assumed annual return is converted to
an equivalent monthly rate, (1 + r)^(1/12) − 1, and each instalment is invested
at the start of its month. ₹10,000 a month for 20 years then ends at
₹45.6 L / ₹57.3 L / ₹72.4 L / ₹92.0 L at 6 / 8 / 10 / 12 %.
These are illustrative assumptions, not forecasts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

DEFAULT_RETURNS = (0.06, 0.08, 0.10)


def monthly_rate(annual: float) -> float:
    """Monthly rate equivalent to an effective annual rate."""
    return (1 + annual) ** (1 / 12) - 1


def schedule(monthly: float, years: int, step_up: float = 0.0,
             pause: tuple[int, int] | None = None) -> np.ndarray:
    """Instalment for each month: step-up once a year; ``pause`` = (first month, months), 1-based."""
    n = int(round(years * 12))
    amounts = np.array([monthly * (1 + step_up) ** (m // 12) for m in range(n)])
    if pause:
        first, length = pause
        amounts[max(0, first - 1):max(0, first - 1) + length] = 0.0
    return amounts


def future_value(monthly: float, years: int, annual: float, step_up: float = 0.0,
                 pause: tuple[int, int] | None = None) -> float:
    """Value at the end of ``years`` with start-of-month instalments."""
    amounts = schedule(monthly, years, step_up, pause)
    r = monthly_rate(annual)
    n = len(amounts)
    growth = (1 + r) ** (n - np.arange(n))
    return float(amounts @ growth)


def path(monthly: float, years: int, annual: float, step_up: float = 0.0,
         pause: tuple[int, int] | None = None) -> np.ndarray:
    """Month-end value for every month (for the chart)."""
    amounts = schedule(monthly, years, step_up, pause)
    r = monthly_rate(annual)
    out, v = np.empty(len(amounts)), 0.0
    for i, a in enumerate(amounts):
        v = (v + a) * (1 + r)
        out[i] = v
    return out


def required_monthly(goal: float, years: int, annual: float, step_up: float = 0.0,
                     pause: tuple[int, int] | None = None) -> float:
    """Starting monthly amount that reaches ``goal`` under an assumed return."""
    return goal / future_value(1.0, years, annual, step_up, pause)


def goal_in_future_money(goal_today: float, years: int, inflation: float) -> float:
    """A goal stated at today's prices, grown by assumed inflation."""
    return goal_today * (1 + inflation) ** years


@dataclass
class SipPlan:
    """Inputs and computed outputs of one SIP planner run. Every value is HYPOTHETICAL."""

    monthly: float
    years: int
    returns: tuple[float, ...] = DEFAULT_RETURNS
    step_up: float = 0.0
    inflation: float = 0.0
    pause: tuple[int, int] | None = None
    goal: float | None = None  # at today's prices when inflation > 0
    currency: str = "₹"
    values: dict[float, float] = field(init=False)
    needed: dict[float, float] = field(init=False)

    def __post_init__(self) -> None:
        self.values = {r: future_value(self.monthly, self.years, r, self.step_up, self.pause)
                       for r in self.returns}
        target = self.goal_nominal
        self.needed = ({r: required_monthly(target, self.years, r, self.step_up, self.pause)
                        for r in self.returns} if target else {})

    @property
    def invested(self) -> float:
        """Total paid in."""
        return float(schedule(self.monthly, self.years, self.step_up, self.pause).sum())

    @property
    def goal_nominal(self) -> float | None:
        """The goal in future money (inflation applied)."""
        if not self.goal:
            return None
        return goal_in_future_money(self.goal, self.years, self.inflation)

    def table(self) -> list[dict]:
        """One row per assumed return: projected value and (goal mode) monthly needed."""
        rows = []
        for r in self.returns:
            row = {"Assumed return (illustrative)": f"{r:.1%}", "Invested": round(self.invested),
                   "Projected value": round(self.values[r])}
            if self.needed:
                row["Monthly needed for goal"] = round(self.needed[r])
            if self.inflation:
                row["Value in today's money"] = round(self.values[r] / (1 + self.inflation) ** self.years)
            rows.append(row)
        return rows

    def facts(self) -> list[str]:
        """Facts for Explain / Show sources (inputs first, then outputs)."""
        c = self.currency
        f = [f"Monthly amount: {c}{self.monthly:,.0f} for {self.years} years",
             f"Step-up: {self.step_up:.0%} a year; inflation: {self.inflation:.1%}; "
             f"pause: {self.pause or 'none'}",
             f"Invested: {c}{self.invested:,.0f}"]
        for r in self.returns:
            f.append(f"Assumed {r:.0%} (illustrative, not a forecast): {c}{self.values[r]:,.0f}")
        if self.needed:
            f.append(f"Goal: {c}{self.goal:,.0f} today = {c}{self.goal_nominal:,.0f} then")
            f += [f"Monthly needed at {r:.0%}: {c}{v:,.0f}" for r, v in self.needed.items()]
        return f

    def to_record(self) -> dict:
        """What Save plan stores (with today's date added by the store)."""
        return {"kind": "sip", "monthly": self.monthly, "years": self.years,
                "returns": list(self.returns), "step_up": self.step_up,
                "inflation": self.inflation, "pause": self.pause, "goal": self.goal,
                "currency": self.currency, "values": {str(k): v for k, v in self.values.items()},
                "invested": self.invested, "label": "illustrative assumptions"}


def averaging(navs: list[float], amount: float) -> dict[str, float]:
    """Rupee-cost averaging arithmetic for a fixed amount each month."""
    units = [amount / n for n in navs]
    total = sum(units)
    return {"units": total, "average_cost": amount * len(navs) / total,
            "average_nav": sum(navs) / len(navs), "value_at_last": total * navs[-1]}
