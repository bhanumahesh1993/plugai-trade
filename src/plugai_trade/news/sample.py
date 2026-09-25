"""The bundled synthetic headline set and its synthetic prices (offline default).

Every company here is fictional (Kaveri Pumps and Lakeshore Devices are the
book's running examples). The set is deterministic: same dates, same rows on
every machine. Prices for these companies are the benchmark plus seeded noise
plus a small reaction around each headline's first tradable session, so the
event study has a shape to find. None of it is market information.
"""

from __future__ import annotations

import bisect
import hashlib
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache

import numpy as np
import polars as pl

from . import clock

START = date(2025, 1, 1)
SYNTHETIC_TAG = "synthetic sample"

COMPANIES = {
    "IN": [("KAVERIPUMP", "Kaveri Pumps", "कावेरी पम्प्स"),
           ("DECCANTEX", "Deccan Textiles", "दक्कन टेक्सटाइल्स"),
           ("SAHYCEM", "Sahyadri Cement", "सह्याद्रि सीमेंट"),
           ("NARMADAFD", "Narmada Foods", "नर्मदा फूड्स"),
           ("KONKANLOG", "Konkan Logistics", "कोंकण लॉजिस्टिक्स"),
           ("TUNGSTEEL", "Tungabhadra Steel", "तुंगभद्रा स्टील"),
           ("GODAPHARM", "Godavari Pharma", "गोदावरी फार्मा"),
           ("MALABFIN", "Malabar Finance", "मालाबार फाइनेंस")],
    "US": [("LKSD", "Lakeshore Devices", ""), ("PRRL", "Prairie Rail", ""),
           ("BYBT", "Bayside Biotech", ""), ("CPSW", "Cedar Point Software", ""),
           ("HBGR", "Harbor Grocers", ""), ("SMSL", "Summit Solar", ""),
           ("RWIN", "Redwood Insurance", ""), ("GRLG", "Granite Logistics", "")],
}

# (template, true tone). {c} company, {p} percent, {x} amount, {q} quarter.
TEMPLATES = {
    "IN": [
        ("{c} Q{q} net profit rises {p}% to ₹{x} crore", "positive"),
        ("{c} wins ₹{x} crore order from state utility", "positive"),
        ("{c} board approves interim dividend", "positive"),
        ("{c} raises full-year revenue guidance", "positive"),
        ("{c} loss narrows to ₹{x} crore", "positive"),
        ("{c} results better than feared despite cost pressure", "positive"),
        ("{c} Q{q} profit falls {p}% on weak demand", "negative"),
        ("{c} receives show-cause notice from regulator", "negative"),
        ("{c} CFO resigns with immediate effect", "negative"),
        ("{c} plant shutdown after fire; production halted", "negative"),
        ("{c} cuts revenue guidance citing slowdown", "negative"),
        ("{c} growth slows as order book stays flat", "negative"),
        ("{c} schedules board meeting to consider results", "neutral"),
        ("{c} order book steady at ₹{x} crore", "neutral"),
        ("{c} appoints new independent director", "neutral"),
        ("{c} files shareholding pattern for the quarter", "neutral"),
        ("{c} capital expenditure plan unchanged at ₹{x} crore", "neutral"),
        ("{c} to hold analyst call after results", "neutral"),
    ],
    "US": [
        ("8-K: {c} reports Q{q} revenue up {p}%", "positive"),
        ("8-K: {c} announces ${x} million contract award", "positive"),
        ("8-K: {c} raises full-year outlook", "positive"),
        ("{c} net loss narrows to ${x} million", "positive"),
        ("{c} quarter better than feared despite margin pressure", "positive"),
        ("8-K: {c} announces CEO departure", "negative"),
        ("8-K: {c} discloses SEC subpoena", "negative"),
        ("{c} Q{q} earnings fall {p}% on weak orders", "negative"),
        ("8-K: {c} cuts dividend", "negative"),
        ("{c} growth slows as backlog stays flat", "negative"),
        ("8-K: {c} enters ${x} million credit agreement", "neutral"),
        ("8-K: {c} elects new board member", "neutral"),
        ("{c} backlog steady at ${x} million", "neutral"),
        ("8-K: {c} sets date for annual meeting", "neutral"),
        ("{c} capital spending plan unchanged", "neutral"),
    ],
}

HINDI = [  # (original, English translation, true tone)
    ("{h} का मुनाफा {p}% घटा", "{c} profit falls {p}%", "negative"),
    ("{h} को ₹{x} करोड़ का ऑर्डर मिला", "{c} wins ₹{x} crore order", "positive"),
    ("{h} की बोर्ड बैठक अगले सप्ताह", "{c} board meeting next week", "neutral"),
    ("{h} का घाटा कम हुआ", "{c} loss narrows", "positive"),
    ("{h} के सीएफओ ने इस्तीफा दिया", "{c} CFO resigns", "negative"),
]

SOURCE_MIX = {"IN": [("nse-rss", 0.5), ("bse-rss", 0.35), ("gdelt", 0.15)],
              "US": [("sec-8k", 0.7), ("gdelt", 0.3)]}
RATE = {"IN": 2.3, "US": 2.3}  # headlines per session day
# Average abnormal reaction by session offset from day 0 (fractions).
EFFECT = {"positive": {0: 0.0156, 1: 0.0020, 2: 0.00115},
          "negative": {0: -0.0191, 1: -0.0013, 2: -0.00095}}


