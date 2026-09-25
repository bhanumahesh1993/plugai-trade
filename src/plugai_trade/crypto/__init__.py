"""Portfolio › Crypto Monitor: funding, liquidation distance, basis, VDA ledger.

    from plugai_trade import crypto
    pos = crypto.Position("BTC", side="long", notional=500_000, leverage=10, entry=60_000)
    crypto.funding_tiles(pos, rate=0.0656 / 100)     # Funding/8h, Annualised, 30-day cost …
    crypto.liquidation_distance(10)                  # 0.095 → the book's 9.5 %

All arithmetic is here. Public data (prices, funding history) comes from
``Crypto public (CCXT)`` when ccxt is installed and the network answers; otherwise
the lab uses deterministic synthetic prints (the Chapter 25 month). Keys are
never needed and never used: the monitor is read-only and paper-only.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

import numpy as np
import polars as pl

from .. import data, reference

FIU_IND_LIST_URL = "https://fiuindia.gov.in/"  # official site; it publishes the registered-entity list
ALERT_TYPES = ("Funding", "Liquidation distance", "Price band", "Exchange notice")
DEFAULT_MAINTENANCE = 0.005  # model input from the book's worked example; each venue publishes its own tiers

# Chapter 25's synthetic month: 90 funding prints (% per 8 h), 3 a day for 30 days.
SAMPLE_FUNDING_PCT = (
    0.0064, 0.0135, 0.0108, 0.0087, 0.0122, 0.0077, 0.0152, 0.0114, 0.0099, 0.0119, 0.0074,
    0.0113, 0.0124, 0.0124, 0.0113, 0.0077, 0.0108, 0.007, 0.0106, 0.0088, 0.0084, 0.0119,
    0.0147, 0.0136, 0.0093, 0.0092, 0.008, 0.0089, 0.0105, 0.0112, 0.0092, 0.0102, 0.0076,
    0.009, 0.0256, 0.0376, 0.0466, 0.0549, 0.0626, 0.0656, 0.0672, 0.071, 0.0647, 0.063,
    0.0521, 0.0452, 0.0382, 0.0239, 0.0099, 0.0107, 0.0066, 0.0122, 0.0083, 0.0082, 0.0085,
    0.0102, 0.0085, 0.0086, 0.0111, 0.0105, 0.0128, 0.0118, 0.0127, 0.0075, 0.0007, -0.0068,
    -0.0122, -0.0182, -0.0162, -0.0118, -0.01, -0.0014, 0.0082, 0.0106, 0.0076, 0.0101, 0.009,
    0.0078, 0.0061, 0.0151, 0.0128, 0.0124, 0.0065, 0.012, 0.0093, 0.0073, 0.0088, 0.009,
    0.0136, 0.0104,
)
SCREENSHOT_PRINT = 40  # 1-based print of the day-12 spike shown in the book's screenshot


# ------------------------------------------------------------------ positions
@dataclass
class Position:
    """A watched (paper) perpetual or spot position."""

    symbol: str
    side: str = "long"  # long | short
    notional: float = 500_000.0
    leverage: float = 10.0
    entry: float = 60_000.0
    margin_mode: str = "isolated"
    venue: str = "synthetic"
    kind: str = "perpetual"  # perpetual | spot
    maintenance: float = DEFAULT_MAINTENANCE

    @property
    def margin(self) -> float:
        """Margin behind the position (notional ÷ leverage)."""
        return self.notional / self.leverage


def liquidation_distance(leverage: float, maintenance: float = DEFAULT_MAINTENANCE) -> float:
    """Adverse move to liquidation, isolated margin, fees and funding ignored: 1/L − mm."""
    if leverage <= 0:
        raise ValueError("leverage must be positive")
    return max(0.0, 1.0 / leverage - maintenance)


def liquidation_price(entry: float, leverage: float, side: str = "long",
                      maintenance: float = DEFAULT_MAINTENANCE) -> float:
    """Price at which the isolated position is closed by the venue (model)."""
    d = liquidation_distance(leverage, maintenance)
    return entry * (1 - d) if side == "long" else entry * (1 + d)


def liquidation_table(levs: tuple[float, ...] = (2, 5, 10, 20, 50), entry: float = 60_000,
                      notional: float = 500_000,
                      maintenance: float = DEFAULT_MAINTENANCE) -> pl.DataFrame:
    """The book's leverage table: fall to liquidation, liquidation price, margin."""
    return pl.DataFrame({
        "Leverage": [f"{lv:g}×" for lv in levs],
        "Fall to liquidation %": [round(liquidation_distance(lv, maintenance) * 100, 2) for lv in levs],
        "Liquidation price": [round(liquidation_price(entry, lv, "long", maintenance), 2) for lv in levs],
        "Margin": [round(notional / lv, 2) for lv in levs],
    })


