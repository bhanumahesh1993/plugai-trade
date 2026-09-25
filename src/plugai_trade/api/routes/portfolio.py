"""API routes: portfolio (Portfolio Reviewer, Crypto Monitor, Forecast Journal).

Thin wrappers over ``plugai_trade.portfolio``, ``plugai_trade.crypto`` and
``plugai_trade.forecast``. Holdings, fund files, targets, ETF pairs, crypto
positions and the VDA ledger live in this process per market, exactly as the
classic page keeps them in its session; saved plans, theses, notes, alerts and
forecasts go to the lab store through the same engine functions.

Files arrive as base64 inside JSON (the UI reads them in the browser), so the
bytes are parsed here and never sent to an AI model. Every AI call from these
screens is ``sensitive=True``: it stays on the local model.
"""

from __future__ import annotations

import base64
import binascii
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ... import ai, config, crypto, forecast, reference
from ... import portfolio as pf
from ...portfolio import allocation, etf, funds, holdings, income, sip, thesis
from ...store import default as store
from .. import clean as _clean

router = APIRouter()
_state: dict[str, dict[str, Any]] = {}


def _reset() -> None:
    """Forget in-process state (tests)."""
    _state.clear()


def _mkt(m: str | None) -> str:
    m = m or config.get("market", "IN")
    if m not in ("IN", "US"):
        raise HTTPException(400, "market must be IN or US")
    return m


def _cur(market: str) -> str:
    return "₹" if market == "IN" else "$"


def _st(market: str) -> dict[str, Any]:
    if market not in _state:
        _state[market] = {}
    return _state[market]


def _bytes(b64: str) -> bytes:
    try:
        return base64.b64decode(b64.split(",", 1)[-1], validate=False)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(400, "The file could not be read. Choose it again.") from exc


def _key(fact: str) -> str:
    return fact.split(":")[0].strip()


def _find(facts: list[str], prefix: str) -> str:
    """The fact key starting with ``prefix`` (so a tile can light from its citation)."""
    return next((_key(f) for f in facts if f.startswith(prefix)), prefix)


def _tile(label: str, value: Any, fact: str | None = None, **kw: Any) -> dict[str, Any]:
    return {"label": label, "value": value, "fact": fact or label, **kw}


# ================================================================== AI (local only)
class ExplainIn(BaseModel):
    facts: list[str]
    question: str | None = None
    section: str = "Portfolio"


@router.post("/api/portfolio/explain")
def explain(body: ExplainIn) -> dict[str, Any]:
    """Explain / Second opinion on the local model only: holdings are private."""
    class _F:
        def facts(self_inner):
            return body.facts
    out = ai.explain(_F(), body.question, section=body.section, sensitive=True)
    return {"text": out.text, "sources": out.sources, "model": out.model, "where": out.where,
            "blocked": out.blocked}


# ================================================================== Portfolio Reviewer
def _catalogue(market: str) -> dict[str, funds.Fund]:
    cat = funds.catalogue(market)
    cat.update(_st(market).get("fundfiles", {}))
    return cat


def _rows(market: str) -> list[holdings.Holding]:
    s = _st(market)
    if "holdings" not in s:
        s["holdings"] = holdings.match(holdings.sample_holdings(market), funds.catalogue(market))
        s["label"] = "Sample portfolio (synthetic, lesson 15)"
    return s["holdings"]


def _holdings_out(market: str) -> dict[str, Any]:
    rows = _rows(market)
    cat = _catalogue(market)
    total = sum(h.value for h in rows)
    return _clean({
        "market": market, "label": _st(market).get("label", ""),
        "rows": [{"index": i, "name": h.name, "units": h.units, "price": h.price, "value": h.value,
                  "asset_class": h.asset_class, "account": h.account, "plan": h.plan,
                  "match": h.match, "matched_to": cat[h.match].name if h.match in cat else None}
                 for i, h in enumerate(rows)],
        "count": len(rows), "total": total, "total_text": pf.money(total, _cur(market)),
        "unmatched": sum(1 for h in rows if not h.matched),
        "catalogue": [{"id": k, "name": f.name} for k, f in cat.items()],
    })


@router.get("/api/portfolio/holdings")
def get_holdings(market: str | None = None) -> dict[str, Any]:
    return _holdings_out(_mkt(market))


class MarketIn(BaseModel):
    market: str | None = None


@router.post("/api/portfolio/sample")
def load_sample(body: MarketIn) -> dict[str, Any]:
    """Load sample portfolio."""
    m = _mkt(body.market)
    _st(m).pop("holdings", None)
    return _holdings_out(m)


class ImportIn(BaseModel):
    market: str | None = None
    filename: str
    content_b64: str
    password: str = ""
    account: str = ""


@router.post("/api/portfolio/import")
def import_holdings(body: ImportIn) -> dict[str, Any]:
    """Import holdings: CAS PDF (password, read locally), broker CSV or generic CSV."""
    m = _mkt(body.market)
    raw = _bytes(body.content_b64)
    try:
        if body.filename.lower().endswith(".pdf"):
            rows = holdings.read_cas_pdf(raw, body.password)
        else:
            rows = holdings.parse_holdings_csv(raw.decode("utf-8", "ignore"), body.account)
    except HTTPException:
        raise
    except Exception as exc:  # the importer's own message; the old table stays
        raise HTTPException(400, str(exc) or "That file could not be read.") from exc
    if not rows:
        raise HTTPException(400, "No holdings found in that file. Try the generic CSV template: "
                                 "name, units, price, value, asset_class, account.")
    s = _st(m)
    s["holdings"] = holdings.match(rows, _catalogue(m))
    s["label"] = f"Imported: {body.filename}"
    store().audit("holdings_import", {"file": body.filename, "rows": len(rows), "market": m})
    return {**_holdings_out(m), "imported": len(rows)}


class MatchIn(BaseModel):
    market: str | None = None
    index: int
    fund_id: str


