"""Ask My Journal: a plain-English question → a constrained query → rows and numbers.

Common questions are pattern-matched. Anything else can go to the local model, which
may only return a *query spec* (whitelisted fields, operators and groupings); code
turns the spec into SQL and runs it on the journal with Polars. The SQL that ran is
what **Show query** displays, so every number can be re-run next month.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from typing import Any

import polars as pl

from .. import ai
from .detectors import RuleCard, TOO_FEW, MIN_N, enrich

#: Fields a query may filter or group on, with their SQL type.
FIELDS: dict[str, str] = {
    "trade_id": "int", "date": "str", "symbol": "str", "underlying": "str", "side": "str",
    "setup": "str", "account": "str", "weekday": "str", "hour": "int", "tod_bucket": "str",
    "window": "str", "hold_minutes": "num", "gap_minutes": "num", "minutes_from_open": "num",
    "r": "num", "gross": "num", "net": "num", "charges": "num", "day_seq": "int",
    "win": "bool", "broke_rule": "bool", "reentry_after_loss": "bool",
    "after_two_losses": "bool", "prev_loss_same_day": "bool", "is_paper": "bool",
    "is_replay": "bool", "is_pilot": "bool", "rules_broken": "str",
}
OPS = ("=", "!=", ">", ">=", "<", "<=", "in", "is", "like")
GROUPS = ("tod_bucket", "weekday", "setup", "underlying", "symbol", "side", "window", "hour",
          "date", "account", "win", "broke_rule")

EXAMPLES = (
    "How did I do on trades I opened soon after a loss this month?",
    "Compare my SPY and QQQ trades held more than an hour with the rest.",
    "How do my trades after two losses in a row compare with the rest?",
    "Results by time of day",
    "Which of those broke a Rule Card line?",
    "How do my expiry-afternoon trades compare?",
)

SPEC_SCHEMA = {
    "type": "object",
    "properties": {
        "filters": {"type": "array", "items": {"type": "array"}},
        "group_by": {"type": ["string", "null"]},
        "compare": {"type": ["array", "null"]},
        "label": {"type": "string"},
    },
    "required": ["filters", "label"],
}


class QueryError(ValueError):
    """A spec that uses a field or operator outside the whitelist."""


@dataclass
class QuerySpec:
    """What the lab understood: filters, an optional grouping or 'compare with the rest'."""

    filters: list[list[Any]] = field(default_factory=list)   # [field, op, value]
    group_by: str | None = None
    compare: list[Any] | None = None                          # [field, op, value]
    label: str = "all trades"

    def validate(self) -> "QuerySpec":
        for cond in [*self.filters, *([self.compare] if self.compare else [])]:
            if len(cond) != 3 or cond[0] not in FIELDS or str(cond[1]).lower() not in OPS:
                raise QueryError(f"Not allowed in a journal query: {cond}")
        if self.group_by and self.group_by not in GROUPS:
            raise QueryError(f"Cannot group by {self.group_by!r}")
        return self

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, text: str | dict) -> "QuerySpec":
        d = json.loads(text) if isinstance(text, str) else dict(text)
        return cls(filters=[list(f) for f in d.get("filters", [])], group_by=d.get("group_by"),
                   compare=list(d["compare"]) if d.get("compare") else None,
                   label=d.get("label", "all trades")).validate()

    # ---------------------------------------------------------------- SQL
    def where_sql(self) -> str:
        return " AND ".join(_cond_sql(c) for c in self.filters) if self.filters else "TRUE"

    def to_sql(self) -> str:
        """The exact SQL that runs on the ``journal`` view."""
        self.validate()
        metrics = ("COUNT(*) AS trades, SUM(CASE WHEN win THEN 1 ELSE 0 END) AS wins, "
                   "ROUND(SUM(r), 2) AS total_r, ROUND(AVG(r), 2) AS mean_r, "
                   "ROUND(SUM(charges), 2) AS charges, ROUND(SUM(net), 2) AS net, "
                   "MEDIAN(hold_minutes) AS median_hold_min")
        if self.compare:
            key = f"CASE WHEN {_cond_sql(self.compare)} THEN 'match' ELSE 'rest' END"
            return (f"SELECT {key} AS grp, {metrics} FROM journal WHERE {self.where_sql()} "
                    f"GROUP BY grp ORDER BY grp")
        if self.group_by:
            g = self.group_by
            return (f"SELECT {g}, {metrics} FROM journal WHERE {self.where_sql()} "
                    f"GROUP BY {g} ORDER BY {g}")
        return f"SELECT {metrics} FROM journal WHERE {self.where_sql()}"

    def rows_sql(self) -> str:
        where = self.where_sql()
        if self.compare:
            where = f"({where}) AND {_cond_sql(self.compare)}"
        return f"SELECT trade_id FROM journal WHERE {where} ORDER BY trade_id"


def _lit(v: Any) -> str:
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(float(v)) if isinstance(v, float) else str(v)
    return "'" + str(v).replace("'", "''") + "'"


def _cond_sql(c: list[Any]) -> str:
    f, op, v = c[0], str(c[1]).lower(), c[2]
    if f not in FIELDS or op not in OPS:
        raise QueryError(f"Not allowed: {c}")
    if op == "is":
        return f"{f}" if v else f"NOT {f}"
    if op == "in":
        vals = v if isinstance(v, (list, tuple)) else [v]
        return f"{f} IN ({', '.join(_lit(x) for x in vals)})"
    if op == "like":
        return f"{f} LIKE {_lit('%' + str(v) + '%')}"
    return f"{f} {op} {_lit(v)}"


# ------------------------------------------------------------------ execution
def journal_view(trades: pl.DataFrame, card: RuleCard | None = None) -> pl.DataFrame:
    """The enriched journal every query runs on (one row per round trip)."""
    e = enrich(trades, card)
    if e.is_empty():
        return pl.DataFrame(schema={k: pl.Utf8 for k in FIELDS})
    return e.with_columns(
        is_paper=pl.col("tags").list.contains("PAPER").fill_null(False),
        is_replay=pl.col("tags").list.contains("REPLAY").fill_null(False),
        is_pilot=pl.col("tags").list.contains("PILOT").fill_null(False),
        rules_broken=pl.col("rules_broken").fill_null(""),
    ).select([c for c in FIELDS])


def execute(spec: QuerySpec, view: pl.DataFrame) -> tuple[pl.DataFrame, list[int]]:
    """Run the spec's SQL; return (result table, matching trade ids)."""
    if view.is_empty() or view.schema.get("r") == pl.Utf8:
        return pl.DataFrame(), []
    ctx = pl.SQLContext(journal=view)
    table = ctx.execute(spec.to_sql()).collect()
    rows = ctx.execute(spec.rows_sql()).collect()["trade_id"].to_list()
    return table, rows


