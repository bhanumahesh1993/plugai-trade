"""Paper Trading › Alerts — rules checked in code on completed bars, labelled SIMULATED.

    from plugai_trade import alerts
    fired = alerts.evaluate(bars, symbol="NIFTY FUT")    # the Scheduler calls this

An alert is *proposed* until you click Accept; only *active* alerts are
evaluated. Every message starts with SIMULATED, names its plan, says what
happened (never what to do) and passes the AI output filter. An alert may
create a *pending* paper order (Attach paper order); never a filled one.
Expired alerts are logged, not deleted. Quiet hours hold all but the alerts
marked to break through.
"""

from __future__ import annotations

import smtplib
from dataclasses import asdict, dataclass, field
from datetime import datetime, time
from email.message import EmailMessage
from typing import Any

import httpx
import polars as pl

from . import ai, config, indicators, keys
from .store import default as store
from .store import now

CHANNELS = ("Desktop", "Email", "Telegram")
KINDS = ("price", "indicator", "event", "funding", "liquidation", "price_band", "loss_limit")
CONDITIONS = ("touch above", "touch below", "close above", "close below", "outside band",
              "abs above", "within half distance", "new item", "day loss below")
BAR_SIZES = ("tick", "1-min close", "15-min close", "daily close", "4-hour close",
             "completed funding print")
STAMP = "SIMULATED"
FOOTER = "Paper only — PlugAI-Trade places no real orders."


@dataclass
class Alert:
    name: str
    symbol: str
    market: str = "IN"
    kind: str = "price"
    condition: str = "touch above"
    level: float | None = None
    level2: float | None = None         # upper band / liquidation price
    indicator: str | None = None        # e.g. "sma_20" (compared with close)
    bar_size: str = "1-min close"
    plan_id: int | None = None
    plan_name: str = ""
    expires: str = ""                   # ISO date or datetime; empty = no expiry
    channels: list[str] = field(default_factory=lambda: ["Desktop"])
    attach_paper_order: bool = False
    order_draft: dict[str, Any] | None = None   # the paper order to create when ticked
    breakthrough: bool = False          # may sound during quiet hours
    ai_note: bool = False
    repeat: bool = False
    when: str = ""                      # date alerts (e.g. Futures & Roll › Set roll alert)
    text: str = ""
    status: str = "proposed"            # proposed | active | fired | expired | paused
    id: int | None = None

    def describe(self) -> str:
        lv = self.indicator or (f"{self.level:,.2f}" if self.level is not None else "")
        if self.condition == "outside band" and self.level2 is not None:
            lv = f"{self.level:,.2f}–{self.level2:,.2f}"
        return f"{self.symbol}: {self.bar_size} {self.condition} {lv}".strip()


# ---------------------------------------------------------------- storage
def save(alert: Alert) -> Alert:
    body = {k: v for k, v in asdict(alert).items() if k != "id"}
    if alert.id is None:
        alert.id = store().add("alerts", body, tag=alert.status)
    else:
        store().update("alerts", alert.id, body, tag=alert.status)
    return alert


STATUSES = ("proposed", "active", "fired", "expired", "paused")


def _from_row(r: dict[str, Any]) -> Alert:
    """Build an Alert from a stored row, including rows other screens wrote in a looser shape
    (e.g. Futures & Roll's roll reminders: label/text/date)."""
    keys_ = Alert.__dataclass_fields__
    body = {k: v for k, v in r.items() if k in keys_ and k != "id"}
    body.setdefault("name", r.get("text") or r.get("label") or f"Alert #{r['id']}")
    body.setdefault("symbol", r.get("symbol", ""))
    if "when" not in body and r.get("date"):
        body["when"] = str(r["date"])[:10]
        body.setdefault("kind", "date")
        body.setdefault("condition", "on date")
        body.setdefault("bar_size", "daily close")
    if "status" not in body:
        body["status"] = r.get("tag") if r.get("tag") in STATUSES else "active"
    a = Alert(**body)
    a.id = r["id"]
    return a


def load_all(status: str | None = None) -> list[Alert]:
    out = [_from_row(r) for r in store().all("alerts")]
    return [a for a in out if status is None or a.status == status]


def accept(alert: Alert) -> Alert:
    """Nothing is active until you click Accept."""
    alert.status = "active"
    return save(alert)


