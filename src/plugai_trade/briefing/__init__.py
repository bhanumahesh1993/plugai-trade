"""Today › Daily Briefing: watchlist moves, overnight news, events, questions.

    from plugai_trade import briefing
    b = briefing.generate(["NIFTY", "BANKNIFTY"], market="IN", cutoff="08:45")
    for line in b.lines:
        print(line.flag, line.panel, line.text, line.source)

The filter runs in code before any model sees the text: nothing after the
cutoff, nothing older than the previous close, nothing off your list. Every
line carries a ✓ sourced or ? unsourced flag set by code, with the reason; the
model cannot switch a flag on. There is no buy/sell/target field anywhere.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .. import config, data
from ..earnings import calendar
from ..store import default as store

TZ = {"IN": ZoneInfo("Asia/Kolkata"), "US": ZoneInfo("America/New_York")}
TZ_LABEL = {"IN": "IST", "US": "ET"}
CLOSE = {"IN": time(15, 30), "US": time(16, 0)}
DEFAULTS = {
    "IN": {"run_time": "07:30", "cutoff": "08:45", "days": "NSE trading days"},
    "US": {"run_time": "07:00", "cutoff": "08:40", "days": "NYSE trading days"},
}
FEEDS = {
    "IN": [
        (
            "NSE announcements RSS",
            "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml",
        ),
        ("BSE announcements RSS", "https://www.bseindia.com/data/xml/notices.xml"),
    ],
    "US": [
        (
            "SEC EDGAR 8-K feed",
            "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&output=atom",
        )
    ],
}
SAMPLE_SOURCE = "Sample feed (offline, illustrative)"


@dataclass
class Line:
    """One briefing line with its flag set by code."""

    panel: str  # Watchlist | Overnight news | Events today
    text: str
    sourced: bool
    source: str = ""
    published: str = ""
    reason: str = ""  # why a line is unsourced

    @property
    def flag(self) -> str:
        return "✓" if self.sourced else "?"


@dataclass
class NewsItem:
    """A headline with its publication time (None when the feed gave none)."""

    title: str
    source: str
    published: datetime | None
    symbol: str = ""  # empty = general market cue


@dataclass
class Briefing:
    """One edition of the morning briefing."""

    market: str
    day: date
    cutoff: str
    edition: int
    lines: list[Line]
    questions: list[str]
    yesterday: str
    sources: list[str]
    dropped: list[str] = field(default_factory=list)

    def header(self) -> str:
        return (
            f"Daily Briefing · {self.market} · {self.day:%a %d %b %Y} · edition {self.edition} · "
            f"cutoff {self.cutoff} {TZ_LABEL[self.market]} · {' · '.join(self.sources)}"
        )

    def counts(self) -> tuple[int, int]:
        ok = sum(ln.sourced for ln in self.lines)
        return ok, len(self.lines) - ok

    def panel(self, name: str) -> list[Line]:
        return [ln for ln in self.lines if ln.panel == name]

    def facts(self) -> list[str]:
        out = [self.header()]
        out += [
            f"{ln.flag} {ln.panel}: {ln.text}"
            + (f" ({ln.source}, {ln.published})" if ln.sourced else f" (unsourced: {ln.reason})")
            for ln in self.lines
        ]
        out += [f"Question: {q}" for q in self.questions]
        out.append(f"Yesterday: {self.yesterday}")
        return out

    def as_record(self) -> dict[str, Any]:
        rec = asdict(self)
        rec["day"] = self.day.isoformat()
        return rec


# ---------------------------------------------------------------- inputs
def previous_session(day: date) -> date:
    d = day - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def watchlist_lines(
    symbols: list[str], market: str, day: date, source: str | None = None
) -> list[Line]:
    """Close, change and anything unusual (gap, volume spike) for each name, from data."""
    last = previous_session(day)
    out = []
    for s in symbols:
        try:
            df = data.get(
                s, market=market, start=last - timedelta(days=45), end=last, source=source
            )
        except Exception as exc:  # a source failing is normal; the line stays, flagged
            out.append(
                Line("Watchlist", f"{s}: no data", False, reason=f"source unreachable ({exc})")
            )
            continue
        if df.height < 22:
            out.append(
                Line(
                    "Watchlist",
                    f"{s}: too little data",
                    False,
                    reason="source returned fewer than 22 bars",
                )
            )
            continue
        c, p = float(df["close"][-1]), float(df["close"][-2])
        chg = (c / p - 1) * 100
        extra = []
        vol_avg = float(df["volume"][-21:-1].mean())
        if vol_avg and float(df["volume"][-1]) >= 1.5 * vol_avg:
            extra.append(f"volume {float(df['volume'][-1]) / vol_avg:.1f}× 20-day average")
        gap = (float(df["open"][-1]) / p - 1) * 100
        if abs(gap) >= 1.0:
            extra.append(f"opened {gap:+.2f}% from the prior close")
        text = f"{s} {c:,.2f} · {chg:+.2f}%" + (f" · {'; '.join(extra)}" if extra else "")
        out.append(Line("Watchlist", text, True, str(df["source"][-1]), f"bar {df['date'][-1]}"))
    return out


def sample_news(market: str, day: date) -> list[NewsItem]:
    """Illustrative overnight items for offline use (clearly labelled as a sample)."""
    tz = TZ[market]
    prev = previous_session(day)

    def at(d: date, hh: int, mm: int) -> datetime:
        return datetime.combine(d, time(hh, mm), tzinfo=tz)

    if market == "IN":
        return [
            NewsItem(
                "US indices closed lower overnight (sample headline)", SAMPLE_SOURCE, at(day, 1, 30)
            ),
            NewsItem("Asian markets opened mixed (sample headline)", SAMPLE_SOURCE, at(day, 6, 30)),
            NewsItem(
                "GIFT Nifty indicates a lower open (forwarded message, no time)",
                "Forwarded message",
                None,
            ),
            NewsItem(
                "Rupee opens flat against the dollar (sample headline)",
                SAMPLE_SOURCE,
                at(day, 9, 5),
            ),
            NewsItem(
                "Last week's policy preview (sample headline)",
                SAMPLE_SOURCE,
                at(prev - timedelta(days=3), 18, 0),
            ),
        ]
    return [
        NewsItem(
            "European indices closed higher (sample headline)", SAMPLE_SOURCE, at(prev, 11, 35)
        ),
        NewsItem(
            "Asian markets closed mixed overnight (sample headline)", SAMPLE_SOURCE, at(day, 3, 10)
        ),
        NewsItem("Futures point lower before the open (social post, no time)", "Social post", None),
        NewsItem("Jobless claims released (sample headline)", SAMPLE_SOURCE, at(day, 8, 45)),
        NewsItem(
            "Old analyst note resurfaces (sample headline)",
            SAMPLE_SOURCE,
            at(prev - timedelta(days=4), 9, 0),
        ),
    ]


def fetch_news(market: str, timeout: float = 6.0) -> tuple[list[NewsItem], list[str]]:
    """Headlines from the free RSS feeds. Returns (items, errors); never raises."""
    import feedparser

    items, errors = [], []
    for name, url in config.get(f"briefing.feeds.{market}", None) or FEEDS[market]:
        try:
            r = httpx.get(
                url,
                timeout=timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": config.get("data.edgar_contact", "")
                    or "PlugAI-Trade research lab"
                },
            )
            r.raise_for_status()
        except httpx.HTTPError as exc:
            errors.append(f"{name}: {exc.__class__.__name__}")
            continue
        for e in feedparser.parse(r.text).entries[:80]:
            ts = e.get("published_parsed") or e.get("updated_parsed")
            when = datetime(*ts[:6], tzinfo=ZoneInfo("UTC")).astimezone(TZ[market]) if ts else None
            items.append(NewsItem(e.get("title", "").strip(), name, when, symbol="?"))
    return items, errors


def filter_news(
    items: list[NewsItem], market: str, day: date, cutoff: str, symbols: list[str]
) -> tuple[list[Line], list[str]]:
    """Point-in-time filter, in code: keep lines after the previous close and before the cutoff."""
    tz = TZ[market]
    cut = datetime.combine(day, time.fromisoformat(cutoff), tzinfo=tz)
    prev_close = datetime.combine(previous_session(day), CLOSE[market], tzinfo=tz)
    keep, dropped = [], []
    wanted = [s.lower() for s in symbols]
    for it in items:
        if it.symbol == "?" and not any(w in it.title.lower() for w in wanted):
            continue  # company feed item about a name not on your list
        if it.published is None:
            keep.append(Line("Overnight news", it.title, False, it.source, "", "no timestamp"))
            continue
        stamp = f"{it.published:%d %b %H:%M} {TZ_LABEL[market]}"
        if it.published > cut:
            dropped.append(f"{it.title} · {stamp} · after the cutoff (waits for the next edition)")
        elif it.published < prev_close:
            dropped.append(f"{it.title} · {stamp} · older than the previous close")
        else:
            keep.append(Line("Overnight news", it.title, True, it.source, stamp))
    return keep, dropped


def event_lines(market: str, day: date, symbols: list[str]) -> list[Line]:
    """Scheduled events today from the lab calendar, each with its source."""
    return [
        Line("Events today", e.label(), True, e.source, f"stamped {e.stamped}")
        for e in calendar.events(market, day, day, symbols)
    ]


def yesterday_lesson() -> str:
    """The last lesson or note you wrote in the journal (local only)."""
    auto = ("levels", "event_move", "ipo_plan")  # saved by screens, not lessons you wrote
    notes = [r for r in store().all("notes", tag="journal", limit=200) if r.get("kind") not in auto]
    rows = store().all("journal", limit=200) + notes
    rows.sort(key=lambda r: r["created"], reverse=True)
    for row in rows:
        for key in ("lesson", "note", "notes", "text"):
            if str(row.get(key) or "").strip():
                return f"{row[key]} (Journal, {row['created'][:10]})"
    return "No journal note yet. Write one line after today's close."


def questions(lines: list[Line]) -> list[str]:
    """Three or four questions that connect the facts to your plan. Never an answer."""
    qs: list[str] = []
    for ln in lines:
        if ln.panel == "Events today" and "expiry" in ln.text:
            qs.append(f"{ln.text.split(' · ')[0]}: does your expiry rule apply today?")
        elif ln.panel == "Events today" and "results" in ln.text:
            qs.append(f"{ln.text.split(' · ')[0]}: does your plan say to hold through it?")
        elif ln.panel == "Events today":
            qs.append(
                f"{ln.text.split(' · ')[0]} is scheduled today: what does your Rule Card say "
                "about trading around it?"
            )
    for ln in lines:
        if not ln.sourced:
            qs.append(f"Who checks the unsourced line “{ln.text}” before you act on it?")
            break
    for ln in lines:
        if ln.panel == "Watchlist" and "volume" in ln.text:
            qs.append(
                f"{ln.text.split(' ')[0]} traded on unusual volume: is that inside your plan's "
                "normal range?"
            )
            break
    if not qs:
        qs.append(
            "Nothing scheduled touches your list: which rule on your Rule Card matters most today?"
        )
    try:  # Chapter 34: the weekly rhythm's reminders appear here
        from .. import workspace
        qs.extend(workspace.rhythm())
    except Exception:
        pass
    return list(dict.fromkeys(qs))[:5]


# ---------------------------------------------------------------- generate / save
def _edition(market: str, day: date) -> int:
    return 1 + sum(
        1 for r in store().all("briefings", tag=market) if r.get("day") == day.isoformat()
    )


def generate(
    symbols: list[str],
    market: str = "IN",
    cutoff: str | None = None,
    day: date | None = None,
    online: bool = False,
    save: bool = True,
    source: str | None = None,
) -> Briefing:
    """Build one edition. ``online=True`` reads the RSS feeds, else the offline sample items."""
    day = day or date.today()
    cutoff = cutoff or DEFAULTS[market]["cutoff"]
    wl = watchlist_lines(symbols, market, day, source)
    sources = sorted({ln.source for ln in wl if ln.sourced})
    items, errs = fetch_news(market) if online else ([], [])
    if not items:
        items = sample_news(market, day)
        sources.append(SAMPLE_SOURCE if not errs else f"{SAMPLE_SOURCE} (feeds unreachable)")
    else:
        sources += sorted({i.source for i in items})
    news, dropped = filter_news(items, market, day, cutoff, symbols)
    ev = event_lines(market, day, symbols)
    lines = wl + news + ev
    b = Briefing(
        market,
        day,
        cutoff,
        _edition(market, day),
        lines,
        questions(lines),
        yesterday_lesson(),
        sources,
        dropped,
    )
    if save:
        store().add("briefings", b.as_record(), tag=market)
    return b


def editions(market: str, day: date | None = None) -> list[dict[str, Any]]:
    """Saved editions (newest first), optionally for one day."""
    rows = store().all("briefings", tag=market)
    return [r for r in rows if day is None or r.get("day") == day.isoformat()]


def schedule(
    market: str,
    run_time: str | None = None,
    cutoff: str | None = None,
    delivery: list[str] | None = None,
    refresh_time: str | None = None,
) -> int:
    """Save the Schedule dialog as a job: market days, run time, news cutoff, delivery."""
    d = DEFAULTS[market]
    body = {
        "kind": "Daily Briefing",
        "market": market,
        "days": d["days"],
        "run_time": run_time or d["run_time"],
        "news_cutoff": cutoff or d["cutoff"],
        "refresh_time": refresh_time,
        "delivery": delivery or ["Dashboard"],
        "tz": TZ_LABEL[market],
        "model": "local",
        "active": True,
    }
    return store().add("jobs", body, tag="briefing")