@router.post("/api/portfolio/match")
def match_by_hand(body: MatchIn) -> dict[str, Any]:
    m = _mkt(body.market)
    rows, cat = _rows(m), _catalogue(m)
    if not 0 <= body.index < len(rows):
        raise HTTPException(400, "That holding is no longer in the table. Reload the page.")
    if body.fund_id not in cat:
        raise HTTPException(400, "Unknown fund. Pick one from the list.")
    h = rows[body.index]
    h.match, h.asset_class = body.fund_id, cat[body.fund_id].asset_class
    return _holdings_out(m)


# ------------------------------------------------------------------ Overlap
def _fund_list(market: str) -> list[funds.Fund]:
    cat = _catalogue(market)
    ids = list(dict.fromkeys(h.match for h in _rows(market) if h.match))
    fl = [cat[i] for i in ids if i in cat and len(cat[i].holdings) > 1]
    extra = [f for f in _st(market).get("fundfiles", {}).values() if f.fund_id not in ids]
    return fl + extra


@router.get("/api/portfolio/overlap")
def get_overlap(market: str | None = None) -> dict[str, Any]:
    m = _mkt(market)
    fl = _fund_list(m)
    if len(fl) < 2:
        return {"funds": [{"id": f.fund_id, "name": f.name} for f in fl], "cells": [], "facts": [],
                "tiles": [], "csv": ""}
    cells = [{"row": a.fund_id, "col": b.fund_id, "overlap": round(funds.overlap(a.holdings, b.holdings)),
              "shared": [{"company": c, "weight": w} for c, w in funds.shared(a.holdings, b.holdings, 5)]}
             for a in fl for b in fl]
    facts = [f"Funds: {', '.join(f.name for f in fl)}"]
    pairs = []
    for a, b in funds.pairs_of(fl):
        v = funds.overlap(a.holdings, b.holdings)
        facts.append(f"Overlap {a.name} ↔ {b.name}: {v:.0f}%")
        pairs.append((v, a, b))
    hi = max(pairs, key=lambda p: p[0])
    lo = min(pairs, key=lambda p: p[0])
    tiles = [_tile("Highest overlap", f"{hi[0]:.0f}%", f"Overlap {hi[1].name} ↔ {hi[2].name}",
                   sub=f"{hi[1].fund_id} and {hi[2].fund_id}", big=True),
             _tile("Lowest overlap", f"{lo[0]:.0f}%", f"Overlap {lo[1].name} ↔ {lo[2].name}",
                   sub=f"{lo[1].fund_id} and {lo[2].fund_id}"),
             _tile("Funds compared", len(fl), "Funds")]
    return _clean({"funds": [{"id": f.fund_id, "name": f.name} for f in fl], "cells": cells,
                   "facts": facts, "tiles": tiles, "csv": funds.overlap_matrix(fl).write_csv()})


class FundFileIn(BaseModel):
    market: str | None = None
    name: str
    content_b64: str


@router.post("/api/portfolio/fund-file")
def add_fund_file(body: FundFileIn) -> dict[str, Any]:
    """Add fund holdings file (AMFI monthly portfolio / fund-house CSV)."""
    m = _mkt(body.market)
    if not body.name.strip():
        raise HTTPException(400, "Type the fund's name, then click Add fund.")
    ff = _st(m).setdefault("fundfiles", {})
    try:
        fund = funds.parse_holdings_csv(_bytes(body.content_b64).decode("utf-8", "ignore"),
                                        f"F{len(ff) + 1}", body.name.strip(), market=m)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    ff[fund.fund_id] = fund
    return {"added": fund.name, "companies": len(fund.holdings), **get_overlap(m)}


# ------------------------------------------------------------------ Costs
class CostsIn(BaseModel):
    market: str | None = None
    amount: float | None = None
    years: int | None = None
    gross_pct: float | None = None
    low_pct: float | None = None
    high_pct: float | None = None
    equity_only: bool = False  # the book's Chapter 15 figure covers Priya's five equity funds


FEE_GAP_DEFAULTS = {"IN": (1_000_000.0, 15, 10.0, 0.6, 1.6), "US": (50_000.0, 25, 8.0, 0.05, 0.75)}


@router.post("/api/portfolio/costs")
def costs(body: CostsIn) -> dict[str, Any]:
    m = _mkt(body.market)
    cur = _cur(m)
    cat = _catalogue(m)
    pos = [(cat[h.match], h.value, h.plan or ("Regular" if m == "IN" else "—"))
           for h in _rows(m) if h.match in cat
           and (not body.equity_only or cat[h.match].asset_class in ("Equity", "US stocks"))]
    if not pos:
        raise HTTPException(400, "No matched funds yet. Match holdings by hand on the Holdings tab.")
    audit = funds.cost_audit(pos, cur)
    d = FEE_GAP_DEFAULTS[m]
    amt = body.amount if body.amount is not None else d[0]
    yrs = body.years if body.years is not None else d[1]
    gross = body.gross_pct if body.gross_pct is not None else d[2]
    lo = body.low_pct if body.low_pct is not None else d[3]
    hi = body.high_pct if body.high_pct is not None else d[4]
    a, b = funds.fee_gap(amt, int(yrs), gross / 100, lo / 100, hi / 100)
    facts = audit.facts()
    tiles = [_tile("Weighted TER now", f"{audit.weighted_ter:.2f}%", _find(facts, "Weighted TER now"),
                   sub=f"{pf.money(audit.annual, cur)} a year")]
    if m == "IN":
        tiles.append(_tile("Weighted TER in direct plans", f"{audit.weighted_direct_ter:.2f}%",
                           _find(facts, "Weighted TER in direct"),
                           sub=f"{pf.money(audit.direct_annual, cur)} a year"))
        tiles.insert(0, _tile("Annual difference", pf.money(audit.annual - audit.direct_annual, cur),
                              big=True, tone="bear", sub="Regular minus direct, a year"))
    else:
        tiles[0]["big"] = True
    tiles.append(_tile("Portfolio value", pf.money(audit.total, cur)))
    return _clean({"rows": audit.frame().to_dicts(), "tiles": tiles, "facts": facts,
                   "weighted_ter": audit.weighted_ter, "weighted_direct_ter": audit.weighted_direct_ter,
                   "annual": audit.annual, "direct_annual": audit.direct_annual,
                   "fee_gap": {"amount": amt, "years": yrs, "gross_pct": gross, "low_pct": lo,
                               "high_pct": hi, "cheaper": a, "dearer": b, "difference": a - b,
                               "cheaper_text": pf.money(a, cur), "dearer_text": pf.money(b, cur),
                               "difference_text": pf.money(a - b, cur)}})


