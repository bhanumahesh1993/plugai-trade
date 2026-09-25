"""Plain English → rule spec (Chapter 11's "sentence to rules").

The deterministic parser handles the book's phrasings: N-day averages (simple or
exponential), crosses / first close above, close above/below an average, "hold
while the fast average is above the slow one", 52-week highs, RSI thresholds,
N-month momentum, time stops, percentage stops, check days, "fill next open",
volatility sizing with buffer and cap, cost profiles and slippage.

Anything the sentence leaves out is filled with a default and listed in
``spec.assumed`` — the Strategy Builder paints those fields amber. When the
parser cannot find an entry at all and a model is reachable, a model may draft
the spec (``ai.complete(schema=...)``); the result is validated like any other.
"""

from __future__ import annotations

import re
from typing import Any

from .. import ai
from .. import costs as _costs
from .spec import DAYS_PER_MONTH, Condition, Cost, Operand, Size, Spec, SpecError

_UNIT_DAYS = {"day": 1, "d": 1, "session": 1, "bar": 1, "week": 5, "wk": 5, "month": DAYS_PER_MONTH,
              "mo": DAYS_PER_MONTH, "year": 252}

_CROSS_UP = (r"first closes? above|closes? back above|crosse?s? (?:above|over)|crosses up through|"
             r"moves? above|breaks? above|rises? above")
_CROSS_DN = (r"first closes? below|closes? back below|crosse?s? (?:below|under)|crosses down through|"
             r"moves? below|breaks? below")
_ABOVE = r"is above|closes? above|stays? above|remains? above|trades? above|is over|is higher than|" \
         r"is greater than|exceeds?|above|over|higher than"
_BELOW = r"is below|closes? below|falls? below|drops? below|dips? below|stays? below|is under|" \
         r"is lower than|is less than|below|under|lower than"
_COMPARATORS = [("cross_above", _CROSS_UP), ("cross_below", _CROSS_DN),
                ("above", _ABOVE), ("below", _BELOW)]
_CMP_RE = re.compile("|".join(f"(?P<{op}>\\b(?:{pat})\\b)" for op, pat in _COMPARATORS))

_AVG = re.compile(r"(\d+)\s*[- ]?\s*(day|d|week|wk|month|mo)?s?[- ]?(simple|exponential)?[- ]?"
                  r"(?:moving[- ])?(average|avg|sma|ema|dma|ma)\b")
_AVG_PREFIX = re.compile(r"\b(sma|ema|dma|ma)\s*\(?\s*(\d+)\s*\)?")
_BARE = re.compile(r"\b(\d+)-(day|week|month)\b(?!\s*(?:high|low|return|momentum|ago|s\b))")
_EXTREME = re.compile(r"(\d+)[- ](week|day|month)s?[- ](high|low)")
_AGO = re.compile(r"(?:its |the )?(?:close|price|level)?\s*(\d+)\s*(month|week|day|session)s?\s+"
                  r"(?:ago|earlier|before)")
_RSI = re.compile(r"\brsi\s*(?:\(\s*(\d+)\s*\)|(\d+)(?!\s*(?:%|\.)))?")
_CLOSE = re.compile(r"\b(close|closing price|price|it|the stock|the index|the etf|the market)\b")
_NUM = re.compile(r"(?<![\w.-])(\d+(?:\.\d+)?)(?![\w%-])")

_FILL_NEXT = re.compile(r"(?:(?:fill(?:ed)?|at)\s+(?:the\s+)?)?next\s+(?:session'?s?\s+|day'?s?\s+|"
                        r"trading day'?s?\s+|bar'?s?\s+|morning'?s?\s+)?open(?:ing)?")
_FILL_EARLY = re.compile(r"(today'?s|same[- ]day|this bar'?s|the same) (?:open|close)|"
                         r"\bat the close\b|\bon the close\b|\bsame bar\b")
_MOMENTUM = re.compile(r"(\d+)[- ](month|week|day)s? (?:return|momentum|performance|change) is "
                       r"(positive|negative|above zero|below zero)")
_NEW_EXTREME = re.compile(r"new (\d+)[- ](week|day|month)s? (high|low)")

_VERBS = {
    "entry": re.compile(r"\b(buy|enter|go long|get in|get long|long entry)\b"),
    "exit": re.compile(r"\b(sell|exit|get out|close (?:the )?(?:trade|position)|go to cash|step aside)\b"),
    "hold": re.compile(r"\b(hold|stay (?:long|in)|be (?:long|in)|own it|stay invested)\b"),
}


