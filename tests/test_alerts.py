"""Alerts: proposals need Accept, SIMULATED messages, expiry, quiet hours, pending paper orders."""

from datetime import datetime

import polars as pl
import pytest

from plugai_trade import ai, alerts, config, keys, paper, plans
from plugai_trade.store import default as store


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    monkeypatch.setattr(ai, "complete", lambda *a, **k: ai.Explanation(text="", where="Fallback"))


def frame(closes, highs=None, day="2026-05-26"):
    highs = highs or closes
    return pl.DataFrame({"date": [day] * len(closes),
                         "time": [f"{day}T09:{15 + 5 * i:02d}" for i in range(len(closes))],
                         "open": closes, "high": highs, "low": [c - 5 for c in closes],
                         "close": closes, "volume": [1e5] * len(closes)})


def saved_plan():
    p = plans.new_plan("Seven-field plan", "IN", "NIFTY FUT", name="Kavita NIFTY")
    p.entry, p.stop, p.qty, p.side = 24850, 24700, 65, "long"
    p.fields.update({"Exit logic": "Trail under the 20-day average", "Events": "Tuesday expiry"})
    p.trigger_expiry = "2026-05-27"
    return plans.save(p)


def test_from_plan_proposes_but_nothing_active_until_accept():
    props = alerts.from_plan(saved_plan())
    kinds = [a.kind for a in props]
    assert kinds == ["price", "price", "indicator", "event", "loss_limit"]
    assert all(a.status == "proposed" for a in props)
    for a in props:
        alerts.save(a)
    assert alerts.evaluate(frame([24800, 24900], [24800, 24900]), symbol="NIFTY FUT") == []
    entry = props[0]
    alerts.accept(entry)
    fired = alerts.evaluate(frame([24800, 24860], [24810, 24870]), symbol="NIFTY FUT")
    assert len(fired) == 1
    msg = fired[0].message
    assert msg.startswith("SIMULATED") and "Kavita NIFTY" in msg and "traded above 24,850.00" in msg
    assert "buy" not in msg.lower().replace("paper order", "")
    assert store().all("alert_log", tag="fired")
    # one-shot: does not fire again
    assert alerts.evaluate(frame([24800, 24860], [24810, 24870]), symbol="NIFTY FUT") == []


def test_evaluate_reads_only_the_last_completed_bar():
    a = alerts.accept(alerts.Alert("x", "SPY", "US", "price", "close above", 101, bar_size="1-min close"))
    early = frame([100, 102, 99])        # crossed above earlier, but the last bar is below
    assert alerts.evaluate(early, symbol="SPY") == []
    assert alerts.load_all("active")[0].id == a.id


def test_indicator_alert_close_below_sma():
    closes = [100.0] * 25 + [90.0]
    alerts.accept(alerts.Alert("exit", "SPY", "US", "indicator", "close below", indicator="sma_20",
                               bar_size="daily close"))
    fired = alerts.evaluate(frame(closes), symbol="SPY")
    assert fired and "closed below" in fired[0].what


def test_expiry_is_logged_not_deleted():
    a = alerts.accept(alerts.Alert("trigger", "SPY", "US", "price", "touch above", 500,
                                   expires="2026-05-25"))
    assert alerts.evaluate(frame([100, 101]), symbol="SPY") == []
    assert alerts.load_all("expired")[0].id == a.id
    assert store().all("alert_log", tag="expired")


def test_quiet_hours_hold_unless_breakthrough():
    config.set_value("alerts.quiet_hours", "23:00-06:00")
    assert alerts.in_quiet_hours(datetime(2026, 5, 26, 2, 0))
    assert not alerts.in_quiet_hours(datetime(2026, 5, 26, 12, 0))
    alerts.accept(alerts.Alert("band", "BTC-PERP", "IN", "price_band", "outside band", 90, level2=110,
                               bar_size="4-hour close"))
    alerts.accept(alerts.Alert("liq", "BTC-PERP", "IN", "liquidation", "within half distance",
                               100, level2=80.5, breakthrough=True))
    fired = alerts.evaluate({"BTC-PERP": frame([100, 85])}, at=datetime(2026, 5, 26, 2, 0))
    held = {f.alert.name: f.held for f in fired}
    assert held == {"band": True, "liq": False}
    assert store().all("alert_log", tag="held")


def test_from_crypto_monitor_and_funding_alert():
    props = alerts.from_crypto_monitor({"symbol": "BTC-PERP", "entry": 60000, "leverage": 10})
    assert [a.kind for a in props] == ["funding", "liquidation", "price_band"]
    assert props[1].level2 == 54300.0                         # 9.5% below at 10× with 0.5% maint.
    alerts.accept(props[0])
    fired = alerts.evaluate({"BTC-PERP": frame([60000, 60100])}, context={"funding": {"BTC-PERP": 0.0007}})
    assert fired and "+0.0700% per 8 h" in fired[0].what


def test_attach_paper_order_creates_pending_never_a_fill():
    entry = alerts.from_plan(saved_plan())[0]
    entry.attach_paper_order = True
    alerts.accept(entry)
    fired = alerts.evaluate(frame([24800, 24860], [24810, 24870]), symbol="NIFTY FUT")
    pid = fired[0].pending_order_id
    assert pid and [r["id"] for r in paper.pending()] == [pid]
    assert "waiting on the Paper Desk for your Accept" in fired[0].message
    assert store().count("paper_positions") == 0


def test_send_test_and_telegram_channel(monkeypatch):
    sent = {}
    monkeypatch.setattr(keys, "get_key", lambda name: "123:ABC" if name == "telegram_bot_token" else None)
    config.set_value("alerts.telegram_chat_id", "42")

    class R:
        status_code = 200

    def fake_post(url, json, timeout):
        sent.update(url=url, **json)
        return R()

    monkeypatch.setattr(alerts.httpx, "post", fake_post)
    a = alerts.save(alerts.Alert("Entry", "SPY", "US", plan_name="Marcus SPY",
                                 channels=["Desktop", "Telegram", "Email"]))
    msg, delivered = alerts.send_test(a)
    assert msg.startswith("SIMULATED") and "Marcus SPY" in msg
    assert delivered == ["Desktop", "Telegram"]               # Email not set up → logged failure
    assert sent["chat_id"] == "42" and sent["text"].startswith("SIMULATED")
    assert store().all("alert_log", tag="delivery_failed")
    assert "123:ABC" not in str(store().all("alert_log"))    # the token is never logged


def test_message_passes_output_filter():
    a = alerts.Alert("x", "SPY", "US")
    m = alerts.message(a, "you should buy now", "2026-05-26T09:30")
    assert m.startswith("SIMULATED") and "you should buy" not in m.lower()


def test_rows_from_other_screens_load_and_date_alert_fires():
    store().add("alerts", {"label": "SIMULATED", "kind": "roll", "text": "Roll window opens",
                           "date": "2026-05-26", "symbol": "NIFTY"}, tag="roll")
    a = alerts.load_all()[0]
    assert a.status == "active" and a.when == "2026-05-26" and a.name == "Roll window opens"
    assert alerts.evaluate({"NIFTY": frame([1, 2], day="2026-05-25")}) == []
    fired = alerts.evaluate({"NIFTY": frame([1, 2], day="2026-05-26")})
    assert fired and fired[0].message.startswith("SIMULATED")


def test_crypto_monitor_proposals_stay_proposed():
    for a in alerts.from_crypto_monitor({"symbol": "BTC-PERP", "entry": 60000, "leverage": 5}):
        alerts.save(a)
    assert len(alerts.load_all("proposed")) == 3 and not alerts.load_all("active")
