"""Fund holdings, look-through overlap, concentration and the expense-ratio audit.

Overlap between two funds = Σ over shared companies of the *smaller* weight.
The bundled sample funds are synthetic (names are categories, not real schemes);
Priya's five funds reproduce the Chapter 15 overlap matrix exactly
(A↔E 57 %, A↔B 40 %, C lowest), and her ₹12 lakh costs ₹10,680 a year more in
regular plans (weighted TER 1.53 %) than in direct plans (0.64 %).
"""

from __future__ import annotations

import csv
import io
import itertools
from dataclasses import dataclass, field

import polars as pl

SECTORS = ("Financials", "IT", "Energy", "Consumer staples", "Consumer discretionary",
           "Industrials", "Healthcare", "Materials", "Telecom", "Utilities")


@dataclass
class Fund:
    """A fund with its look-through holdings (company → weight in %, summing to 100)."""

    fund_id: str
    name: str
    category: str
    asset_class: str
    holdings: dict[str, float]
    sectors: dict[str, str] = field(default_factory=dict)
    ter_regular: float | None = None  # % a year
    ter_direct: float | None = None
    market: str = "IN"


def overlap(a: dict[str, float], b: dict[str, float]) -> float:
    """Share of money (%) the two funds have in the same companies."""
    return sum(min(w, b[c]) for c, w in a.items() if c in b)


def shared(a: dict[str, float], b: dict[str, float], top: int = 10) -> list[tuple[str, float]]:
    """The shared companies behind an overlap cell (hover text), largest first."""
    rows = [(c, min(w, b[c])) for c, w in a.items() if c in b]
    return sorted(rows, key=lambda r: -r[1])[:top]


def overlap_matrix(funds: list[Fund]) -> pl.DataFrame:
    """Square overlap matrix (%), rounded to whole points like the book's figure."""
    rows = []
    for f in funds:
        rows.append({"Fund": f.name, **{g.fund_id: round(overlap(f.holdings, g.holdings))
                                         for g in funds}})
    return pl.DataFrame(rows)


@dataclass
class LookThrough:
    """Concentration once every fund is opened up to its companies."""

    exposures: dict[str, float]  # company → money
    sectors: dict[str, float]  # sector → money
    total: float

    @property
    def companies(self) -> int:
        """Distinct companies held through all funds."""
        return len(self.exposures)

    def top(self, n: int = 10) -> list[tuple[str, float]]:
        """Largest companies as a share of the whole portfolio."""
        return [(c, v / self.total) for c, v in sorted(self.exposures.items(),
                                                        key=lambda kv: -kv[1])[:n]]

    @property
    def top10_share(self) -> float:
        """Share of the portfolio in the ten largest companies."""
        return sum(s for _, s in self.top(10))

    def facts(self) -> list[str]:
        """Facts for Explain."""
        big = self.top(1)
        f = [f"Look-through companies: {self.companies}",
             f"Largest single company: {big[0][0]} {big[0][1]:.1%}" if big else "No holdings",
             f"Top 10 companies: {self.top10_share:.1%} of the portfolio"]
        for s, v in sorted(self.sectors.items(), key=lambda kv: -kv[1])[:3]:
            f.append(f"Sector {s}: {v / self.total:.1%}")
        return f


def look_through(positions: list[tuple[Fund, float]],
                 direct: dict[str, tuple[float, str]] | None = None) -> LookThrough:
    """Open every fund up. ``positions`` = (fund, money); ``direct`` = shares held outright."""
    exp: dict[str, float] = {}
    sec: dict[str, float] = {}
    for fund, value in positions:
        for c, w in fund.holdings.items():
            money = value * w / 100
            exp[c] = exp.get(c, 0.0) + money
            s = fund.sectors.get(c, "Other")
            sec[s] = sec.get(s, 0.0) + money
    for c, (value, s) in (direct or {}).items():
        exp[c] = exp.get(c, 0.0) + value
        sec[s] = sec.get(s, 0.0) + value
    total = sum(v for _, v in positions) + sum(v for v, _ in (direct or {}).values())
    return LookThrough(exp, sec, total)


# ------------------------------------------------------------------ costs
@dataclass
class CostRow:
    """One fund in the Costs panel."""

    name: str
    plan: str
    value: float
    ter: float
    direct_ter: float | None

    @property
    def annual(self) -> float:
        """Rupees (or dollars) a year at the current TER."""
        return self.value * self.ter / 100

    @property
    def direct_annual(self) -> float | None:
        """The same money in the direct plan."""
        return None if self.direct_ter is None else self.value * self.direct_ter / 100

    @property
    def difference(self) -> float:
        """Annual difference, regular minus direct (0 when already direct)."""
        d = self.direct_annual
        return 0.0 if d is None else self.annual - d


