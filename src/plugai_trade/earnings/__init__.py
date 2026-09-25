"""Research › Earnings Desk: results calendar, results digest, implied vs historical move.

    from plugai_trade import earnings
    rows = earnings.results_calendar(["SYN-IN-004", "NIFTY"], market="IN", macro=True)
    im = earnings.implied_move("SYN-US-006", market="US")
    print(im.facts())            # Straddle, Implied move, Average move (last 8), Median, Largest

Dates come from the lab calendar with a source and time stamp on every row.
The digest's Change column and every move are computed in code. The option
chain offline is synthetic and labelled so; nothing here suggests a trade.
"""

from __future__ import annotations

import hashlib
import math
import re
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import polars as pl

from .. import alerts, data
from .. import indicators as ind
from ..data import INDEX_SYMBOLS
from ..docdesk import Document, extract
from ..docdesk.extract import CONFIDENT, HEDGING
from ..store import default as store
from . import calendar
from .calendar import Event
from .pricing import straddle

# ---------------------------------------------------------------- results calendar


def _touches(e: Event, symbols: set[str]) -> bool:
    return e.kind in ("macro", "expiry") or e.symbol in symbols


def results_calendar(
    symbols: list[str],
    market: str,
    start: date | None = None,
    days: int = 7,
    macro: bool = True,
    positions: list[str] | None = None,
    windows: dict[str, date] | None = None,
) -> list[dict[str, Any]]:
    """Calendar rows for the week with an Overlap column.

    Overlap is flagged when more than one event on a day touches an open
    position, or when a results date falls inside a plan's holding window.
    """
    start = start or date.today()
    end = start + timedelta(days=days)
    evs = calendar.events(market, start, end, symbols, macro=macro)
    held = set(positions or [])
    windows = windows or {}
    rows = []
    for e in evs:
        same_day = [x for x in evs if x.date == e.date and _touches(x, held)]
        overlap = ""
        if held and _touches(e, held) and len(same_day) > 1:
            overlap = f"{len(same_day)} events touch open positions"
        if e.symbol in windows and e.date <= windows[e.symbol]:
            overlap = (overlap + "; " if overlap else "") + "inside plan holding window"
        rows.append(
            {
                "Date": e.date.isoformat(),
                "Time": f"{e.time} {e.tz}",
                "Event": e.title,
                "Symbol": e.symbol or "—",
                "Kind": e.kind,
                "Status": "estimated" if e.estimated else "confirmed",
                "Source": e.source,
                "Stamped": e.stamped,
                "Overlap": overlap,
            }
        )
    return rows


def send_to_alerts(rows: list[dict[str, Any]], market: str, channel: str = "Desktop") -> list[int]:
    """One SIMULATED event alert per row, *proposed* until you click Accept in Alerts."""
    out = []
    for r in rows:
        a = alerts.Alert(
            name=f"{r['Event']} · {r['Date']} {r['Time']}",
            symbol=r["Symbol"],
            market=market,
            kind="event",
            condition="new item",
            bar_size="daily close",
            expires=r["Date"],
            channels=[channel],
            plan_name="Earnings Desk",
        )
        out.append(alerts.save(a).id)
    return out


# ---------------------------------------------------------------- results digest
_NUM = re.compile(
    r"(₹|\$)?\s?(\d[\d,]*(?:\.\d+)?)\s*(crore|cr|million|mn|bn|billion|%|days)?", re.IGNORECASE
)
DIGEST_FIELDS = ("Revenue", "EBITDA margin", "Net profit", "Receivable days")


def figures(quote: str) -> list[tuple[float, str]]:
    """Numbers quoted in a sentence with their unit (₹ crore, %, days …), in order."""
    out = []
    for cur, num, unit in _NUM.findall(quote):
        if not cur and not unit:
            if re.fullmatch(r"\d{1,2}", num):  # bare small numbers such as "78" count as days
                unit = "days" if "day" in quote.lower() else ""
            if not unit:
                continue
        out.append((float(num.replace(",", "")), (cur + " " + unit).strip()))
    return out


