"""Describe your screen → rule cards, with a deterministic parser.

The parser understands the common phrasings in Chapters 9, 17 and 21. Every
word it had to *interpret* (a vague word such as "near" or "rising" with no
number) gets an amber "?" and a note saying which number it chose, so you can
edit it. Clauses it cannot read are returned, never silently dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

NUM = r"(\d+(?:\.\d+)?)"
AT_LEAST = r"(?:>=|≥|at least|above|over|more than|greater than|of)?"


@dataclass
class Rule:
    """One rule card: metric, comparison, threshold, plain-English text."""

    metric: str  # e.g. "below_high_pct", "close_vs_sma:50", "rsi:14"
    op: str  # ">=", "<=", ">", "<"
    value: float
    text: str
    interpreted: str = ""  # non-empty → amber "?" with the choice the parser made

    def passes(self, x: float | None) -> bool:
        if x is None:
            return False
        return {
            ">=": x >= self.value,
            "<=": x <= self.value,
            ">": x > self.value,
            "<": x < self.value,
        }[self.op]

    def near_miss(self, x: float | None, band: float = 0.10) -> bool:
        """Passes, but within ``band`` (10%) of a non-zero threshold — "only just"."""
        if x is None or not self.value or not self.passes(x):
            return False
        return abs(x - self.value) <= band * abs(self.value)

    def card(self) -> str:
        flag = " ?" if self.interpreted else ""
        return f"{self.text}{flag}"


@dataclass
class Parsed:
    """Output of the parser."""

    rules: list[Rule] = field(default_factory=list)
    exclude_events: int | None = None
    unparsed: list[str] = field(default_factory=list)

    def read_back(self) -> str:
        """Every rule back in plain English, numbered."""
        lines = [
            f"{i}. {r.text}" + (f"  (interpreted: {r.interpreted})" if r.interpreted else "")
            for i, r in enumerate(self.rules, 1)
        ]
        if self.exclude_events is not None:
            lines.append(
                f"{len(lines) + 1}. Exclude names with results within "
                f"{self.exclude_events} sessions"
            )
        for u in self.unparsed:
            lines.append(f"Not understood (edit or remove): “{u}”")
        return "\n".join(lines)

    def facts(self) -> list[str]:
        return self.read_back().splitlines()


LABELS: dict[str, str] = {
    "below_high_pct": "Below high %",
    "vol_ratio": "Vol ratio",
    "day_vol_ratio": "Vol × 20d",
    "traded_value": "Value",
    "rsi": "RSI",
    "gap_pct": "Gap %",
    "gap_abs_pct": "Gap %",
    "rvol": "RVOL",
    "deliv_pct": "Deliv %",
    "deliv_pct_20d": "Deliv % (20d)",
    "deliv_ratio": "Deliv vs 20d",
    "dist_sma_atr": "To 20d avg (ATR)",
    "rs_3m": "RS 3m",
    "lower_closes": "Lower closes (5)",
    "dip_vol_ratio": "Dip vol ratio",
    "above_high": "Above base high %",
    "close": "Close",
    "close_vs_sma": "vs avg %",
    "sma_cross": "Avg gap %",
    "sma_slope": "Avg slope %",
    "base_range_atr": "Base (ATR)",
    "has_item": "Item since close",
}


def label(metric: str, market: str = "IN") -> str:
    """Column header for a metric."""
    base, _, arg = metric.partition(":")
    if base == "traded_value":
        return "Value ₹ cr" if market == "IN" else "Value $ m"
    if base == "close_vs_sma":
        return f"vs {arg}d avg %"
    if base == "sma_cross":
        a, b = arg.split(":")
        return f"{a}d vs {b}d avg %"
    if base == "sma_slope":
        return f"{arg}d avg slope %"
    if base == "rsi":
        return f"RSI({arg})"
    if base == "dist_sma_atr":
        return f"To {arg}d avg (ATR)"
    if base == "above_high":
        return f"Above {arg}d high %"
    return LABELS.get(base, base)


def _clauses(text: str) -> list[str]:
    text = text.replace("\n", ";")
    text = re.sub(r",\s*(both rising)", r" \1", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*\d+[.)]\s*", "", text, flags=re.MULTILINE)
    parts = re.split(
        r";|,|\.\s|\band\b(?! (?:the )?\d+[- ]day)|\bwith\b|\bwhere\b", text, flags=re.IGNORECASE
    )
    return [p.strip(" .") for p in parts if p and p.strip(" .")]


def _op(word: str) -> str:
    word = word.strip().lower()
    if word in ("below", "under", "<", "less than", "at most", "<=", "≤", "no more than"):
        return "<=" if word in ("at most", "<=", "≤", "no more than") else "<"
    return ">=" if word in (">=", "≥", "at least") else ">"


def _parse_clause(c: str, market: str) -> list[Rule] | int | None:
    """Rules for one clause; an int means "exclude events within N sessions"."""
    s = c.lower().replace("–", "-")
    cur = "₹" if market == "IN" else "$"

    m = re.search(r"exclude .*?events? within\s+(\d+)", s)
    if m:
        return int(m.group(1))

    m = re.search(
        rf"within\s+{NUM}\s*%\s+(?:of|below|from)\s+(?:the |its |their )?52[- ]week high", s
    )
    if m:
        v = float(m.group(1))
        return [
            Rule(
                "below_high_pct",
                "<=",
                v,
                f"Close within {v:g}% of the 52-week high",
                "52-week high = highest intraday high of the last 250 sessions",
            )
        ]
    if re.search(r"(near|close to|at) (?:the |its |their |a )?(?:new )?52[- ]week highs?", s):
        return [
            Rule(
                "below_high_pct",
                "<=",
                5.0,
                "Close within 5% of the 52-week high",
                '"near" read as within 5% of the highest high of the last 250 sessions',
            )
        ]

    m = re.search(
        rf"within\s+{NUM}\s*atr\s+of\s+(?:the |its )?(\d+)[- ]day (?:moving )?(?:average|avg|ma)", s
    )
    if m:
        v, n = float(m.group(1)), int(m.group(2))
        out = [Rule(f"dist_sma_atr:{n}", "<=", v, f"Close within {v:g} ATR of the {n}-day average")]
        m2 = re.search(r"(\d+)\s+lower closes", s)
        if m2:
            k = int(m2.group(1))
            out.append(
                Rule("lower_closes", ">=", k, f"At least {k} lower closes in the last 5 sessions")
            )
        return out
    m = re.search(r"(?:at least|>=|≥)?\s*(\d+)\s+lower closes", s)
    if m:
        k = int(m.group(1))
        return [Rule("lower_closes", ">=", k, f"At least {k} lower closes in the last 5 sessions")]
    if re.search(r"\bpull(?:ed)?[- ]?back\b", s):
        return [
            Rule(
                "dist_sma_atr:20",
                "<=",
                1.0,
                "Close within 1 ATR of the 20-day average",
                '"pullback" read as within 1 ATR of the 20-day average',
            ),
            Rule(
                "lower_closes",
                ">=",
                3,
                "At least 3 lower closes in the last 5 sessions",
                '"pullback" also needs at least 3 lower closes in 5 sessions',
            ),
        ]

    m = re.search(rf"(?:dip|pullback) volume\s*(?:at most|<=|≤|below|under)?\s*{NUM}\s*(?:x|×)", s)
    if m:
        v = float(m.group(1))
        return [
            Rule(
                "dip_vol_ratio",
                "<=",
                v,
                f"Average volume of the last 5 sessions at most {v:g} × the prior 20-day average",
            )
        ]
    if re.search(r"lighter volume|volume (?:drying up|falling|declining)|quieter", s):
        return [
            Rule(
                "dip_vol_ratio",
                "<=",
                0.8,
                "Average volume of the last 5 sessions at most 0.8 × the prior 20-day average",
                '"lighter" read as 20% below the prior 20-day average',
            )
        ]

    m = re.search(rf"(?:rvol|relative volume)\s*{AT_LEAST}\s*{NUM}", s)
    if m:
        v = float(m.group(1))
        return [Rule("rvol", ">=", v, f"Relative volume (RVOL) at least {v:g}")]
    m = re.search(rf"volume\s*(?:ratio)?\s*{AT_LEAST}\s*{NUM}\s*(?:x|×|times)", s)
    if m:
        v = float(m.group(1))
        if "50-day" not in s and "20-day" in s:
            return [
                Rule(
                    "day_vol_ratio",
                    ">=",
                    v,
                    f"Last session's volume at least {v:g} × the prior 20-day average",
                )
            ]
        return [
            Rule("vol_ratio", ">=", v, f"20-day average volume at least {v:g} × the 50-day average")
        ]
    if re.search(
        r"volume (?:is )?(?:rising|picking up|increasing|expanding|up)|rising volume|"
        r"increasing volume|higher volume|heavier volume",
        s,
    ):
        return [
            Rule(
                "vol_ratio",
                ">=",
                1.2,
                "20-day average volume at least 1.2 × the 50-day average",
                '"rising" read as 20-day average ≥ 1.2 × 50-day average (shares, not value)',
            )
        ]

    m = re.search(
        r"(\d+)[- ]day (?:moving )?(?:average|avg|ma|sma) (above|over|below|under) "
        r"(?:the |its )?(\d+)[- ]day",
        s,
    )
    if m:
        a, b, op = int(m.group(1)), int(m.group(3)), _op(m.group(2))
        word = "above" if op == ">" else "below"
        out = [Rule(f"sma_cross:{a}:{b}", op, 0.0, f"{a}-day average {word} the {b}-day average")]
        if "rising" in s:
            out += [
                Rule(f"sma_slope:{a}", ">", 0.0, f"{a}-day average rising over 10 sessions"),
                Rule(f"sma_slope:{b}", ">", 0.0, f"{b}-day average rising over 10 sessions"),
            ]
        return out
    m = re.search(
        r"(?:close|price|trading)?\s*(above|over|below|under) (?:the |its |their )?(\d+)[- ]day "
        r"(?:moving |simple )?(?:average|avg|ma|sma|dma)",
        s,
    )
    if m:
        n, op = int(m.group(2)), _op(m.group(1))
        word = "above" if op == ">" else "below"
        return [Rule(f"close_vs_sma:{n}", op, 0.0, f"Close {word} the {n}-day average")]
    if re.search(r"\b(?:up ?trend|uptrend|trending up)\b", s):
        return [
            Rule(
                "sma_cross:50:200",
                ">",
                0.0,
                "50-day average above the 200-day average",
                '"uptrend" read as 50-day average above the 200-day average',
            )
        ]

    m = re.search(rf"rsi\s*(?:\((\d+)\))?\s*(below|under|<|above|over|>|<=|>=|≤|≥)\s*{NUM}", s)
    if m:
        n, op, v = int(m.group(1) or 14), _op(m.group(2)), float(m.group(3))
        word = "below" if op in ("<", "<=") else "above"
        return [Rule(f"rsi:{n}", op, v, f"RSI({n}) {word} {v:g}")]
    if "oversold" in s:
        return [
            Rule("rsi:14", "<", 30.0, "RSI(14) below 30", '"oversold" read as RSI(14) below 30')
        ]
    if "overbought" in s:
        return [
            Rule("rsi:14", ">", 70.0, "RSI(14) above 70", '"overbought" read as RSI(14) above 70')
        ]

    if re.search(r"\brs\b|relative strength", s):
        m = re.search(rf"(?:above|over|>)\s*{NUM}", s)
        v = float(m.group(1)) if m else 0.0
        note = (
            "RS = 3-month return minus the index's (percentage points)"
            if not m
            else "RS is not RSI: read as 3-month return minus the index's, in points"
        )
        return [
            Rule(
                "rs_3m",
                ">",
                v,
                f"Relative strength vs the index over 3 months above {v:g} pts",
                note,
            )
        ]

    m = re.search(rf"gap(?:s|ped)?\s*(up|down)?\s*{AT_LEAST}\s*{NUM}\s*%", s)
    if m:
        v, side = float(m.group(2)), m.group(1)
        if side == "up":
            return [Rule("gap_pct", ">=", v, f"Gap up at least {v:g}% from the previous close")]
        if side == "down":
            return [Rule("gap_pct", "<=", -v, f"Gap down at least {v:g}% from the previous close")]
        return [
            Rule("gap_abs_pct", ">=", v, f"Gap at least {v:g}% either way from the previous close")
        ]
    if re.search(r"\bgap(?:s|ped)? up\b", s):
        return [
            Rule(
                "gap_pct",
                ">=",
                2.0,
                "Gap up at least 2% from the previous close",
                '"gap up" read as at least 2%',
            )
        ]

    if re.search(r"deliver", s):
        if market != "IN":
            return None
        m = re.search(rf"{AT_LEAST}\s*{NUM}\s*%", s)
        if m:
            v = float(m.group(1))
            return [Rule("deliv_pct_20d", ">=", v, f"Delivery % (20-day average) at least {v:g}%")]
        return [
            Rule(
                "deliv_ratio",
                ">=",
                1.2,
                "Delivery % at least 1.2 × its own 20-day average",
                '"rising delivery" compared with the stock\'s own 20-day average',
            )
        ]

    if re.search(r"liquid|traded value|turnover", s):
        m = re.search(rf"(?:₹|rs\.?|\$)?\s*{NUM}\s*(cr|crore|m|mn|million)", s)
        default = 10.0 if market == "IN" else 20.0
        v = float(m.group(1)) if m else default
        unit = "crore" if market == "IN" else "million"
        rule = Rule(
            "traded_value", ">=", v, f"Median 20-day traded value at least {cur}{v:g} {unit}"
        )
        if not m:
            rule.interpreted = f'"liquid" read as {cur}{v:g} {unit} a day; your size sets this'
        return [rule]

    m = re.search(r"(?:close )?above (?:the |its )?(?:prior )?(\d+)[- ](?:day|session) high", s)
    if m:
        n = int(m.group(1))
        return [Rule(f"above_high:{n}", ">", 0.0, f"Close above the prior {n}-session high")]
    m = re.search(rf"base (?:range )?(?:narrower than|at most|within|below)\s*{NUM}\s*atr", s)
    if m:
        v = float(m.group(1))
        return [Rule("base_range_atr:25", "<=", v, f"25-session base no wider than {v:g} ATR")]
    if re.search(r"break ?out", s):
        return [
            Rule(
                "above_high:25",
                ">",
                0.0,
                "Close above the prior 25-session high",
                '"breakout" read as a close above the prior 25-session high',
            )
        ]

    m = re.search(
        rf"(?:price|close|stocks?)\s*(above|over|below|under)\s*(?:₹|rs\.?|\$)\s*{NUM}", s
    )
    if m:
        op, v = _op(m.group(1)), float(m.group(2))
        word = "above" if op == ">" else "below"
        return [Rule("close", op, v, f"Close {word} {cur}{v:g}")]

    if re.search(r"time[- ]stamped|catalyst|news|headline|filing", s):
        return [
            Rule(
                "has_item",
                ">=",
                1,
                "A time-stamped item since the last close",
                "items come from the news feed with a publication time",
            )
        ]
    return None


def parse(text: str, market: str = "IN") -> Parsed:
    """Turn a plain-English description into rule cards."""
    out = Parsed()
    for clause in _clauses(text):
        got = _parse_clause(clause, market)
        if got is None:
            if re.search(r"\w{3,}", clause):
                out.unparsed.append(clause)
        elif isinstance(got, int):
            out.exclude_events = got
        else:
            out.rules.extend(r for r in got if all(r.metric != x.metric for x in out.rules))
    return out
