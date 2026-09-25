"""API routes: Derivatives › Futures & Roll (Chapter 24) and Derivatives › Contract Table.

Thin: every number comes from ``plugai_trade.futures`` / ``plugai_trade.reference``; store
writes mirror the classic pages.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...store import default as store
from .. import clean as _clean

router = APIRouter()

_DEFAULT = {"IN": "NIFTY", "US": "MES"}
_CHOICES = {"IN": ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "USDINR", "CRUDEOIL",
                   "CRUDEOILM", "GOLD"],
            "US": ["MES", "MNQ", "MCL", "MGC", "ES", "CL"]}
_BASIS = {"IN": ["NIFTY", "BANKNIFTY"], "US": ["SPY"]}
_ROLL = {"IN": ["NIFTY", "BANKNIFTY"], "US": ["MES", "MNQ"]}
_MARGIN = {"IN": ["NIFTY", "BANKNIFTY", "CRUDEOIL"], "US": ["MES", "MNQ", "MCL"]}


def _mkt(market: str) -> str:
    if market not in ("IN", "US"):
        raise HTTPException(400, "market must be IN or US")
    return market


def _spec(symbol: str):
    from ... import futures
    try:
        return futures.spec(symbol)
    except KeyError as exc:
        raise HTTPException(400, f"{symbol} is not in the Contract Table. Pick a listed contract.") from exc


def _unit(sp) -> str:
    """The dated table's own unit (barrel, gram) when it has one; the spec defaults to index point."""
    from ... import reference
    root = "india" if sp.market == "IN" else "us"
    unit = str(reference.lookup(f"{root}.contracts.{sp.symbol}.unit") or sp.unit)
    return {"bbl": "barrel", "oz": "troy ounce"}.get(unit, unit)


def _book_fill(symbol: str, market: str) -> dict[str, str]:
    """Exchange / settlement / expiry the dated row leaves out, from the book's Ch 24 specs box.

    Some reference rows (CL, MCL, MGC, CRUDEOIL…) carry only a lot or multiplier, so the
    spec falls back to generic values (Cboe, cash). The book's printed values fill those gaps,
    marked † like every pending value.
    """
    from ... import futures, reference
    p = futures.PENDING_SPECS.get(symbol.upper())
    if not p or p["market"] != market:
        return {}
    root = "india" if market == "IN" else "us"
    row = reference.lookup(f"{root}.contracts.{symbol.upper()}") or {}
    return {k: str(p[k]) for k in ("exchange", "settlement", "expiry") if k not in row and p.get(k)}


def _spot_of(symbol: str, mkt: str) -> float:
    """Same proxy as the classic page: index spot, or SPY × 10 for the S&P futures."""
    from ... import data
    base = symbol if symbol in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY") else (
        "SPY" if symbol in ("MES", "ES") else symbol)
    px = float(data.get(base, market=mkt, source="synthetic")["close"][-1])
    return px * 10 if symbol in ("MES", "ES") else px


# ================================================================== Futures & Roll
@router.get("/api/derivatives/choices")
def choices(market: str = "IN") -> dict[str, Any]:
    from ... import reference
    m = _mkt(market)
    return {"market": m, "default": _DEFAULT[m], "contracts": _CHOICES[m], "basis": _BASIS[m],
            "roll": _ROLL[m], "margin": _MARGIN[m], "as_of": reference.as_of()}


# ------------------------------------------------------------------ Contract tab
class ContractsIn(BaseModel):
    market: str = "IN"
    symbols: list[str]