def log(alert: Alert | None, event: str, message: str = "", **extra: Any) -> int:
    return store().add("alert_log", {"alert_id": alert.id if alert else None,
                                     "name": alert.name if alert else "", "event": event,
                                     "message": message, "at": now(), **extra}, tag=event)


# ---------------------------------------------------------------- proposals
def from_plan(plan: Any, market: str | None = None) -> list[Alert]:
    """New alert → From plan: entry trigger, stop, exit condition, event and loss limit."""
    mk = market or plan.market
    long = plan.side == "long"
    base = dict(symbol=plan.symbol, market=mk, plan_id=plan.id, plan_name=plan.name,
                expires=plan.trigger_expiry or "")
    out: list[Alert] = []
    if plan.entry:
        order = {"symbol": plan.symbol, "market": mk, "side": "buy" if long else "sell",
                 "qty": plan.qty, "kind": "stop", "price": plan.entry, "stop": plan.stop,
                 "plan_id": plan.id, "risk_money": plan.risk_money} if plan.qty else None
        out.append(Alert(f"Entry trigger · {plan.name}", kind="price",
                         condition="touch above" if long else "touch below", level=plan.entry,
                         bar_size="tick", order_draft=order, **base))
    if plan.stop:
        out.append(Alert(f"Stop · {plan.name}", kind="price",
                         condition="touch below" if long else "touch above", level=plan.stop,
                         bar_size="tick", breakthrough=True, **{**base, "expires": ""}))
    exit_text = (plan.fields.get("Exit logic") or "").lower()
    if "20-day" in exit_text or "20 day" in exit_text:
        out.append(Alert(f"Exit condition · {plan.name}", kind="indicator",
                         condition="close below" if long else "close above", indicator="sma_20",
                         bar_size="daily close", **{**base, "expires": ""}))
    if (plan.fields.get("Events") or "").strip():
        out.append(Alert(f"Event · {plan.name}", kind="event", condition="new item",
                         bar_size="daily close", **{**base, "expires": ""}))
    out.append(Alert(f"Daily loss −1R · {plan.name}", kind="loss_limit", condition="day loss below",
                     level=-1.0, bar_size="1-min close", breakthrough=True, **{**base, "expires": ""}))
    return out


def from_crypto_monitor(position: dict[str, Any], funding_threshold: float = 0.0003,
                        band_pct: float = 0.10, maintenance: float = 0.005) -> list[Alert]:
    """New alert → From Crypto Monitor: funding, liquidation distance and price band (Ch 25)."""
    sym = position["symbol"]
    entry = float(position.get("entry") or position.get("price"))
    lev = float(position.get("leverage") or 1)
    long = position.get("side", "long") in ("long", "buy")
    dist = max(1 / lev - maintenance, 0.0)
    liq = entry * (1 - dist) if long else entry * (1 + dist)
    base = dict(symbol=sym, market=position.get("market", "IN"),
                plan_name=position.get("name", f"{sym} paper position"))
    return [
        Alert(f"Funding · {sym}", kind="funding", condition="abs above", level=funding_threshold,
              bar_size="completed funding print", breakthrough=True, **base),
        Alert(f"Liquidation distance · {sym}", kind="liquidation", condition="within half distance",
              level=entry, level2=round(liq, 2), bar_size="4-hour close", breakthrough=True, **base),
        Alert(f"Price band · {sym}", kind="price_band", condition="outside band",
              level=round(entry * (1 - band_pct), 2), level2=round(entry * (1 + band_pct), 2),
              bar_size="4-hour close", **base),
    ]


# ---------------------------------------------------------------- evaluation
@dataclass
class Firing:
    alert: Alert
    at: str
    price: float
    what: str
    message: str
    held: bool = False
    delivered: list[str] = field(default_factory=list)
    pending_order_id: int | None = None


def _bar_time(row: dict[str, Any]) -> str:
    return str(row.get("time") or row.get("date"))[:16]


def stamp_of(row: dict[str, Any]) -> str:
    """The bar's date, YYYY-MM-DD."""
    return _bar_time(row)[:10]