def change(current: float, prior: float, unit: str) -> str:
    """Change computed in code: % for money, percentage points for %, difference for days."""
    if unit.endswith("%"):
        return f"{current - prior:+.1f} pp"
    if "day" in unit:
        return f"{current - prior:+g}"
    return f"{(current / prior - 1) * 100:+.1f}%" if prior else "n/a"


def guidance_chip(before: str, after: str) -> str:
    """unchanged / wording softer / wording firmer, from words added or dropped."""

    def words(s: str) -> list[str]:
        return re.findall(r"[a-z]+", s.lower())

    a, b = words(before), words(after)
    if a == b:
        return "unchanged"
    firm = set(CONFIDENT) | {"high", "higher", "raise", "raised", "upgrade", "above", "record"}
    soft = {w for w in HEDGING if " " not in w} | {
        "low",
        "lower",
        "cut",
        "below",
        "moderate",
        "subject",
        "continue",
    }
    dropped, added = set(a) - set(b), set(b) - set(a)
    score = (len(added & firm) - len(dropped & firm)) - (len(added & soft) - len(dropped & soft))
    if score < 0:
        return "wording softer"
    if score > 0:
        return "wording firmer"
    return "unchanged"


@dataclass
class Digest:
    """Results digest: quoted figures with page chips, Change computed in code."""

    company: str
    rows: list[dict[str, Any]]
    guidance_now: str
    guidance_cite: str
    guidance_before: str = ""
    guidance_before_cite: str = ""
    chip: str = "no previous digest"
    consensus: list[dict[str, Any]] = field(default_factory=list)

    def facts(self) -> list[str]:
        out = [
            f"{r['Item']}: {r['This quarter']} vs {r['Comparison']} ({r['Change']}) {r['Page']}"
            for r in self.rows
        ]
        out.append(f"Guidance now: “{self.guidance_now}” {self.guidance_cite}")
        if self.guidance_before:
            out.append(f"Guidance before: “{self.guidance_before}” {self.guidance_before_cite}")
        out.append(f"Guidance chip: {self.chip}")
        out += [
            f"Consensus {c['Item']}: {c['Consensus']} ({c['Source']}); difference {c['Difference']}"
            for c in self.consensus
        ]
        return out


def digest(
    doc: Document, company: str | None = None, prior: dict[str, str] | None = None
) -> Digest:
    """Run the quote-first results template, then compute the Change column.

    ``prior`` is last quarter's saved guidance ({"quote", "cite"}); by default
    the most recent saved digest for the company is used.
    """
    company = company or doc.name
    ext = extract(doc, "Results set")
    rows = []
    for r in ext.rows:
        if r.field not in DIGEST_FIELDS:
            continue
        nums = figures(r.quote) if r.status == "found" else []
        if len(nums) >= 2:
            (cur, unit), (prev, _) = nums[0], nums[1]
            rows.append(
                {
                    "Item": r.field,
                    "This quarter": _fmt(cur, unit),
                    "Comparison": _fmt(prev, unit),
                    "Change": change(cur, prev, unit),
                    "Page": r.cite,
                }
            )
        else:
            rows.append(
                {
                    "Item": r.field,
                    "This quarter": r.quote or "not found in source",
                    "Comparison": "—",
                    "Change": "—",
                    "Page": r.cite,
                }
            )
    g = next(r for r in ext.rows if r.field == "Guidance")
    out = Digest(company, rows, g.quote or "not found in source", g.cite)
    before = prior or last_guidance(company)
    if before and g.status == "found":
        out.guidance_before, out.guidance_before_cite = before["quote"], before.get("cite", "")
        out.chip = guidance_chip(before["quote"], g.quote)
    return out


