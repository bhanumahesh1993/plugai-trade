"""Live-stream status for the Paper Desk (read-only market data only)."""

from __future__ import annotations

from .. import config, keys

LIVE_SOURCES = {"IN": [("upstox", "upstox_analytics_token"), ("fyers", "fyers_token"),
                       ("angel", "angel_jwt")],
                "US": [("alpaca", "alpaca_key_id")]}


def status(market: str | None = None) -> dict:
    """{"ok": bool, "source": name|None}. OK when streaming is on and a keyed source exists."""
    market = market or config.get("market", "IN")
    if not config.get("data.live_stream", False):
        return {"ok": False, "source": None, "why": "Live stream is off (Settings › Data Sources)."}
    for name, key in LIVE_SOURCES.get(market, []):
        if keys.get_key(key):
            return {"ok": True, "source": name}
    return {"ok": False, "source": None, "why": "No broker or Alpaca key connected."}