def in_quiet_hours(at: datetime | None = None, window: str | None = None) -> bool:
    """True inside the quiet-hours window (e.g. '23:00-06:00', may wrap midnight)."""
    window = window if window is not None else config.get("alerts.quiet_hours", "")
    if not window:
        return False
    at = at or datetime.now()
    lo, hi = (time.fromisoformat(x.strip()) for x in window.split("-"))
    t = at.time()
    return (lo <= t < hi) if lo < hi else (t >= lo or t < hi)


def _expired(a: Alert, stamp: str) -> bool:
    if not a.expires:
        return False
    exp = a.expires if len(a.expires) > 10 else a.expires + "T23:59"
    return stamp[:16] > exp[:16]


def _check(a: Alert, frame: pl.DataFrame, context: dict[str, Any]) -> tuple[bool, str, float]:
    """Is the alert's condition true on the last completed bar? (No bar after it is read.)"""
    last = frame.row(frame.height - 1, named=True)
    prev = frame.row(frame.height - 2, named=True) if frame.height > 1 else None
    c, hi, lo = float(last["close"]), float(last["high"]), float(last["low"])
    lv = a.level
    if a.kind in ("price", "indicator"):
        ref = lv
        if a.indicator:
            name = a.indicator
            n = int(name.split("_")[1]) if "_" in name else 20
            col = getattr(indicators, name.split("_")[0])(frame, n)[name]
            ref = float(col[-1]) if col[-1] is not None else None
        if ref is None:
            return False, "", c
        use_hilo = a.bar_size == "tick"
        if a.condition in ("touch above", "close above"):
            now_ok = (hi if use_hilo else c) >= ref
            was = prev is not None and (float(prev["high"] if use_hilo else prev["close"]) >= ref)
            return now_ok and not was, f"{'traded' if use_hilo else 'closed'} above {ref:,.2f}", c
        now_ok = (lo if use_hilo else c) <= ref
        was = prev is not None and (float(prev["low"] if use_hilo else prev["close"]) <= ref)
        return now_ok and not was, f"{'traded' if use_hilo else 'closed'} below {ref:,.2f}", c
    if a.kind == "price_band":
        ok = c < float(a.level) or c > float(a.level2)
        return ok, f"closed at {c:,.2f}, outside {a.level:,.2f}–{a.level2:,.2f}", c
    if a.kind == "liquidation":
        entry, liq = float(a.level), float(a.level2)
        half = entry - (entry - liq) / 2
        ok = c <= half if liq < entry else c >= half
        return ok, f"closed at {c:,.2f}, within half the distance to liquidation {liq:,.2f}", c
    if a.kind == "funding":
        rate = context.get("funding", {}).get(a.symbol)
        if rate is None:
            return False, "", c
        return abs(rate) > float(lv), f"funding print {rate:+.4%} per 8 h", c
    if a.kind == "loss_limit":
        day_r = context.get("day_r")
        if day_r is None:
            return False, "", c
        return day_r <= float(lv), f"day result {day_r:+.2f}R", c
    if a.kind in ("date", "roll"):
        return bool(a.when) and stamp_of(last) >= a.when[:10], a.text or f"date {a.when} reached", c
    if a.kind == "event":
        items = context.get("events", {}).get(a.symbol, [])
        return bool(items), "new item: " + "; ".join(items[:2]), c
    return False, "", c


def message(a: Alert, what: str, at: str, pending_id: int | None = None) -> str:
    """SIMULATED · plan · what happened. Never what to do."""
    plan = f"plan #{a.plan_id} {a.plan_name}" if a.plan_id else (a.plan_name or "no plan")
    text = f"{STAMP} · {a.name} · {plan}: {a.symbol} {what} ({a.bar_size}, bar {at})."
    if pending_id:
        text += f" Pending paper order #{pending_id} is waiting on the Paper Desk for your Accept."
    text, _ = ai.output_filter(text)
    return f"{text} {FOOTER}"


def _ai_note(a: Alert, what: str) -> str:
    out = ai.complete(f"FACTS: [1] {a.symbol} {what}. [2] Alert: {a.name}.\nTASK: One short "
                      "sentence of context using only the facts. No advice.",
                      section="Paper Trading")
    return out.text.strip()