# ------------------------------------------------------------------ funding
def funding_payment(notional: float, rate: float, side: str = "long") -> float:
    """One funding payment. Positive = you pay (long pays when the rate is positive)."""
    sign = 1 if side == "long" else -1
    return sign * notional * rate


def annualised(rate: float, times_per_day: int = 3) -> float:
    """Funding per interval × times a day × 365."""
    return rate * times_per_day * 365


def cost_over(notional: float, rate: float, days: int = 30, times_per_day: int = 3) -> float:
    """What the current print would cost if it stayed put for ``days`` (a projection)."""
    return notional * rate * times_per_day * days


def cumulative_cost(notional: float, rates: list[float] | np.ndarray,
                    side: str = "long") -> np.ndarray:
    """Running total of funding paid (negative = received) across prints."""
    return np.cumsum([funding_payment(notional, r, side) for r in rates])


@dataclass
class FundingTiles:
    """The six Crypto Monitor tiles, computed in code."""

    rate: float
    times_per_day: int
    notional: float
    leverage: float
    to_liquidation: float
    side: str
    currency: str = "₹"

    @property
    def annualised(self) -> float:
        """Annualised funding rate."""
        return annualised(self.rate, self.times_per_day)

    @property
    def cost_30d(self) -> float:
        """30-day cost at the current print."""
        return cost_over(self.notional, self.rate, 30, self.times_per_day) * (
            1 if self.side == "long" else -1)

    def tiles(self) -> dict[str, str]:
        """Tile label → display value, exactly as the screen shows them."""
        c = self.currency
        return {"Funding/8h": f"{self.rate * 100:.4f}%",
                "Annualised": f"≈ {self.annualised * 100:.1f}%",
                "30-day cost": f"{c}{self.cost_30d:,.0f}",
                "To liquidation": f"{'−' if self.side == 'long' else '+'}{self.to_liquidation * 100:.1f}%",
                "Notional": f"{c}{self.notional:,.0f}",
                "Leverage": f"{self.leverage:g}×"}

    def facts(self) -> list[str]:
        """Facts for Explain / Show sources."""
        c = self.currency
        return [f"Funding per 8 h: {self.rate * 100:.4f}%",
                f"Funding times per day: {self.times_per_day}",
                f"Annualised: {self.annualised * 100:.1f}% ({self.rate * 100:.4f}% × "
                f"{self.times_per_day} × 365)",
                f"30-day cost at this print ({self.side}): {c}{self.cost_30d:,.0f}",
                f"One payment: {c}{funding_payment(self.notional, self.rate, self.side):,.0f}",
                f"Notional: {c}{self.notional:,.0f}; leverage {self.leverage:g}×; margin "
                f"{c}{self.notional / self.leverage:,.0f}",
                f"Distance to liquidation (isolated, fees and funding ignored): "
                f"{self.to_liquidation * 100:.1f}%"]


def funding_tiles(pos: Position, rate: float, times_per_day: int = 3,
                  currency: str = "₹") -> FundingTiles:
    """Build the tiles for one position at the current funding print."""
    return FundingTiles(rate, times_per_day, pos.notional, pos.leverage,
                        liquidation_distance(pos.leverage, pos.maintenance), pos.side, currency)


def funding_history(symbol: str = "BTC", venue: str = "binance") -> tuple[pl.DataFrame, str]:
    """Funding prints (rate as a fraction). Returns (frame, provenance).

    Tries ccxt's public ``fetch_funding_rate_history``; on any failure (no ccxt,
    no network, venue without the endpoint) returns the book's synthetic month.
    """
    try:
        import ccxt  # optional extra: uv tool install 'plugai-trade[crypto]'
        ex = getattr(ccxt, venue)({"enableRateLimit": True, "timeout": 5000})
        rows = ex.fetch_funding_rate_history(f"{symbol}/USDT:USDT", limit=90)
        if rows:
            return pl.DataFrame({"print": list(range(1, len(rows) + 1)),
                                 "time": [r.get("datetime") for r in rows],
                                 "rate": [float(r["fundingRate"]) for r in rows]}), \
                f"Crypto public (CCXT) · {venue}"
    except Exception:  # optional source; fall back quietly to the offline sample
        pass
    return sample_funding(), "Synthetic · Chapter 25 month"


def sample_funding() -> pl.DataFrame:
    """The Chapter 25 synthetic month: 90 prints, 3 a day."""
    n = len(SAMPLE_FUNDING_PCT)
    return pl.DataFrame({"print": list(range(1, n + 1)),
                         "time": [f"day {i // 3 + 1} · {['00:00', '08:00', '16:00'][i % 3]}"
                                  for i in range(n)],
                         "rate": [r / 100 for r in SAMPLE_FUNDING_PCT]})


