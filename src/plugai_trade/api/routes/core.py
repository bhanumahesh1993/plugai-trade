"""API routes: core."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ... import BOOK_EDITION, __version__, ai, config, data, reference
from .. import clean as _clean

router = APIRouter()
# ------------------------------------------------------------------ status bar
@router.get("/api/status")
def status() -> dict[str, Any]:
    s = ai.status()
    return {"version": __version__, "edition": BOOK_EDITION, "market": config.get("market", "IN"),
            "ai": s, "as_of": reference.as_of(),
            "data": {"source": "synthetic", "age": "offline sample"}}


class MarketIn(BaseModel):
    market: str


@router.post("/api/market")
def set_market(body: MarketIn) -> dict[str, str]:
    if body.market not in ("IN", "US"):
        raise HTTPException(400, "market must be IN or US")
    config.set_value("market", body.market)
    return {"market": body.market}


# ------------------------------------------------------------------ home
@router.get("/api/clock")
def clock() -> dict[str, Any]:
    out = {}
    for mkt, key, tz in (("IN", "india", "Asia/Kolkata"), ("US", "us", "America/New_York")):
        sess = reference.lookup(f"{key}.sessions.cash") or {}
        now = datetime.now(ZoneInfo(tz))
        op = datetime.combine(now.date(), datetime.strptime(sess.get("open", "09:15"), "%H:%M").time(), ZoneInfo(tz))
        cl = datetime.combine(now.date(), datetime.strptime(sess.get("close", "15:30"), "%H:%M").time(), ZoneInfo(tz))
        weekday = now.weekday() < 5
        state = "open" if weekday and op <= now <= cl else ("pre-open" if weekday and now < op else "closed")
        out[mkt] = {"time": now.strftime("%H:%M"), "tz": tz, "open": sess.get("open"),
                    "close": sess.get("close"), "state": state}
    return out


@router.get("/api/watchlist")
def watchlist(market: str = "IN") -> list[dict[str, Any]]:
    syms = (config.get("watchlists", {}) or {}).get(market, [])
    rows = []
    for s in syms:
        df = data.get(s, market=market, start=date.today() - timedelta(days=60), end=date.today())
        closes = df["close"].to_list()
        if len(closes) < 2:
            continue
        rows.append({"symbol": s, "last": closes[-1], "change": closes[-1] / closes[-2] - 1,
                     "spark": closes[-30:], "source": df["source"][-1]})
    return _clean(rows)


@router.get("/api/bars")
def bars(symbol: str, market: str = "IN", days: int = 250) -> dict[str, Any]:
    df = data.get(symbol, market=market, start=date.today() - timedelta(days=int(days * 1.5)),
                  end=date.today())
    return _clean({"symbol": symbol, "source": df["source"][-1] if df.height else None,
                   "bars": df.select("date", "open", "high", "low", "close", "volume")
                   .tail(days).to_dicts()})


# ------------------------------------------------------------------ AI
class ExplainIn(BaseModel):
    facts: list[str]
    question: str | None = None
    section: str = "Research"


@router.post("/api/explain")
def explain(body: ExplainIn) -> dict[str, Any]:
    class _F:
        def facts(self_inner):
            return body.facts
    out = ai.explain(_F(), body.question, section=body.section)
    return {"text": out.text, "sources": out.sources, "model": out.model, "where": out.where,
            "blocked": out.blocked}