@router.post("/api/derivatives/contracts")
def contracts(body: ContractsIn) -> dict[str, Any]:
    """Spec rows and the OI build-up snapshot for the contracts on the Contract tab."""
    from ... import futures
    from ...options.chain import fmt_num
    syms = [s.upper().replace(" FUT", "") for s in body.symbols] or [_DEFAULT[_mkt(body.market)]]
    rows, facts = [], []
    for sym in syms:
        sp = _spec(sym)
        unit = _unit(sp)
        fill = _book_fill(sym, sp.market)
        exchange = fill.get("exchange", sp.exchange)
        settlement = fill.get("settlement", sp.settlement)
        expiry = fill.get("expiry", sp.expiry)
        source = sp.source + (f" ({', '.join(fill)} from book Ch 24 †)" if fill else "")
        rows.append({"symbol": sym, "contract": f"{sym} FUT", "exchange": exchange,
                     "market": sp.market, "multiplier": sp.multiplier,
                     "multiplier_text": fmt_num(sp.multiplier, sp.market), "unit": unit,
                     "settlement": settlement, "expiry": expiry, "source": source,
                     "pending": sp.pending or bool(fill)})
        facts.append(f"{sym}: {fmt_num(sp.multiplier, sp.market)} per {unit}, "
                     f"{settlement}-settled, expiry {expiry or 'see exchange'} ({source})")
    oi = futures.oi_snapshot(syms)
    oi_rows = oi.to_dicts()
    facts += [f"{r['contract']}: price {r['price_change_pct']:+.2f}%, near OI "
              f"{r['oi_change_near_pct']:+.2f}%, next OI {r['oi_change_next_pct']:+.2f}% → "
              f"{r['label']}; {r['roll_check']}" for r in oi_rows]
    mcx = [r["symbol"] for r in rows if r["exchange"] == "MCX"]
    return _clean({"rows": rows, "oi": oi_rows, "facts": facts, "mcx": mcx})


class SplitIn(BaseModel):
    symbol: str = "CRUDEOIL"
    bench_from: float = 70.0
    bench_to: float = 70.0
    fx_from: float = 88.00
    fx_to: float = 88.80


@router.post("/api/derivatives/usdinr-split")
def usdinr_split(body: SplitIn) -> dict[str, Any]:
    """An MCX move divided into a benchmark part and a currency part."""
    from ... import futures
    from ...options.chain import fmt_money
    if _spec(body.symbol).exchange != "MCX":
        raise HTTPException(400, "The USDINR split applies to MCX contracts. Add CRUDEOIL first.")
    if body.fx_from <= 0 or body.fx_to <= 0:
        raise HTTPException(400, "USDINR must be above zero.")
    sp = futures.usdinr_split(body.bench_from, body.bench_to, body.fx_from, body.fx_to,
                              symbol=body.symbol)
    return _clean({"symbol": body.symbol.upper(), "units": sp.units,
                   "benchmark_part": sp.benchmark_part * sp.units,
                   "currency_part": sp.currency_part * sp.units,
                   "inr_from": sp.inr_from, "inr_to": sp.inr_to,
                   "tiles": {"Benchmark part / lot": fmt_money(sp.benchmark_part * sp.units, "IN"),
                             "Currency part / lot": fmt_money(sp.currency_part * sp.units, "IN"),
                             "Rupee price": f"{fmt_money(sp.inr_from, 'IN')} → {fmt_money(sp.inr_to, 'IN')}"},
                   "facts": sp.facts()})


# ------------------------------------------------------------------ Basis tab
class BasisIn(BaseModel):
    symbol: str = "NIFTY"
    market: str = "IN"
    rate_pct: float = 6.5
    dividend_pct: float = 1.3


@router.post("/api/derivatives/basis")
def basis(body: BasisIn) -> dict[str, Any]:
    """Synthetic convergence, the latest basis label and fair value for the next expiries."""
    from ... import futures
    m = _mkt(body.market)
    rate, div = body.rate_pct / 100, body.dividend_pct / 100
    try:
        df = futures.basis_series(body.symbol, rate=rate, dividend_yield=div, market=m)
    except Exception as exc:
        raise HTTPException(400, f"No synthetic series for {body.symbol}: {exc}") from exc
    recs = df.to_dicts()
    last = recs[-2] if len(recs) > 1 else recs[-1]
    label = futures.basis_label(last["basis"], last["fair_basis"])
    spot = float(recs[-1]["spot"])
    rows = []
    for exp in futures.expiries(body.symbol if m == "IN" else "MES", 3):
        days = (exp - date.today()).days
        fv = futures.fair_value(spot, days, rate, div)
        rows.append({"expiry": exp.isoformat(), "days": days, "spot": round(spot, 2),
                     "fair_value": round(fv, 2), "fair_basis": round(fv - spot, 2)})
    facts = [f"{r['expiry']}: fair value {r['fair_value']:,.2f}, fair basis {r['fair_basis']:+.2f} "
             f"({r['days']} days)" for r in rows] + [f"Latest basis reading: {label}"]
    return _clean({"series": recs, "label": label, "yesterday": last, "fair": rows,
                   "rate_pct": body.rate_pct, "dividend_pct": body.dividend_pct, "facts": facts})