def _rng(*parts: str) -> np.random.Generator:
    h = hashlib.sha256("|".join(parts).encode()).hexdigest()[:8]
    return np.random.default_rng(int(h, 16))


def _row_id(source: str, link: str, published: str) -> str:
    return hashlib.sha1(f"{source}|{link}|{published}".encode()).hexdigest()[:12]


def _clock_time(rng: np.random.Generator, market: str) -> time:
    """Mix of pre-open, in-session and after-close publication times."""
    s = clock.session(market)
    open_h = int(s["open"][:2])
    close_h = int(s["close"][:2])
    bucket = rng.choice(["pre", "in", "after"], p=[0.2, 0.4, 0.4])
    if bucket == "pre":
        h = int(rng.integers(open_h - 3, open_h))
    elif bucket == "in":
        h = int(rng.integers(open_h + 1, close_h))
    else:
        h = int(rng.integers(close_h, min(close_h + 6, 23)))
    return time(h, int(rng.integers(0, 60)))


def _one(rng: np.random.Generator, market: str, day: date, n: int) -> dict:
    sym, name, hname = COMPANIES[market][int(rng.integers(len(COMPANIES[market])))]
    names, probs = zip(*SOURCE_MIX[market])
    source = str(rng.choice(names, p=probs))
    fill = {"c": name, "h": hname, "p": int(rng.integers(4, 31)),
            "x": int(rng.integers(12, 2400)), "q": (day.month - 1) // 3 + 1}
    lang, original = "en", ""
    if market == "IN" and source == "gdelt" and rng.random() < 0.7:
        orig, trans, tone = HINDI[int(rng.integers(len(HINDI)))]
        lang, original, headline = "hi", orig.format(**fill), trans.format(**fill)
    else:
        tmpl, tone = TEMPLATES[market][int(rng.integers(len(TEMPLATES[market])))]
        headline = tmpl.format(**fill)
    tz = clock.zone(market)
    local = datetime.combine(day, _clock_time(rng, market), tz)
    pub_utc = local.astimezone(UTC)
    if source == "bse-rss" and rng.random() < 0.06:
        raw = f"{day:%d %b %Y}"  # date only: no usable time → Unstamped tray
    elif source == "gdelt":
        raw = f"{pub_utc:%Y%m%dT%H%M%SZ}"
    elif source == "sec-8k":
        raw = local.isoformat()
    else:
        raw = f"{local:%d-%b-%Y %H:%M:%S} IST"
    link = f"https://example.invalid/{source}/{day:%Y%m%d}/{n}"
    seen = pub_utc + timedelta(minutes=int(rng.integers(2, 15)))
    return {"id": _row_id(source, link, raw), "source": source, "market": market,
            "symbol": sym, "company": name, "headline": headline, "lang": lang,
            "original": original or headline, "link": link, "published_raw": raw,
            "seen_utc": seen, "tone": tone}


def _all(market: str) -> tuple[dict, ...]:
    """Every synthetic item from 2025-01-01 to today (seeded by date, so stable)."""
    return _all_until(market, date.today())


@lru_cache(maxsize=4)
def _all_until(market: str, today: date) -> tuple[dict, ...]:
    rows: list[dict] = []
    d = START
    while d <= today:
        rng = _rng("news", market, d.isoformat())
        if clock.is_session_day(d, market) or rng.random() < 0.15:
            for i in range(int(rng.poisson(RATE[market]))):
                rows.append(_one(rng, market, d, i))
        d += timedelta(days=1)
    return tuple(rows)


def raw_rows(market: str, sources: list[str], start: date, end: date) -> list[dict]:
    """Raw synthetic items for ``sources`` published between ``start`` and ``end``."""
    out, now = [], datetime.now(UTC)
    for r in _all(market):
        day = r["seen_utc"].astimezone(clock.zone(market)).date()
        if r["source"] in sources and start <= day <= end and r["seen_utc"] <= now:
            out.append({k: v for k, v in r.items() if k != "tone"})
    return out


def is_sample_symbol(symbol: str) -> bool:
    """True for the fictional companies in the bundled set."""
    return any(symbol == s for rows in COMPANIES.values() for s, _, _ in rows)


def _events(symbol: str, market: str) -> list[tuple[date, str]]:
    out = []
    for r in _all(market):
        if r["symbol"] == symbol and r["tone"] != "neutral":
            tf = clock.tradable_from(r["seen_utc"], market)
            out.append((tf.date(), r["tone"]))
    return out


def prices(symbol: str, market: str, bench: pl.DataFrame) -> pl.DataFrame:
    """Synthetic daily closes for a fictional company, built on ``bench``'s dates.

    Returns ``date, close``: beta × benchmark return + seeded noise + the
    reaction to each non-neutral headline around its first tradable session.
    """
    dates = bench["date"].to_list()
    b = np.diff(np.log(bench["close"].to_numpy()), prepend=np.nan)
    b[0] = 0.0
    rng = _rng("px", symbol)
    beta = 0.8 + 0.4 * rng.random()
    rets = beta * b + rng.normal(0.0, 0.009, len(dates))
    for day, tone in _events(symbol, market):
        i0 = bisect.bisect_left(dates, day)
        if i0 >= len(dates) or (dates[i0] - day).days > 5:
            continue
        for off, eff in EFFECT[tone].items():
            if i0 + off < len(rets):
                rets[i0 + off] += eff
    close = 100.0 * np.exp(np.cumsum(rets))
    return pl.DataFrame({"date": dates, "close": close})