@dataclass
class Answer:
    """A journal answer: the question, the read-back, the SQL, the numbers and the rows."""

    question: str
    spec: QuerySpec
    table: pl.DataFrame
    rows: list[int]
    text: str
    via: str = "pattern"          # pattern | model | follow-up
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def sql(self) -> str:
        return self.spec.to_sql()

    def facts(self) -> list[str]:
        out = [f"Question: {self.question}", f"Query: {self.spec.label}", f"SQL: {self.sql}"]
        for r in self.table.iter_rows(named=True):
            out.append(", ".join(f"{k}={v}" for k, v in r.items()))
        out.append(f"Rows: {', '.join(map(str, self.rows[:60]))}")
        out += [f"{k}: {v}" for k, v in self.extras.items()]
        return out


# ------------------------------------------------------------------ parsing
_WORDS = {"a": 1.0, "an": 1.0, "one": 1.0, "two": 2.0}


def _duration(m: re.Match) -> float:
    """Minutes from a matched '<n> <hours|minutes>' phrase."""
    n = _WORDS.get(m.group("n")) or float(m.group("n"))
    return n * 60 if m.group("unit").startswith("h") else n


def parse(question: str, symbols: list[str] | None = None,
          previous: QuerySpec | None = None) -> QuerySpec | None:
    """Pattern-match a common question into a spec, or None if nothing matched."""
    q = question.lower().strip()
    follow = previous is not None and re.match(r"^(which of those|of those|and |what about|"
                                               r"how many of those|those )", q)
    filters: list[list[Any]] = [list(f) for f in previous.filters] if follow else []
    if follow and previous.compare:
        filters.append(list(previous.compare))
    labels: list[str] = [previous.label] if follow else []
    cond: list[Any] | None = None
    cond_label = ""
    group: str | None = None

    m = re.search(r"(soon|quick\w*|right|straight|within (?P<n>\d+) min\w*) after (a|losing|my)"
                  r" (loss|losing|trade)", q) or re.search(r"after a loss", q)
    if m:
        mins = int(m.group("n")) if "n" in m.groupdict() and m.group("n") else 30
        filters += [["prev_loss_same_day", "is", True], ["gap_minutes", "<=", mins]]
        labels.append(f"trades where the previous trade on the same day was a loss and the gap "
                      f"was {mins} minutes or less")
    if re.search(r"after (two|2) losses", q):
        cond, cond_label = ["after_two_losses", "is", True], "trades after two losses in a row"
    m = re.search(r"held (more|longer|over) than (?P<n>\d+|an?|one|two) ?"
                  r"(?P<unit>hours?|min\w*)", q)
    if m:
        cond = ["hold_minutes", ">", _duration(m)]
        cond_label = f"trades held more than {_duration(m):g} minutes (entry to exit)"
    m = re.search(r"held (less|shorter|under) than (?P<n>\d+|an?|one|two) ?(?P<unit>hours?|min\w*)",
                  q)
    if m:
        cond = ["hold_minutes", "<", _duration(m)]
        cond_label = f"trades held less than {_duration(m):g} minutes (entry to exit)"
    m = re.search(r"first (?P<n>\d+) ?min", q) or re.search(r"\bopening (minutes|trades)", q)
    if m:
        n = int(m.groupdict().get("n") or 15)
        cond = ["minutes_from_open", "<", n]
        cond_label = f"trades opened in the first {n} minutes"
    if "expiry afternoon" in q or "expiry-afternoon" in q:
        cond, cond_label = ["window", "=", "expiry afternoon"], "expiry-afternoon trades"
    if re.search(r"last (30|half hour)", q):
        cond, cond_label = ["window", "=", "last 30 min"], "trades in the last 30 minutes"
    if re.search(r"broke (a|the|any) (rule|line)|rule(-| )break|broke a rule card", q):
        filters.append(["broke_rule", "is", True])
        labels.append("that broke at least one Rule Card line")
    elif re.search(r"(followed|broke no|kept) (the |my )?(rule|line)", q):
        filters.append(["broke_rule", "is", False])
        labels.append("that broke no Rule Card line")
    if re.search(r"\b(losers|losing trades)\b", q):
        filters.append(["win", "is", False])
        labels.append("losing trades")
    elif re.search(r"\b(winners|winning trades)\b", q):
        filters.append(["win", "is", True])
        labels.append("winning trades")
    if re.search(r"\blong (trades|side|positions)\b|\blongs\b", q):
        filters.append(["side", "=", "LONG"])
        labels.append("long trades")
    elif re.search(r"\bshort (trades|side|positions)\b|\bshorts\b", q):
        filters.append(["side", "=", "SHORT"])
        labels.append("short trades")
    if re.search(r"\bpaper\b", q):
        filters.append(["is_paper", "is", True])
        labels.append("PAPER trades")
    named = [s for s in (symbols or []) if re.search(rf"\b{re.escape(s.lower())}\b", q)]
    if named:
        filters.append(["underlying", "in", named])
        labels.append(" and ".join(named) + " trades")
    for pat, g in ((r"time of day|by hour|entry time|by the hour", "tod_bucket"),
                   (r"weekday|day of (the )?week|by day\b", "weekday"),
                   (r"by setup|each setup|per setup", "setup"),
                   (r"by (symbol|instrument|ticker)", "underlying"),
                   (r"by date|per day|each day", "date")):
        if re.search(pat, q):
            group = g
    compare = bool(re.search(r"compare|compared|with the rest|vs\.? the rest|against the rest|"
                             r"than the rest|versus", q))
    if cond is not None and not compare:
        filters.append(cond)
        labels.append(cond_label)
        cond = None
    if cond is None and compare and len(named) > 1 and not group:
        group = "underlying"
        filters = [f for f in filters if f[0] != "underlying"] + [["underlying", "in", named]]
    if not (filters or group or cond):
        return None
    label = "; ".join(x for x in labels if x) or "all trades"
    if cond is not None:
        label += (" · " if labels else "") + f"{cond_label} vs the rest"
    if group:
        label += f" · grouped by {group}"
    return QuerySpec(filters=filters, group_by=group, compare=cond, label=label).validate()


