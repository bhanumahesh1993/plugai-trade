"""API routes: backtest."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ... import data
from .. import clean as _clean

router = APIRouter()
# ------------------------------------------------------------------ backtest
class BacktestIn(BaseModel):
    idea: str
    symbol: str = "NIFTY"
    market: str = "IN"
    costs: str | None = None
    start: str = "2016-01-01"


@router.post("/api/backtest/run")
def backtest_run(body: BacktestIn) -> dict[str, Any]:
    from ... import backtest
    try:
        spec = backtest.rules(body.idea)
    except Exception as exc:
        raise HTTPException(400, f"Could not read the rule: {exc}") from exc
    bars_df = data.get(body.symbol, market=body.market, start=body.start, end=date.today())
    profile = body.costs or ("IN-equity-delivery" if body.market == "IN" else "US-equity")
    res = backtest.run(spec, bars_df, costs=profile)
    card = res.card()
    eq = res.equity
    peak = [max(eq[: i + 1]) for i in range(len(eq))]
    dd = [e / p - 1 for e, p in zip(eq, peak)]
    return _clean({
        "read_back": spec.read_back(), "cards": spec.cards(), "stats": res.stats(),
        "dates": [d.isoformat() for d in res.dates], "equity": list(eq),
        "benchmark": list(res.benchmark), "drawdown": dd, "trades": res.trades[-50:],
        "card": card.to_dict(), "facts": res.facts(), "trials": res.trial_count(),
        "source": bars_df["source"][-1],
    })


