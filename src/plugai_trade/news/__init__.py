"""News & sentiment pipeline (Chapter 28): collect, stamp, score, measure.

    from plugai_trade import news
    heads = news.fetch(["nse-rss", "bse-rss"], market="IN",
                       start="2026-01-01", end="2026-05-29")
    fb  = news.score(heads, scorer="finbert")
    llm = news.score(heads, scorer="llm")        # your local model
    cmp = news.compare(fb, llm)
    print(cmp.table())                           # agreement counts
    cmp.disagreements().head(20)                 # read these yourself

    es = news.event_study(cmp.agreed("positive"), window=(-5, 10),
                          benchmark="NIFTY", entry="tradable_from",
                          costs="IN-equity-delivery")
    es.report()          # average path, bands, cost table, trials

Every headline carries three clocks — Published, Seen and Tradable from (the
next session open after it was seen, by the IST / ET rules in the reference
tables). Rows without a usable time go to the Unstamped tray and are never
scored. Live feeds are appended to a point-in-time store in the lab folder and
never overwritten. Offline, or when the feeds return nothing for the dates you
asked for, the bundled synthetic set (fictional companies) is used and labelled.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

import polars as pl

from .. import config
from ..data import httpkit
from . import clock, feeds, sample, scoring
from .study import Comparison, EventStudy, event_study

__all__ = [
    "SOURCES",
    "Comparison",
    "EventStudy",
    "compare",
    "default_sources",
    "event_study",
    "fetch",
    "last_status",
    "score",
    "stored",
    "unstamped",
]

SOURCES = {
    "nse-rss": ("NSE announcements RSS", "IN"),
    "bse-rss": ("BSE notices RSS", "IN"),
    "sec-8k": ("SEC EDGAR (8-K)", "US"),
    "gdelt": ("GDELT news", "ANY"),
}
SCORERS = ("finbert", "llm", "lexicon")
DUP_MINUTES = 60

COLUMNS = ["id", "source", "market", "symbol", "company", "headline", "lang", "original", "link",
           "published", "seen", "tradable_from", "published_raw", "published_utc", "seen_utc",
           "tradable_from_utc", "published_day", "tradable_day"]

_TRAY: dict[str, list[dict[str, Any]]] = {}
_STATUS: dict[str, str] = {}


def default_sources(market: str) -> list[str]:
    """The feeds ticked by default for a market (GDELT covers both)."""
    return [k for k, (_, m) in SOURCES.items() if m in (market, "ANY")]


def _to_date(d: str | date | None, default: date) -> date:
    if d is None or d == "":
        return default
    return d if isinstance(d, date) else date.fromisoformat(str(d)[:10])


# ---------------------------------------------------------------- headline store
def _store_file(name: str):
    return config.path("news", name)


def _read_jsonl(name: str) -> list[dict[str, Any]]:
    f = _store_file(name)
    if not f.exists():
        return []
    return [json.loads(line) for line in f.read_text().splitlines() if line.strip()]


def _append_jsonl(name: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with _store_file(name).open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, default=str, ensure_ascii=False) + "\n")


def _remember(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Append new live items (append-only); keep the first Seen time for known ones."""
    known = {r["id"]: r for r in _read_jsonl("headlines.jsonl")}
    new = [r for r in raw if r["id"] not in known]
    _append_jsonl("headlines.jsonl", new)
    return [{**r, "seen_utc": known[r["id"]]["seen_utc"]} if r["id"] in known else r
            for r in raw]


# ---------------------------------------------------------------- stamping
def _match_symbol(item: dict[str, Any], market: str) -> str:
    if item.get("symbol"):
        return str(item["symbol"])
    text = f"{item.get('company', '')} {item.get('headline', '')}".upper()
    aliases = config.get("news.aliases", {}) or {}
    for alias, sym in aliases.items():
        if str(alias).upper() in text:
            return str(sym)
    for sym in (config.get("watchlists", {}) or {}).get(market, []):
        if re.search(rf"\b{re.escape(str(sym).upper())}\b", text):
            return str(sym)
    return ""