def spec_from_model(question: str, previous: QuerySpec | None = None) -> QuerySpec | None:
    """Ask the local model for a spec (never numbers); None if no model or invalid spec."""
    prompt = (
        "Turn the trader's question into a JSON query spec for their trading journal. "
        "Return ONLY JSON with keys: filters (list of [field, op, value]), group_by (field or "
        "null), compare (one [field, op, value] to compare against the rest, or null), label "
        "(plain-English read-back of what you will count). Do not compute anything.\n"
        f"Allowed fields: {', '.join(FIELDS)}\nAllowed ops: {', '.join(OPS)}\n"
        f"Allowed group_by: {', '.join(GROUPS)}\n"
        + (f"Previous query: {previous.to_json()}\n" if previous else "")
        + f"Question: {ai.fence_untrusted(question)}")
    out = ai.complete(prompt, section="Journal", schema=SPEC_SCHEMA, sensitive=True)
    if not out.text:
        return None
    try:
        return QuerySpec.from_json(ai.extract_json(out.text))
    except (ValueError, QueryError, TypeError, KeyError):
        return None


def _sentence(spec: QuerySpec, table: pl.DataFrame, market: str) -> str:
    cur = "₹" if market == "IN" else "$"
    if table.is_empty():
        return "No trades matched this query."
    parts = []
    for i, r in enumerate(table.iter_rows(named=True)):
        head = ""
        if spec.compare:
            head = "Matching trades: " if r["grp"] == "match" else "All other trades: "
        elif spec.group_by:
            head = f"{r[spec.group_by]}: "
        n = int(r["trades"] or 0)
        if not n:
            parts.append(head + "no trades.")
            continue
        tr = r["total_r"] or 0.0
        verb = "made" if tr >= 0 else "lost"
        note = f" n = {n}: {TOO_FEW}." if n < MIN_N else f" n = {n}."
        parts.append(
            f"{head}{n} trades [q1] won {int(r['wins'] or 0)} times [q2] and {verb} "
            f"{abs(tr):.2f}R in total [q3], paying {cur}{(r['charges'] or 0):,.2f} in charges "
            f"[q4]; median hold {r['median_hold_min']} min.{note}")
    return " ".join(parts)