@dataclass
class CostAudit:
    """Expense-ratio audit with the direct-plan equivalent of every regular plan."""

    rows: list[CostRow]
    currency: str = "₹"

    @property
    def total(self) -> float:
        """Portfolio value."""
        return sum(r.value for r in self.rows)

    @property
    def annual(self) -> float:
        """Fees a year now."""
        return sum(r.annual for r in self.rows)

    @property
    def direct_annual(self) -> float:
        """Fees a year if every regular plan were its direct equivalent."""
        return sum(r.direct_annual if r.direct_annual is not None else r.annual for r in self.rows)

    @property
    def weighted_ter(self) -> float:
        """Money-weighted TER now (%)."""
        return self.annual / self.total * 100

    @property
    def weighted_direct_ter(self) -> float:
        """Money-weighted TER in direct plans (%)."""
        return self.direct_annual / self.total * 100

    def frame(self) -> pl.DataFrame:
        """The Costs table."""
        return pl.DataFrame([{"Fund": r.name, "Plan": r.plan, "Value": round(r.value),
                              "TER %": r.ter, "Direct TER %": r.direct_ter,
                              "A year": round(r.annual),
                              "Direct, a year": None if r.direct_annual is None else round(r.direct_annual),
                              "Difference a year": round(r.difference)} for r in self.rows])

    def facts(self) -> list[str]:
        """Facts for Explain."""
        c = self.currency
        return [f"Portfolio value: {c}{self.total:,.0f}",
                f"Weighted TER now: {self.weighted_ter:.2f}% = {c}{self.annual:,.0f} a year",
                f"Weighted TER in direct plans: {self.weighted_direct_ter:.2f}% = "
                f"{c}{self.direct_annual:,.0f} a year",
                f"Annual difference: {c}{self.annual - self.direct_annual:,.0f}",
                "Switching can trigger capital-gains tax and exit loads: a judgment for you "
                "or your adviser"]


def cost_audit(positions: list[tuple[Fund, float, str]], currency: str = "₹") -> CostAudit:
    """``positions`` = (fund, money, plan) with plan 'Regular' or 'Direct' (or a US share class)."""
    rows = []
    for fund, value, plan in positions:
        if plan.lower() == "regular":
            rows.append(CostRow(fund.name, plan, value, fund.ter_regular or 0.0, fund.ter_direct))
        else:
            ter = fund.ter_direct if fund.ter_direct is not None else (fund.ter_regular or 0.0)
            rows.append(CostRow(fund.name, plan, value, ter, None))
    return CostAudit(rows, currency)


def fee_gap(amount: float, years: int, gross: float, fee_low: float, fee_high: float) -> tuple[float, float]:
    """End values with two fees on the same assumed gross return (all as fractions)."""
    return (amount * (1 + gross - fee_low) ** years, amount * (1 + gross - fee_high) ** years)


# ------------------------------------------------------------------ holdings files
def parse_holdings_csv(text: str, fund_id: str, name: str, asset_class: str = "Equity",
                       market: str = "IN") -> Fund:
    """A fund-house / AMFI monthly portfolio CSV: company, weight (%) and optional sector."""
    reader = csv.DictReader(io.StringIO(text))
    cols = {c.lower().strip(): c for c in reader.fieldnames or []}
    ccol = next((cols[k] for k in cols if k in ("company", "name", "holding", "security",
                                                 "name of the instrument", "issuer")), None)
    wcol = next((cols[k] for k in cols if "weight" in k or "% to nav" in k or k in ("%", "pct")), None)
    scol = next((cols[k] for k in cols if "sector" in k or "industry" in k), None)
    if not ccol or not wcol:
        raise ValueError("Holdings file needs a company column and a weight / % to NAV column.")
    holdings, sectors = {}, {}
    for r in reader:
        c = (r.get(ccol) or "").strip()
        w = str(r.get(wcol) or "").replace("%", "").replace(",", "").strip()
        if not c or not w:
            continue
        holdings[c] = holdings.get(c, 0.0) + float(w)
        if scol:
            sectors[c] = (r.get(scol) or "Other").strip()
    return Fund(fund_id, name, "Imported", asset_class, holdings, sectors, market=market)