# ------------------------------------------------------------------ Concentration
@router.get("/api/portfolio/concentration")
def concentration(market: str | None = None) -> dict[str, Any]:
    m = _mkt(market)
    cat = _catalogue(m)
    pos = [(cat[h.match], h.value) for h in _rows(m) if h.match in cat and len(cat[h.match].holdings) > 1]
    if not pos:
        return {"empty": True, "tiles": [], "facts": [], "top": [], "sectors": []}
    lt = funds.look_through(pos)
    facts = lt.facts()
    big = lt.top(1)[0]
    tiles = [_tile("Top 10 companies", f"{lt.top10_share:.1%}", big=True, sub="of the portfolio"),
             _tile("Largest single company", f"{big[1]:.1%}", sub=big[0]),
             _tile("Look-through companies", lt.companies)]
    return _clean({"empty": False, "tiles": tiles, "facts": facts,
                   "top": [{"company": c, "share": s} for c, s in lt.top(10)],
                   "sectors": [{"sector": s, "share": v / lt.total, "fact": f"Sector {s}"}
                               for s, v in sorted(lt.sectors.items(), key=lambda kv: -kv[1])]})


# ------------------------------------------------------------------ Allocation
def _sleeves(rows: list[holdings.Holding]) -> dict[str, float]:
    out: dict[str, float] = {}
    for h in rows:
        out[h.asset_class] = out.get(h.asset_class, 0.0) + h.value
    return out


def _default_target(market: str, sleeves: list[str]) -> dict[str, float]:
    """The book's examples (60/30/10 IN, 60/20/20 US) when the sleeves match, else equal."""
    book = ({"Equity": 60.0, "Debt": 30.0, "Gold": 10.0} if market == "IN"
            else {"US stocks": 60.0, "Intl": 20.0, "Bonds": 20.0})
    if set(sleeves) == set(book):
        return book
    even = round(100 / len(sleeves), 1)
    out = {s: even for s in sleeves}
    out[sleeves[-1]] = round(100 - even * (len(sleeves) - 1), 1)
    return out


class AllocationIn(BaseModel):
    market: str | None = None
    monthly: float = 0.0


@router.post("/api/portfolio/allocation")
def get_allocation(body: AllocationIn) -> dict[str, Any]:
    m = _mkt(body.market)
    cur = _cur(m)
    values = _sleeves(_rows(m))
    s = _st(m)
    if "target" not in s:
        s["target"] = (_default_target(m, list(values)), 5.0)
    tgt, band = s["target"]
    tgt = {k: tgt.get(k, 0.0) for k in values} | {k: v for k, v in tgt.items() if k not in values}
    total_t = sum(tgt.values())
    out: dict[str, Any] = {"target": tgt, "band": band, "sleeves": list(values),
                           "checklist": list(allocation.CHECKLIST), "currency": cur}
    if abs(total_t - 100) > 0.05:
        return _clean({**out, "warning": f"Target adds up to {total_t:.1f}%, not 100%. "
                                         "Click Set target.", "rows": [], "facts": [], "tiles": []})
    alloc = allocation.drift(values, {k: v / 100 for k, v in tgt.items()}, band / 100, body.monthly, cur)
    rows = alloc.rows()
    facts = alloc.facts()
    outside = [r for r in rows if r["Status"] != "inside"]
    tiles = [_tile("Sleeves outside band", len(outside), "Portfolio value", big=True,
                   sub=", ".join(r["Sleeve"] for r in outside) or "All inside their bands")]
    tiles += [_tile(sd.sleeve, f"{sd.now:.1%}", sd.sleeve,
                    sub=f"target {sd.target:.0%}, {sd.drift * 100:+.1f} pts") for sd in alloc.sleeves]
    return _clean({**out, "warning": None, "rows": rows, "facts": facts, "tiles": tiles,
                   "total_text": pf.money(alloc.total, cur)})


class TargetIn(BaseModel):
    market: str | None = None
    target: dict[str, float]
    band: float = Field(5.0, ge=0.5, le=25.0)


@router.post("/api/portfolio/allocation/target")
def save_target(body: TargetIn) -> dict[str, Any]:
    """Save target (also stored in the plans table)."""
    m = _mkt(body.market)
    if any(v < 0 or v > 100 for v in body.target.values()):
        raise HTTPException(400, "Each target must be between 0 and 100%.")
    _st(m)["target"] = (dict(body.target), body.band)
    store().add("plans", {"kind": "allocation_target", "market": m, "target": body.target,
                          "band": body.band}, tag="allocation")
    return get_allocation(AllocationIn(market=m))


class LotIn(BaseModel):
    bought: date
    units: float
    cost: float


class SaleIn(BaseModel):
    lots: list[LotIn]
    units: float = 50.0
    price: float = 60.0


@router.post("/api/portfolio/sale-lots")
def sale_lots(body: SaleIn) -> list[dict[str, Any]]:
    """Lots for a sale (estimate, Draft for your CA / CPA)."""
    lots = [allocation.Lot(lt.bought, lt.units, lt.cost) for lt in body.lots if lt.units > 0]
    return _clean(allocation.sale_lots(lots, body.units, body.price))


# ------------------------------------------------------------------ ETF check
ETF_DEFAULTS = {"IN": (500_000.0, 10, 12.40), "US": (50_000.0, 10, 10.0)}
ETF_INAV = 100.90  # the synthetic reference iNAV the classic page quotes


def _etfs(market: str) -> list[etf.SyntheticEtf]:
    s = _st(market)
    if "etfs" not in s:
        s["etfs"] = etf.sample_etfs(market)
    return s["etfs"][-2:]


class EtfIn(BaseModel):
    market: str | None = None
    amount: float | None = None
    years: int | None = None
    index_return_pct: float | None = None
    threshold_pct: float = Field(etf.PREMIUM_THRESHOLD * 100, ge=0.1, le=5.0)


