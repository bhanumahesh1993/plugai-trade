"""API routes: Derivatives › Options Strategy Builder (Chapters 22–23).

Thin: every number comes from ``plugai_trade.options``; store writes mirror the classic page.
"""

from __future__ import annotations

import math
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...store import default as store
from .. import clean as _clean

router = APIRouter()

# Underlyings offered as quick picks (any symbol can still be typed).
_UNDERLYINGS = {"IN": ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"], "US": ["SPY", "SPX", "QQQ"]}
_DEFAULT = {"IN": "NIFTY", "US": "SPY"}


# ------------------------------------------------------------------ models
class LegIn(BaseModel):
    kind: str
    strike: float
    side: str = "buy"
    qty: int = 1
    expiry: str = "weekly"


class OptionsIn(BaseModel):
    """A strategy on the lesson chain: legs plus the underlying's spot / IV overrides."""

    symbol: str = "NIFTY"
    market: str | None = None
    legs: list[LegIn]
    days_left: float | None = None
    spot: float | None = None
    iv_pct: float | None = Field(None, description="IV % for every leg; blank = the chain's")
    name: str = ""
    account: str = "cash"


class ScenarioIn(OptionsIn):
    gap: float = 0.0          # points (IN) or dollars (US)
    iv_change: float = 0.0    # IV points


class StressIn(OptionsIn):
    extra: list[dict[str, Any]] = []   # [{"label", "gap_pct", "iv_pts"}]


class PresetIn(BaseModel):
    name: str
    symbol: str = "NIFTY"
    market: str | None = None
    spot: float | None = None


class SaveIn(OptionsIn):
    facts: list[str] = []
    ai_explanation: str = ""
    exit_rule: str = ""


# ------------------------------------------------------------------ helpers
def _legs(body: OptionsIn):
    from ... import options
    if not body.legs:
        raise HTTPException(400, "Add a leg first: Add leg, then Buy or Sell, then Call or Put.")
    iv = body.iv_pct / 100 if body.iv_pct else None
    try:
        return [options.leg(body.symbol, kind=lg.kind, strike=lg.strike, expiry=lg.expiry,
                            side=lg.side, qty=lg.qty, spot=body.spot, iv=iv, market=body.market)
                for lg in body.legs]
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, f"Could not price this strategy: {exc}") from exc


def _strategy(body: OptionsIn):
    from ... import options
    try:
        return options.strategy(_legs(body), name=body.name)
    except ValueError as exc:
        raise HTTPException(400, f"Could not price this strategy: {exc}") from exc


def _single(view):
    opts = [lg for lg in view.legs if lg.kind != "stock"]
    return opts[0] if len(view.legs) == 1 and opts else None


def _scn_days(strat, days: float | None) -> float:
    """Scenarios reprice at the slider's days, but tomorrow's open at the earliest."""
    d = strat.days_left if days is None else days
    return min(d, max(strat.days_left - 1, 0.0))


# ------------------------------------------------------------------ underlying
@router.get("/api/options/underlying")
def underlying(symbol: str = "", market: str = "IN") -> dict[str, Any]:
    """Spot, strike step, lot and the default strike for a new strategy on ``symbol``."""
    from ... import options
    from ...options import chain, presets
    sym = (symbol or _DEFAULT.get(market, "NIFTY")).strip().upper()
    try:
        mkt = chain.market_of(sym, market)
        spot = chain.default_spot(sym, mkt)
    except Exception as exc:
        raise HTTPException(400, f"No lesson data for {sym}: {exc}. Try NIFTY or SPY.") from exc
    step = presets.strike_step(spot)
    lot, note = chain.units_per_lot(sym, mkt)
    return _clean({"symbol": sym, "market": mkt, "spot": spot, "step": step, "lot": lot,
                   "lot_note": note, "strike": round(spot * 1.009 / (5 * step)) * 5 * step,
                   "currency": chain.CURRENCY[mkt], "choices": _UNDERLYINGS.get(mkt, []),
                   "presets": list(options.PRESETS)})


