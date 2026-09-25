"""Futures & Roll (Chapter 24): specs, MTM ledger, margin call distance, basis, roll, OI, USDINR.

Every number is computed here; the AI only narrates. Lot sizes and multipliers come
from ``plugai_trade.reference``. A few contracts the book uses (MCX crude and gold,
CME micro WTI/gold, E-mini parents) are not yet rows in the reference tables; until
they are, ``PENDING_SPECS`` supplies the book's printed values and every screen marks
them "† pending reference row".
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import polars as pl

from . import costs, reference
from .options.chain import fmt_money, fmt_num

# Book values (Ch 24 specs box) for contracts missing from reference/tables.yaml.
PENDING_SPECS: dict[str, dict] = {
    "CRUDEOIL": {"market": "IN", "exchange": "MCX", "lot": 100, "unit": "barrel",
                 "settlement": "cash", "expiry": "monthly (MCX calendar)"},
    "CRUDEOILM": {"market": "IN", "exchange": "MCX", "lot": 10, "unit": "barrel",
                  "settlement": "cash", "expiry": "monthly (MCX calendar)"},
    "GOLD": {"market": "IN", "exchange": "MCX", "lot": 1000, "unit": "gram",
             "settlement": "delivery", "expiry": "bi-monthly (MCX calendar)"},
    "MCL": {"market": "US", "exchange": "NYMEX", "multiplier": 100, "unit": "barrel",
            "settlement": "cash", "expiry": "monthly"},
    "MGC": {"market": "US", "exchange": "COMEX", "multiplier": 10, "unit": "troy ounce",
            "settlement": "delivery", "expiry": "bi-monthly"},
    "CL": {"market": "US", "exchange": "NYMEX", "multiplier": 1000, "unit": "barrel",
           "settlement": "physical delivery", "expiry": "monthly"},
    "ES": {"market": "US", "exchange": "CME", "multiplier": 50, "unit": "index point",
           "settlement": "cash", "expiry": "quarterly (Mar/Jun/Sep/Dec)"},
}

# Chapter 24's worked paths (synthetic settlements), used by "Replay path" → Book sample.
BOOK_PATHS: dict[str, dict] = {
    "NIFTY": {"entry": 25000.0, "cash": 240000.0,
              "settles": [25060, 24910, 24780, 24560, 24620, 24850, 24990, 25130, 25080, 25210]},
    "MES": {"entry": 5600.0, "cash": 3000.0, "initial": 2400.0, "maintenance": 2200.0,
            "settles": [5572, 5530, 5480, 5455, 5430]},
}

QUARTERLY = {"MES", "MNQ", "ES", "NQ"}
OI_LABELS = ("Long build-up", "Short covering", "Short build-up", "Long unwinding")


# ============================================================== contract specs
@dataclass(frozen=True)
class ContractSpec:
    """The four numbers' inputs: multiplier, currency, settlement and expiry rule."""

    symbol: str
    market: str
    exchange: str
    multiplier: float
    unit: str
    settlement: str
    expiry: str
    source: str
    pending: bool = False

    @property
    def currency(self) -> str:
        return "₹" if self.market == "IN" else "$"


def spec(symbol: str) -> ContractSpec:
    """Contract spec from the reference tables (or a pending book row, flagged)."""
    s = symbol.upper().replace(" FUT", "")
    row = reference.lookup(f"india.contracts.{s}")
    if row:
        lot = row.get("lot") or row.get("lot_usd") or 1
        return ContractSpec(s, "IN", row.get("exchange", "NSE"), float(lot),
                            "USD" if "lot_usd" in row else "index point",
                            str(row.get("settlement", "")), str(row.get("expiry", "")),
                            f"reference as of {reference.as_of()}")
    row = reference.lookup(f"us.contracts.{s}")
    if row:
        return ContractSpec(s, "US", "CME" if s in QUARTERLY else "Cboe",
                            float(row.get("multiplier", 100)), "index point",
                            str(row.get("settlement", "cash")), str(row.get("expiry", "")),
                            f"reference as of {reference.as_of()}")
    if s in PENDING_SPECS:
        p = PENDING_SPECS[s]
        return ContractSpec(s, p["market"], p["exchange"], float(p.get("lot") or p["multiplier"]),
                            p["unit"], p["settlement"], p["expiry"],
                            "† pending reference row (book Ch 24 value)", pending=True)
    raise KeyError(f"{symbol} is not in the Contract Table")