@router.post("/api/portfolio/etf")
def etf_check(body: EtfIn) -> dict[str, Any]:
    m = _mkt(body.market)
    cur = _cur(m)
    pair = _etfs(m)
    checks = [e.check() for e in pair]
    d = ETF_DEFAULTS[m]
    amount = body.amount if body.amount is not None else d[0]
    years = body.years if body.years is not None else d[1]
    idx_r = body.index_return_pct if body.index_return_pct is not None else d[2]
    ra = idx_r / 100 + (checks[0].td[1] or 0.0)
    rb = idx_r / 100 + (checks[1].td[1] or 0.0)
    a, b, gap = etf.cost_of_gap(amount, int(years), ra, rb)
    facts = [f for c in checks for f in c.facts()] + [f"Cost of the gap: {pf.money(gap, cur)}"]
    thin = pair[-1]
    prem = [float(p) for p in thin.intraday_premium]
    peak, now = max(prem), prem[-1]
    buy = 200_000 if m == "IN" else 20_000
    thr = body.threshold_pct
    return _clean({
        "funds": [{"name": c.name, "tiles": _etf_tiles(c)} for c in checks],
        "gap": {"amount": amount, "years": years, "index_return_pct": idx_r, "a": a, "b": b, "gap": gap,
                "a_text": pf.money(a, cur), "b_text": pf.money(b, cur), "gap_text": pf.money(gap, cur)},
        "premium": {"name": thin.name, "times": etf.session_times(len(prem)),
                    "values": [round(p * 100, 2) for p in prem], "threshold": thr,
                    "peak": peak, "now": now, "inav": ETF_INAV,
                    "flagged": peak * 100 > thr, "buy": buy, "buy_text": pf.money(buy, cur),
                    "peak_cost_text": pf.money(etf.premium_cost(buy, ETF_INAV * (1 + peak), ETF_INAV), cur)},
        "facts": facts,
    })


def _etf_tiles(c: etf.EtfCheck) -> list[dict[str, Any]]:
    """The engine's four tiles, split into a headline value and a sub-line for display."""
    out = []
    for k, v in c.tiles().items():
        head, sub = v, None
        if k == "Tracking difference" and " · " in v:
            parts = v.split(" · ")
            head, sub = parts[0], ", ".join(parts[1:])
        elif k == "Trading cost" and " (" in v:
            head, _, rest = v.partition(" (")
            sub = rest.rstrip(")")
        out.append({"label": k, "value": head, "sub": sub, "fact": f"{c.name} {k}"})
    return out


class EtfAddIn(BaseModel):
    market: str | None = None
    name: str


@router.post("/api/portfolio/etf/add")
def etf_add(body: EtfAddIn) -> dict[str, Any]:
    """Add ETF: a synthetic stand-in until a free NAV / iNAV source is connected."""
    m = _mkt(body.market)
    if not body.name.strip():
        raise HTTPException(400, "Type an ETF name or ticker first.")
    _etfs(m)
    s = _st(m)
    s["etfs"] = [*s["etfs"][-1:], etf.stand_in(body.name.strip(), s["etfs"][0])]
    return {"added": s["etfs"][-1].name}


class EtfSaveIn(EtfIn):
    pass


@router.post("/api/portfolio/etf/save")
def etf_save(body: EtfSaveIn) -> dict[str, Any]:
    """Save to thesis: the comparison goes to the Thesis tracker's table."""
    m = _mkt(body.market)
    out = etf_check(body)
    checks = [e.check() for e in _etfs(m)]
    tid = store().add("theses", {"kind": "etf_comparison", "market": m,
                                 "funds": [c.name for c in checks],
                                 "tiles": [c.tiles() for c in checks],
                                 "cost_of_gap": out["gap"]["gap"], "amount": out["gap"]["amount"],
                                 "years": out["gap"]["years"]}, tag="etf")
    return {"id": tid}


# ------------------------------------------------------------------ Income
class IncomeIn(BaseModel):
    market: str | None = None
    holding_period: bool = False
    slab_pct: float = 30.0
    cess_pct: float | None = None
    bracket_pct: float = 22.0
    qualified: bool = True
    qualified_rate: float = 0.15
    niit: bool = False


@router.post("/api/portfolio/income")
def income_tab(body: IncomeIn) -> dict[str, Any]:
    m = _mkt(body.market)
    cur = _cur(m)
    held = income.sample_income(m)
    hp = m == "US" and body.holding_period
    cess_table = pf.cess_rate()
    cess = body.cess_pct if body.cess_pct is not None else (cess_table or 0.04) * 100
    try:
        if m == "IN":
            summ = income.summarise(held, "IN", slab=body.slab_pct / 100, cess=cess / 100)
        else:
            summ = income.summarise(held, "US", bracket=body.bracket_pct / 100, qualified=body.qualified,
                                    qualified_rate=body.qualified_rate, niit=body.niit,
                                    check_holding_period=hp)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    facts = summ.facts()
    rows = []
    for h in held:
        r = h.row(hp)
        r["flag"] = str(r["Safety"]).startswith("⚠")
        r["Safety"] = str(r["Safety"]).lstrip("⚠ ").strip()
        rows.append(r)
    tiles = [_tile("After-tax income", pf.money(summ.net, cur), _find(facts, "After-tax income"),
                   big=True, sub=summ.profile),
             _tile("Gross income (12m)", pf.money(summ.gross, cur), _find(facts, "Gross dividends")),
             _tile("Next quarter, if unchanged", pf.money(summ.net / 4, cur), _find(facts, "Expected next quarter")),
             _tile("Safety flags", len(summ.flagged), _find(facts, "Safety flags"),
                   sub=", ".join(summ.flagged) or "none")]
    return _clean({"rows": rows, "trap": income.yield_trap_series(), "trap_cut_month": income.TRAP_CUT_MONTH,
                   "tiles": tiles, "facts": facts, "profile": summ.profile,
                   "cess_pct": cess, "cess_in_table": cess_table is not None,
                   "qualified_rates": list(reference.lookup("us.tax.long_term", [0.0, 0.15, 0.20]))})