# ------------------------------------------------------------------ Roll calendar tab
class RollIn(BaseModel):
    symbol: str = "NIFTY"
    market: str = "IN"
    before: int = 5
    spot: float | None = None
    near: float | None = None
    next: float | None = None
    slippage: float = 0.0


@router.post("/api/derivatives/roll")
def roll(body: RollIn) -> dict[str, Any]:
    """Next three expiries with roll windows, the itemised roll cost and the joined vs
    back-adjusted series."""
    from ... import futures
    m = _mkt(body.market)
    if not 1 <= body.before <= 10:
        raise HTTPException(400, "The roll window opens 1 to 10 sessions before expiry.")
    _spec(body.symbol)
    exps = futures.expiries(body.symbol, 3)
    cal = []
    for e in exps:
        w0, w1 = futures.roll_window(e, body.before)
        cal.append({"contract": f"{body.symbol} {e:%b %Y}", "expiry": e.isoformat(),
                    "window_from": w0.isoformat(), "window_to": w1.isoformat(),
                    "window": f"{w0:%d %b} – {w1:%d %b}"})
    base = _spot_of(body.symbol, m)
    defaults = {"spot": round(base, 2), "near": round(futures.fair_value(base, body.before), 2),
                "next": round(futures.fair_value(base, body.before + 28), 2)}
    spot = body.spot if body.spot is not None else defaults["spot"]
    near = body.near if body.near is not None else defaults["near"]
    nxt = body.next if body.next is not None else defaults["next"]
    plan = futures.roll_cost(body.symbol, near, nxt, spot, days_near=body.before,
                             slippage_points=body.slippage)
    series = futures.contract_series(body.symbol, market=m, roll_days_before=body.before)
    facts = plan.facts() + [f"{r['contract']}: expiry {r['expiry']}, window {r['window']}" for r in cal]
    return _clean({"calendar": cal, "defaults": defaults,
                   "inputs": {"spot": spot, "near": near, "next": nxt, "slippage": body.slippage},
                   "spread": plan.spread, "fair_spread": plan.fair_spread, "costs": plan.costs,
                   "series": series.select("date", "contract", "joined", "adjusted", "roll").to_dicts(),
                   "roll_dates": series.filter(series["roll"])["date"].to_list()[1:],
                   "facts": facts})


class RollActionIn(BaseModel):
    symbol: str = "NIFTY"
    market: str = "IN"
    before: int = 5


@router.post("/api/derivatives/roll/alert")
def roll_alert(body: RollActionIn) -> dict[str, Any]:
    """Set roll alert: goes to Paper Trading › Alerts for the window's first day (SIMULATED)."""
    from ... import futures
    _spec(body.symbol)
    exp = futures.expiries(body.symbol, 1)[0]
    w0, _ = futures.roll_window(exp, body.before)
    aid = store().add("alerts", {"label": "SIMULATED", "kind": "roll",
                                 "text": f"Roll window opens for {body.symbol} {exp:%b %Y}",
                                 "date": w0.isoformat(), "symbol": body.symbol}, tag="roll")
    return {"id": aid, "date": w0.isoformat(), "contract": f"{body.symbol} {exp:%b %Y}"}


@router.post("/api/derivatives/roll/trend-lab")
def send_to_trend_lab(body: RollActionIn) -> dict[str, Any]:
    """Send to Trend Lab: the back-adjusted series and its roll dates travel together."""
    from ... import futures
    _spec(body.symbol)
    series = futures.contract_series(body.symbol, market=_mkt(body.market),
                                     roll_days_before=body.before)
    rolls = [d.isoformat() for d in series.filter(series["roll"])["date"].to_list()]
    nid = store().add("notes", {"screen": "Futures & Roll", "kind": "back_adjusted_series",
                                "symbol": body.symbol, "rows": series.height,
                                "roll_dates": rolls}, tag="trend_lab")
    return {"id": nid, "rows": series.height, "roll_dates": rolls}


