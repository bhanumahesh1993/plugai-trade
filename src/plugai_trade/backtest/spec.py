"""The rule spec: what a strategy *is*, as data (Chapter 11's four rule cards).

A :class:`Spec` is plain, JSON-serialisable data: ENTRY and EXIT conditions, the
FILL (always the next session's open), the check clock, SIZE and COST. Every
field the trader's words did not state is listed in ``assumed`` so the Strategy
Builder can paint it amber. Agents and plugins produce specs as dicts;
``Spec.from_dict`` + ``validate`` turn them into something the engine accepts.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .. import costs as _costs

OPERAND_KINDS = ("close", "sma", "ema", "high_n", "low_n", "rsi", "close_ago", "value")
OPS = ("above", "below", "cross_above", "cross_below")
MODES = ("entry_exit", "hold_while", "rotation")
CHECKS = ("daily", "weekly", "monthly")
SIZE_METHODS = ("all_capital", "vol_target", "equal_weight")
FILL_NEXT_OPEN = "next_open"
DAYS_PER_MONTH = 21

DEFAULT_CAPITAL = {"IN": 500_000.0, "US": 10_000.0}
DEFAULT_SLEEVE = {"IN": 800_000.0, "US": 60_000.0}
DEFAULT_SLIPPAGE_PCT = {"IN": 0.05, "US": 0.02}  # per side, an assumption the trader can change


class SpecError(ValueError):
    """A rule spec that the engine refuses to run, with a plain-English reason."""


@dataclass
class Operand:
    """One side of a comparison: the close, an average, a level, or a number."""

    kind: str = "close"
    n: int | None = None
    value: float | None = None

    def label(self, short: bool = False) -> str:
        """Plain-English name, e.g. ``50-day simple average``."""
        k, n = self.kind, self.n
        if k == "close":
            return "the close"
        if k == "value":
            return _num(self.value)
        if k == "sma":
            return f"{n}-day avg" if short else f"the {n}-day simple average"
        if k == "ema":
            return f"{n}-day EMA" if short else f"the {n}-day exponential average"
        if k == "high_n":
            return "the 52-week high" if n == 252 else f"the {n}-day high"
        if k == "low_n":
            return "the 52-week low" if n == 252 else f"the {n}-day low"
        if k == "rsi":
            return f"RSI({n})"
        if k == "close_ago":
            if n and n % DAYS_PER_MONTH == 0:
                return f"the close {n // DAYS_PER_MONTH} months earlier"
            return f"the close {n} sessions earlier"
        return k

    def warmup(self) -> int:
        return int(self.n or 0) + 1


@dataclass
class Condition:
    """``left op right``, measured on the last completed bar."""

    op: str = "above"
    left: Operand = field(default_factory=Operand)
    right: Operand = field(default_factory=lambda: Operand("sma", 50))

    def english(self, short: bool = False) -> str:
        l, r = self.left.label(short), self.right.label(short)
        return {
            "above": f"{l} is above {r}",
            "below": f"{l} is below {r}",
            "cross_above": f"{l} first moves above {r}",
            "cross_below": f"{l} first moves below {r}",
        }[self.op]

    def when(self) -> str:
        """A clause for read-back: "on the first close above …" or "when … is above …"."""
        if self.op.startswith("cross") and self.left.kind == "close":
            side = "above" if self.op == "cross_above" else "below"
            return f"on the first close {side} {self.right.label()}"
        return f"when {self.english()}"

    def operands(self) -> list[Operand]:
        return [self.left, self.right]


@dataclass
class Size:
    """SIZE card. ``all_capital`` = whole units with all cash; ``vol_target`` = Chapter 18."""

    method: str = "all_capital"
    capital: float | None = None      # None → market default (₹5,00,000 / $10,000)
    target_vol: float = 0.12          # annual, as a fraction
    buffer: float = 0.10              # ignore changes smaller than this share of the sleeve
    cap: float = 1.0                  # max exposure as a share of the sleeve
    borrowing: bool = False
    vol_lookback: int = 20            # sessions used to measure the daily move


@dataclass
class Cost:
    """COST card: the charges profile (from the dated tables) and assumed slippage."""

    profile: str | None = None        # None → whatever run(costs=...) says
    slippage_pct: float | None = None  # per side, percent; None → market default


@dataclass
class Spec:
    """A complete, testable rule. JSON-serialisable via ``to_dict``/``from_dict``."""

    text: str = ""
    mode: str = "entry_exit"
    entry: list[Condition] = field(default_factory=list)
    exit: list[Condition] = field(default_factory=list)
    time_stop: int | None = None      # sessions after entry
    stop_loss_pct: float | None = None  # close this far below the entry fill → exit
    fill: str = FILL_NEXT_OPEN
    check: str = "daily"
    size: Size = field(default_factory=Size)
    cost: Cost = field(default_factory=Cost)
    universe: list[str] = field(default_factory=list)  # rotation only
    lookback_months: int = 6                            # rotation only
    top_n: int = 2                                      # rotation only
    assumed: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    origin: str = "parser"            # parser | model | agent | user
    family: str | None = None
    market: str | None = None

    # ------------------------------------------------------------ serialise
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | Spec) -> Spec:
        """Build a spec from a dict (agents, plugins, saved reports). Unknown keys are ignored."""
        if isinstance(d, Spec):
            return copy.deepcopy(d)
        if not isinstance(d, dict):
            raise SpecError("a rule spec must be a dict or a Spec")
        d = dict(d)

        def cond(c: dict[str, Any]) -> Condition:
            return Condition(op=c.get("op", "above"), left=_operand(c.get("left", {})),
                             right=_operand(c.get("right", {})))

        known = set(cls.__dataclass_fields__)
        base = {k: v for k, v in d.items() if k in known}
        base["entry"] = [cond(c) for c in d.get("entry") or []]
        base["exit"] = [cond(c) for c in d.get("exit") or []]
        base["size"] = Size(**{k: v for k, v in (d.get("size") or {}).items()
                                if k in Size.__dataclass_fields__})
        base["cost"] = Cost(**{k: v for k, v in (d.get("cost") or {}).items()
                               if k in Cost.__dataclass_fields__})
        return cls(**base)

    # ------------------------------------------------------------ identity
    def digest(self) -> str:
        """Hash of everything that changes a result (not the wording or notes)."""
        d = self.to_dict()
        for k in ("text", "assumed", "notes", "origin", "family"):
            d.pop(k, None)
        return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:16]

    def family_key(self) -> str:
        """The *idea* a trial belongs to: indicator types, not their lengths or comparators."""
        if self.family:
            return self.family
        if self.mode == "rotation":
            return "rotation"
        parts = []
        for side, conds in (("entry", self.entry), ("exit", self.exit)):
            kinds = sorted({f"{c.left.kind}/{c.right.kind}" for c in conds})
            parts.append(f"{side}:{'+'.join(kinds) or '-'}")
        if self.time_stop:
            parts.append("time")
        return f"{self.mode}|{'|'.join(parts)}"

    def market_of(self, profile: str | None = None) -> str:
        if self.market in ("IN", "US"):
            return self.market
        p = self.cost.profile or profile or "IN-equity-delivery"
        return "US" if p.startswith("US") else "IN"

    # ------------------------------------------------------------ parameters
    def params(self) -> dict[str, int]:
        """Tunable whole-number settings, as ``path → value`` (for neighbours and sweeps)."""
        out: dict[str, int] = {}
        if self.mode == "rotation":
            return {"lookback_months": self.lookback_months, "top_n": self.top_n}
        seen: dict[tuple[str, int], str] = {}
        for side, conds in (("entry", self.entry), ("exit", self.exit)):
            for i, c in enumerate(conds):
                for name, op in (("left", c.left), ("right", c.right)):
                    if op.n and op.kind in ("sma", "ema", "high_n", "low_n", "close_ago", "rsi"):
                        key = (op.kind, int(op.n))
                        if key in seen:  # the same average on both cards moves together
                            continue
                        path = f"{side}.{i}.{name}.n"
                        seen[key] = path
                        out[path] = int(op.n)
        if self.time_stop:
            out["time_stop"] = int(self.time_stop)
        return out

    def with_params(self, values: dict[str, int]) -> Spec:
        """A copy with some parameters changed; linked operands (same kind and length) move together."""
        new = copy.deepcopy(self)
        for path, v in values.items():
            v = int(v)
            if path in ("time_stop", "lookback_months", "top_n"):
                setattr(new, path, v)
                continue
            side, i, name, _ = path.split(".")
            op = getattr(getattr(new, side)[int(i)], name)
            old = (op.kind, op.n)
            for conds in (new.entry, new.exit):
                for c in conds:
                    for o in c.operands():
                        if (o.kind, o.n) == old and o is not op:
                            o.n = v
            op.n = v
        return new

    def param_label(self, path: str) -> str:
        if path in ("time_stop", "lookback_months", "top_n"):
            return {"time_stop": "time stop (sessions)", "lookback_months": "lookback (months)",
                    "top_n": "top N"}[path]
        side, i, name, _ = path.split(".")
        cond = getattr(self, side)[int(i)]
        op = getattr(cond, name)
        if cond.left.kind in ("sma", "ema") and cond.right.kind in ("sma", "ema"):
            return f"{'fast' if name == 'left' else 'slow'} average (days)"
        if op.kind == "close_ago":
            return "momentum lookback (sessions)"
        return f"{side} {op.kind.replace('_n', '').upper()} length"

    def warmup(self) -> int:
        ops = [o for c in self.entry + self.exit for o in c.operands()]
        w = max([o.warmup() for o in ops] or [1])
        if self.size.method == "vol_target":
            w = max(w, self.size.vol_lookback + 1)
        if self.mode == "rotation":
            w = max(w, self.lookback_months * DAYS_PER_MONTH + 1)
        return w

    # ------------------------------------------------------------ validate
    def validate(self) -> Spec:
        """Raise :class:`SpecError` for anything the engine must refuse. Returns self."""
        if self.mode not in MODES:
            raise SpecError(f"unknown mode {self.mode!r}")
        if self.fill != FILL_NEXT_OPEN:
            raise SpecError("FILL cannot be earlier than the next session's open: a signal is "
                            "known only after the bar that forms it has closed.")
        if self.check not in CHECKS:
            raise SpecError(f"check must be one of {', '.join(CHECKS)}")
        if self.mode == "rotation":
            if len(self.universe) < 2:
                raise SpecError("a rotation needs a universe of at least two instruments")
            if not 1 <= self.top_n < len(self.universe):
                raise SpecError("top N must be at least 1 and smaller than the universe")
            if not 1 <= self.lookback_months <= 36:
                raise SpecError("lookback must be 1–36 months")
        else:
            if not self.entry:
                raise SpecError("ENTRY is empty: the rule never says when to hold")
            if self.mode == "entry_exit" and not (self.exit or self.time_stop or self.stop_loss_pct):
                raise SpecError("EXIT is empty: add an exit condition, a time stop or a stop")
        for c in self.entry + self.exit:
            if c.op not in OPS:
                raise SpecError(f"unknown comparison {c.op!r}")
            for o in c.operands():
                if o.kind not in OPERAND_KINDS:
                    raise SpecError(f"unknown measure {o.kind!r}")
                if o.kind == "value" and o.value is None:
                    raise SpecError("a number on a rule card is missing")
                if o.kind not in ("close", "value") and not (o.n and 1 <= int(o.n) <= 2000):
                    raise SpecError(f"{o.kind} needs a length between 1 and 2000 sessions")
        if self.time_stop is not None and not 1 <= self.time_stop <= 2000:
            raise SpecError("time stop must be 1–2000 sessions")
        if self.stop_loss_pct is not None and not 0 < self.stop_loss_pct < 100:
            raise SpecError("stop must be between 0% and 100% below the entry")
        s = self.size
        if s.method not in SIZE_METHODS:
            raise SpecError(f"unknown size method {s.method!r}")
        if s.capital is not None and s.capital <= 0:
            raise SpecError("capital must be positive")
        if not 0 < s.target_vol <= 1:
            raise SpecError("target volatility must be between 0% and 100% a year")
        if not 0 <= s.buffer < 1:
            raise SpecError("buffer must be between 0% and 100%")
        max_cap = 3.0 if s.borrowing else 1.0
        if not 0 < s.cap <= max_cap:
            raise SpecError("cap must be above 0% and at most 100% without borrowing")
        if not 2 <= s.vol_lookback <= 500:
            raise SpecError("volatility lookback must be 2–500 sessions")
        if self.cost.profile is not None and self.cost.profile not in _costs.PROFILES:
            raise SpecError(f"unknown cost profile {self.cost.profile!r}")
        if self.cost.slippage_pct is not None and not 0 <= self.cost.slippage_pct <= 2:
            raise SpecError("slippage must be 0–2% a side")
        return self

    # ------------------------------------------------------------ English
    def read_back(self) -> str:
        """The rule in plain English (check 1). Assumed choices are marked "(assumed)"."""
        a = set(self.assumed)
        fill = "at the next session's open"
        lines: list[str] = []
        if self.mode == "rotation":
            lines.append(
                f"On the last session of each month, ranks {len(self.universe)} instruments by "
                f"their {self.lookback_months}-month return and holds the top {self.top_n} in "
                f"equal weights; switches fill {fill}.")
        elif self.mode == "hold_while":
            cond = " and ".join(c.english() for c in self.entry)
            lines.append(f"Holds while {cond}; when that stops being true it sells {fill}.")
        else:
            entry = ", and ".join(c.when() for c in self.entry)
            lines.append(f"Buys {fill} {entry}.")
            exits = [c.when() for c in self.exit]
            if self.time_stop:
                exits.append(f"when {self.time_stop} sessions have passed since the entry")
            if self.stop_loss_pct:
                exits.append(f"when the close is {_num(self.stop_loss_pct)}% or more below "
                             "the entry fill")
            lines.append(f"Sells {fill} " + ", or ".join(exits) + ".")
        clock = {"daily": "after every session's close",
                 "weekly": "once a week, after Friday's close",
                 "monthly": "once a month, after the last session's close"}[self.check]
        lines.append(f"Signals are checked {clock}{_mark('check', a)}, using only completed bars.")
        lines.append(self._size_english(a))
        lines.append(self._cost_english(a))
        if any(x.startswith(("entry.average", "exit.average")) for x in a):
            lines.append("Averages are simple averages of closing prices (assumed).")
        if "entry.basis" in a or "exit.basis" in a:
            lines.append("\"Price\" is read as the daily close (assumed).")
        return " ".join(lines)

    def _size_english(self, a: set[str]) -> str:
        s, cap = self.size, self.size.capital
        cap_txt = "" if cap is None else f" of {_num(cap)}"
        if s.method == "vol_target":
            borrow = "no borrowing" if not s.borrowing else "borrowing allowed"
            return (f"Size: volatility target {_num(s.target_vol * 100)}% a year on the sleeve{cap_txt}"
                    f"{_mark('size.target_vol', a)}, measured over {s.vol_lookback} sessions"
                    f"{_mark('size.vol_lookback', a)}; changes smaller than {_num(s.buffer * 100)}% "
                    f"of the sleeve are skipped{_mark('size.buffer', a)}; capped at "
                    f"{_num(s.cap * 100)}% ({borrow}){_mark('size.cap', a)}; whole units.")
        if s.method == "equal_weight":
            return f"Size: the capital{cap_txt} split equally across holdings, whole units."
        return f"Size: all capital{cap_txt}, whole units{_mark('size.method', a)}."

    def _cost_english(self, a: set[str]) -> str:
        prof = f"{self.cost.profile} charges" if self.cost.profile else \
            "charges for the cost profile chosen at run time"
        slip = (f"the market default ({_num(DEFAULT_SLIPPAGE_PCT['IN'])}% India, "
                                                    f"{_num(DEFAULT_SLIPPAGE_PCT['US'])}% US)") if self.cost.slippage_pct is None \
            else f"{_num(self.cost.slippage_pct)}%"
        return (f"Costs: {prof}, from the dated tables{_mark('cost.profile', a)}, plus "
                f"slippage of {slip} a side{_mark('cost.slippage', a)}.")

    def facts(self) -> list[str]:
        """Facts for ``ai.explain``: the rule cards and every assumed field, nothing computed."""
        out = [f"{c['title']}: " + "; ".join(t for t, _ in c["lines"]) for c in self.cards()]
        out.append("Assumed (not stated in your words): " + (", ".join(self.assumed) or "none"))
        out += [f"Note: {n}" for n in self.notes]
        return out

    def cards(self) -> list[dict[str, Any]]:
        """The four rule cards for the Strategy Builder: ENTRY, EXIT, FILL, SIZE · COST."""
        a = set(self.assumed)
        if self.mode == "rotation":
            entry = [(f"Top {self.top_n} by {self.lookback_months}-month return", False),
                     (f"Universe: {', '.join(self.universe)}", False)]
            exit_ = [("Leaves the top N at a monthly check", False)]
        else:
            entry_flag = bool({"entry.average", "entry.basis"} & a)
            entry = [(c.english(short=True), entry_flag) for c in self.entry]
            if self.mode == "hold_while":
                exit_ = [("When the ENTRY condition stops being true", False)]
            else:
                exit_flag = bool({"exit.average", "exit.basis"} & a)
                exit_ = [(c.english(short=True), exit_flag) for c in self.exit]
                if self.time_stop:
                    exit_.append((f"Time stop: {self.time_stop} sessions", False))
                if self.stop_loss_pct:
                    exit_.append((f"Stop: close {_num(self.stop_loss_pct)}% below entry", False))
        clock = {"daily": "every session", "weekly": "Fridays", "monthly": "month-end"}[self.check]
        fill = [("Next session's open", "fill" in a), (f"Checked {clock}", "check" in a)]
        s = self.size
        if s.method == "vol_target":
            size = [(f"Volatility target {_num(s.target_vol * 100)}%/yr", "size.target_vol" in a),
                     (f"Buffer {_num(s.buffer * 100)}% · cap {_num(s.cap * 100)}%",
                      "size.buffer" in a or "size.cap" in a)]
        else:
            size = [("All capital, whole units" if s.method == "all_capital"
                     else "Equal weight, whole units", "size.method" in a)]
        slip = "default" if self.cost.slippage_pct is None else f"{_num(self.cost.slippage_pct)}%"
        size += [(self.cost.profile or "Run's cost profile", "cost.profile" in a),
                 (f"Slippage {slip} a side", "cost.slippage" in a)]
        return [{"title": "ENTRY", "lines": entry}, {"title": "EXIT", "lines": exit_},
                {"title": "FILL", "lines": fill}, {"title": "SIZE · COST", "lines": size}]


def _operand(d: dict[str, Any] | Operand) -> Operand:
    if isinstance(d, Operand):
        return d
    return Operand(kind=d.get("kind", "close"), n=d.get("n"), value=d.get("value"))


def _num(x: float | None) -> str:
    if x is None:
        return "?"
    x = float(x)
    if x.is_integer():
        return f"{int(x):,}"
    return f"{x:,.2f}".rstrip("0").rstrip(".")


def _mark(key: str, assumed: set[str]) -> str:
    return " (assumed)" if key in assumed else ""


def ma_crossover(fast: int = 50, slow: int = 200, check: str = "weekly",
                 target_vol: float = 0.12, buffer: float = 0.10, cap: float = 1.0,
                 sleeve: float | None = None, vol_target: bool = True) -> Spec:
    """Trend Lab preset: hold while the fast average is above the slow one (Chapter 18)."""
    cond = Condition("above", Operand("sma", fast), Operand("sma", slow))
    size = Size(method="vol_target" if vol_target else "all_capital", capital=sleeve,
                target_vol=target_vol, buffer=buffer, cap=cap)
    return Spec(text=f"MA crossover {fast}/{slow}", mode="hold_while", entry=[cond],
                check=check, size=size, family="trend:ma_crossover", origin="user")


def ts_momentum(months: int = 12, check: str = "weekly", target_vol: float = 0.12,
                buffer: float = 0.10, cap: float = 1.0, sleeve: float | None = None,
                vol_target: bool = True) -> Spec:
    """Trend Lab preset: hold while the close is above the close ``months`` ago."""
    cond = Condition("above", Operand("close"), Operand("close_ago", months * DAYS_PER_MONTH))
    size = Size(method="vol_target" if vol_target else "all_capital", capital=sleeve,
                target_vol=target_vol, buffer=buffer, cap=cap)
    return Spec(text=f"Time-series momentum {months} months", mode="hold_while", entry=[cond],
                check=check, size=size, family="trend:ts_momentum", origin="user")


def rotation(universe: list[str], lookback_months: int = 6, top_n: int = 2,
             capital: float | None = None, slippage_pct: float | None = None) -> Spec:
    """Trend Lab Rotation preset (Chapter 16): monthly, top N by lookback return."""
    return Spec(text=f"Rotation: top {top_n} of {len(universe)} by {lookback_months}-month return",
                mode="rotation", universe=list(universe), lookback_months=lookback_months,
                top_n=top_n, check="monthly", size=Size(method="equal_weight", capital=capital),
                cost=Cost(slippage_pct=slippage_pct), family="rotation", origin="user")