# ------------------------------------------------------------------ SIP planner
class SipIn(BaseModel):
    market: str | None = None
    monthly: float = Field(10_000.0, ge=0)
    years: int = Field(20, ge=1, le=50)
    returns_pct: list[float] = [6.0, 8.0, 10.0]
    inflation_pct: float = Field(0.0, ge=0, le=20)
    step_up_pct: float = Field(0.0, ge=0, le=50)
    pause_from: int = Field(0, ge=0, le=600)
    pause_months: int = Field(0, ge=0, le=120)
    goal: float | None = None
    start: date | None = None


def _plan(body: SipIn) -> tuple[str, sip.SipPlan, tuple | None]:
    m = _mkt(body.market)
    if not body.returns_pct or any(not -20 <= r <= 30 for r in body.returns_pct):
        raise HTTPException(400, "Each assumed return must be between −20% and 30%.")
    rets = tuple(r / 100 for r in body.returns_pct)
    pause = (body.pause_from, body.pause_months) if body.pause_from and body.pause_months else None
    plan = sip.SipPlan(body.monthly, body.years, rets, body.step_up_pct / 100, body.inflation_pct / 100,
                       pause, body.goal or None, _cur(m))
    return m, plan, pause


@router.post("/api/portfolio/sip")
def sip_plan(body: SipIn) -> dict[str, Any]:
    m, plan, pause = _plan(body)
    cur = _cur(m)
    facts = plan.facts()
    inv = sip.schedule(plan.monthly, plan.years, plan.step_up, pause).cumsum()
    series = [{"name": f"{r:.0%} assumed", "values": [float(v) for v in sip.path(
        plan.monthly, plan.years, r, plan.step_up, pause)]} for r in plan.returns]
    tiles = [_tile(f"Assumed {r:.0%}", pf.money(v, cur), _find(facts, f"Assumed {r:.0%}"),
                   sub="illustrative, not a forecast", big=i == len(plan.returns) - 1)
             for i, (r, v) in enumerate(plan.values.items())]
    tiles.insert(0, _tile("Invested", pf.money(plan.invested, cur)))
    if plan.needed:
        tiles += [_tile(f"Monthly needed at {r:.0%}", pf.money(v, cur), _find(facts, f"Monthly needed at {r:.0%}"))
                  for r, v in plan.needed.items()]
    return _clean({"table": plan.table(), "facts": facts, "tiles": tiles, "series": series,
                   "invested": [float(v) for v in inv], "months": list(range(1, len(inv) + 1)),
                   "values": {f"{r:.4f}": v for r, v in plan.values.items()},
                   "goal_nominal": plan.goal_nominal})


@router.post("/api/portfolio/sip/save")
def sip_save(body: SipIn) -> dict[str, Any]:
    """Save plan with today's date."""
    m, plan, _ = _plan(body)
    rec = {**plan.to_record(), "market": m, "saved": date.today().isoformat()}
    if body.start:
        rec["start"] = body.start.isoformat()
    return {"id": store().add("plans", _clean(rec), tag="sip"), "saved": rec["saved"]}


# ------------------------------------------------------------------ Thesis tracker
def _thesis_out(tid: int, t: thesis.Thesis) -> dict[str, Any]:
    check = t.check()
    for r in check:
        r["review"] = r["Status"] == "⚠ review"
        r["Status"] = r["Status"].replace("⚠ ", "").replace("✓ ", "")
    facts = t.facts()
    return _clean({"id": tid, "holding": t.holding, "why": t.why,
                   "conditions": [{"metric": c.metric, "op": c.op, "threshold": c.threshold,
                                   "text": c.text()} for c in t.conditions],
                   "figures": t.figures, "check": check, "tripped": t.tripped, "facts": facts,
                   "tiles": [_tile("Conditions tripped", t.tripped, big=True, sub="a prompt to look, not a sale"),
                             _tile("Conditions", len(t.conditions), "Holding")]})


@router.get("/api/portfolio/theses")
def list_theses() -> dict[str, Any]:
    saved = thesis.load_all()
    if not saved:
        thesis.save(thesis.sample_thesis())
        saved = thesis.load_all()
    etfs = [r for r in store().all("theses") if r.get("kind") == "etf_comparison"]
    return _clean({"theses": [_thesis_out(i, t) for i, t in saved], "ops": list(thesis.OPS),
                   "etf_comparisons": [{"id": r["id"], "created": r.get("created"), "funds": r.get("funds"),
                                        "cost_of_gap": r.get("cost_of_gap"), "market": r.get("market")}
                                       for r in etfs]})


class ConditionIn(BaseModel):
    metric: str
    op: str
    threshold: float


class ThesisIn(BaseModel):
    holding: str
    why: str
    conditions: list[ConditionIn]


@router.post("/api/portfolio/theses")
def add_thesis(body: ThesisIn) -> dict[str, Any]:
    """Save thesis."""
    if not body.holding.strip():
        raise HTTPException(400, "Pick or type the holding first.")
    conds = [thesis.Condition(c.metric.strip(), c.op, c.threshold) for c in body.conditions if c.metric.strip()]
    if not conds:
        raise HTTPException(400, "Add at least one condition (metric, comparison, threshold).")
    if any(c.op not in thesis.OPS for c in conds):
        raise HTTPException(400, f"Comparison must be one of {', '.join(thesis.OPS)}.")
    tid = thesis.save(thesis.Thesis(body.holding.strip(), body.why.strip(), conds))
    return {"id": tid, **list_theses()}


def _load(tid: int) -> thesis.Thesis:
    t = dict(thesis.load_all()).get(tid)
    if t is None:
        raise HTTPException(400, "That thesis no longer exists. Reload the page.")
    return t


class FigureIn(BaseModel):
    quarter: str
    metric: str
    value: float
    source: str = ""


@router.post("/api/portfolio/theses/{tid}/figure")
def add_figure(tid: int, body: FigureIn) -> dict[str, Any]:
    t = _load(tid)
    if body.metric not in {c.metric for c in t.conditions}:
        raise HTTPException(400, "Pick one of this thesis's metrics.")
    t.figures.append({"quarter": body.quarter, "metric": body.metric, "value": body.value,
                      "source": body.source})
    thesis.save(t, tid)
    return _thesis_out(tid, t)


class NoteIn(BaseModel):
    text: str


