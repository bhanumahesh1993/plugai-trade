"""API routes: paper."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...store import default as store
from .. import clean as _clean

router = APIRouter()
# ------------------------------------------------------------------ paper desk
_desks: dict[str, Any] = {}


def _desk(market: str):
    from ...paper import PaperDesk, Replay, session_bars
    if market not in _desks:
        desk = PaperDesk(market=market, mode="REPLAY", write_journal=False,
                         starting_balance=1_500_000.0 if market == "IN" else 40_000.0)
        sym = "NIFTY FUT" if market == "IN" else "SPY"
        data_sym = "NIFTY" if market == "IN" else "SPY"
        replay = Replay(symbol=sym, bars=session_bars(data_sym, market, interval="1m"))
        replay.step(desk, 30)   # open the session with 30 minutes on the tape
        _desks[market] = {"desk": desk, "replay": replay, "symbol": sym}
    return _desks[market]


def _desk_state(market: str) -> dict[str, Any]:
    d = _desk(market)
    desk = d["desk"]
    return _clean({
        "market": market, "symbol": d["symbol"], "mode": desk.mode, "now": desk.now,
        "cash": desk.cash, "equity": desk.equity(), "day_pnl": desk.day_pnl(),
        "killed": desk.killed, "limits": desk.limits(), "guardrails": desk.guardrail_strip(),
        "orders": [o.__dict__ for o in desk.orders][-20:],
        "positions": [{**p.__dict__, "open_pnl": p.open_pnl()} for p in desk.positions],
        "trades": desk.trades[-20:], "blocked": desk.blocked[-10:],
        "last_bar": desk.last_bar.get(d["symbol"]),
        "tape": d["replay"].visible().tail(120).to_dicts(),
        "pending": store().all("paper_orders", tag="pending")[:20],
    })


@router.get("/api/paper/state")
def paper_state(market: str = "IN") -> dict[str, Any]:
    return _desk_state(market)


class PaperOrderIn(BaseModel):
    market: str = "IN"
    symbol: str
    side: str
    qty: int
    kind: str = "market"
    price: float | None = None
    stop: float | None = None
    target: float | None = None


@router.post("/api/paper/order")
def paper_order(body: PaperOrderIn) -> dict[str, Any]:
    desk = _desk(body.market)["desk"]
    try:
        desk.place_paper_order(body.symbol, body.side, body.qty, kind=body.kind, price=body.price,
                               stop=body.stop, target=body.target)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return _desk_state(body.market)


@router.post("/api/paper/step")
def paper_step(market: str = "IN", n: int = 1) -> dict[str, Any]:
    d = _desk(market)
    if not d["replay"].done:
        d["replay"].step(d["desk"], n)
    return _desk_state(market)


@router.post("/api/paper/kill")
def paper_kill(market: str = "IN") -> dict[str, Any]:
    _desk(market)["desk"].kill_switch()
    return _desk_state(market)