@router.post("/api/options/preset")
def preset(body: PresetIn) -> dict[str, Any]:
    """Income preset legs, with Sell and Buy already set (monthly lesson chain)."""
    from ... import options
    try:
        legs = options.preset(body.name, body.symbol, market=body.market, spot=body.spot)
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return _clean({"name": body.name, "legs": [
        {"side": lg.side, "kind": lg.kind, "strike": lg.strike, "expiry": "monthly", "qty": lg.qty}
        for lg in legs]})


# ------------------------------------------------------------------ quote
@router.post("/api/options/quote")
def options_quote(body: OptionsIn) -> dict[str, Any]:
    """Tiles, payoff, margin and leg table for the position at ``days_left``."""
    from ...options import presets
    strat = _strategy(body)
    days = strat.days_left if body.days_left is None else max(0.0, min(body.days_left, strat.days_left))
    view = strat.at(days)
    single = _single(view)
    if single is not None:
        tiles = single.tiles().display()
        facts = [f"{k}: {v}" for k, v in tiles.items()]
        leg_lines = single.facts()[:5]
    else:
        tiles = view.summary(body.account).tiles()
        facts = view.summary(body.account).facts()
        leg_lines = view.facts()[: len(view.legs) + 1]
    summ = view.summary(body.account)
    pay = view.payoff()
    spot = view.spot
    em = view.expected_move()
    lg0 = view.legs[0]
    m = view.market
    from ...options.chain import fmt_money
    margin_facts = []
    if summ.margin is not None and single is not None:   # multi-leg facts already carry these
        label = "Margin estimate" + (" (expiry day)" if days <= 0 else "")
        shown = summ.margin_expiry_day if days <= 0 else summ.margin
        margin_facts = [f"{label}: ≈ {fmt_money(shown or 0, m, 0)}",
                        f"Margin on expiry day: ≈ {fmt_money(summ.margin_expiry_day or 0, m, 0)}",
                        f"Margin model: {summ.margin_model} — an estimate, not your broker's figure"]
    return _clean({
        "symbol": strat.symbol, "market": m, "spot": spot, "lot": strat.lot,
        "currency": lg0.currency, "name": strat.name, "tiles": tiles, "single": single is not None,
        "per": "per lot" if single is not None else "whole position",
        "payoff": {"spot": list(pay["spot"]), "expiry": list(pay["expiry"]), "now": list(pay["now"])},
        "expected_move": em, "band": [spot - em, spot + em],
        "breakevens": view.breakevens(), "greeks": view.greeks(), "facts": facts,
        "leg_lines": leg_lines, "days_left": days, "days_max": strat.days_left,
        "days_slider_max": int(math.ceil(strat.days_left)),
        "step": presets.strike_step(spot), "base_iv": strat.base_iv,
        "lot_note": lg0.lot_note, "chain_label": lg0.chain_label, "rate": lg0.rate,
        "margin": {"estimate": summ.margin, "expiry_day": summ.margin_expiry_day,
                   "model": summ.margin_model, "parts": summ.margin_parts,
                   "facts": margin_facts, "account": body.account},
        "legs": [{"kind": lg.kind, "strike": lg.strike, "side": lg.side, "qty": lg.qty,
                  "premium": lg.premium, "days": lg.days, "lot": lg.lot, "iv": lg.iv,
                  "describe": lg.describe()} for lg in strat.legs],
        "strategy": strat.to_dict(),
    })


# ------------------------------------------------------------------ IV panel
@router.get("/api/options/iv")
def iv_panel(symbol: str = "NIFTY", window: int = 252) -> dict[str, Any]:
    from ... import options
    try:
        ivr = options.iv_rank(symbol, window=window)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _clean({"symbol": ivr.symbol, "iv": ivr.iv, "rank": ivr.rank,
                   "percentile": ivr.percentile, "low": ivr.low, "high": ivr.high,
                   "window": ivr.window, "below_days": ivr.below_days, "source": ivr.source,
                   "dates": ivr.dates, "series": ivr.series,
                   "events": [{"date": d, "text": e} for d, e in ivr.events],
                   "facts": ivr.facts()})