def price_history(symbol: str, market: str = "CRYPTO") -> pl.DataFrame:
    """Daily bars for a coin from the configured crypto chain, else synthetic."""
    try:
        return data.get(symbol, market=market)
    except Exception:
        return data.get(symbol, market=market, source="synthetic")


def quote(symbol: str, venue: str = "binance") -> tuple[float, float, str]:
    """(spot, perp, provenance). Public ccxt tickers when available, else synthetic.

    The synthetic perp sits a fixed 0.04 % above spot so the Basis column has a value
    to read; it carries no market information.
    """
    try:
        import ccxt
        ex = getattr(ccxt, venue)({"enableRateLimit": True, "timeout": 5000})
        spot = float(ex.fetch_ticker(f"{symbol}/USDT")["last"])
        perp = float(ex.fetch_ticker(f"{symbol}/USDT:USDT")["last"])
        return spot, perp, f"Crypto public (CCXT) · {venue}"
    except Exception:  # optional source; fall back to the offline series
        pass
    bars = data.get(symbol, market="CRYPTO", source="synthetic")
    spot = float(bars["close"][-1])
    return spot, spot * 1.0004, "Synthetic · offline"


def basis(perp_price: float, spot_price: float) -> float:
    """Perp's gap to spot as a fraction (the input behind the funding rate)."""
    return perp_price / spot_price - 1


# ------------------------------------------------------------------ alerts
def propose_alerts(pos: Position, funding_level: float = 0.0003, band_pct: float = 0.10,
                   market: str = "IN") -> list:
    """The four crypto alert types, prefilled from a position (``alerts.Alert``, status proposed).

    Funding, liquidation distance and price band come from ``alerts.from_crypto_monitor``;
    the exchange-notice alert watches the venue's status page. Inactive until Accept.
    """
    from .. import alerts

    position = {"symbol": pos.symbol, "entry": pos.entry, "leverage": pos.leverage,
                "side": pos.side, "market": market,
                "name": f"{pos.symbol} {pos.kind} · {pos.side} · {pos.venue}"}
    out = alerts.from_crypto_monitor(position, funding_level, band_pct, pos.maintenance)
    out.append(alerts.Alert(f"Exchange notice · {pos.venue}", symbol=pos.symbol, market=market,
                            kind="event", condition="new item", bar_size="daily close",
                            plan_name=position["name"]))
    return out


def alert_type(alert) -> str:
    """Book name (Funding, Liquidation distance, Price band, Exchange notice) of a proposed alert."""
    return {"funding": "Funding", "liquidation": "Liquidation distance",
            "price_band": "Price band", "event": "Exchange notice"}.get(alert.kind, alert.kind)


def send_to_alerts(proposed: list) -> list[int]:
    """Save proposed alerts for Paper Trading › Alerts (they stay inactive until Accept)."""
    from .. import alerts

    return [alerts.save(a).id for a in proposed]


# ------------------------------------------------------------------ India VDA ledger
@dataclass
class VdaRow:
    """One VDA sale. Gains and losses are kept apart and never netted."""

    trade: str
    asset: str
    bought: float
    sold: float
    tds: float | None = None
    date: str = ""

    @property
    def result(self) -> float:
        """Sale minus cost."""
        return self.sold - self.bought

    @property
    def expected_tds(self) -> float:
        """1% of the sale consideration (rate from the dated table)."""
        return self.sold * float(reference.lookup("india.tax.vda_tds"))