def _fmt(v: float, unit: str) -> str:
    if unit.startswith("₹"):
        return f"₹{v:,g} cr"
    if unit.startswith("$"):
        return f"${v:,g} m"
    if unit == "%":
        return f"{v:g}%"
    return f"{v:g}"


def add_consensus(d: Digest, item: str, consensus: float, source: str, as_of: str) -> Digest:
    """The Consensus box: figures you copied, with source and date. The desk only subtracts."""
    row = next((r for r in d.rows if r["Item"] == item), None)
    actual = figures(row["This quarter"]) if row else []
    diff = "n/a"
    if actual:
        val, unit = actual[0]
        diff = change(val, consensus, unit)
    d.consensus.append(
        {"Item": item, "Consensus": consensus, "Source": f"{source} · {as_of}", "Difference": diff}
    )
    return d


def save_digest(d: Digest, market: str) -> int:
    """Accept: save to the Thesis tracker so next quarter's guidance comparison starts here."""
    return store().add(
        "theses",
        {
            "holding": d.company,
            "why": "Results digest (Earnings Desk)",
            "conditions": [],
            "figures": [],
            "name": d.company,
            "kind": "earnings_digest",
            "market": market,
            "rows": d.rows,
            "guidance": {"quote": d.guidance_now, "cite": d.guidance_cite},
            "chip": d.chip,
            "consensus": d.consensus,
            "source": "Earnings Desk",
        },
        tag="earnings_digest",
    )


def last_guidance(company: str) -> dict[str, str] | None:
    """Last saved guidance sentence for a company (History)."""
    for row in store().all("theses", tag="earnings_digest"):
        if row.get("name") == company:
            return row.get("guidance")
    return None


def history(company: str) -> list[dict[str, Any]]:
    """Saved digests for a company, newest first."""
    return [r for r in store().all("theses", tag="earnings_digest") if r.get("name") == company]


# ---------------------------------------------------------------- moves
def _reaction(bars: pl.DataFrame, e: Event) -> dict[str, Any] | None:
    """Close before the announcement *time* → close of the first session that could react."""
    after_close = e.time >= ("15:30" if e.market == "IN" else "16:00")
    before = (
        bars.filter(pl.col("date") <= e.date)
        if after_close
        else bars.filter(pl.col("date") < e.date)
    )
    react = (
        bars.filter(pl.col("date") > e.date)
        if after_close
        else bars.filter(pl.col("date") >= e.date)
    )
    if not before.height or not react.height:
        return None
    c0, c1 = float(before["close"][-1]), float(react["close"][0])
    return {
        "event": e.date.isoformat(),
        "time": f"{e.time} {e.tz}",
        "close_before": round(c0, 2),
        "close_after": round(c1, 2),
        "move_pct": round((c1 / c0 - 1) * 100, 2),
        "from": before["date"][-1].isoformat(),
        "to": react["date"][0].isoformat(),
    }


def historical_moves(
    symbol: str, market: str, asof: date | None = None, n: int = 8, source: str | None = "synthetic"
) -> list[dict[str, Any]]:
    """The last ``n`` results-day moves, each tied to its announcement."""
    asof = asof or date.today()
    evs = calendar.results_dates(symbol, market, asof - timedelta(days=int(n * 95)), asof)[-n:]
    if not evs:
        return []
    bars = data.get(
        symbol, market=market, start=evs[0].date - timedelta(days=10), end=asof, source=source
    )
    return [m for m in (_reaction(bars, e) for e in evs) if m]


def in_fo_list(symbol: str, market: str) -> bool:
    """Does the (synthetic) universe list options on this name? Indices and US names: yes."""
    if market == "US" or symbol.upper() in INDEX_SYMBOLS:
        return True
    return int(hashlib.sha256(symbol.encode()).hexdigest()[:6], 16) % 3 == 0


def _strike_step(spot: float) -> float:
    raw = spot * 0.005
    mag = 10 ** math.floor(math.log10(raw))
    return next(m * mag for m in (1, 2, 2.5, 5, 10) if raw <= m * mag)


