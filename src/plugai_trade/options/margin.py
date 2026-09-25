"""Margin estimates — labelled estimates, never a broker's figure.

India: the book's lab SPAN-style model (Chapter 23) — worst one-day loss over price
moves up to ±8% (seven steps) and volatility ±4 points, plus a 2% exposure add-on
per net short lot, plus SEBI's extra 2% on short index options on expiry day.
US: Regulation-T style — cash for shares or for a cash-secured put's strike, the
20% / 10% formula for a naked short option, the maximum loss for a spread.
Parameters are read from the reference tables when present (``india.margin_model``
/ ``us.margin_model``) and otherwise use the book's stated lab assumptions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import reference

if TYPE_CHECKING:
    from .strategy import Strategy

_IN_DEFAULTS = {"price_range": 0.08, "price_steps": 3, "vol_shift": 0.04, "horizon_days": 1,
                "exposure_pct": 0.02, "expiry_day_elm_pct": 0.02}
_US_DEFAULTS = {"naked_pct": 0.20, "naked_min_pct": 0.10}


def _param(market: str, name: str) -> float:
    root = "india" if market == "IN" else "us"
    defaults = _IN_DEFAULTS if market == "IN" else _US_DEFAULTS
    return float(reference.lookup(f"{root}.margin_model.{name}", defaults[name]))


def _short_lots(strategy: Strategy) -> int:
    """Net short option lots for the exposure add-on: the larger of the short call and short put side."""
    calls = sum(lg.qty for lg in strategy.legs if lg.kind == "call" and lg.side == "sell")
    puts = sum(lg.qty for lg in strategy.legs if lg.kind == "put" and lg.side == "sell")
    return max(calls, puts)


def india_span_style(strategy: Strategy) -> dict[str, float]:
    """SPAN-style scan loss, exposure add-on and the expiry-day extra, in rupees."""
    stock_value = sum(lg.spot * lg.units for lg in strategy.legs
                      if lg.kind == "stock" and lg.side == "buy")
    shorts = _short_lots(strategy)
    if shorts == 0:
        paid = max(sum(lg.sign * lg.premium * lg.units for lg in strategy.legs
                       if lg.kind != "stock"), 0.0)
        total = paid + stock_value
        return {"span": 0.0, "exposure": 0.0, "premium_paid": paid, "stock": stock_value,
                "margin": total, "expiry_day_extra": 0.0, "margin_expiry_day": total}
    rng, steps = _param("IN", "price_range"), int(_param("IN", "price_steps"))
    dv, horizon = _param("IN", "vol_shift"), _param("IN", "horizon_days")
    moves = [rng * i / steps for i in range(-steps, steps + 1)]
    worst = 0.0
    for m in moves:
        for shift in (-dv, 0.0, dv):
            pnl = strategy.pnl(strategy.spot * (1 + m), elapsed=horizon, iv_shift=shift)
            worst = max(worst, -float(pnl))
    base = strategy.spot * strategy.lot * shorts
    exposure = _param("IN", "exposure_pct") * base
    extra = _param("IN", "expiry_day_elm_pct") * base
    margin = worst + exposure + stock_value
    return {"span": round(worst, 2), "exposure": round(exposure, 2), "premium_paid": 0.0,
            "stock": stock_value, "margin": round(margin, 2),
            "expiry_day_extra": round(extra, 2), "margin_expiry_day": round(margin + extra, 2)}


def _naked_short(lg, spot: float, cash_account: bool) -> float:
    """Reg-T style requirement for one naked short option leg (all contracts)."""
    if lg.kind == "put" and cash_account:
        return lg.strike * lg.units
    otm = max(spot - lg.strike, 0.0) if lg.kind == "put" else max(lg.strike - spot, 0.0)
    floor_base = lg.strike if lg.kind == "put" else spot
    per_unit = max(_param("US", "naked_pct") * spot - otm,
                   _param("US", "naked_min_pct") * floor_base) + lg.premium
    return per_unit * lg.units


def us_reg_t_style(strategy: Strategy, account: str = "cash") -> dict[str, float]:
    """Cash for shares, strike cash (cash account) or the 20% formula for naked puts,
    the maximum loss for spreads, premium for long options."""
    legs = strategy.legs
    shares = sum(lg.units for lg in legs if lg.kind == "stock" and lg.side == "buy")
    stock_cost = sum(lg.premium * lg.units for lg in legs if lg.kind == "stock" and lg.side == "buy")
    covered_units = shares
    naked: list = []
    paired: list = []
    for kind in ("call", "put"):
        longs = [lg for lg in legs if lg.kind == kind and lg.side == "buy"]
        shorts = [lg for lg in legs if lg.kind == kind and lg.side == "sell"]
        long_units = sum(lg.units for lg in longs)
        for lg in shorts:
            if kind == "call" and covered_units >= lg.units:
                covered_units -= lg.units
                continue
            if long_units >= lg.units:
                long_units -= lg.units
                paired.append(lg)
            else:
                naked.append(lg)
        paired += longs
    spread_req = 0.0
    if paired:
        from .strategy import Strategy  # local import avoids a cycle

        sub = Strategy(paired)
        s = sub.summary(with_margin=False)
        spread_req = s.max_loss if s.max_loss is not None else 0.0
        if not any(lg.side == "sell" for lg in paired):
            spread_req = max(sub.entry_value, 0.0)
    naked_req = sum(_naked_short(lg, strategy.spot, account == "cash") for lg in naked)
    margin = stock_cost + spread_req + naked_req
    return {"stock": round(stock_cost, 2), "spreads": round(spread_req, 2),
            "naked": round(naked_req, 2), "margin": round(margin, 2),
            "expiry_day_extra": 0.0, "margin_expiry_day": round(margin, 2)}


def estimate(strategy: Strategy, account: str = "cash") -> dict[str, float]:
    """Market-appropriate margin estimate, with its components."""
    if strategy.market == "IN":
        out = india_span_style(strategy)
        out["model"] = "SPAN-style estimate (±8% price, ±4 vol pts, 1 day) + 2% exposure"
    else:
        out = us_reg_t_style(strategy, account)
        out["model"] = f"Reg-T style estimate ({account} account)"
    return out