# ------------------------------------------------------------------ scenarios
@router.post("/api/options/scenario")
def scenario(body: ScenarioIn) -> dict[str, Any]:
    """Your scenario (Gap / IV spike) repriced, and its P&L attribution."""
    strat = _strategy(body)
    d = _scn_days(strat, body.days_left)
    single = _single(strat)
    m = strat.market
    from ...options.chain import fmt_money
    if single is not None:
        sc = single.scenario(gap=body.gap, iv=body.iv_change, days_left=d)
        out = {"single": True, "value": sc.price, "pnl": sc.pnl, "max_loss": sc.max_loss,
               "tiles": {"Value per unit": fmt_money(sc.price, m, 2 if m == "US" else 1),
                         "P&L per lot": fmt_money(sc.pnl, m)},
               "facts": sc.facts()}
    else:
        row = strat.stress(gap=body.gap / strat.spot, iv_to=strat.base_iv + body.iv_change / 100,
                           days=strat.days_left - d, label="Your scenario")
        out = {"single": False, "value": row.value, "pnl": row.pnl,
               "tiles": {"Your scenario": fmt_money(row.pnl, m)}, "facts": row.facts()}
    att = strat.attribution(spot=strat.spot + body.gap, iv=strat.base_iv + body.iv_change / 100,
                            days=strat.days_left - d)
    out.update({"days_left": d, "attribution": {"parts": att.parts(), "actual": att.actual,
                                                "facts": att.facts()}})
    return _clean(out)


@router.post("/api/options/stress")
def stress(body: StressIn) -> dict[str, Any]:
    """The chapter's default scenario set plus your own rows, repriced one day after entry."""
    strat = _strategy(body)
    try:
        extra = [(str(e.get("label") or "My scenario"), float(e.get("gap_pct", 0)) / 100,
                  None if e.get("iv_pts") in (None, "") else float(e["iv_pts"])) for e in body.extra]
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, f"Each scenario needs a gap % and IV points: {exc}") from exc
    rows = strat.stress_table(extra)
    mp, ml = strat.max_profit_loss()
    return _clean({"rows": [{"label": r.label, "spot": r.spot, "iv": r.iv, "days_left": r.days_left,
                             "pnl": r.pnl} for r in rows],
                   "max_loss": ml, "worst": min(r.pnl for r in rows),
                   "facts": [r.facts()[0] for r in rows]})


# ------------------------------------------------------------------ save / send
@router.post("/api/options/plan")
def save_to_plan(body: SaveIn) -> dict[str, Any]:
    """Save to plan (tag: options). Earlier versions are kept as history."""
    strat = _strategy(body)
    st = store()
    versions = [p for p in st.all("plans", tag="options") if p.get("name") == strat.name]
    version = len(versions) + 1
    st.add("plans", {"name": strat.name, "version": version, "screen": "Options Strategy Builder",
                     "strategy": strat.to_dict(), "tiles": body.facts,
                     "ai_explanation": body.ai_explanation, "exit_rule": body.exit_rule},
           tag="options")
    st.audit("options.save_to_plan", {"name": strat.name, "version": version})
    return _clean({"name": strat.name, "version": version, "history": plans(strat.name)["plans"]})


@router.get("/api/options/plans")
def plans(name: str = "") -> dict[str, Any]:
    """Saved options plans (newest first); filter by strategy name for a version history."""
    rows = [p for p in store().all("plans", tag="options") if not name or p.get("name") == name]
    return _clean({"plans": [{"id": p.get("id"), "created": p.get("created"), "name": p.get("name"),
                              "version": p.get("version"), "exit_rule": p.get("exit_rule", ""),
                              "has_explanation": bool(p.get("ai_explanation")),
                              "legs": len((p.get("strategy") or {}).get("legs", [])),
                              "symbol": (p.get("strategy") or {}).get("symbol")} for p in rows]})


@router.post("/api/options/paper")
def send_to_paper(body: OptionsIn) -> dict[str, Any]:
    """Send to Paper Desk as a pending paper order: nothing fills until you Accept there."""
    strat = _strategy(body)
    st = store()
    oid = st.add("paper_orders", {"source": "Options Strategy Builder", "kind": "options",
                                  "strategy": strat.to_dict(), "status": "pending",
                                  "note": "PAPER ONLY — review and Accept in Paper Desk"},
                 tag="pending")
    st.audit("options.send_to_paper", {"name": strat.name})
    return {"id": oid, "name": strat.name, "status": "pending"}