def ask(question: str, trades: pl.DataFrame, previous: QuerySpec | None = None,
        use_model: bool = True, card: RuleCard | None = None) -> Answer:
    """Answer a plain-English question about the journal. Numbers come from SQL only."""
    view = journal_view(trades, card)
    symbols = sorted({s for s in view["underlying"].to_list() if s}) if view.height else []
    spec, via = parse(question, symbols, previous), "pattern"
    if spec and previous is not None and spec.label.startswith(previous.label):
        via = "follow-up"
    if spec is None and use_model:
        spec, via = spec_from_model(question, previous), "model"
    if spec is None:
        return Answer(question, QuerySpec(label="(not understood)"), pl.DataFrame(), [],
                      "I could not turn that into a journal query. Try one of: "
                      + " · ".join(EXAMPLES), via="none")
    table, rows = execute(spec, view)
    market = (trades["market"][0] if trades.height else None) or "IN"
    extras: dict[str, Any] = {}
    if any(f[0] == "prev_loss_same_day" for f in spec.filters) and view.height:
        e = enrich(trades, card)
        med = lambda s: None if s.is_empty() else round(float(s.median()), 1)  # noqa: E731
        extras["median wait after a loss (min)"] = med(
            e.filter(pl.col("prev_win") == False)["gap_minutes"].drop_nulls())  # noqa: E712
        extras["median wait after a win (min)"] = med(
            e.filter(pl.col("prev_win") == True)["gap_minutes"].drop_nulls())  # noqa: E712
    text = _sentence(spec, table, market)
    if extras:
        text += (f" Your median wait after a loss was {extras['median wait after a loss (min)']} "
                 f"minutes, against {extras['median wait after a win (min)']} after a win [q5].")
    return Answer(question, spec, table, rows, text, via=via, extras=extras)


def run_pinned(spec: QuerySpec, trades: pl.DataFrame, start: str, end: str,
               card: RuleCard | None = None) -> Answer:
    """Re-run a pinned question on one week (Weekly Review)."""
    week = QuerySpec(filters=[*spec.filters, ["date", ">=", start], ["date", "<=", end]],
                     group_by=spec.group_by, compare=spec.compare, label=spec.label)
    view = journal_view(trades, card)
    table, rows = execute(week, view)
    market = (trades["market"][0] if trades.height else None) or "IN"
    return Answer(spec.label, week, table, rows, _sentence(week, table, market), via="pinned")


def week_bounds(day: str) -> tuple[str, str]:
    """Monday and Sunday (ISO strings) of the week containing ``day``."""
    from datetime import date as _d
    d = _d.fromisoformat(day)
    mon = d - timedelta(days=d.weekday())
    return mon.isoformat(), (mon + timedelta(days=6)).isoformat()