@dataclass(frozen=True)
class Position:
    """Notional, margin, leverage and the value of one point for a futures position."""

    symbol: str
    market: str
    price: float
    qty: int
    multiplier: float
    margin: float

    @property
    def notional(self) -> float:
        return self.price * self.multiplier * self.qty

    @property
    def leverage(self) -> float:
        return self.notional / self.margin if self.margin else float("inf")

    @property
    def one_point(self) -> float:
        return self.multiplier * self.qty

    def facts(self) -> list[str]:
        m = self.market
        return [f"Contract: {self.qty} × {self.symbol} at {fmt_num(self.price, m, 2)}",
                f"Notional: {fmt_money(self.notional, m)}",
                f"Margin (illustrative): {fmt_money(self.margin, m)}",
                f"Leverage: {self.leverage:.1f}×",
                f"One point: {fmt_money(self.one_point, m, 2 if self.one_point % 1 else 0)}"]


def position(symbol: str, price: float, qty: int = 1, margin_rate: float = 0.12,
             initial: float | None = None) -> Position:
    """Four numbers for a position; margin = ``initial`` per contract or ``margin_rate`` × notional."""
    sp = spec(symbol)
    margin = initial * qty if initial is not None else margin_rate * price * sp.multiplier * qty
    return Position(sp.symbol, sp.market, float(price), qty, sp.multiplier, margin)


# ============================================================== MTM ledger
@dataclass
class Shock:
    """A gap applied to the ledger's latest state."""

    gap: float
    price: float
    mtm: float
    cash: float
    margin_required: float
    shortfall: float
    market: str

    def facts(self) -> list[str]:
        m = self.market
        return [f"Shock {self.gap * 100:+.1f}% → price {fmt_num(self.price, m, 2)}",
                f"MTM hit: {fmt_money(self.mtm, m)}",
                f"Cash after shock: {fmt_money(self.cash, m)}",
                f"Margin required after shock: {fmt_money(self.margin_required, m)}",
                ("Short of margin by " + fmt_money(self.shortfall, m)) if self.shortfall > 0
                else "Still covered after the shock"]


@dataclass
class Ledger:
    """Day-by-day mark-to-market ledger for one futures position."""

    symbol: str
    market: str
    entry: float
    qty: int
    side: int
    multiplier: float
    start_cash: float
    margin_rate: float | None
    initial: float | None
    maintenance: float | None
    rows: pl.DataFrame = field(repr=False)

    @property
    def units(self) -> float:
        return self.multiplier * self.qty

    def required(self, price: float) -> float:
        """Margin required at a price (percentage model) or the initial margin (fixed model)."""
        if self.margin_rate is not None:
            return self.margin_rate * price * self.units
        return float(self.initial or 0.0) * self.qty

    def upto(self, day: int) -> Ledger:
        """The ledger as it stood after ``day`` sessions."""
        return Ledger(**{**self.__dict__, "rows": self.rows.head(day)})

    @property
    def last(self) -> dict:
        return self.rows.row(-1, named=True) if self.rows.height else {
            "settle": self.entry, "cash": self.start_cash, "free_cash": self.start_cash - self.required(self.entry)}

    def move_to_margin_call(self) -> tuple[float, float]:
        """(points, price) of the move that uses up free cash (maintenance floor for fixed margin)."""
        last = self.last
        price = float(last["settle"])
        if self.margin_rate is not None:
            per_point = self.units * (1 - self.side * self.margin_rate)
            room = float(last["cash"]) - self.required(price)
        else:
            per_point = self.units
            room = float(last["cash"]) - float(self.maintenance or 0.0) * self.qty
        pts = room / per_point if per_point else float("inf")
        return -self.side * pts, price - self.side * pts

    def shock(self, gap: float) -> Shock:
        """Apply a gap (fraction, e.g. −0.03) to the latest settlement."""
        last = self.last
        p0 = float(last["settle"])
        p1 = p0 * (1 + gap)
        mtm = self.side * (p1 - p0) * self.units
        cash = float(last["cash"]) + mtm
        if self.margin_rate is not None:
            need = self.required(p1)
            short = max(need - cash, 0.0)
        else:
            need = float(self.initial or 0.0) * self.qty
            short = max(need - cash, 0.0) if cash < float(self.maintenance or 0) * self.qty else 0.0
        return Shock(gap, round(p1, 2), round(mtm, 2), round(cash, 2), round(need, 2),
                     round(short, 2), self.market)

    def facts(self) -> list[str]:
        m = self.market
        flows = self.rows["mtm"].abs().sum() if self.rows.height else 0.0
        pnl = float(self.rows["mtm"].sum()) if self.rows.height else 0.0
        out = [f"Position: {'long' if self.side > 0 else 'short'} {self.qty} × {self.symbol} "
               f"from {fmt_num(self.entry, m, 2)} ({fmt_num(self.multiplier, m)} per point)",
               f"Sessions: {self.rows.height}",
               f"Net P&L: {fmt_money(pnl, m)}; cash moved in and out: {fmt_money(flows, m)}"]
        if self.rows.height:
            worst = self.rows.sort("free_cash").row(0, named=True)
            out.append(f"Worst free cash: {fmt_money(worst['free_cash'], m)} on day {worst['day']}")
            last = self.last
            out.append(f"Latest: settle {fmt_num(last['settle'], m, 2)}, MTM {fmt_money(last['mtm'], m)}, "
                       f"free cash {fmt_money(last['free_cash'], m)} ({last['status']})")
        pts, price = self.move_to_margin_call()
        out.append(f"Move to margin call: {pts:+,.0f} points (price {fmt_num(price, m, 2)})")
        return out