# ------------------------------------------------------------------ Margin & MTM tab
@router.get("/api/derivatives/margin/defaults")
def margin_defaults(symbol: str = "NIFTY", market: str = "IN") -> dict[str, Any]:
    """Entry, cash and (US) initial / maintenance defaults: the book's sample when there is one."""
    from ... import futures, reference
    m = _mkt(market)
    sp = _spec(symbol)
    book = futures.BOOK_PATHS.get(sp.symbol, {})
    entry = float(book.get("entry", round(_spot_of(sp.symbol, m), 2)))
    initial = float(book.get("initial", 0.08 * entry * sp.multiplier))
    return _clean({"symbol": sp.symbol, "entry": entry,
                   "cash": float(book.get("cash", 0.25 * entry * sp.multiplier)),
                   "initial": initial, "maintenance": float(book.get("maintenance", 0.9 * initial)),
                   "margin_pct": 12.0, "has_book": bool(book), "multiplier": sp.multiplier,
                   "unit": _unit(sp), "source": sp.source, "pending": sp.pending,
                   "as_of": reference.as_of()})


class MarginIn(BaseModel):
    symbol: str = "NIFTY"
    market: str = "IN"
    entry: float
    cash: float
    qty: int = 1
    side: str = "long"
    margin_pct: float | None = 12.0          # India: % of notional (illustrative)
    initial: float | None = None             # US: per contract
    maintenance: float | None = None
    path: str = "book"                       # "book" (Ch 24 sample) or "synthetic"
    replay: bool = False
    day: int | None = None
    shock_pct: float | None = None


@router.post("/api/derivatives/margin")
def margin(body: MarginIn) -> dict[str, Any]:
    """Position tiles; with ``replay`` the MTM ledger to ``day``; with ``shock_pct`` the gap test."""
    from ... import futures
    from ...options.chain import fmt_money, fmt_num
    m = _mkt(body.market)
    sp = _spec(body.symbol)
    if body.qty < 1:
        raise HTTPException(400, "Contracts must be at least 1.")
    if body.side not in ("long", "short"):
        raise HTTPException(400, "Side must be long or short.")
    us = m == "US"
    if us and (body.initial is None or body.maintenance is None):
        raise HTTPException(400, "Enter the initial and maintenance margin per contract.")
    rate = None if us else (body.margin_pct or 12.0) / 100
    init = body.initial if us else None
    maint = body.maintenance if us else None
    pos = futures.position(sp.symbol, body.entry, body.qty, margin_rate=rate or 0.12, initial=init)
    pos_tiles = {}
    for line in pos.facts()[1:]:
        k, v = line.split(": ", 1)
        pos_tiles[k] = v
    out: dict[str, Any] = {"symbol": sp.symbol, "position_tiles": pos_tiles,
                           "facts": pos.facts(), "replayed": False}
    if not body.replay:
        return _clean(out)
    book = futures.BOOK_PATHS.get(sp.symbol)
    use_book = body.path == "book" and book is not None
    settles = book["settles"] if use_book else futures.synthetic_settles(sp.symbol, body.entry, 10)
    led = futures.mtm_ledger(sp.symbol, body.entry, settles, body.cash, qty=body.qty,
                             side=body.side, margin_rate=rate, initial=init, maintenance=maint)
    n = led.rows.height
    day = body.day if body.day is not None else (min(4, n) if use_book else n)
    day = max(1, min(day, n))
    now = led.upto(day)
    last = now.last
    pts, px = now.move_to_margin_call()
    call_now = last["free_cash"] < 0
    out.update({
        "replayed": True, "path": "book" if use_book else "synthetic", "sessions": n, "day": day,
        "rows": led.rows.to_dicts(),
        "tiles": {"MTM today": fmt_money(last["mtm"], m), "Free cash": fmt_money(last["free_cash"], m),
                  "Move to margin call": "call due now" if call_now
                  else f"≈ {pts:+,.0f} pts".replace("-", "−")},
        "mtm_today": last["mtm"], "free_cash": last["free_cash"],
        "move_points": pts, "call_price": px, "call_price_text": fmt_num(px, m, 2),
    })
    out["facts"] = out["facts"] + now.facts()
    if body.shock_pct is not None:
        sh = now.shock(body.shock_pct / 100)
        label = f"{sh.gap * 100:+.1f}% gap".replace("-", "−")
        out["shock"] = {"label": f"{label}: short" if sh.shortfall > 0 else label,
                        "value": fmt_money(sh.shortfall, m) if sh.shortfall > 0 else "covered",
                        "shortfall": sh.shortfall, "price": sh.price, "mtm": sh.mtm, "cash": sh.cash,
                        "margin_required": sh.margin_required,
                        "tiles": {"MTM hit": fmt_money(sh.mtm, m),
                                  "Cash after shock": fmt_money(sh.cash, m),
                                  "Margin required after shock": fmt_money(sh.margin_required, m)},
                        "facts": sh.facts()}
        out["facts"] = out["facts"] + sh.facts()
    return _clean(out)