@router.post("/api/portfolio/theses/{tid}/note")
def add_note(tid: int, body: NoteIn) -> dict[str, Any]:
    """Add note to journal."""
    t = _load(tid)
    if not body.text.strip():
        raise HTTPException(400, "Write your decision first.")
    return {"id": thesis.add_note_to_journal(body.text.strip(), t.holding)}


# ================================================================== Crypto Monitor
VENUES = ("binance", "coinbase", "kraken", "Delta Exchange India", "CoinDCX", "synthetic")
PUBLIC = ("binance", "coinbase", "kraken")


def _positions(market: str) -> list[crypto.Position]:
    s = _st(market)
    if "positions" not in s:
        notional = 500_000.0 if market == "IN" else 5_000.0
        s["positions"] = [crypto.Position("BTC", "long", notional, 10, 60_000.0, venue="synthetic")]
    return s["positions"]


def _pos_out(p: crypto.Position, i: int, cur: str) -> dict[str, Any]:
    return {"index": i, "symbol": p.symbol, "side": p.side, "notional": p.notional,
            "notional_text": pf.money(p.notional, cur), "leverage": p.leverage, "entry": p.entry,
            "margin_mode": p.margin_mode, "venue": p.venue, "kind": p.kind,
            "maintenance": p.maintenance}


@router.get("/api/portfolio/crypto/watch")
def crypto_watch(market: str | None = None) -> dict[str, Any]:
    m = _mkt(market)
    cur = _cur(m)
    rows = []
    for p in _positions(m):
        spot, perp, prov = crypto.quote(p.symbol, p.venue if p.venue in PUBLIC else "binance")
        rows.append({"Symbol": p.symbol, "Type": p.kind, "Venue": p.venue, "Side": p.side,
                     "Spot": round(spot, 2), "Perp": round(perp, 2) if p.kind == "perpetual" else None,
                     "Basis": crypto.basis(perp, spot) if p.kind == "perpetual" else None,
                     "Notional": pf.money(p.notional, cur), "Leverage": f"{p.leverage:g}×",
                     "Margin mode": p.margin_mode, "Source": prov})
    for sym in ("BTC", "ETH"):
        if not any(r["Symbol"] == sym and r["Type"] == "spot" for r in rows):
            spot, perp, prov = crypto.quote(sym)
            rows.append({"Symbol": sym, "Type": "spot (watch)", "Venue": "—", "Side": "—",
                         "Spot": round(spot, 2), "Perp": round(perp, 2),
                         "Basis": crypto.basis(perp, spot), "Notional": "—",
                         "Leverage": "—", "Margin mode": "—", "Source": prov})
    return _clean({"rows": rows, "source": rows[0]["Source"] if rows else "Synthetic · offline",
                   "positions": [_pos_out(p, i, cur) for i, p in enumerate(_positions(m))],
                   "venues": list(VENUES), "default_maintenance_pct": crypto.DEFAULT_MAINTENANCE * 100,
                   "fiu_url": crypto.FIU_IND_LIST_URL})


class PositionIn(BaseModel):
    market: str | None = None
    venue: str = "synthetic"
    symbol: str = "BTC"
    kind: str = "perpetual"
    side: str = "long"
    notional: float = Field(500_000.0, gt=0)
    leverage: float = Field(10.0, ge=1, le=125)
    margin_mode: str = "isolated"
    entry: float = Field(60_000.0, gt=0)
    maintenance_pct: float = Field(crypto.DEFAULT_MAINTENANCE * 100, ge=0, le=10)


@router.post("/api/portfolio/crypto/positions")
def add_position(body: PositionIn) -> dict[str, Any]:
    """Add position (paper; public data only, no exchange key)."""
    m = _mkt(body.market)
    if body.venue not in VENUES:
        raise HTTPException(400, f"Venue must be one of {', '.join(VENUES)}.")
    if body.side not in ("long", "short") or body.kind not in ("perpetual", "spot"):
        raise HTTPException(400, "Side is long or short; type is perpetual or spot.")
    _positions(m).append(crypto.Position(body.symbol, body.side, body.notional,
                                         body.leverage if body.kind == "perpetual" else 1.0,
                                         body.entry, body.margin_mode, body.venue, body.kind,
                                         body.maintenance_pct / 100))
    return crypto_watch(m)


@router.get("/api/portfolio/crypto/fiu-notes")
def fiu_notes() -> list[dict[str, Any]]:
    return _clean([{"created": r.get("created", "")[:10], "text": r.get("text", "")}
                   for r in store().all("notes", tag="fiu_check", limit=3)])


class FiuIn(BaseModel):
    text: str


@router.post("/api/portfolio/crypto/fiu-notes")
def save_fiu_note(body: FiuIn) -> list[dict[str, Any]]:
    if not body.text.strip():
        raise HTTPException(400, "Write the venue, the date you checked and what the list showed.")
    store().add("notes", {"screen": "Crypto Monitor", "text": body.text.strip()}, tag="fiu_check")
    return fiu_notes()


def _perps(m: str) -> list[tuple[int, crypto.Position]]:
    return [(i, p) for i, p in enumerate(_positions(m)) if p.kind == "perpetual"]


class FundingIn(BaseModel):
    market: str | None = None
    index: int | None = None  # index into the position list
    times_per_day: int = Field(3, ge=1, le=24)
    print_no: int | None = None  # 1-based