def parse(text: str) -> Spec:
    """Deterministic parse. Raises :class:`SpecError` if no condition can be found."""
    raw = text.strip()
    if not raw:
        raise SpecError("Describe your idea in one sentence, e.g. \"Buy when the close is above "
                        "the 50-day average; sell when it is below the 20-day average\".")
    t = _normalise(raw)
    spec = Spec(text=raw, origin="parser")
    assumed: set[str] = set()
    _global_modifiers(t, spec, assumed)
    entry: list[Condition] = []
    exit_: list[Condition] = []
    hold: list[Condition] = []
    pending = ""  # "When the 20-day crosses above the 50-day, buy": condition before the verb
    for clause in _clauses(t):
        role = _role(clause)
        if role is None:
            pending = clause if _CMP_RE.search(clause) else ""
            continue
        if pending and not _CMP_RE.search(clause):
            clause = f"{clause} {pending}"
        pending = ""
        conds = _conditions(_FILL_NEXT.sub(" ", clause), role, assumed, entry or hold)
        {"entry": entry, "exit": exit_, "hold": hold}[role].extend(conds)
    if hold:
        spec.mode, spec.entry, spec.exit = "hold_while", hold, []
    else:
        spec.mode, spec.entry, spec.exit = "entry_exit", entry, exit_
    if not spec.entry:
        raise SpecError("No entry condition found. Try: \"Buy when the close is above the 50-day "
                        "average; sell when it is below the 20-day average\".")
    spec.assumed = sorted(assumed)
    return spec


def rules(text: str, use_model: bool | None = None, section: str = "Strategy") -> Spec:
    """Plain English → validated :class:`Spec` (``backtest.rules``).

    ``use_model=None`` (default) asks a model only when the deterministic parser
    finds nothing and a model is reachable; ``True`` always tries the model first
    (falling back to the parser); ``False`` never calls a model.
    """
    if use_model:
        drafted = _model_draft(text, section)
        if drafted is not None:
            return drafted
    try:
        return parse(text).validate()
    except SpecError:
        if use_model is None and ai.ollama_ok():
            drafted = _model_draft(text, section)
            if drafted is not None:
                return drafted
        raise


# ------------------------------------------------------------------ pieces
def _normalise(text: str) -> str:
    t = text.lower().replace("’", "'").replace("–", "-").replace("—", "-")
    t = re.sub(r"\s*>=?\s*", " above ", t)
    t = re.sub(r"\s*<=?\s*", " below ", t)
    return re.sub(r"\s+", " ", t)


def _clauses(t: str) -> list[str]:
    parts = re.split(r";|\.(?!\d)|\bthen\b|,\s*(?=(?:and\s+)?(?:sell|exit|get out|buy|enter|hold|"
                     r"check|fill|size)\b)|\band\s+(?=(?:sell|exit|get out)\b)", t)
    return [p.strip(" ,") for p in parts if p and p.strip(" ,")]


def _role(clause: str) -> str | None:
    if re.match(r"^(check|fill|size|costs?|slippage|use|risk|target)\b", clause):
        return None
    hits = {role: m.start() for role, rx in _VERBS.items() if (m := rx.search(clause))}
    if not hits:
        return None
    return min(hits, key=hits.get)


def _conditions(clause: str, role: str, assumed: set[str], prior: list[Condition]
                ) -> list[Condition]:
    side = "exit" if role == "exit" else "entry"
    out: list[Condition] = []
    for m in _MOMENTUM.finditer(clause):
        n = int(m.group(1)) * _UNIT_DAYS[m.group(2)]
        op = "above" if m.group(3) in ("positive", "above zero") else "below"
        out.append(Condition(op, Operand("close"), Operand("close_ago", n)))
    for m in _NEW_EXTREME.finditer(clause):
        n = _extreme_len(int(m.group(1)), m.group(2))
        kind = "high_n" if m.group(3) == "high" else "low_n"
        out.append(Condition("above" if kind == "high_n" else "below", Operand("close"),
                             Operand(kind, n)))
    if out:
        return out
    parts = [p for p in re.split(r"\b(?:and|or)\b", clause) if _CMP_RE.search(p)]
    for part in parts or [clause]:
        c = _one_condition(part, side, assumed, prior)
        if c is not None:
            out.append(c)
    return out


def _one_condition(part: str, side: str, assumed: set[str], prior: list[Condition]
                   ) -> Condition | None:
    m = _CMP_RE.search(part)
    if not m:
        return None
    op = next(k for k, v in m.groupdict().items() if v)
    left_txt, right_txt = part[: m.start()], part[m.end():]
    lefts = _operands(left_txt, side, assumed)
    rights = _operands(right_txt, side, assumed)
    left = lefts[-1] if lefts else None
    right = rights[0] if rights else None
    if right is None and prior:  # "sell when it crosses below": same two lines as the entry
        base = prior[0]
        left, right = Operand(**vars(base.left)), Operand(**vars(base.right))
    if right is None:
        return None
    left = left or Operand("close")
    if left.kind == "close" and not re.search(r"\bclos", part):
        assumed.add(f"{side}.basis")  # "price" / "it" read as the daily close
    if left.kind == "value" and right.kind != "value":
        left, right = right, left
        op = {"above": "below", "below": "above", "cross_above": "cross_below",
              "cross_below": "cross_above"}[op]
    return Condition(op, left, right)


