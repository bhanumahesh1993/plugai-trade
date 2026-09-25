"""The three clocks of a headline: Published, Seen and Tradable from (Chapter 28).

Session hours, time zones and holidays come only from the dated reference
tables (``india.sessions.cash`` / ``us.sessions.cash``). A time with no zone is
never guessed: :func:`parse_time` returns ``None`` and the row goes to the
Unstamped tray.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

from .. import reference

_REF_KEY = {"IN": "india", "US": "us"}
_NAMED = {"IST": "+05:30", "EST": "-05:00", "EDT": "-04:00", "CST": "-06:00",
          "CDT": "-05:00", "PST": "-08:00", "PDT": "-07:00", "GMT": "+00:00", "UTC": "+00:00",
          "UT": "+00:00"}


def session(market: str) -> dict[str, str]:
    """Regular cash session for ``market`` from the reference tables."""
    return dict(reference.lookup(f"{_REF_KEY[market]}.sessions.cash") or {})


def zone(market: str) -> ZoneInfo:
    """Exchange time zone (Asia/Kolkata or America/New_York)."""
    return ZoneInfo(session(market).get("tz", "UTC"))


def zone_label(market: str) -> str:
    """Short label printed beside local times."""
    return "IST" if market == "IN" else "ET"


def holidays(market: str) -> set[date]:
    """Exchange holidays listed in the reference tables (may be empty)."""
    raw = reference.lookup(f"{_REF_KEY[market]}.holidays", []) or []
    return {date.fromisoformat(str(d)) for d in raw}


def is_session_day(d: date, market: str) -> bool:
    """Weekday that is not a listed exchange holiday."""
    return d.weekday() < 5 and d not in holidays(market)


def next_session_day(d: date, market: str) -> date:
    """``d`` itself if it is a session day, otherwise the next one."""
    while not is_session_day(d, market):
        d += timedelta(days=1)
    return d


def _hm(text: str) -> time:
    h, m = text.split(":")
    return time(int(h), int(m))


def tradable_from(seen_utc: datetime, market: str) -> datetime:
    """First moment a price could be traded after the headline was seen.

    Before the open on a session day → that day's open. During the session →
    the next minute. After the close, on a weekend or a holiday → the next
    session's open. Returned in the exchange's own time zone.
    """
    tz = zone(market)
    s = session(market)
    open_t, close_t = _hm(s.get("open", "09:15")), _hm(s.get("close", "15:30"))
    local = seen_utc.astimezone(tz)
    day = local.date()
    if is_session_day(day, market):
        if local.time() < open_t:
            return datetime.combine(day, open_t, tz)
        if local.time() < close_t:
            nxt = (local + timedelta(minutes=1)).replace(second=0, microsecond=0)
            return nxt
    nday = next_session_day(day + timedelta(days=1), market)
    return datetime.combine(nday, open_t, tz)


def parse_time(raw: str | None, default_zone: str | None = None) -> datetime | None:
    """Parse a feed's time string to UTC; ``None`` when there is no usable time.

    ``default_zone`` is used only for sources whose publisher documents the
    zone (NSE and BSE publish in IST). Dates without a clock time are unusable.
    """
    text = (raw or "").strip()
    if not text or not re.search(r"\d{1,2}:\d{2}|T\d{6}", text):
        return None
    dt = _try_parse(text)
    if dt is None:
        return None
    if dt.tzinfo is None:
        if not default_zone:
            return None
        dt = dt.replace(tzinfo=ZoneInfo(default_zone))
    return dt.astimezone(UTC)


def _try_parse(text: str) -> datetime | None:
    """Datetime from RFC 822, ISO 8601, GDELT or exchange formats; naive when zone-less."""
    offset = ""
    m = re.search(r"\s*\b(IST|EST|EDT|CST|CDT|PST|PDT|GMT|UTC|UT)$", text, re.IGNORECASE)
    if m:
        text, offset = text[: m.start()].strip(), _NAMED[m.group(1).upper()]
    elif text.endswith("Z"):
        text, offset = text[:-1], "+00:00"
    has_zone = bool(offset) or bool(re.search(r"[+-]\d{2}:?\d{2}$", text))
    dt: datetime | None = None
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        pass
    if dt is None:
        for fmt in (None, "%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d %b %Y %H:%M",
                    "%d %b %Y %H:%M:%S", "%Y%m%dT%H%M%S", "%Y%m%dT%H%M%S%z"):
            try:
                dt = datetime.fromisoformat(text) if fmt is None else datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        return None
    if offset:
        return dt.replace(tzinfo=datetime.strptime(offset, "%z").tzinfo)
    return dt if has_zone else dt.replace(tzinfo=None)


def local_str(dt: datetime | None, market: str) -> str:
    """``2026-05-12 16:21 ET`` style display string (empty for ``None``)."""
    if dt is None:
        return ""
    return f"{dt.astimezone(zone(market)):%Y-%m-%d %H:%M} {zone_label(market)}"