@router.post("/api/portfolio/crypto/funding")
def funding(body: FundingIn) -> dict[str, Any]:
    m = _mkt(body.market)
    cur = _cur(m)
    perps = _perps(m)
    if not perps:
        return {"empty": True, "perps": []}
    idx = body.index if body.index is not None and any(i == body.index for i, _ in perps) else perps[0][0]
    pos = _positions(m)[idx]
    hist, prov = crypto.funding_history(pos.symbol, "binance" if pos.venue == "synthetic" else pos.venue)
    n = hist.height
    default_print = min(crypto.SCREENSHOT_PRINT if prov.startswith("Synthetic") else n, n)
    at = min(max(body.print_no or default_print, 1), n)
    rate = float(hist["rate"][at - 1])
    ft = crypto.funding_tiles(pos, rate, body.times_per_day, cur)
    facts = ft.facts()
    fkeys = {"Funding/8h": "Funding per 8 h", "Annualised": "Annualised",
             "30-day cost": _find(facts, "30-day cost"), "To liquidation": _find(facts, "Distance to liquidation"),
             "Notional": "Notional", "Leverage": "Notional"}
    tone = {"30-day cost": "bear" if ft.cost_30d > 0 else "bull"}
    tiles = [_tile(k, v, fkeys[k], big=k == "Annualised", tone=tone.get(k)) for k, v in ft.tiles().items()]
    rates = hist["rate"].to_list()
    return _clean({
        "empty": False, "index": idx, "source": prov, "prints": n, "print_no": at,
        "default_print": default_print, "rate": rate, "times_per_day": body.times_per_day,
        "perps": [{"index": i, "label": f"{p.symbol} perp, {p.side}, {pf.money(p.notional, cur)}, {p.leverage:g}×"}
                  for i, p in perps],
        "tiles": tiles, "facts": facts,
        "history": {"print": hist["print"].to_list(), "time": hist["time"].to_list(),
                    "rate_pct": [r * 100 for r in rates],
                    "cumulative": [float(x) for x in crypto.cumulative_cost(pos.notional, rates, pos.side)]},
        "liquidation": crypto.liquidation_table(entry=pos.entry, notional=pos.notional,
                                                maintenance=pos.maintenance).to_dicts(),
        "position": _pos_out(pos, idx, cur),
    })


class SendAlertsIn(BaseModel):
    market: str | None = None
    index: int | None = None
    level_pct: float | None = Field(None, ge=0, le=1)  # funding alert level, % per 8 h
    kinds: list[str] | None = None


@router.post("/api/portfolio/crypto/send-alerts")
def send_alerts(body: SendAlertsIn) -> dict[str, Any]:
    """Send to Alerts: proposed only; nothing is active until Accept in Paper Trading › Alerts."""
    m = _mkt(body.market)
    pos_list = _positions(m)
    idx = body.index if body.index is not None and 0 <= body.index < len(pos_list) else 0
    pos = pos_list[idx]
    level = (body.level_pct if body.level_pct is not None else 0.03) / 100
    proposed = crypto.propose_alerts(pos, level, market=m)
    if body.kinds is not None:
        bad = set(body.kinds) - set(crypto.ALERT_TYPES)
        if bad:
            raise HTTPException(400, f"Unknown alert type: {', '.join(sorted(bad))}.")
        proposed = [a for a in proposed if crypto.alert_type(a) in body.kinds]
    ids = crypto.send_to_alerts(proposed)
    return {"count": len(ids), "ids": ids}


@router.get("/api/portfolio/crypto/alerts")
def crypto_alerts() -> dict[str, Any]:
    from ... import alerts
    rows = [a for a in alerts.load_all() if a.kind in ("funding", "liquidation", "price_band")
            or a.name.startswith("Exchange notice")]
    return _clean({"types": list(crypto.ALERT_TYPES),
                   "rows": [{"id": a.id, "type": crypto.alert_type(a),
                             "alert": (f"{a.symbol}: {a.bar_size} {a.condition} {a.level * 100:.3f}% per 8 h"
                                       if a.kind == "funding" and a.level is not None else a.describe()),
                             "quiet_hours": "may sound" if a.breakthrough else "held",
                             "status": a.status} for a in rows]})


# ------------------------------------------------------------------ India VDA ledger
def _ledger_rows() -> list[crypto.VdaRow]:
    s = _st("IN")
    if "ledger" not in s:
        s["ledger"] = crypto.sample_ledger().rows
    return s["ledger"]


class LedgerIn(BaseModel):
    cess_pct: float | None = Field(None, ge=0, le=10)
    statement_b64: str | None = None  # Form 26AS / AIS CSV, for Reconcile TDS


def _ledger(cess_pct: float | None) -> tuple[crypto.VdaLedger, float]:
    cess = cess_pct if cess_pct is not None else (pf.cess_rate() or 0.04) * 100
    return crypto.VdaLedger(_ledger_rows(), cess / 100), cess


@router.post("/api/portfolio/crypto/ledger")
def vda_ledger(body: LedgerIn) -> dict[str, Any]:
    led, cess = _ledger(body.cess_pct)
    facts = led.facts()
    rs = "₹"
    tiles = [_tile("Taxable VDA income", pf.money(led.gains, rs), big=True),
             _tile("Losses (recorded, not set off)", pf.money(led.losses, rs), tone="bear"),
             _tile("Tax at dated rate + cess", pf.money(led.tax(), rs), _find(facts, "Tax at")),
             _tile("TDS credit", pf.money(led.tds_total, rs)),
             _tile("Remaining to pay", pf.money(led.remaining, rs)),
             _tile("Cost of no set-off", pf.money(led.tax() - led.tax(netted=True), rs),
                   _find(facts, "If losses could be netted"))]
    return _clean({"rows": led.frame().to_dicts(), "tiles": tiles, "facts": facts, "cess_pct": cess,
                   "cess_in_table": pf.cess_rate() is not None,
                   "vda_rate": float(reference.lookup("india.tax.vda_rate")),
                   "vda_tds": float(reference.lookup("india.tax.vda_tds"))})


class TradebookIn(BaseModel):
    content_b64: str


@router.post("/api/portfolio/crypto/ledger/import")
def import_tradebook(body: TradebookIn) -> dict[str, Any]:
    """Import tradebook (exchange trade-history CSV: trade, asset, bought, sold, tds)."""
    try:
        rows = crypto.parse_trades_csv(_bytes(body.content_b64).decode("utf-8", "ignore"))
    except Exception as exc:
        raise HTTPException(400, f"Could not read the file: {exc}") from exc
    if not rows:
        raise HTTPException(400, "No sales found. The CSV needs bought and sold columns "
                                 "(trade, asset, bought, sold, tds).")
    _st("IN")["ledger"] = rows
    return {"imported": len(rows)}