def mtm_ledger(symbol: str, entry: float, settles: Iterable[float], cash: float, qty: int = 1,
               side: str = "long", margin_rate: float | None = 0.12, initial: float | None = None,
               maintenance: float | None = None) -> Ledger:
    """Replay settlements: change, MTM cash flow, cash, margin required, free cash, status.

    India style: ``margin_rate`` × notional. US style: pass ``initial`` and ``maintenance``
    per contract; a call restores the account to the initial level.
    """
    sp = spec(symbol)
    sgn = 1 if side == "long" else -1
    fixed = initial is not None
    led = Ledger(sp.symbol, sp.market, float(entry), qty, sgn, sp.multiplier, float(cash),
                 None if fixed else margin_rate, initial, maintenance if fixed else None,
                 pl.DataFrame())
    rows, prev, bal = [], float(entry), float(cash)
    for i, px in enumerate(settles, start=1):
        px = float(px)
        mtm = sgn * (px - prev) * led.units
        bal += mtm
        need = led.required(px)
        free = bal - (float(maintenance) * qty if fixed else need)
        if fixed:
            status = (f"call: add {fmt_money(need - bal, sp.market)}" if free < 0
                      else "at initial" if abs(bal - need) < 1e-9
                      else f"above {fmt_money(float(maintenance) * qty, sp.market)}")
        else:
            status = f"call: add {fmt_money(-free, sp.market)}" if free < 0 else "covered"
        rows.append({"day": i, "settle": px, "change": px - prev, "mtm": round(mtm, 2),
                     "cash": round(bal, 2), "margin_required": round(need, 2),
                     "free_cash": round(free, 2), "status": status})
        prev = px
    led.rows = pl.DataFrame(rows) if rows else pl.DataFrame(
        schema={"day": pl.Int64, "settle": pl.Float64, "change": pl.Float64, "mtm": pl.Float64,
                "cash": pl.Float64, "margin_required": pl.Float64, "free_cash": pl.Float64,
                "status": pl.Utf8})
    return led


def synthetic_settles(symbol: str, start: float, sessions: int = 10, vol: float = 0.009,
                      seed: int = 24) -> list[float]:
    """A seeded synthetic settlement path (for Replay path when no history is loaded)."""
    rng = np.random.default_rng(seed + sum(map(ord, symbol)))
    path = start * np.exp(np.cumsum(rng.normal(0, vol, sessions)))
    return [round(float(x), 2) for x in path]


# ============================================================== basis & fair value
def fair_value(spot: float, days: float, rate: float = 0.065, dividend_yield: float = 0.013) -> float:
    """Cost-of-carry fair futures price: spot × (1 + (r − q) × days ÷ 365)."""
    return spot * (1 + (rate - dividend_yield) * days / 365.0)


def basis_label(basis: float, fair: float, tolerance: float = 5.0) -> str:
    """Premium / discount to fair value — a description, not a signal."""
    gap = basis - fair
    if abs(gap) <= tolerance:
        return "near fair value"
    return "premium to fair value" if gap > 0 else "discount to fair value"