def _stamp(item: dict[str, Any], market: str) -> dict[str, Any]:
    """Add the three clocks, or a reason when the row belongs in the Unstamped tray."""
    seen = item["seen_utc"]
    if isinstance(seen, str):
        seen = datetime.fromisoformat(seen)
    pub = clock.parse_time(item.get("published_raw"), item.get("default_zone"))
    row = {k: item.get(k, "") for k in ("id", "source", "company", "headline", "lang",
                                         "original", "link", "published_raw")}
    row.update(market=market, symbol=_match_symbol(item, market), seen_utc=seen)
    if pub is None:
        row["reason"] = "no usable time (missing zone or clock time)"
        return row
    if item.get("updated_only"):
        row["reason"] = "feed shows only an 'updated' time"
        return row
    effective = max(pub, seen)
    tf = clock.tradable_from(effective, market)
    row.update(published_utc=pub, published=clock.local_str(pub, market),
               seen=clock.local_str(seen, market), tradable_from=clock.local_str(tf, market),
               tradable_from_utc=tf.astimezone(UTC),
               published_day=pub.astimezone(clock.zone(market)).date(), tradable_day=tf.date())
    return row


def _dedupe(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Same story from two feeds within an hour: keep the earliest, set the other aside."""
    keep, aside, last = [], [], {}
    for r in sorted(rows, key=lambda x: x["published_utc"]):
        key = (r["symbol"] or r["company"], re.sub(r"\W+", " ", r["headline"].lower()).strip())
        prev = last.get(key)
        if prev and r["published_utc"] - prev["published_utc"] <= timedelta(minutes=DUP_MINUTES):
            aside.append({**r, "reason": f"duplicate of {prev['source']} {prev['published']}"})
            continue
        last[key] = r
        keep.append(r)
    return keep, aside


def _frame(rows: list[dict[str, Any]]) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame(schema={c: pl.Utf8 for c in COLUMNS})
    df = pl.DataFrame([{c: r.get(c) for c in COLUMNS} for r in rows])
    return df.sort("published_utc")


def _collect(sources: list[str], market: str, start: date, end: date,
             query: str) -> list[dict[str, Any]]:
    """Live items from each source; failures are recorded in :func:`last_status`."""
    raw: list[dict[str, Any]] = []
    seen_now = datetime.now(UTC).replace(microsecond=0)
    for src in sources:
        if httpkit.offline():
            _STATUS[src] = "offline"
            continue
        try:
            items = feeds.collect(src, market, start, end, query)
        except feeds.NeedsContact as exc:
            _STATUS[src] = str(exc)
            continue
        except Exception as exc:  # a feed failing is normal; say so and carry on
            _STATUS[src] = f"failed: {str(exc)[:120]}"
            continue
        for it in items:
            it["id"] = sample._row_id(src, it.get("link", ""), it.get("published_raw", ""))
            it["seen_utc"] = seen_now
        _STATUS[src] = f"{len(items)} items"
        raw += items
    return _remember(raw) if raw else []


def fetch(sources: list[str] | str | None = None, market: str = "IN", start: Any = None,
          end: Any = None, query: str | None = None) -> pl.DataFrame:
    """Stamped headlines for ``sources`` published between ``start`` and ``end``.

    Sources: ``nse-rss``, ``bse-rss``, ``sec-8k``, ``gdelt`` and ``rss:<url>``.
    Each row has Published, Seen and Tradable from in IST or ET. Rows without a
    usable time (and same-story duplicates) go to :func:`unstamped` instead.
    """
    srcs = [sources] if isinstance(sources, str) else list(sources or default_sources(market))
    end_d = _to_date(end, date.today())
    start_d = _to_date(start, end_d - timedelta(days=7))
    watch = (config.get("watchlists", {}) or {}).get(market, [])
    q = query or " OR ".join(f'"{s}"' for s in watch[:5]) or "stock market"
    raw = _collect(srcs, market, start_d, end_d, q)
    raw += [{**r, "seen_utc": r["seen_utc"]} for r in _read_jsonl("headlines.jsonl")
            if r["source"] in srcs and r["id"] not in {x["id"] for x in raw}]
    stamped, tray = [], []
    for it in raw:
        row = _stamp(it, market)
        (tray if "reason" in row else stamped).append(row)
    stamped = [r for r in stamped if start_d <= r["published_day"] <= end_d]
    if not stamped:  # offline, or the feeds hold nothing for these dates
        for src in srcs:
            _STATUS[src] = (_STATUS.get(src, "") + " · " if _STATUS.get(src) else "") + \
                f"using the bundled {sample.SYNTHETIC_TAG} (fictional companies)"
        tray = []
        for it in sample.raw_rows(market, srcs, start_d, end_d):
            it["default_zone"] = None
            row = _stamp(it, market)
            (tray if "reason" in row else stamped).append(row)
        for r in stamped + tray:
            r["source"] = f"{r['source']} ({sample.SYNTHETIC_TAG})"
        stamped = [r for r in stamped if start_d <= r["published_day"] <= end_d]
    stamped, dups = _dedupe(stamped)
    _TRAY[market] = tray + dups
    return _frame(stamped)


def unstamped(market: str = "IN") -> pl.DataFrame:
    """The Unstamped tray from the last fetch: rows that are never scored, with the reason."""
    rows = _TRAY.get(market, [])
    cols = ["source", "headline", "published_raw", "reason", "link"]
    if not rows:
        return pl.DataFrame(schema={c: pl.Utf8 for c in cols})
    return pl.DataFrame([{c: str(r.get(c, "")) for c in cols} for r in rows])


def last_status() -> dict[str, str]:
    """What each source did on the last fetch (items, offline, failed, needs contact)."""
    return dict(_STATUS)


def stored(market: str = "IN", since: Any = None) -> pl.DataFrame:
    """Live headlines already in the point-in-time store (stamped), optionally since a date."""
    since_d = _to_date(since, date(1970, 1, 1))
    rows = [_stamp(r, market) for r in _read_jsonl("headlines.jsonl")]
    rows = [r for r in rows if "reason" not in r and r["published_day"] >= since_d
            and SOURCES.get(r["source"], ("", "ANY"))[1] in (market, "ANY")]
    return _frame(rows)


# ---------------------------------------------------------------- scoring
def score(heads: pl.DataFrame, scorer: str = "finbert", save: bool = True) -> pl.DataFrame:
    """Label each stamped headline positive / negative / neutral (/ unclear).

    ``scorer``: ``"finbert"`` (lexicon fallback when transformers is missing),
    ``"llm"`` (your model; rule fallback when none is reachable) or ``"lexicon"``.
    Hindi rows keep the original; FinBERT and the lexicon read the translation
    (``path="translated"``), a reachable language model reads the original
    (``path="direct"``). Rows without a Tradable-from time are refused.
    """
    if scorer not in SCORERS:
        raise ValueError(f"scorer must be one of {', '.join(SCORERS)}")
    if heads.height and "tradable_from" in heads.columns:
        heads = heads.filter(pl.col("tradable_from").is_not_null()
                             & (pl.col("tradable_from") != ""))
    if not heads.height:
        return heads.with_columns(pl.lit(None, pl.Utf8).alias(c) for c in
                                  ("label", "score", "reason", "scorer", "scorer_used", "path"))
    texts = heads["headline"].to_list()
    if scorer == "llm":
        items = [(r["id"], r["company"] or r["symbol"],
                  r["original"] if r["lang"] != "en" else r["headline"])
                 for r in heads.iter_rows(named=True)]
        got, used = scoring.score_llm(items)
        labs = [got[i] for i, _, _ in items]
        direct = not used.startswith("Rules")
    elif scorer == "finbert":
        labs, used = scoring.score_finbert(texts)
        direct = False
    else:
        labs, used = [scoring.lexicon_label(t) for t in texts], "Lexicon (Loughran–McDonald-style)"
        direct = False
    paths = ["direct" if (direct or lg == "en") else "translated" for lg in heads["lang"]]
    out = heads.with_columns(
        pl.Series("label", [x[0] for x in labs], pl.Utf8),
        pl.Series("score", [float(x[1]) for x in labs], pl.Float64),
        pl.Series("reason", [x[2] for x in labs], pl.Utf8),
        pl.lit(scorer).alias("scorer"), pl.lit(used).alias("scorer_used"),
        pl.Series("path", paths, pl.Utf8))
    if save:
        _append_jsonl("scores.jsonl", [
            {"id": r["id"], "scorer": scorer, "scorer_used": used, "label": r["label"],
             "score": r["score"], "at": datetime.now(UTC).isoformat(timespec="seconds")}
            for r in out.select("id", "label", "score").iter_rows(named=True)])
    return out


def scored_ids(scorer: str) -> set[str]:
    """Ids already scored by ``scorer`` (the Scheduler scores only new rows)."""
    return {r["id"] for r in _read_jsonl("scores.jsonl") if r.get("scorer") == scorer}


def compare(a: pl.DataFrame, b: pl.DataFrame) -> Comparison:
    """Agreement between two scorers on the same headlines."""
    return Comparison(a, b)