def _operands(txt: str, side: str, assumed: set[str]) -> list[Operand]:
    """Operands in reading order; overlapping matches keep the more specific one."""
    found: list[tuple[int, int, Operand]] = []

    def take(m: re.Match, op: Operand, flag: str | None = None) -> None:
        s, e = m.span()
        if all(e <= a or s >= b for a, b, _ in found):
            found.append((s, e, op))
            if flag:
                assumed.add(flag)

    for m in _EXTREME.finditer(txt):
        take(m, Operand("high_n" if m.group(3) == "high" else "low_n",
                        _extreme_len(int(m.group(1)), m.group(2))))
    for m in _AGO.finditer(txt):
        take(m, Operand("close_ago", int(m.group(1)) * _UNIT_DAYS[m.group(2)]))
    for m in _AVG.finditer(txt):
        n = int(m.group(1)) * _UNIT_DAYS.get(m.group(2) or "day", 1)
        take(m, *_average(n, m.group(3), m.group(4), side))
    for m in _AVG_PREFIX.finditer(txt):
        take(m, *_average(int(m.group(2)), None, m.group(1), side))
    for m in _BARE.finditer(txt):
        take(m, *_average(int(m.group(1)) * _UNIT_DAYS[m.group(2)], None, None, side))
    for m in _RSI.finditer(txt):
        n = m.group(1) or m.group(2)
        take(m, Operand("rsi", int(n or 14)), None if n else f"{side}.rsi_length")
    for m in _CLOSE.finditer(txt):
        take(m, Operand("close"))
    for m in _NUM.finditer(txt):
        take(m, Operand("value", value=float(m.group(1))))
    return [op for _, _, op in sorted(found, key=lambda x: x[0])]


def _average(n: int, flavour: str | None, word: str | None, side: str
             ) -> tuple[Operand, str | None]:
    """An average operand, plus the assumed-flag when the type was not stated."""
    if flavour == "exponential" or word == "ema":
        return Operand("ema", n), None
    if flavour == "simple" or word == "sma":
        return Operand("sma", n), None
    return Operand("sma", n), f"{side}.average"


def _extreme_len(n: int, unit: str) -> int:
    if unit == "week" and n == 52:
        return 252
    return n * _UNIT_DAYS[unit]


def _pct(rx: str, t: str) -> float | None:
    m = re.search(rx, t)
    return float(next(g for g in m.groups() if g)) if m else None


def _global_modifiers(t: str, spec: Spec, assumed: set[str]) -> None:
    """FILL, check clock, SIZE and COST phrases, wherever they appear."""
    if not _FILL_NEXT.search(t):
        if _FILL_EARLY.search(t):
            spec.notes.append("FILL set to the next session's open: a signal formed on a bar's "
                              "close cannot trade on that same bar.")
        else:
            assumed.add("fill")
    if re.search(r"\bfridays?\b|\bweekly\b|once a week|every week|weekends?", t):
        spec.check = "weekly"
    elif re.search(r"\bmonthly\b|month[- ]end|once a month|every month", t):
        spec.check = "monthly"
    elif not re.search(r"\bdaily\b|every (?:day|session)|each (?:day|session)", t):
        assumed.add("check")
    _size(t, spec, assumed)
    _cost(t, spec, assumed)
    ts = re.search(r"(?:after|time stop(?: of)?|hold(?:ing)? (?:for|period of)|max(?:imum)? of)\s+"
                   r"(\d+)\s*(day|session|bar|week|month)s?", t)
    if ts:
        spec.time_stop = int(ts.group(1)) * _UNIT_DAYS[ts.group(2)]
    sl = _pct(r"stop(?:[- ]loss)?\s*(?:at|of)?\s*(\d+(?:\.\d+)?)\s*%|(\d+(?:\.\d+)?)\s*%\s*"
              r"(?:stop|below (?:the )?entry)", t)
    if sl is not None:
        spec.stop_loss_pct = sl


