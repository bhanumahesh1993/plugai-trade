"""Live headline feeds: NSE and BSE announcements RSS, SEC EDGAR 8-K Atom, GDELT, any RSS.

All requests go through :mod:`plugai_trade.data.httpkit` (timeouts, pacing,
offline switch). Each function returns raw items — source, headline, link, the
feed's own time string and the zone the publisher documents (if any). Stamping
happens later, in :func:`plugai_trade.news.fetch`.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import feedparser

from .. import config
from ..data import httpkit

NSE_RSS = "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml"
BSE_RSS = "https://www.bseindia.com/data/xml/notices.xml"
SEC_8K = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&company="
          "&dateb=&owner=include&start=0&count=100&output=atom")
GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_INTERVAL = 5.0  # GDELT asks for about one request every 5 seconds
SEC_INTERVAL = 0.15  # < 10 requests a second

LIVE = ("nse-rss", "bse-rss", "sec-8k", "gdelt")


class NeedsContact(RuntimeError):
    """SEC EDGAR needs a contact name and email for its User-Agent."""


def edgar_contact() -> str:
    """The contact from Settings (``data.edgar_contact``), or raise :class:`NeedsContact`."""
    contact = str(config.get("data.edgar_contact", "") or "").strip()
    if "@" not in contact:
        raise NeedsContact("SEC EDGAR asks for a contact name and email for its User-Agent. "
                           "Enter it once in News Pipeline › Sources (or Settings › Data Sources).")
    return contact


def _rss(url: str, source: str, headers: dict[str, str] | None = None,
         default_zone: str | None = None, min_interval: float = 0.0) -> list[dict[str, Any]]:
    resp = httpkit.get(url, headers=headers or {"User-Agent": httpkit.BROWSER_UA},
                       min_interval=min_interval)
    feed = feedparser.parse(resp.content)
    out = []
    for e in feed.entries:
        title = str(e.get("title", "")).strip()
        if not title:
            continue
        raw = str(e.get("published") or e.get("updated") or e.get("pubDate") or "")
        company = title.split(" - ")[0].strip() if " - " in title else ""
        out.append({"source": source, "headline": title, "link": str(e.get("link", "")),
                    "published_raw": raw, "default_zone": default_zone, "company": company,
                    "lang": str(e.get("language", "") or "en")[:2], "original": title,
                    "updated_only": not e.get("published") and bool(e.get("updated"))})
    return out


def nse() -> list[dict[str, Any]]:
    """NSE online announcements (times published in IST)."""
    return _rss(NSE_RSS, "nse-rss", default_zone="Asia/Kolkata", min_interval=1.0)


def bse() -> list[dict[str, Any]]:
    """BSE notices (times published in IST; carries a BSE copyright line)."""
    return _rss(BSE_RSS, "bse-rss", default_zone="Asia/Kolkata", min_interval=1.0)


def sec_8k() -> list[dict[str, Any]]:
    """Latest 8-K filings from EDGAR's Atom feed (acceptance time, Eastern)."""
    ua = {"User-Agent": f"PlugAI-Trade {edgar_contact()}"}
    rows = _rss(SEC_8K, "sec-8k", headers=ua, min_interval=SEC_INTERVAL)
    for r in rows:  # "8-K - LAKESHORE DEVICES INC (0000123456) (Filer)"
        parts = r["headline"].split(" - ", 1)
        if len(parts) == 2:
            r["company"] = parts[1].split(" (")[0].strip()
    return rows


def gdelt(query: str, start: date, end: date, market: str) -> list[dict[str, Any]]:
    """GDELT DOC 2.0 article list (UTC ``seendate``; last three months only)."""
    params = {"query": query, "mode": "artlist", "format": "json", "maxrecords": "75",
              "startdatetime": f"{start:%Y%m%d}000000", "enddatetime": f"{end:%Y%m%d}235959",
              "sort": "datedesc"}
    if market == "IN":
        params["query"] = f"({query}) sourcecountry:IN"
    resp = httpkit.get(GDELT, params=params, min_interval=GDELT_INTERVAL)
    try:
        arts = resp.json().get("articles", [])
    except ValueError:
        return []
    out = []
    for a in arts:
        lang = "hi" if str(a.get("language", "")).lower().startswith("hindi") else "en"
        out.append({"source": "gdelt", "headline": str(a.get("title", "")).strip(),
                    "link": str(a.get("url", "")), "published_raw": str(a.get("seendate", "")),
                    "default_zone": None, "company": "", "lang": lang,
                    "original": str(a.get("title", "")).strip(), "updated_only": False})
    return out


def any_rss(url: str) -> list[dict[str, Any]]:
    """Any publisher's RSS feed (``rss:<url>``). Zone-less times are never guessed."""
    return _rss(url, f"rss:{url}")


def collect(source: str, market: str, start: date, end: date, query: str) -> list[dict[str, Any]]:
    """Raw items from one named source."""
    if source == "nse-rss":
        return nse()
    if source == "bse-rss":
        return bse()
    if source == "sec-8k":
        return sec_8k()
    if source == "gdelt":
        return gdelt(query, start, end, market)
    if source.startswith("rss:"):
        return any_rss(source[4:])
    raise ValueError(f"unknown news source {source!r}; use nse-rss, bse-rss, sec-8k, gdelt "
                     "or rss:<url>")