@dataclass
class ImpliedMove:
    """Implied vs historical move tiles, all computed in code."""

    symbol: str
    market: str
    event: str
    event_date: date
    expiry: date
    spot: float
    strike: float
    call: float
    put: float
    straddle: float
    iv: float
    base_iv: float
    moves: list[dict[str, Any]]
    chain_source: str
    asof: date

    @property
    def implied_move_pct(self) -> float:
        return self.straddle / self.spot * 100

    def tiles(self) -> dict[str, str]:
        abs_moves = [abs(m["move_pct"]) for m in self.moves]
        t = {"Straddle": f"{self.straddle:,.2f}", "Implied move": f"±{self.implied_move_pct:.2f}%"}
        if abs_moves:
            t |= {
                "Average move (last 8)": f"{statistics.mean(abs_moves):.2f}%",
                "Median": f"{statistics.median(abs_moves):.2f}%",
                "Largest": f"{max(abs_moves):.2f}%",
            }
        return t

    def facts(self) -> list[str]:
        out = [
            f"{self.symbol}: {self.event} on {self.event_date}; first expiry after it "
            f"{self.expiry}; spot {self.spot:,.2f} (last close before the announcement time)",
            f"ATM strike {self.strike:,.2f}: call {self.call:,.2f}, put {self.put:,.2f} "
            f"({self.chain_source})",
        ]
        out += [f"{k}: {v}" for k, v in self.tiles().items()]
        out += [
            f"Results move {m['event']}: {m['move_pct']:+.2f}% ({m['from']} → {m['to']})"
            for m in self.moves
        ]
        return out

    def scenarios(self, moves: tuple[float, ...] = (-10, -5, 0, 5, 10)) -> pl.DataFrame:
        """Straddle value one day later after an IV crush to the normal level."""
        years = max((self.expiry - self.event_date).days - 1, 0) / 365
        rows = []
        for m in moves:
            s = self.spot * (1 + m / 100)
            _, _, v = straddle(s, self.strike, years, self.base_iv)
            rows.append(
                {
                    "Move": f"{m:+d}%",
                    "Spot": round(s, 2),
                    "Straddle after IV crush": round(v, 2),
                    "Change": round(v - self.straddle, 2),
                }
            )
        return pl.DataFrame(rows)

    def event_split(self, normal_daily_vol: float | None = None) -> dict[str, float]:
        """Approximate: event-day move = √(total variance − (days − 1) × normal-day variance)."""
        days = max(calendar.sessions_between(self.asof, self.expiry), 1)
        total_var = (self.iv**2) * max((self.expiry - self.asof).days, 1) / 365
        normal = normal_daily_vol if normal_daily_vol is not None else self.base_iv / math.sqrt(252)
        event_var = max(total_var - (days - 1) * normal**2, 0.0)
        return {
            "sessions to expiry": days,
            "normal-day move %": round(normal * 100, 2),
            "event-day move %": round(math.sqrt(event_var) * 100, 2),
        }


def _first_expiry_after(market: str, d: date) -> date:
    """India: the next index expiry in the Contract Table. US: the following weekly Friday."""
    if market == "IN":
        exp = [
            e.date for e in calendar.expiry_events(market, d, d + timedelta(days=45)) if e.date > d
        ]
        if exp:
            return exp[0]
    return d + timedelta(days=(4 - d.weekday()) % 7 or 7)