def _size(t: str, spec: Spec, assumed: set[str]) -> None:
    s = Size()
    vol = _pct(r"(\d+(?:\.\d+)?)\s*%\s*(?:annual |yearly |a year |per year )?(?:volatility|vol)\b|"
               r"(?:volatility|vol)(?: target)?(?: of)?\s*(\d+(?:\.\d+)?)\s*%", t)
    cap_amt = re.search(r"(₹|rs\.?\s?|inr\s?|\$|usd\s?)([\d,]+(?:\.\d+)?)\s*(lakhs?|crores?|k)?", t)
    if cap_amt:
        v = float(cap_amt.group(2).replace(",", ""))
        v *= {"lakh": 1e5, "lakhs": 1e5, "crore": 1e7, "crores": 1e7, "k": 1e3}.get(
            cap_amt.group(3) or "", 1)
        s.capital = v
        if cap_amt.group(1).strip() in ("$", "usd"):
            spec.market = "US"
        else:
            spec.market = "IN"
    if vol is not None:
        s.method, s.target_vol = "vol_target", vol / 100
        buf = _pct(r"(\d+(?:\.\d+)?)\s*%\s*buffer|buffer(?: of)?\s*(\d+(?:\.\d+)?)\s*%", t)
        if buf is None:
            assumed.add("size.buffer")
        else:
            s.buffer = buf / 100
        cap = _pct(r"cap(?:ped)?(?: at)?\s*(\d+(?:\.\d+)?)\s*%|(\d+(?:\.\d+)?)\s*%\s*cap", t)
        if re.search(r"with borrowing|borrowing allowed|use leverage|with leverage", t):
            s.borrowing = True
        if cap is not None:
            s.cap = cap / 100
        elif not re.search(r"no borrowing|no leverage|without borrowing", t):
            assumed.add("size.cap")
        lb = re.search(r"(?:volatility|vol)[^;]*?over (\d+) (?:days|sessions)", t)
        if lb:
            s.vol_lookback = int(lb.group(1))
        else:
            assumed.add("size.vol_lookback")
    elif not re.search(r"all (?:the )?(?:capital|cash|money)|all[- ]in|whole (?:capital|account)|"
                       r"full (?:capital|size)", t):
        assumed.add("size.method")
    spec.size = s


def _cost(t: str, spec: Spec, assumed: set[str]) -> None:
    c = Cost()
    for p in _costs.PROFILES:
        if p.lower() in t:
            c.profile = p
    if c.profile is None:
        if re.search(r"\bintraday\b", t):
            c.profile = "IN-equity-intraday"
        elif re.search(r"\bdelivery\b", t):
            c.profile = "IN-equity-delivery"
        else:
            assumed.add("cost.profile")
    slip = _pct(r"slippage(?: of)?\s*(\d+(?:\.\d+)?)\s*%|(\d+(?:\.\d+)?)\s*%\s*slippage", t)
    if slip is None:
        assumed.add("cost.slippage")
    else:
        c.slippage_pct = slip
    spec.cost = c


# ------------------------------------------------------------------ model path
SPEC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "mode": {"type": "string", "enum": ["entry_exit", "hold_while"]},
        "entry": {"type": "array", "items": {"$ref": "#/$defs/cond"}},
        "exit": {"type": "array", "items": {"$ref": "#/$defs/cond"}},
        "time_stop": {"type": ["integer", "null"]},
        "check": {"type": "string", "enum": ["daily", "weekly", "monthly"]},
        "size": {"type": "object", "properties": {
            "method": {"type": "string", "enum": ["all_capital", "vol_target"]},
            "target_vol": {"type": "number"}, "buffer": {"type": "number"},
            "cap": {"type": "number"}}},
        "assumed": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["mode", "entry"],
    "$defs": {"cond": {"type": "object", "properties": {
        "op": {"type": "string", "enum": ["above", "below", "cross_above", "cross_below"]},
        "left": {"$ref": "#/$defs/operand"}, "right": {"$ref": "#/$defs/operand"}},
        "required": ["op", "left", "right"]},
        "operand": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": ["close", "sma", "ema", "high_n", "low_n", "rsi",
                                                 "close_ago", "value"]},
            "n": {"type": ["integer", "null"]}, "value": {"type": ["number", "null"]}},
            "required": ["kind"]}},
}

_MODEL_TASK = (
    "Translate the trading idea below into a JSON rule spec that matches the schema. Do not "
    "compute any numbers, do not judge the idea, do not recommend any security. Use only "
    "lengths and thresholds stated in the idea. List every choice you had to make in "
    "\"assumed\". Fills are always at the next session's open.\n\n")


def _model_draft(text: str, section: str) -> Spec | None:
    """Ask a model to draft the spec; returns None if unreachable or invalid."""
    out = ai.complete(_MODEL_TASK + ai.fence_untrusted(text), section=section, schema=SPEC_SCHEMA)
    if not out.text:
        return None
    try:
        d = ai.extract_json(out.text)
        d["text"], d["origin"] = text, "model"
        d.pop("fill", None)
        spec = Spec.from_dict(d)
        spec.assumed = sorted(set(spec.assumed) | {"cost.profile", "cost.slippage"})
        spec.notes.append(f"Drafted by {out.model}; read it back before you test it.")
        return spec.validate()
    except (ValueError, TypeError, KeyError, SpecError):
        return None