def basis_series(symbol: str = "NIFTY", sessions: int = 22, rate: float = 0.065,
                 dividend_yield: float = 0.013, seed: int = 24, market: str = "IN") -> pl.DataFrame:
    """Synthetic convergence: spot from the data layer, futures = fair + noise that fades to expiry."""
    from . import data

    bars = data.get(symbol, market=market, source="synthetic")
    spot = bars["close"].tail(sessions + 1).to_numpy()
    dates = bars["date"].tail(sessions + 1).to_list()
    days_left = np.array([round((sessions - i) * 7 / 5) for i in range(sessions + 1)], float)
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, 8, sessions + 1) * (days_left / max(days_left[0], 1))
    fair = spot * (rate - dividend_yield) * days_left / 365.0
    fut = spot + fair + noise
    fut[-1] = spot[-1]
    return pl.DataFrame({"date": dates, "days_left": days_left, "spot": spot.round(2),
                         "futures": fut.round(2), "basis": (fut - spot).round(2),
                         "fair_basis": fair.round(2)})


# ============================================================== roll calendar
def _holidays() -> set[date]:
    raw = reference.lookup("india.holidays", []) or []
    return {date.fromisoformat(str(d)) for d in raw}


def _prev_business_day(d: date, holidays: set[date]) -> date:
    while d.weekday() >= 5 or d in holidays:
        d -= timedelta(days=1)
    return d


def last_weekday(year: int, month: int, weekday: int) -> date:
    """Last given weekday (0 = Monday) of a month."""
    d = date(year, month, calendar.monthrange(year, month)[1])
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def third_friday(year: int, month: int) -> date:
    """Third Friday of a month (CME equity-index last trading day)."""
    first = date(year, month, 1)
    return first + timedelta(days=(4 - first.weekday()) % 7 + 14)


def expiries(symbol: str, n: int = 3, after: date | None = None) -> list[date]:
    """Next ``n`` expiries: India monthly last Tuesday (holiday-adjusted when the reference
    lists holidays), US equity-index micros quarterly third Friday."""
    s = symbol.upper().replace(" FUT", "")
    start = after or date.today()
    out: list[date] = []
    y, m = start.year, start.month
    quarterly = s in QUARTERLY
    hol = _holidays()
    while len(out) < n:
        if not quarterly or m in (3, 6, 9, 12):
            d = third_friday(y, m) if quarterly else _prev_business_day(last_weekday(y, m, 1), hol)
            if d >= start:
                out.append(d)
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def roll_window(expiry: date, days_before: int = 5, length: int = 3) -> tuple[date, date]:
    """Business-day window that opens ``days_before`` sessions before expiry."""
    d, count = expiry, 0
    while count < days_before:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            count += 1
    end, count = d, 1
    while count < length:
        end += timedelta(days=1)
        if end.weekday() < 5:
            count += 1
    return d, min(end, expiry - timedelta(days=1))


@dataclass
class RollPlan:
    """What a roll costs: the calendar spread (not a fee) and the itemised round trip (a cost)."""

    symbol: str
    market: str
    near: float
    next: float
    spot: float
    days_near: float
    days_next: float
    costs: dict[str, float]
    rate: float = 0.065
    dividend_yield: float = 0.013

    @property
    def spread(self) -> float:
        return self.next - self.near

    @property
    def fair_spread(self) -> float:
        return (fair_value(self.spot, self.days_next, self.rate, self.dividend_yield)
                - fair_value(self.spot, self.days_near, self.rate, self.dividend_yield))

    def facts(self) -> list[str]:
        m = self.market
        out = [f"Near: {fmt_num(self.near, m, 2)}; next: {fmt_num(self.next, m, 2)}; spot {fmt_num(self.spot, m, 2)}",
               f"Calendar spread: {self.spread:+,.2f} points (not a fee)",
               f"Fair spread from carry: {self.fair_spread:+,.2f} points",
               f"Roll round-trip cost: {fmt_money(self.costs['total'], m, 2)}"]
        out += [f"  {k}: {fmt_money(v, m, 2)}" for k, v in self.costs.items() if k != "total" and v]
        return out