class FuturesPlanIn(BaseModel):
    symbol: str
    market: str = "IN"
    entry: float
    qty: int = 1
    side: str = "long"
    call_price: float | None = None
    facts: list[str] = []
    ai_explanation: str = ""


@router.post("/api/derivatives/plan")
def save_futures_plan(body: FuturesPlanIn) -> dict[str, Any]:
    """Save to plan (tag: futures): the position and its Move to margin call line."""
    name = f"{body.symbol} FUT {body.side}"
    st = store()
    versions = [p for p in st.all("plans", tag="futures") if p.get("name") == name]
    version = len(versions) + 1
    st.add("plans", {"name": name, "version": version, "screen": "Futures & Roll",
                     "symbol": body.symbol, "market": body.market, "entry": body.entry,
                     "qty": body.qty, "side": body.side, "margin_call_price": body.call_price,
                     "tiles": body.facts, "ai_explanation": body.ai_explanation}, tag="futures")
    st.audit("futures.save_to_plan", {"name": name, "version": version})
    return {"name": name, "version": version}


# ================================================================== Contract Table
def _asset(row: dict) -> str:
    if row["Symbol"] == "USDINR":
        return "Currency"
    if row["Exchange"] in ("MCX", "NYMEX", "COMEX"):
        return "Commodity"
    return "Index / ETF"


@router.get("/api/derivatives/contract-table")
def contract_table() -> dict[str, Any]:
    """Dated rows, sessions and fees from the reference tables, with the as-of date."""
    from ... import futures, reference
    rows, seen = [], set()
    for r in futures.contract_rows():
        pending = str(r.get("Source", "")).startswith("†")
        # A pending book row is redundant once the dated reference table carries the symbol;
        # its exchange / settlement / expiry fill the gaps that row leaves (see _book_fill).
        if pending and (r["Market"], r["Symbol"]) in seen:
            continue
        seen.add((r["Market"], r["Symbol"]))
        src = " ".join(str(r.get("Source", "")).replace(" · ", ", ").split()).strip(", ")
        fill = _book_fill(r["Symbol"], r["Market"])
        if fill:
            r = {**r, **{k.title(): v for k, v in fill.items()}}
            src = (src + ", " if src else "") + f"{', '.join(fill)} from book Ch 24 †"
            pending = True
        rows.append({**r, "Source": src, "Asset": _asset(r), "Pending": pending})
    sessions = []
    for mkt, root in (("IN", "india"), ("US", "us")):
        for name, s in (reference.lookup(f"{root}.sessions", {}) or {}).items():
            hours = f"{s['open']}–{s['close']}" if "open" in s else s.get("note", "")
            sessions.append({"Market": mkt, "Session": name, "Hours": hours,
                             "Time zone": s.get("tz", ""), "Settlement": s.get("settlement", "")})
    stt = reference.lookup("india.charges.stt", {}) or {}
    fees = [{"Market": "IN", "Fee": "Brokerage per order (typical)",
             "Value": f"₹{float(reference.lookup('india.charges.brokerage_per_order') or 0):g}"},
            {"Market": "IN", "Fee": "STT futures (sell)",
             "Value": f"{stt.get('futures', {}).get('sell', 0) * 100:.3f}%"},
            {"Market": "IN", "Fee": "STT options premium (sell)",
             "Value": f"{stt.get('options_premium', {}).get('sell', 0) * 100:.3f}%"},
            {"Market": "IN", "Fee": "STT options exercised",
             "Value": f"{stt.get('options_exercised', 0) * 100:.3f}%"},
            {"Market": "US", "Fee": "Options contract fee (typical)",
             "Value": f"${reference.lookup('us.charges.options_contract_fee')}"},
            {"Market": "US", "Fee": "Regulatory per $ sold",
             "Value": f"${float(reference.lookup('us.charges.regulatory_per_dollar_sold') or 0) * 1000:.2f} "
                      "per $1,000 sold"}]
    return _clean({"as_of": reference.as_of(), "rows": rows, "sessions": sessions, "fees": fees})