@dataclass
class VdaLedger:
    """Schedule-VDA-shaped ledger. A draft for your CA."""

    rows: list[VdaRow] = field(default_factory=list)
    cess: float = 0.0

    @property
    def gains(self) -> float:
        """Sum of positive results only."""
        return sum(r.result for r in self.rows if r.result > 0)

    @property
    def losses(self) -> float:
        """Sum of losses (recorded, never set off)."""
        return sum(r.result for r in self.rows if r.result < 0)

    @property
    def tds_total(self) -> float:
        """TDS deducted (as recorded, else 1% of each sale)."""
        return sum(r.tds if r.tds is not None else r.expected_tds for r in self.rows)

    def tax(self, netted: bool = False) -> float:
        """Tax at the dated VDA rate plus cess. ``netted=True`` shows what set-off would give."""
        base = self.gains + (self.losses if netted else 0.0)
        return max(0.0, base) * float(reference.lookup("india.tax.vda_rate")) * (1 + self.cess)

    @property
    def remaining(self) -> float:
        """Tax still to pay after the TDS credit."""
        return self.tax() - self.tds_total

    def frame(self) -> pl.DataFrame:
        """Rows with separate Gains and Losses columns."""
        return pl.DataFrame({
            "Trade": [r.trade for r in self.rows], "Asset": [r.asset for r in self.rows],
            "Bought": [r.bought for r in self.rows], "Sold": [r.sold for r in self.rows],
            "Gains": [max(r.result, 0.0) for r in self.rows],
            "Losses": [min(r.result, 0.0) for r in self.rows],
            "TDS 1%": [r.tds if r.tds is not None else r.expected_tds for r in self.rows]},
            schema_overrides={"Bought": pl.Float64, "Sold": pl.Float64, "Gains": pl.Float64,
                              "Losses": pl.Float64, "TDS 1%": pl.Float64})

    def facts(self) -> list[str]:
        """Facts for Explain (the AI explains rows; it never classifies)."""
        rate = float(reference.lookup("india.tax.vda_rate"))
        return [f"Sales: {len(self.rows)}",
                f"Gains (added): ₹{self.gains:,.0f}",
                f"Losses (recorded, not set off): ₹{self.losses:,.0f}",
                f"Taxable VDA income: ₹{self.gains:,.0f}",
                f"Tax at {rate:.0%} with {self.cess:.0%} cess: ₹{self.tax():,.0f}",
                f"TDS credit: ₹{self.tds_total:,.0f}",
                f"Remaining to pay: ₹{self.remaining:,.0f}",
                f"If losses could be netted: ₹{self.tax(netted=True):,.0f} "
                f"(no-set-off costs ₹{self.tax() - self.tax(netted=True):,.0f})",
                "Draft for your CA"]


def sample_ledger(cess: float = 0.0) -> VdaLedger:
    """Farhan's three synthetic sales from Chapter 25."""
    return VdaLedger([VdaRow("A", "BTC", 150_000, 200_000, 2_000),
                      VdaRow("B", "ETH", 80_000, 60_000, 600),
                      VdaRow("C", "BTC", 100_000, 112_000, 1_120)], cess)


def reconcile_tds(ledger: VdaLedger, statement: list[float], tol: float = 1.0) -> pl.DataFrame:
    """Match each sale's TDS to a 26AS/AIS amount; unmatched rows are flagged for your CA."""
    pool = list(statement)
    status, matched = [], []
    for r in ledger.rows:
        want = r.tds if r.tds is not None else r.expected_tds
        hit = next((x for x in pool if abs(x - want) <= tol), None)
        if hit is None:
            status.append("MISMATCH · ask CA")
            matched.append(None)
        else:
            pool.remove(hit)
            status.append("matched")
            matched.append(hit)
    out = pl.DataFrame({"Trade": [r.trade for r in ledger.rows],
                        "Ledger TDS": [r.tds if r.tds is not None else r.expected_tds
                                       for r in ledger.rows],
                        "26AS / AIS": matched, "Status": status},
                       schema_overrides={"Ledger TDS": pl.Float64, "26AS / AIS": pl.Float64})
    if pool:
        extra = pl.DataFrame({"Trade": ["(not in ledger)"] * len(pool), "Ledger TDS": [None] * len(pool),
                              "26AS / AIS": pool, "Status": ["MISMATCH · ask CA"] * len(pool)},
                             schema_overrides={"Ledger TDS": pl.Float64, "26AS / AIS": pl.Float64})
        out = pl.concat([out, extra])
    return out


def parse_statement_csv(text: str) -> list[float]:
    """TDS amounts from a 26AS / AIS export: the first numeric column named like 'tds'."""
    reader = csv.DictReader(io.StringIO(text))
    cols = reader.fieldnames or []
    col = next((c for c in cols if "tds" in c.lower() or "tax deducted" in c.lower()), None)
    if col is None:
        raise ValueError("No TDS column found (expected a header containing 'TDS').")
    return [float(str(r[col]).replace(",", "").replace("₹", "")) for r in reader if r[col]]


def _field(row: dict[str, str], *keys: str) -> float | None:
    """First non-empty numeric value among ``keys`` (commas allowed)."""
    for k in keys:
        v = row.get(k)
        if v not in (None, ""):
            return float(str(v).replace(",", ""))
    return None


def parse_trades_csv(text: str) -> list[VdaRow]:
    """Exchange trade-history CSV with columns asset, bought (cost), sold (sale), tds."""
    rows = []
    for i, r in enumerate(csv.DictReader(io.StringIO(text)), 1):
        low = {k.lower().strip(): v for k, v in r.items() if k}
        bought = _field(low, "bought", "cost", "buy value")
        sold = _field(low, "sold", "sale", "sell value")
        if bought is None or sold is None:
            continue
        rows.append(VdaRow(low.get("trade") or str(i), low.get("asset") or low.get("coin", "?"),
                           bought, sold, _field(low, "tds"), low.get("date", "")))
    return rows