def roll_cost(symbol: str, near: float, nxt: float, spot: float, days_near: float = 5,
              qty: int = 1, side: str = "long", slippage_points: float = 0.0) -> RollPlan:
    """Itemised roll cost from the dated cost tables (close near month, open next month)."""
    sp = spec(symbol)
    units = sp.multiplier * qty
    if side == "long":
        buy, sell = nxt * units, near * units
    else:
        buy, sell = near * units, nxt * units
    items = (costs.india_round_trip(buy, sell, "futures") if sp.market == "IN"
             else costs.us_round_trip(buy, sell))
    items = dict(items)
    if slippage_points:
        items["slippage"] = round(2 * slippage_points * units, 2)
        items["total"] = round(items["total"] + items["slippage"], 2)
    days_next = days_near + (91 if sp.symbol in QUARTERLY else 28)
    return RollPlan(sp.symbol, sp.market, near, nxt, spot, days_near, days_next, items)


# ============================================================== continuous series
def contract_series(symbol: str = "NIFTY", months: int = 3, market: str = "IN", seed: int = 24,
                    roll_days_before: int = 5, rate: float = 0.065,
                    dividend_yield: float = 0.013) -> pl.DataFrame:
    """Synthetic front-month futures joined end to end and back-adjusted.

    Columns: date, contract, joined, adjusted, roll (True on the first day of a new contract).
    Back-adjustment (difference method) shifts every earlier segment by each roll-date spread,
    so the roll jump disappears while day-to-day changes are kept.
    """
    from . import data

    bars = data.get(symbol.replace(" FUT", ""), market=market, source="synthetic")
    last = bars["date"][-1]
    exps = expiries(symbol, months + 1, after=last - timedelta(days=31 * months))
    bars = bars.filter(pl.col("date") > exps[0] - timedelta(days=31))
    rng = np.random.default_rng(seed)
    carry = rate - dividend_yield
    recs = []
    idx = 0
    for d, s in zip(bars["date"].to_list(), bars["close"].to_list()):
        while idx < len(exps) - 1 and d > roll_window(exps[idx], roll_days_before)[0]:
            idx += 1
        exp = exps[idx]
        near_price = s * (1 + carry * max((exp - d).days, 0) / 365.0) + rng.normal(0, 3)
        recs.append({"date": d, "contract": exp.strftime("%b %Y"), "joined": round(near_price, 2)})
    df = pl.DataFrame(recs)
    roll = (df["contract"] != df["contract"].shift(1)).fill_null(False)
    df = df.with_columns(roll.alias("roll"))
    # Gap at each roll = new contract's first price − old contract's last price minus the day's move
    # (approximated by the spot move); adjust earlier segments by the cumulative gaps.
    joined = df["joined"].to_numpy()
    spot = bars["close"].to_numpy()[: len(joined)]
    adj = np.zeros(len(joined))
    for i in np.where(df["roll"].to_numpy())[0]:
        if i == 0:
            continue
        gap = (joined[i] - joined[i - 1]) - (spot[i] - spot[i - 1])
        adj[:i] += gap
    return df.with_columns(pl.Series("adjusted", (joined + adj).round(2)))


# ============================================================== open interest
def oi_label(price_change: float, oi_change: float) -> str:
    """The commentary label for one day: a description, never a signal."""
    if oi_change == 0 or price_change == 0:
        return "No clear label"
    if price_change > 0:
        return "Long build-up" if oi_change > 0 else "Short covering"
    return "Short build-up" if oi_change > 0 else "Long unwinding"


def roll_check(near_oi_change: float, next_oi_change: float) -> str:
    """Is an OI change a roll (near falling, next rising) or new positions?"""
    if near_oi_change < 0 < next_oi_change:
        return "Looks like a roll: near month falling, next month rising"
    if near_oi_change > 0 and next_oi_change > 0:
        return "New positions in both months"
    return "No roll pattern"


def oi_snapshot(symbols: Iterable[str], seed: int = 24) -> pl.DataFrame:
    """Synthetic near/next-month price and OI changes per contract, labelled in code."""
    recs = []
    for sym in symbols:
        rng = np.random.default_rng(seed + sum(map(ord, sym)))
        px, oi_near, oi_next = rng.normal(0, 0.8), rng.normal(0, 5), rng.normal(2, 4)
        recs.append({"contract": sym, "price_change_pct": round(float(px), 2),
                     "oi_change_near_pct": round(float(oi_near), 2),
                     "oi_change_next_pct": round(float(oi_next), 2),
                     "label": oi_label(px, oi_near), "roll_check": roll_check(oi_near, oi_next)})
    return pl.DataFrame(recs)


