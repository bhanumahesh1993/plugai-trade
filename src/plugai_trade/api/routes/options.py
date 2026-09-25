"""API routes: options."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import clean as _clean

router = APIRouter()
# ------------------------------------------------------------------ options
class LegIn(BaseModel):
    kind: str
    strike: float
    side: str = "buy"
    qty: int = 1
    expiry: str = "weekly"


class OptionsIn(BaseModel):
    symbol: str = "NIFTY"
    market: str | None = None
    legs: list[LegIn]
    days_left: float | None = None


@router.post("/api/options/quote")
def options_quote(body: OptionsIn) -> dict[str, Any]:
    from ... import options
    try:
        legs = [options.leg(body.symbol, kind=lg.kind, strike=lg.strike, expiry=lg.expiry,
                            side=lg.side, qty=lg.qty, market=body.market) for lg in body.legs]
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from exc
    strat = options.strategy(legs)
    if body.days_left is not None:
        strat = strat.at(body.days_left)
    single = legs[0] if len(legs) == 1 else None
    tiles = single.tiles().display() if single and body.days_left is None else strat.summary().tiles()
    pay = strat.payoff()
    spot = strat.spot
    em = strat.expected_move()
    greeks = strat.greeks()
    facts = (single.facts() if single else strat.summary().facts())
    return _clean({
        "symbol": strat.symbol, "market": strat.market, "spot": spot, "lot": strat.lot,
        "currency": legs[0].currency, "name": strat.name, "tiles": tiles,
        "payoff": {"spot": list(pay["spot"]), "expiry": list(pay["expiry"]),
                   "now": list(pay["now"])},
        "expected_move": em, "band": [spot - em, spot + em],
        "breakevens": strat.breakevens(), "greeks": greeks, "facts": facts,
        "legs": [{"kind": lg.kind, "strike": lg.strike, "side": lg.side, "qty": lg.qty,
                  "premium": lg.premium, "days": lg.days} for lg in legs],
    })