def implied_move(
    symbol: str, market: str, event: Event | None = None, asof: date | None = None
) -> ImpliedMove | None:
    """Price the first-expiry ATM straddle after the event on the synthetic chain.

    Returns None for a name with no listed options (not in the F&O list).
    """
    asof = asof or date.today()
    if not in_fo_list(symbol, market):
        return None
    if event is None:
        event = calendar.next_event(symbol, market, asof) or Event(
            asof + timedelta(days=7),
            "16:30",
            calendar.TZ[market],
            market,
            "macro",
            symbol,
            "Next scheduled event",
            calendar.rules()["source"],
            asof.isoformat(),
        )
    bars = data.get(
        symbol, market=market, start=asof - timedelta(days=900), end=asof, source="synthetic"
    )
    spot = float(bars["close"][-1])
    rv = float(ind.realised_vol(bars, 20)["vol_20"][-1])
    moves = historical_moves(symbol, market, asof)
    avg = (
        statistics.mean(abs(m["move_pct"]) for m in moves) / 100
        if moves
        else rv / math.sqrt(252) * 2
    )
    expiry = _first_expiry_after(market, event.date)
    days = max((expiry - asof).days, 1)
    base_iv = rv * 1.05
    iv = math.sqrt(base_iv**2 + (avg**2) * 365 / days)
    step = _strike_step(spot)
    strike = round(spot / step) * step
    c, p, s = straddle(spot, strike, days / 365, iv)
    return ImpliedMove(
        symbol,
        market,
        event.title,
        event.date,
        expiry,
        spot,
        strike,
        c,
        p,
        s,
        iv,
        base_iv,
        moves,
        f"synthetic chain (sample) · as of {asof}",
        asof,
    )


def save_move_to_journal(im: ImpliedMove) -> int:
    """Log the implied move before the event; the actual move is added after it."""
    return store().add(
        "notes",
        {
            "screen": "Earnings Desk",
            "kind": "event_move",
            "symbol": im.symbol,
            "market": im.market,
            "event": im.event,
            "event_date": im.event_date.isoformat(),
            "implied_move_pct": round(im.implied_move_pct, 2),
            "straddle": round(im.straddle, 2),
            "actual_move_pct": None,
            "text": f"{im.symbol} {im.event} ({im.event_date}): implied move "
            f"±{im.implied_move_pct:.2f}% before the event",
        },
        tag="journal",
    )


def fill_actual_moves(asof: date | None = None) -> int:
    """After the event: add the actual move to each saved implied-move row. Returns rows updated."""
    asof = asof or date.today()
    n = 0
    for row in store().all("notes", tag="journal"):
        if row.get("kind") != "event_move" or row.get("actual_move_pct") is not None:
            continue
        ev_d = date.fromisoformat(row["event_date"])
        if ev_d >= asof:
            continue
        bars = data.get(
            row["symbol"],
            market=row["market"],
            start=ev_d - timedelta(days=10),
            end=ev_d + timedelta(days=10),
            source="synthetic",
        )
        e = Event(ev_d, "16:30", "", row["market"], "results", row["symbol"], row["event"], "", "")
        m = _reaction(bars, e)
        if m:
            body = {k: v for k, v in row.items() if k not in ("id", "created", "tag")}
            body["actual_move_pct"] = m["move_pct"]
            body["text"] += f"; actual move {m['move_pct']:+.2f}%"
            store().update("notes", row["id"], body)
            n += 1
    return n


def open_in_options_builder(im: ImpliedMove) -> int:
    """Hand the straddle to Derivatives › Options Strategy Builder as a draft (never an order)."""
    legs = [
        {"kind": k, "strike": im.strike, "side": "buy", "expiry": im.expiry.isoformat()}
        for k in ("call", "put")
    ]
    return store().add(
        "notes",
        {
            "kind": "options_prefill",
            "symbol": im.symbol,
            "market": im.market,
            "legs": legs,
            "note": f"Straddle around {im.event} ({im.event_date})",
            "source": "Earnings Desk",
        },
        tag="options_prefill",
    )


__all__ = [
    "Digest",
    "Event",
    "ImpliedMove",
    "add_consensus",
    "calendar",
    "change",
    "digest",
    "figures",
    "fill_actual_moves",
    "guidance_chip",
    "historical_moves",
    "history",
    "implied_move",
    "in_fo_list",
    "last_guidance",
    "open_in_options_builder",
    "results_calendar",
    "save_digest",
    "save_move_to_journal",
    "send_to_alerts",
]