# ============================================================== USDINR split
@dataclass(frozen=True)
class USDINRSplit:
    """An MCX move divided into a benchmark part and a currency part (per unit and per lot)."""

    bench_from: float
    bench_to: float
    fx_from: float
    fx_to: float
    units: float
    residual: float = 0.0

    @property
    def inr_from(self) -> float:
        return self.bench_from * self.fx_from

    @property
    def inr_to(self) -> float:
        return self.bench_to * self.fx_to

    @property
    def benchmark_part(self) -> float:
        """Benchmark move at yesterday's rate, per unit (₹)."""
        return (self.bench_to - self.bench_from) * self.fx_from

    @property
    def currency_part(self) -> float:
        """Rupee move applied to today's benchmark, per unit (₹)."""
        return self.bench_to * (self.fx_to - self.fx_from)

    def facts(self) -> list[str]:
        u = self.units
        return [f"Benchmark: ${self.bench_from:,.2f} → ${self.bench_to:,.2f}",
                f"USDINR: {self.fx_from:.2f} → {self.fx_to:.2f} ({(self.fx_to / self.fx_from - 1) * 100:+.2f}%)",
                f"Rupee-equivalent price: {fmt_money(self.inr_from, 'IN')} → {fmt_money(self.inr_to, 'IN')}",
                f"Benchmark part: {fmt_money(self.benchmark_part, 'IN', 2)}/unit, "
                f"{fmt_money(self.benchmark_part * u, 'IN')}/lot",
                f"Currency part: {fmt_money(self.currency_part, 'IN', 2)}/unit, "
                f"{fmt_money(self.currency_part * u, 'IN')}/lot",
                f"Other (duty, local premium, basis): {fmt_money(self.residual, 'IN', 2)}/unit"]


def usdinr_split(bench_from: float, bench_to: float, fx_from: float, fx_to: float,
                 symbol: str = "CRUDEOIL", mcx_from: float | None = None,
                 mcx_to: float | None = None) -> USDINRSplit:
    """Split a rupee commodity move into benchmark and currency parts (plus any residual)."""
    units = spec(symbol).multiplier
    resid = 0.0
    if mcx_from is not None and mcx_to is not None:
        resid = (mcx_to - mcx_from) - ((bench_to * fx_to) - (bench_from * fx_from))
    return USDINRSplit(bench_from, bench_to, fx_from, fx_to, units, round(resid, 2))


# ============================================================== contract table
def contract_rows() -> list[dict]:
    """Rows for Derivatives › Contract Table, straight from the reference tables."""
    rows = []
    asof = reference.as_of()
    for sym, r in (reference.lookup("india.contracts", {}) or {}).items():
        rows.append({"Symbol": sym, "Market": "IN", "Exchange": r.get("exchange", ""),
                     "Currency": "USD" if "lot_usd" in r else "INR",
                     "Lot / multiplier": r.get("lot") if r.get("lot") is not None
                     else (f"USD {r['lot_usd']:,}" if "lot_usd" in r else "exchange-set"),
                     "Expiry": r.get("expiry", ""), "Settlement": r.get("settlement", ""),
                     "Exposure required": bool(r.get("exposure_required", False)),
                     "Effective from": r.get("effective_from", ""), "Source": r.get("source", ""),
                     "As of": asof})
    for sym, r in (reference.lookup("us.contracts", {}) or {}).items():
        rows.append({"Symbol": sym, "Market": "US", "Exchange": "CME" if sym in QUARTERLY else "Cboe",
                     "Currency": "USD", "Lot / multiplier": r.get("multiplier"),
                     "Expiry": r.get("expiry", "daily / weekly / monthly listings"),
                     "Settlement": r.get("settlement", "cash"),
                     "Exposure required": False,
                     "Effective from": "", "Source": ("§1256" if r.get("sec_1256") else "")
                     + (f" · {r['style']}" if r.get("style") else ""), "As of": asof})
    for sym, p in PENDING_SPECS.items():
        rows.append({"Symbol": sym, "Market": p["market"], "Exchange": p["exchange"],
                     "Currency": "INR" if p["market"] == "IN" else "USD",
                     "Lot / multiplier": p.get("lot") or p.get("multiplier"),
                     "Expiry": p["expiry"], "Settlement": p["settlement"],
                     "Exposure required": False, "Effective from": "",
                     "Source": "† pending reference row (book Ch 24)", "As of": asof})
    return rows