@router.post("/api/portfolio/crypto/ledger/reconcile")
def reconcile(body: LedgerIn) -> dict[str, Any]:
    """Reconcile TDS against Form 26AS / AIS (or the ledger itself when no file is chosen)."""
    led, _ = _ledger(body.cess_pct)
    if body.statement_b64:
        try:
            amounts = crypto.parse_statement_csv(_bytes(body.statement_b64).decode("utf-8", "ignore"))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    else:
        amounts = [r.tds or r.expected_tds for r in led.rows]
    rec = crypto.reconcile_tds(led, amounts).to_dicts()
    return _clean({"rows": rec, "self_check": not body.statement_b64,
                   "mismatches": sum(1 for r in rec if r["Status"] != "matched")})


# ================================================================== Forecast Journal
# The prompt text the classic page sends (app/pages/forecast_journal.py).
RULES_PROMPT = (
    "Below is the full rules text of an event contract.\n{rules}\n\n"
    "Do NOT estimate the probability, do NOT recommend buying or selling, and do NOT do any "
    "arithmetic with prices or fees.\n"
    "1. In one sentence: what exact observation makes YES pay?\n"
    "2. Name the source, the time (with time zone) and any rounding or revisions rule.\n"
    "3. List every ambiguity or edge case, and how the rules say it is resolved.\n"
    "4. List three ways a casual reader could misunderstand this contract."
)
IN_NOTE = ("Disabled for IN: in India, prediction markets are treated as prohibited online money "
           "games (Promotion and Regulation of Online Gaming Act, 2025) and the major platforms "
           "have been blocked. The calibration lesson below still runs offline: score your own "
           "forecasts about your markets, with no market and no money.")


def _card(card: forecast.Scorecard) -> dict[str, Any]:
    if card.n == 0:
        return {"n": 0, "ready": False, "facts": [], "tiles": [], "bins": []}
    facts = card.facts()
    return _clean({"n": card.n, "brier": card.brier, "ready": card.ready, "facts": facts,
                   "min": forecast.MIN_FOR_CALIBRATION, "baseline": forecast.BASELINE,
                   "bins": [b.__dict__ for b in card.bins()],
                   "tiles": [_tile("Brier score", f"{card.brier:.3f}", big=True,
                                   sub=f"{card.brier - forecast.BASELINE:+.3f} vs 0.25".replace("-", "−")),
                             _tile("Resolved forecasts", card.n),
                             _tile("Coin-flip baseline", f"{forecast.BASELINE:.2f}", "Brier score")]})


def _guard(market: str | None) -> None:
    if _mkt(market) == "IN":
        raise HTTPException(400, IN_NOTE)


@router.get("/api/portfolio/forecasts")
def forecasts(market: str | None = None) -> dict[str, Any]:
    m = _mkt(market)
    frame = forecast.journal_frame()
    rows = frame.to_dicts() if not frame.is_empty() else []
    return _clean({"market": m, "disabled": m == "IN", "note": IN_NOTE if m == "IN" else None,
                   "rows": rows, "open": [r for r in rows if r.get("outcome") is None],
                   "score": _card(forecast.scorecard()), "sample": _card(forecast.sample_journal())})


class RulesIn(BaseModel):
    rules: str


@router.post("/api/portfolio/forecasts/rules")
def rules(body: RulesIn) -> dict[str, list[str]]:
    """Resolution rules: source, time and edge-case sentences quoted from the text."""
    return forecast.resolution_rules(body.rules)


@router.post("/api/portfolio/forecasts/rules-ai")
def rules_ai(body: RulesIn) -> dict[str, Any]:
    """Read the rules with AI: what makes YES pay, source, time, edge cases. No numbers."""
    if not body.rules.strip():
        raise HTTPException(400, "Paste the contract's rules first.")
    out = ai.complete(RULES_PROMPT.format(rules=ai.fence_untrusted(body.rules)), section="Portfolio")
    return {"text": out.text or "No AI model is connected; the quoted sentences above are what the "
                                "rules say.", "where": out.where, "model": out.model}


class BreakEvenIn(BaseModel):
    price_cents: float = Field(..., ge=0, le=100)
    fee_cents: float = Field(0.0, ge=0, le=20)


@router.post("/api/portfolio/forecasts/break-even")
def break_even(body: BreakEvenIn) -> dict[str, float]:
    return {"break_even": forecast.break_even(body.price_cents / 100, body.fee_cents / 100)}


class ForecastIn(BaseModel):
    market: str | None = None
    question: str
    rules: str = ""
    prob_pct: float = Field(..., ge=0, le=100)
    reason: str = ""
    platform: str = ""
    price_cents: float | None = Field(None, ge=0, le=100)
    fee_cents: float = Field(0.0, ge=0, le=20)


@router.post("/api/portfolio/forecasts")
def commit(body: ForecastIn) -> dict[str, Any]:
    """Commit forecast: the probability is stored before the price is revealed."""
    _guard(body.market)
    if not body.question.strip():
        raise HTTPException(400, "Type the contract question first.")
    price = None if body.price_cents is None else body.price_cents / 100
    fee = 0.0 if body.price_cents is None else body.fee_cents / 100
    fid = forecast.add(body.question.strip(), body.rules, body.prob_pct / 100, body.reason, price, fee,
                       body.platform)
    return {"id": fid}


class PriceIn(BaseModel):
    market: str | None = None
    price_cents: float = Field(..., ge=0, le=100)
    fee_cents: float = Field(0.0, ge=0, le=20)


@router.post("/api/portfolio/forecasts/{fid}/price")
def save_price(fid: int, body: PriceIn) -> dict[str, Any]:
    """Save price and finish."""
    _guard(body.market)
    if store().get("forecasts", fid) is None:
        raise HTTPException(400, "That forecast no longer exists.")
    forecast.set_price(fid, body.price_cents / 100, body.fee_cents / 100)
    return {"id": fid}


class ResolveIn(BaseModel):
    market: str | None = None
    outcome: int


@router.post("/api/portfolio/forecasts/{fid}/resolve")
def resolve(fid: int, body: ResolveIn) -> dict[str, Any]:
    _guard(body.market)
    if store().get("forecasts", fid) is None:
        raise HTTPException(400, "That forecast no longer exists.")
    try:
        forecast.resolve(fid, body.outcome)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return forecasts(body.market)
