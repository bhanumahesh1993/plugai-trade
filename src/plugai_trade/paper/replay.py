"""LIVE vs Replay: where the Paper Desk's bars come from.

LIVE needs a live source (a broker websocket or Alpaca IEX switched on in
Settings › Data Sources). Without one, the desk offers Replay: any recorded or
synthetic session, fed bar by bar at 1×, 5× or 20×. Replay never reveals a bar
before it has been fed to the engine.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import polars as pl

from .. import config, data
from ..data import synthetic
from .engine import PaperDesk

SPEEDS = {"1×": 1, "5×": 5, "20×": 20}


def live_status() -> tuple[bool, str]:
    """(available, source label). Offline, or with Live stream off, LIVE is unavailable."""
    if not config.get("data.live_stream", False):
        return False, "Live stream is off (Settings › Data Sources)"
    try:
        live = importlib.import_module("plugai_trade.data.live")
        st = live.status()
        return bool(st.get("ok")), str(st.get("source", "live"))
    except Exception:
        return False, "No live source connected"


def last_session(market: str, today: date | None = None) -> date:
    d = today or date.today()
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def session_bars(symbol: str, market: str, day: date | None = None, interval: str = "5m",
                 source: str = "synthetic") -> pl.DataFrame:
    """Bars for one replay session. Intraday keeps a ``time`` column; ``1d`` gives 120 days."""
    day = day or last_session(market)
    if interval == "1d":
        return data.get(symbol, market=market, start=day - timedelta(days=180), end=day,
                        source=source).select("date", "open", "high", "low", "close", "volume")
    if source == "synthetic":
        return synthetic.intraday(symbol, day, interval)
    cached = data.get(symbol, market=market, start=day, end=day, interval=interval, source=source)
    return cached.select("date", "open", "high", "low", "close", "volume")


@dataclass
class Replay:
    """Feeds ``bars`` to a desk ``speed`` bars per step. ``cursor`` = bars already fed."""

    symbol: str
    bars: pl.DataFrame
    speed: int = 1
    cursor: int = 0

    @property
    def done(self) -> bool:
        return self.cursor >= self.bars.height

    def visible(self) -> pl.DataFrame:
        """Only the bars the engine has already seen — never the future."""
        return self.bars.head(self.cursor)

    def step(self, desk: PaperDesk, n: int | None = None) -> list[dict[str, Any]]:
        fed = []
        for _ in range(n or self.speed):
            if self.done:
                break
            bar = self.bars.row(self.cursor, named=True)
            desk.on_bar(self.symbol, bar)
            fed.append(bar)
            self.cursor += 1
        return fed
