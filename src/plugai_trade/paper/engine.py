"""The paper engine: simulated fills, positions, limits and the kill switch.

Nothing here can reach a broker. A ``PaperDesk`` is fed *completed* bars one at
a time (``on_bar``); a paper order placed after bar t is only ever filled on bar
t+1 or later, so no fill can use a price the trader could not have seen.

Fill model (Chapter 13):
- market: next bar's open ± (half spread + slippage), always against you;
- limit: only when the bar trades *through* the limit (a touch is not a fill);
  a gap through the limit fills at the open;
- stop-entry: when the bar reaches the trigger, at max(open, trigger) + costs
  (a gap beyond the trigger fills at the open);
- protective stops are watched on every bar; a gap beyond the stop fills at the open;
- volume cap: at most ``volume_cap`` × bar volume per bar; the rest waits.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .. import config
from ..store import default as store
from .instruments import Instrument, instrument, round_trip_costs

ENTRY_KINDS = ("market", "limit", "stop")


class PaperOrderBlocked(RuntimeError):
    """Raised by ``place_paper_order(..., strict=True)`` when a guardrail blocks it."""


@dataclass
class PaperOrder:
    id: int
    symbol: str
    market: str
    side: str                    # buy | sell
    qty: int                     # units (lots × lot size, or shares)
    kind: str = "market"         # market | limit | stop
    price: float | None = None   # limit price or stop-entry trigger
    stop: float | None = None    # protective stop for the position it opens
    target: float | None = None
    plan_id: int | None = None
    risk_money: float | None = None  # planned 1R for this trade (for R-multiples)
    placed_at: str = ""
    purpose: str = "open"        # open | close
    position_id: int | None = None
    status: str = "WORKING"      # WORKING | FILLED | CANCELLED | BLOCKED
    filled_qty: int = 0
    avg_fill: float = 0.0
    ref_price: float | None = None
    reason: str = ""
    source: str = "ticket"
    unplanned: bool = False
    fills: list[dict[str, Any]] = field(default_factory=list)

    @property
    def remaining(self) -> int:
        return self.qty - self.filled_qty


@dataclass
class PaperPosition:
    id: int
    symbol: str
    market: str
    side: str                    # long | short
    qty: int
    entry: float                 # average fill
    entry_ref: float             # signal / trigger / next-open price
    stop: float | None
    target: float | None
    opened_at: str
    plan_id: int | None
    risk_money: float | None
    unplanned: bool
    initial_stop: float | None = None
    last: float = 0.0
    funding: float = 0.0         # + paid, − received (perps)
    stop_moves: list[dict[str, Any]] = field(default_factory=list)
    rule_breaks: list[str] = field(default_factory=list)
    closing: bool = False

    @property
    def sign(self) -> int:
        return 1 if self.side == "long" else -1

    def open_pnl(self) -> float:
        return (self.last - self.entry) * self.qty * self.sign - self.funding


def _stamp(bar: dict[str, Any]) -> str:
    return str(bar.get("time") or bar.get("date"))[:16]


def _minutes(stamp: str) -> datetime | None:
    try:
        return datetime.fromisoformat(stamp) if "T" in stamp else None
    except ValueError:
        return None


class PaperDesk:
    """One paper account for one session stream (LIVE feed or Replay).

    ``mode`` is PAPER (live feed) or REPLAY; it becomes the journal tag.
    """

    def __init__(self, market: str = "IN", starting_balance: float = 1_500_000.0,
                 mode: str = "PAPER", volume_cap: float = 0.1,
                 instruments: dict[str, Instrument] | None = None,
                 write_journal: bool = True):
        self.market = market
        self.starting_balance = float(starting_balance)
        self.mode = mode
        self.volume_cap = volume_cap
        self.instruments: dict[str, Instrument] = dict(instruments or {})
        self.write_journal = write_journal
        self.orders: list[PaperOrder] = []
        self.positions: list[PaperPosition] = []
        self.trades: list[dict[str, Any]] = []
        self.blocked: list[dict[str, Any]] = []
        self.funding_log: list[dict[str, Any]] = []
        self.funding_rate: dict[str, float] = {}   # per print, e.g. 0.0001 = 0.01% per 8 h
        self.realised = 0.0
        self.session = ""
        self.now = ""
        self.last_bar: dict[str, dict[str, Any]] = {}
        self.killed = False
        self.limit_hit = False
        self.entries_today = 0
        self.day_realised = 0.0
        self.last_loss_exit: str | None = None
        self._ids = 0

    # ------------------------------------------------------------ helpers
    def _next_id(self) -> int:
        self._ids += 1
        return self._ids

    def inst(self, symbol: str) -> Instrument:
        if symbol not in self.instruments:
            self.instruments[symbol] = instrument(symbol, self.market)
        return self.instruments[symbol]

    def set_assumptions(self, symbol: str, half_spread: float, slippage: float) -> None:
        """The desk's slippage setting (same meaning as the backtester's)."""
        self.instruments[symbol] = self.inst(symbol).with_assumptions(half_spread, slippage)

    @property
    def cash(self) -> float:
        return self.starting_balance + self.realised - sum(p.funding for p in self.positions)

    def equity(self) -> float:
        return self.starting_balance + self.realised + sum(p.open_pnl() for p in self.positions)

    def day_pnl(self) -> float:
        """Realised today plus open P&L — what the daily loss limit watches."""
        return self.day_realised + sum(p.open_pnl() for p in self.positions)

    def open_orders(self) -> list[PaperOrder]:
        return [o for o in self.orders if o.status == "WORKING"]

    # ------------------------------------------------------------ guardrails
    def limits(self) -> dict[str, Any]:
        """Current guardrail settings (written by Rule Card › Sync limits)."""
        p = config.get("paper", {}) or {}
        by_mkt = p.get("daily_loss_limit_by_market") or {}
        one = p.get("one_r")
        return {
            "daily_loss_limit": float(by_mkt.get(self.market) or p.get("daily_loss_limit") or 0.0),
            "max_trades_per_day": int(p.get("max_trades_per_day") or 0),
            "cooldown_minutes": int(p.get("cooldown_minutes") or 0),
            "trading_window": (p.get("trading_window") or {}).get(self.market, ""),
            "event_lockout_minutes": int(p.get("event_lockout_minutes") or 0),
            "events": list(p.get("events") or []),
            "one_r": float(one.get(self.market) or 0.0) if isinstance(one, dict) else float(one or 0.0),
        }

    def guardrail_check(self) -> tuple[bool, str]:
        """The five gates plus the kill switch. Returns (ok, reason-if-blocked)."""
        lim = self.limits()
        if self.killed:
            return False, "kill switch · blocked for the rest of the session"
        now = _minutes(self.now)
        win = lim["trading_window"]
        if win and now is not None:
            lo, hi = win.split("-")
            hm = now.strftime("%H:%M")
            if not (lo.strip() <= hm <= hi.strip()):
                return False, f"outside window {win}"
        if lim["max_trades_per_day"] and self.entries_today >= lim["max_trades_per_day"]:
            return False, f"max reached · {lim['max_trades_per_day']} a day"
        if lim["cooldown_minutes"] and self.last_loss_exit and now is not None:
            last = _minutes(self.last_loss_exit)
            if last is not None:
                left = lim["cooldown_minutes"] - (now - last).total_seconds() / 60
                if left > 0:
                    return False, f"cooldown · {math.ceil(left)} min left"
        if self.limit_hit or (lim["daily_loss_limit"] and self.day_pnl() <= -lim["daily_loss_limit"]):
            self.limit_hit = True
            return False, "daily limit hit"
        if lim["event_lockout_minutes"] and now is not None:
            for ev in lim["events"]:
                when = _minutes(str(ev.get("when", ""))[:16])
                if when and abs((now - when).total_seconds()) / 60 <= lim["event_lockout_minutes"]:
                    return False, f"event lockout · {ev.get('name', 'event')}"
        return True, ""

    def guardrail_strip(self) -> dict[str, Any]:
        """Trades left, cooldown timer, day result in R, next lockout (Chapter 21)."""
        lim = self.limits()
        now = _minutes(self.now)
        cooldown = 0
        if lim["cooldown_minutes"] and self.last_loss_exit and now is not None:
            last = _minutes(self.last_loss_exit)
            if last is not None:
                cooldown = max(0, math.ceil(lim["cooldown_minutes"] - (now - last).total_seconds() / 60))
        nxt = None
        if now is not None:
            upcoming = sorted((str(e.get("when", ""))[:16], e.get("name", "event"))
                              for e in lim["events"] if _minutes(str(e.get("when", ""))[:16])
                              and _minutes(str(e.get("when", ""))[:16]) >= now - timedelta(
                                  minutes=lim["event_lockout_minutes"]))
            nxt = f"{upcoming[0][1]} at {upcoming[0][0][11:16]}" if upcoming else None
        one_r = lim["one_r"]
        return {
            "trades_left": (max(0, lim["max_trades_per_day"] - self.entries_today)
                            if lim["max_trades_per_day"] else None),
            "cooldown_min": cooldown,
            "day_r": round(self.day_pnl() / one_r, 2) if one_r else None,
            "day_pnl": round(self.day_pnl(), 2),
            "daily_loss_limit": lim["daily_loss_limit"],
            "next_lockout": nxt,
            "blocked": not self.guardrail_check()[0],
        }

    # ------------------------------------------------------------ paper orders
    def place_paper_order(self, symbol: str, side: str, qty: int, kind: str = "market",
                          price: float | None = None, stop: float | None = None,
                          target: float | None = None, plan_id: int | None = None,
                          risk_money: float | None = None, source: str = "ticket",
                          strict: bool = False) -> PaperOrder:
        """Queue a *paper* order. It passes the guardrails or is recorded as BLOCKED."""
        side = side.lower()
        if side not in ("buy", "sell") or kind not in ENTRY_KINDS or qty <= 0:
            raise ValueError("A paper order needs side buy/sell, kind market/limit/stop and qty > 0.")
        if kind in ("limit", "stop") and not price:
            raise ValueError(f"A {kind} paper order needs a price.")
        o = PaperOrder(self._next_id(), symbol, self.market, side, int(qty), kind, price, stop,
                       target, plan_id, risk_money, self.now, source=source,
                       unplanned=plan_id is None)
        ok, why = self.guardrail_check()
        self.orders.append(o)
        if not ok:
            o.status, o.reason = "BLOCKED", why
            rec = {"symbol": symbol, "side": side, "qty": qty, "kind": kind, "reason": why,
                   "at": self.now, "plan_id": plan_id, "source": source}
            self.blocked.append(rec)
            if self.write_journal:
                store().add("journal", {**rec, "kind": "blocked_paper_order",
                                        "mode": self.mode}, tag="BLOCKED")
            if strict:
                raise PaperOrderBlocked(why)
            return o
        self.entries_today += 1
        return o

    def cancel(self, order_id: int) -> None:
        for o in self.orders:
            if o.id == order_id and o.status == "WORKING":
                o.status = "CANCELLED"

    def close_at_next_bar(self, position_id: int, reason: str = "Close at next bar") -> None:
        """Queue a market close that fills at the next bar's open (plus costs)."""
        for p in self.positions:
            if p.id == position_id and not p.closing:
                p.closing = True
                self.orders.append(PaperOrder(
                    self._next_id(), p.symbol, p.market, "sell" if p.side == "long" else "buy",
                    p.qty, "market", placed_at=self.now, purpose="close", position_id=p.id,
                    reason=reason, plan_id=p.plan_id))

    def move_stop(self, position_id: int, new_stop: float, reason: str) -> None:
        """Change a paper stop. A reason is required; moving it away from entry is a rule break."""
        if not reason or not reason.strip():
            raise ValueError("Moving a stop needs a reason; it is recorded in the journal.")
        for p in self.positions:
            if p.id == position_id:
                away = (p.stop is not None and
                        ((p.side == "long" and new_stop < p.stop) or
                         (p.side == "short" and new_stop > p.stop)))
                p.stop_moves.append({"from": p.stop, "to": new_stop, "reason": reason.strip(),
                                     "at": self.now, "away_from_entry": away})
                if away and "stop moved away" not in p.rule_breaks:
                    p.rule_breaks.append("stop moved away")
                p.stop = new_stop
                return
        raise KeyError(f"No open paper position {position_id}")

    def kill_switch(self) -> dict[str, int]:
        """Cancel every working paper order, close every position at the next bar's open,
        and block new paper orders for the rest of the session. No override."""
        cancelled = 0
        for o in self.orders:
            if o.status == "WORKING" and o.purpose == "open":
                o.status, o.reason = "CANCELLED", "kill switch"
                cancelled += 1
        from .pending import cancel_all_pending
        cancelled += cancel_all_pending("kill switch")
        closing = 0
        for p in list(self.positions):
            if not p.closing:
                self.close_at_next_bar(p.id, "kill switch")
                closing += 1
        self.killed = True
        store().audit("kill_switch", {"mode": self.mode, "at": self.now, "cancelled": cancelled,
                                      "closing": closing})
        return {"cancelled": cancelled, "closing": closing}

    def post_funding(self, symbol: str, rate: float, price: float | None = None) -> float:
        """Post one funding print to every open perp in ``symbol``. Positive: longs pay."""
        total = 0.0
        for p in self.positions:
            if p.symbol != symbol:
                continue
            px = price if price is not None else p.last or p.entry
            pay = round(p.qty * px * rate * p.sign, 2)
            p.funding += pay
            total += pay
            self.funding_log.append({"symbol": symbol, "at": self.now, "rate": rate,
                                     "notional": round(p.qty * px, 2), "paid": pay})
        return total

    # ------------------------------------------------------------ the bar loop
    def on_bar(self, symbol: str, bar: dict[str, Any]) -> None:
        """Process one *completed* bar for ``symbol``. Fills use this bar only."""
        stamp = _stamp(bar)
        session = stamp[:10]
        if session != self.session:
            self._new_session(session)
        self.now = stamp
        inst = self.inst(symbol)
        for o in [o for o in self.orders if o.status == "WORKING" and o.symbol == symbol
                  and o.placed_at != stamp]:
            if o.purpose == "close":
                self._fill_close(o, inst, bar)
            else:
                self._try_entry(o, inst, bar)
        for p in [p for p in self.positions if p.symbol == symbol and not p.closing]:
            self._watch_exits(p, inst, bar)
        for p in self.positions:
            if p.symbol == symbol:
                p.last = float(bar["close"])
        if inst.kind == "perp" and "time" not in bar:
            rate = self.funding_rate.get(symbol, 0.0)
            for _ in range(inst.funding_per_day if rate else 0):
                self.post_funding(symbol, rate, float(bar["close"]))
        self.last_bar[symbol] = dict(bar)
        lim = self.limits()
        if lim["daily_loss_limit"] and self.day_pnl() <= -lim["daily_loss_limit"]:
            self.limit_hit = True

    def _new_session(self, session: str) -> None:
        self.session = session
        self.entries_today = 0
        self.day_realised = 0.0
        self.killed = False
        self.limit_hit = False
        self.last_loss_exit = None

    def _cap(self, o: PaperOrder, bar: dict[str, Any]) -> int:
        vol = float(bar.get("volume") or 0)
        if vol <= 0 or not self.volume_cap:
            return o.remaining
        return max(0, min(o.remaining, int(vol * self.volume_cap)))

    def _entry_price(self, o: PaperOrder, inst: Instrument, bar: dict[str, Any]) -> tuple[float, float] | None:
        """(fill, reference) for an entry on this bar, or None if it does not fill."""
        op, hi, lo = float(bar["open"]), float(bar["high"]), float(bar["low"])
        cost = inst.half_spread + inst.slippage
        buy = o.side == "buy"
        if o.kind == "market":
            return (op + cost if buy else op - cost), op
        if o.kind == "limit":
            lim = float(o.price)
            if buy and lo < lim:
                return min(op, lim), lim
            if not buy and hi > lim:
                return max(op, lim), lim
            return None
        trig = float(o.price)  # stop-entry
        if buy and hi >= trig:
            return max(op, trig) + cost, trig
        if not buy and lo <= trig:
            return min(op, trig) - cost, trig
        return None

    def _try_entry(self, o: PaperOrder, inst: Instrument, bar: dict[str, Any]) -> None:
        got = self._entry_price(o, inst, bar)
        if got is None:
            return
        n = self._cap(o, bar)
        if n <= 0:
            return
        px, ref = got
        self._record_fill(o, n, px, ref)
        if o.remaining == 0:
            o.status = "FILLED"
        pos = next((p for p in self.positions if p.id == o.position_id), None)
        if pos is None:
            pos = PaperPosition(self._next_id(), o.symbol, o.market,
                                "long" if o.side == "buy" else "short", n, px, ref, o.stop,
                                o.target, _stamp(bar), o.plan_id, o.risk_money, o.unplanned,
                                initial_stop=o.stop, last=float(bar["close"]))
            if o.unplanned:
                pos.rule_breaks.append("off-plan")
            self.positions.append(pos)
            o.position_id = pos.id
        else:
            total = pos.qty + n
            pos.entry = (pos.entry * pos.qty + px * n) / total
            pos.qty = total

    def _record_fill(self, o: PaperOrder, n: int, px: float, ref: float) -> None:
        o.fills.append({"at": self.now, "qty": n, "price": round(px, 4), "ref": ref})
        o.avg_fill = (o.avg_fill * o.filled_qty + px * n) / (o.filled_qty + n)
        o.filled_qty += n
        o.ref_price = ref if o.ref_price is None else o.ref_price

    def _fill_close(self, o: PaperOrder, inst: Instrument, bar: dict[str, Any]) -> None:
        pos = next((p for p in self.positions if p.id == o.position_id), None)
        if pos is None:
            o.status = "CANCELLED"
            return
        op = float(bar["open"])
        cost = inst.half_spread + inst.slippage
        px = op - cost if pos.side == "long" else op + cost
        n = min(self._cap(o, bar), pos.qty)
        if n <= 0:
            return
        self._record_fill(o, n, px, op)
        self._exit(pos, inst, n, px, op, o.reason or "Close at next bar")
        if o.remaining == 0 or pos.qty == 0:
            o.status = "FILLED"

    def _watch_exits(self, p: PaperPosition, inst: Instrument, bar: dict[str, Any]) -> None:
        op, hi, lo = float(bar["open"]), float(bar["high"]), float(bar["low"])
        slip = inst.half_spread + inst.slippage
        if p.stop is not None:
            s = float(p.stop)
            if p.side == "long" and lo <= s:
                px = (min(op, s)) - slip       # gap below the stop fills at the open
                self._exit(p, inst, p.qty, px, s, "stop")
                return
            if p.side == "short" and hi >= s:
                px = (max(op, s)) + slip
                self._exit(p, inst, p.qty, px, s, "stop")
                return
        if p.target is not None:
            t = float(p.target)
            if p.side == "long" and hi > t:              # trade-through, like a limit
                self._exit(p, inst, p.qty, max(op, t), t, "target")
            elif p.side == "short" and lo < t:
                self._exit(p, inst, p.qty, min(op, t), t, "target")

    def _exit(self, p: PaperPosition, inst: Instrument, n: int, px: float, ref: float,
              why: str) -> None:
        entry_v, exit_v = p.entry * n, px * n
        buy_v, sell_v = (entry_v, exit_v) if p.side == "long" else (exit_v, entry_v)
        charges = round_trip_costs(inst, buy_v, sell_v)
        gross = round((px - p.entry) * n * p.sign, 2)
        chart_move = round((ref - p.entry_ref) * n * p.sign, 2)
        funding = round(p.funding * n / p.qty, 2) if p.qty else 0.0
        net = round(gross - charges["total"] - funding, 2)
        risk = p.risk_money
        if not risk and p.initial_stop is not None:
            risk = abs(p.entry_ref - float(p.initial_stop)) * n
        trade = {
            "symbol": p.symbol, "market": p.market, "side": p.side, "qty": n,
            "entry_time": p.opened_at, "exit_time": self.now, "date": self.now[:10],
            "entry_ref": p.entry_ref, "entry": round(p.entry, 4), "exit_ref": ref,
            "exit": round(px, 4), "exit_reason": why, "chart_move": chart_move,
            "slippage": round(chart_move - gross, 2), "gross": gross, "costs": charges,
            "costs_total": charges["total"], "funding": funding, "net": net,
            "r": round(net / risk, 3) if risk else None,
            "cost_r": round((charges["total"] + chart_move - gross) / risk, 3) if risk else None,
            "plan_id": p.plan_id, "unplanned": p.unplanned, "stop_moves": p.stop_moves,
            "rule_breaks": list(p.rule_breaks), "mode": self.mode, "kind": "paper_trade",
        }
        self.trades.append(trade)
        self.realised += net
        self.day_realised += net
        if net < 0:
            self.last_loss_exit = self.now
        if self.write_journal:
            store().add("journal", trade, tag=self.mode)
        p.funding -= funding
        p.qty -= n
        if p.qty <= 0:
            self.positions.remove(p)

    # ------------------------------------------------------------ store mirror
    def snapshot(self) -> list[dict[str, Any]]:
        return [{**asdict(p), "open_pnl": round(p.open_pnl(), 2)} for p in self.positions]

    def sync_store(self) -> None:
        """Mirror open paper positions into the store (read by MCP get_paper_positions)."""
        st = store()
        for row in st.all("paper_positions", tag="open"):
            st.delete("paper_positions", row["id"])
        for p in self.snapshot():
            st.add("paper_positions", {**p, "mode": self.mode}, tag="open")
