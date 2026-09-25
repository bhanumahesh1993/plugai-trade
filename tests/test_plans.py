"""Trade Plan templates, critique fallback, versions and hand-offs; Rule Card go/no-go."""

from datetime import date, timedelta

import pytest

from plugai_trade import ai, paper, plans, rulecard, sizing
from plugai_trade.store import default as store


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    monkeypatch.setattr(ai, "complete", lambda *a, **k: ai.Explanation(text="", where="Fallback"))


def test_templates_and_owner_chips():
    swing = dict(plans.TEMPLATES["Weekend swing plan"])
    assert list(swing) == ["Setup", "Trigger", "Stop", "Size", "Exit logic", "Events",
                           "Invalidation", "Alerts"]
    assert [k for k, v in swing.items() if v == plans.CODE] == ["Stop", "Size", "Alerts"]
    assert swing["Events"] == plans.CALENDAR
    seven = dict(plans.TEMPLATES["Seven-field plan"])
    assert len(seven) == 7 and seven["Size"] == plans.CODE
    with pytest.raises(ValueError):
        plans.new_plan("No such template")


def test_calendar_fills_nifty_weekly_expiry():
    ev = plans.calendar_events("NIFTY FUT", "IN", start=date(2026, 5, 22))  # a Friday
    assert ev and ev[0].startswith("NIFTY expiry Tue 26 May")
    assert plans.calendar_events("SPY", "US") == []


def test_versions_are_kept():
    p = plans.save(plans.new_plan("Seven-field plan", "IN", "NIFTY FUT"))
    p.fields["Setup"] = "Pullback to a rising 20-day average"
    plans.save(p)
    p.fields["Setup"] = "Pullback, Friday low 24,700"
    plans.save(p)
    again = plans.load(p.id)
    assert again.version == 3 and len(again.versions) == 2
    assert again.versions[-1]["fields"]["Setup"] == "Pullback to a rising 20-day average"


def test_critique_fallback_checklist_reads_only_plan_fields():
    p = plans.new_plan("Seven-field plan", "IN", "NIFTY FUT")
    p.fields.update({"Setup": "bounce off 20-day avg", "Entry": "Buy above 24,850 maybe",
                     "Stop": "somewhere under Friday low"})
    p.entry, p.stop = 24850, 24900
    c = plans.critique(p)
    assert c.where == "Fallback"
    assert "Exit logic" in c.missing and "Invalidation" in c.missing
    assert any("maybe" in v for v in c.vague) and any("somewhere" in v for v in c.vague)
    assert c.contradictions and "not below the entry" in c.contradictions[0]
    assert "Yes/no" in c.text
    assert all(f.split(":")[0] in p.owners() for f in c.facts())


def test_critique_uses_model_when_available(monkeypatch):
    monkeypatch.setattr(ai, "complete", lambda *a, **k: ai.Explanation(
        text="Missing: exit time.", model="m", where="Local"))
    c = plans.critique(plans.new_plan())
    assert c.text == "Missing: exit time." and c.where == "Local"


def test_size_it_use_in_plan_journal_and_paper_desk():
    p = plans.save(plans.new_plan("Weekend swing plan", "IN", "SYNTH-P"))
    with pytest.raises(ValueError):
        plans.send_to_paper_desk(p)                            # no size yet
    r = sizing.atr_stop(800_000, 0.005, 616.50, 12.79, 1.5, cost_per_lot=1.5, cap_pct=0.2,
                        stop_override=597.30)
    plans.use_size(p, r)
    assert p.qty == 193 and p.stop == 597.30 and "193 shares" in p.fields["Size"]
    assert p.fields["Stop"].startswith("597.30")
    jid = plans.save_to_journal(p)
    row = store().get("journal", jid)
    assert row["tag"] == "PLAN" and row["plan_id"] == p.id
    plans.send_to_paper_desk(p)
    t = paper.load_ticket()
    assert t["symbol"] == "SYNTH-P" and t["qty"] == 193 and t["kind"] == "stop" and t["plan_id"] == p.id


# ---------------------------------------------------------------- Rule Card
def test_rule_card_money_limits_ch12():
    card = rulecard.template_card()
    assert card.money_limits("IN") == {"one_r": 15_000, "daily": 30_000, "weekly": 60_000,
                                       "position_cap": 375_000}
    assert card.money_limits("US")["daily"] == 800 and card.money_limits("US")["weekly"] == 1600


def test_rule_card_versions_and_suggestions():
    card = rulecard.current()
    rulecard.suggest_rules(card, ["No new trade within 30 minutes of a losing trade", ""])
    assert card.rules[-1]["status"] == "suggested" and len(card.accepted_rules()) == len(card.rules) - 1
    rulecard.new_version(card, "first")
    card.daily_limit_r = 1.5
    rulecard.new_version(card, "tighter daily limit")
    assert rulecard.current().version == 2 and rulecard.current().daily_limit_r == 1.5
    assert len(rulecard.history()) == 2
    assert "Data timestamp is today's?" in rulecard.checklist_questions()


def _paper_period(weeks=6, per_week=6, breaks_last_week=0):
    start = date(2026, 3, 2)
    for w in range(weeks):
        for i in range(per_week):
            d = start + timedelta(weeks=w, days=i % 5)
            rb = ["late entry"] if (w == weeks - 1 and i < breaks_last_week) else []
            store().add("journal", {"kind": "paper_trade", "date": str(d), "r": 0.5, "cost_r": 0.03,
                                    "chart_move": 1000, "costs_total": 80, "slippage": 20,
                                    "rule_breaks": rb, "plan_id": 1, "unplanned": False},
                        tag="PAPER")


def test_go_no_go_pass_and_not_yet():
    _paper_period()
    store().audit("kill_switch", {"mode": "PAPER"})
    g = rulecard.go_no_go(account="Paper")
    assert g.verdict == "GO to pilot", g.facts()
    assert g.measures[0].value == "36 · 6 wks"
    store().add("journal", {"kind": "paper_trade", "date": "2026-04-10", "r": -1, "cost_r": 0.03,
                            "chart_move": 1000, "costs_total": 80, "slippage": 20,
                            "rule_breaks": ["late entry"], "unplanned": True}, tag="PAPER")
    g2 = rulecard.go_no_go(account="Paper")
    assert g2.verdict == "NOT YET"
    off = next(m for m in g2.measures if m.name == "Off-plan trades")
    assert not off.passed and off.value == "1" and off.rows
    assert "Profit is deliberately not a measure." in g2.facts()


def test_go_no_go_pilot_account_and_empty():
    g = rulecard.go_no_go(rows=[], account="Pilot")
    assert g.verdict == "NOT YET" and g.measures[0].name == "Pilot length"


def test_save_pilot_plan_and_audit():
    pid = rulecard.save_pilot_plan("IN", 32_850, 1, "2026-08-01", ["Budget used → stop"], "1 lot")
    assert store().get("pilot_plans", pid)["budget"] == 32_850
    with pytest.raises(ValueError):
        rulecard.save_pilot_plan("IN", 0, 1, "2026-08-01", [])
    a = rulecard.start_audit(date(2026, 9, 5))
    assert [i["item"] for i in a["items"]] == list(rulecard.AUDIT_ITEMS)
    assert rulecard.save_audit(a) > 0
