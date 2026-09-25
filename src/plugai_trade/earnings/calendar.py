"""The lab event calendar: results dates, index expiries and macro releases.

Every row carries a source and a time stamp. Offline, results dates are
synthetic (deterministic per symbol) and macro dates follow the sample rules in
``lab_calendar.yaml``; index expiry weekdays come from the dated reference
tables. Nothing here predicts anything: these are dates on a calendar.
"""

from __future__ import annotations

import calendar as _cal
import hashlib
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from functools import lru_cache
from importlib import resources
from typing import Any

import yaml

from .. import reference
from ..data import INDEX_SYMBOLS

TZ = {"IN": "IST", "US": "ET"}
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


@dataclass(frozen=True)
class Event:
    """One calendar row."""

    date: date
    time: str
    tz: str
    market: str
    kind: str  # results | expiry | macro | ipo
    symbol: str
    title: str
    source: str
    stamped: str  # when the source published this row (ISO date)
    estimated: bool = False

    def label(self) -> str:
        est = " (estimated)" if self.estimated else ""
        return f"{self.title}{est} · {self.date:%a %d %b} {self.time} {self.tz}"

    def as_row(self) -> dict[str, Any]:
        row = asdict(self)
        row["date"] = self.date.isoformat()
        return row


@lru_cache(maxsize=1)
def rules() -> dict[str, Any]:
    """The sample calendar rules shipped with the lab."""
    text = resources.files(__package__).joinpath("lab_calendar.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


def _seed(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)


def nth_weekday(year: int, month: int, n: int, weekday: int) -> date:
    """The n-th ``weekday`` (Mon=0) of a month; n=-1 means the last one."""
    days = [
        date(year, month, d)
        for d in range(1, _cal.monthrange(year, month)[1] + 1)
        if date(year, month, d).weekday() == weekday
    ]
    return days[n - 1] if n > 0 else days[n]


def _roll_to_weekday(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _months(spec: Any) -> list[int]:
    return list(range(1, 13)) if spec == "all" else [int(m) for m in spec]


def _month_starts(start: date, end: date) -> list[tuple[int, int]]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def macro_events(market: str, start: date, end: date) -> list[Event]:
    """Macro releases (RBI, CPI, Budget · FOMC, CPI, jobs) from the sample rules."""
    cfg = rules()
    out: list[Event] = []
    for spec in cfg["macro"].get(market, []):
        for y, m in _month_starts(start, end):
            if m not in _months(spec["months"]):
                continue
            if "day" in spec:
                d = _roll_to_weekday(date(y, m, int(spec["day"])))
            else:
                d = nth_weekday(y, m, int(spec["nth"]), int(spec["weekday"]))
            if start <= d <= end:
                out.append(
                    Event(
                        d,
                        spec["time"],
                        TZ[market],
                        market,
                        "macro",
                        "",
                        spec["name"],
                        cfg["source"],
                        (d - timedelta(days=30)).isoformat(),
                    )
                )
    return out


def _weekday_from_reference(dotted: str) -> int | None:
    text = str(reference.lookup(dotted, "") or "")
    for i, name in enumerate(WEEKDAYS):
        if name in text:
            return i
    return None


def expiry_events(market: str, start: date, end: date) -> list[Event]:
    """Index derivative expiries. India weekdays come from the dated Contract Table."""
    cfg = rules()
    out: list[Event] = []
    for spec in cfg["expiries"].get(market, []):
        if "reference" in spec:
            wd = _weekday_from_reference(spec["reference"])
            if wd is None:
                continue
            src = f"Contract Table (as of {reference.as_of()})"
            if spec["kind"] == "weekly":
                d = start
                while d <= end:
                    if d.weekday() == wd:
                        out.append(
                            Event(
                                d,
                                spec["time"],
                                TZ[market],
                                market,
                                "expiry",
                                spec["symbol"],
                                f"{spec['symbol']} weekly expiry",
                                src,
                                reference.as_of(),
                            )
                        )
                    d += timedelta(days=1)
            else:
                for y, m in _month_starts(start, end):
                    d = nth_weekday(y, m, -1, wd)
                    if start <= d <= end:
                        out.append(
                            Event(
                                d,
                                spec["time"],
                                TZ[market],
                                market,
                                "expiry",
                                spec["symbol"],
                                f"{spec['symbol']} monthly expiry",
                                src,
                                reference.as_of(),
                            )
                        )
        else:
            for y, m in _month_starts(start, end):
                d = nth_weekday(y, m, int(spec["nth"]), int(spec["weekday"]))
                if start <= d <= end:
                    out.append(
                        Event(
                            d,
                            spec["time"],
                            TZ[market],
                            market,
                            "expiry",
                            spec["symbol"],
                            spec["name"],
                            cfg["source"],
                            (d - timedelta(days=60)).isoformat(),
                        )
                    )
    return out


def results_dates(symbol: str, market: str, start: date, end: date) -> list[Event]:
    """Synthetic quarterly results dates for a stock (none for indices and ETFs)."""
    if symbol.upper() in INDEX_SYMBOLS:
        return []
    cfg = rules()["results"][market]
    out: list[Event] = []
    for year in range(start.year - 1, end.year + 1):
        for q_end in (date(year, 3, 31), date(year, 6, 30), date(year, 9, 30), date(year, 12, 31)):
            s = _seed(f"{symbol}{q_end}")
            d = _roll_to_weekday(q_end + timedelta(days=18 + s % 26))
            if not start <= d <= end:
                continue
            time = cfg["time"] if market == "IN" else cfg["times"][s % 2]
            title = f"{symbol} results" + (" (board meeting)" if market == "IN" else "")
            estimated = market == "US" and (s // 7) % 3 == 0
            out.append(
                Event(
                    d,
                    time,
                    TZ[market],
                    market,
                    "results",
                    symbol,
                    title,
                    cfg["source"],
                    (d - timedelta(days=9)).isoformat(),
                    estimated,
                )
            )
    return out


def events(
    market: str,
    start: date,
    end: date,
    symbols: list[str] | tuple[str, ...] = (),
    macro: bool = True,
    expiries: bool = True,
) -> list[Event]:
    """All calendar rows for ``market`` between two dates, sorted by date and time."""
    out: list[Event] = []
    for s in symbols:
        out += results_dates(s, market, start, end)
    if expiries:
        out += expiry_events(market, start, end)
    if macro:
        out += macro_events(market, start, end)
    return sorted(out, key=lambda e: (e.date, e.time, e.title))


def next_event(symbol: str, market: str, asof: date, horizon_days: int = 120) -> Event | None:
    """The first results row for ``symbol`` after ``asof``."""
    rows = results_dates(
        symbol, market, asof + timedelta(days=1), asof + timedelta(days=horizon_days)
    )
    return rows[0] if rows else None


def sessions_between(a: date, b: date) -> int:
    """Weekday sessions from ``a`` (exclusive) to ``b`` (inclusive)."""
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n