# ------------------------------------------------------------------ bundled samples
# Blocks of companies shared by exactly these funds, with each fund's total weight
# in the block. Solved so every pairwise overlap equals the book's matrix.
_PRIYA_BLOCKS: list[tuple[str, float, int]] = [
    ("ABCDE", 22, 8), ("ABDE", 12, 5), ("ADE", 11, 4), ("ABE", 6, 3), ("AC", 2, 1),
    ("AE", 6, 2), ("BC", 10, 4), ("BE", 9, 3), ("CE", 5, 2), ("DE", 7, 3),
    ("A", 41, 20), ("B", 41, 20), ("C", 61, 30), ("D", 48, 22), ("E", 22, 11),
]
PRIYA_FUNDS = {  # id: (name, TER regular %, TER direct %, value ₹)
    "A": ("A · Large-cap", 1.70, 0.78, 300_000),
    "B": ("B · Flexi-cap", 1.76, 0.80, 250_000),
    "C": ("C · Large & Mid", 1.85, 0.86, 200_000),
    "D": ("D · ELSS", 1.80, 0.74, 150_000),
    "E": ("E · NIFTY 50 index", 0.82, 0.17, 300_000),
}


def _split(total: float, n: int, decay: float = 0.715) -> list[float]:
    """Split a block weight into ``n`` decreasing company weights that sum to ``total``."""
    raw = [decay ** i for i in range(n)]
    s = sum(raw)
    return [total * x / s for x in raw]


def _build(blocks: list[tuple[str, float, int]], ids: str, prefix: str) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {i: {} for i in ids}
    k = 0
    for members, weight, count in blocks:
        # the all-fund block is steeper so the look-through reads like the book:
        # largest company 8.7 %, top ten 36.3 % of Priya's portfolio
        for w in _split(weight, count, 0.6125 if len(members) == len(ids) else 0.715):
            k += 1
            name = f"{prefix} Co {k:03d}"
            for m in members:
                out[m][name] = w
    return out


def _sector(name: str) -> str:
    return SECTORS[int(name.split()[-1]) % len(SECTORS)]


def sample_funds_in() -> list[Fund]:
    """Priya's five synthetic equity funds (Chapter 15)."""
    hold = _build(_PRIYA_BLOCKS, "ABCDE", "Syn")
    funds = []
    for fid, (name, reg, dire, _value) in PRIYA_FUNDS.items():
        cat = name.split(" · ")[1]
        funds.append(Fund(fid, name, cat, "Equity", hold[fid], {c: _sector(c) for c in hold[fid]},
                          reg, dire, "IN"))
    funds.append(Fund("DEBT", "Short-duration debt fund", "Debt", "Debt", {"Govt bonds (synthetic)": 100.0},
                      {"Govt bonds (synthetic)": "Debt"}, 0.95, 0.35, "IN"))
    funds.append(Fund("GOLD", "Gold ETF", "Gold", "Gold", {"Gold (synthetic)": 100.0},
                      {"Gold (synthetic)": "Gold"}, 0.55, 0.55, "IN"))
    return funds


MARK_FUNDS = {
    "S": ("S&P 500 index fund (401k)", 0.04, None, "US large-cap blend"),
    "T": ("Total US market ETF (Roth IRA)", 0.03, None, "US total market"),
    "G": ("Large-cap growth ETF (brokerage)", 0.18, None, "US large-cap growth"),
}


def sample_funds_us() -> list[Fund]:
    """Mark's three synthetic US funds (Chapter 15): one bet across three accounts."""
    blocks = [("STG", 30, 10), ("ST", 38, 30), ("SG", 4, 3), ("TG", 4, 3), ("S", 28, 15),
              ("T", 28, 40), ("G", 62, 25)]
    hold = _build(blocks, "STG", "US")
    return [Fund(fid, name, cat, "US stocks", hold[fid], {c: _sector(c) for c in hold[fid]},
                 ter, None, "US") for fid, (name, ter, _d, cat) in MARK_FUNDS.items()] + [
        Fund("INTL", "International index fund", "International", "Intl", {"Intl basket": 100.0},
             {"Intl basket": "International"}, 0.07, None, "US"),
        Fund("BOND", "US bond index fund", "Bonds", "Bonds", {"US Treasury basket": 100.0},
             {"US Treasury basket": "Bonds"}, 0.05, None, "US")]


def catalogue(market: str) -> dict[str, Fund]:
    """Known funds for matching imported holdings (samples plus uploaded holdings files)."""
    funds = sample_funds_in() if market == "IN" else sample_funds_us()
    return {f.fund_id: f for f in funds}


def pairs_of(funds: list[Fund]) -> list[tuple[Fund, Fund]]:
    """Every unordered pair of funds."""
    return list(itertools.combinations(funds, 2))