def evaluate(bars: pl.DataFrame | dict[str, pl.DataFrame], symbol: str | None = None,
             context: dict[str, Any] | None = None, at: datetime | None = None,
             deliver_now: bool = True) -> list[Firing]:
    """Check every active alert against the last completed bar (the Scheduler calls this).

    ``bars``: one frame (then ``symbol`` names it) or ``{symbol: frame}``. ``context``
    may carry ``funding`` {symbol: rate}, ``day_r`` and ``events`` {symbol: [text]}.
    """
    frames = bars if isinstance(bars, dict) else {symbol or "": bars}
    context = context or {}
    fired: list[Firing] = []
    for a in load_all("active"):
        frame = frames.get(a.symbol)
        if frame is None and len(frames) == 1 and "" in frames:
            frame = frames[""]
        if frame is None or frame.height == 0:
            continue
        stamp = _bar_time(frame.row(frame.height - 1, named=True))
        if _expired(a, stamp):
            a.status = "expired"
            save(a)
            log(a, "expired", f"{a.name} expired at {a.expires}")
            continue
        ok, what, price = _check(a, frame, context)
        if not ok:
            continue
        pid = None
        if a.attach_paper_order and a.order_draft:
            from .paper import draft_pending
            pid = draft_pending(a.order_draft, source=f"Alert #{a.id}")
        msg = message(a, what, stamp, pid)
        if a.ai_note:
            note = _ai_note(a, what)
            if note:
                msg += f" Note: {note}"
        held = in_quiet_hours(at) and not a.breakthrough
        f = Firing(a, stamp, price, what, msg, held, pending_order_id=pid)
        if held:
            log(a, "held", msg, bar=stamp)
        elif deliver_now:
            f.delivered = deliver(msg, a.channels)
            log(a, "fired", msg, bar=stamp, delivered=f.delivered)
        if not a.repeat:
            a.status = "fired"
            save(a)
        fired.append(f)
    return fired


# ---------------------------------------------------------------- channels
def deliver(text: str, channels: list[str]) -> list[str]:
    """Send ``text`` to each channel; returns the channels that accepted it."""
    if not text.startswith(STAMP):
        text = f"{STAMP} · {text}"
    ok = []
    for ch in channels:
        try:
            if ch == "Desktop":
                store().add("notes", {"kind": "desktop_alert", "text": text}, tag="alert")
            elif ch == "Email":
                _email(text)
            elif ch == "Telegram":
                _telegram(text)
            else:
                continue
            ok.append(ch)
        except Exception as exc:  # delivery failures are logged, never raised
            log(None, "delivery_failed", f"{ch}: {str(exc)[:200]}")
    return ok


def _email(text: str) -> None:
    cfg = config.get("alerts.email", {}) or {}
    if not cfg.get("to") or not cfg.get("smtp_host"):
        raise RuntimeError("Email not set up: add an address and SMTP server on the Alerts screen")
    msg = EmailMessage()
    msg["Subject"] = "SIMULATED · PlugAI-Trade alert"
    msg["From"] = cfg.get("from") or cfg["to"]
    msg["To"] = cfg["to"]
    msg.set_content(text)
    with smtplib.SMTP(cfg["smtp_host"], int(cfg.get("smtp_port", 587)), timeout=10) as s:
        s.starttls()
        pw = keys.get_key("smtp_password")
        if pw:
            s.login(cfg.get("from") or cfg["to"], pw)
        s.send_message(msg)


def _telegram(text: str) -> None:
    token = keys.get_key("telegram_bot_token")
    chat = config.get("alerts.telegram_chat_id", "")
    if not token or not chat:
        raise RuntimeError("Telegram not set up: add the BotFather token (Keys) and your chat id")
    r = httpx.post(f"https://api.telegram.org/bot{token}/sendMessage",
                   json={"chat_id": chat, "text": text}, timeout=10)
    if r.status_code != 200:
        raise RuntimeError(f"Telegram returned HTTP {r.status_code}")


def send_test(alert: Alert) -> tuple[str, list[str]]:
    """Send test: a SIMULATED message naming the plan, through the alert's channels."""
    msg = message(alert, "test message (no condition was checked)", now()[:16])
    delivered = deliver(msg, alert.channels)
    log(alert, "test", msg, delivered=delivered)
    return msg, delivered


def alert_log(limit: int = 200) -> list[dict[str, Any]]:
    return store().all("alert_log", limit=limit)
