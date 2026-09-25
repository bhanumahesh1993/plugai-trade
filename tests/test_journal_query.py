"""Ask My Journal specs and SQL, and the Weekly Review built from them."""

import polars as pl
import pytest

from plugai_trade import ai, journal
from plugai_trade.journal import detectors, query, review


@pytest.fixture
def kavita():
    return journal.sample("kavita")


def test_soon_after_a_loss_reads_back_and_matches_detector(kavita):
    a = journal.ask("How did I do on trades I opened soon after a loss this month?", kavita,
                    use_model=False)
    assert "previous trade on the same day was a loss" in a.spec.label
    assert "gap_minutes <= 30" in a.sql and a.via == "pattern"
    rep = journal.detect(kavita)
    assert a.rows == rep.reentries.rows
    assert int(a.table["trades"][0]) == rep.reentries.n
    assert a.table["total_r"][0] == pytest.approx(rep.reentries.total_r, abs=0.01)
    assert "[q5]" in a.text and "too few to conclude" in a.text


def test_compare_held_over_an_hour_with_the_rest_and_follow_up():
    m = journal.sample("marcus")
    a = journal.ask("Compare my SPY and QQQ trades held more than an hour with the rest.", m,
                    use_model=False)
    assert a.spec.compare == ["hold_minutes", ">", 60.0]
    assert set(a.table["grp"].to_list()) == {"match", "rest"}
    assert int(a.table["trades"].sum()) == m.height
    b = journal.ask("Which of those broke a Rule Card line?", m, previous=a.spec,
                    use_model=False)
    assert b.via == "follow-up" and ["broke_rule", "is", True] in b.spec.filters
    assert set(b.rows) <= set(a.rows)


def test_group_by_time_of_day(kavita):
    a = journal.ask("Show my results by time of day", kavita, use_model=False)
    assert a.spec.group_by == "tod_bucket"
    assert int(a.table["trades"].sum()) == 54


def test_unknown_question_without_model_says_so(kavita, monkeypatch):
    monkeypatch.setattr(ai, "complete", lambda *a, **k: ai.Explanation(text=""))
    a = journal.ask("What is the meaning of life?", kavita)
    assert a.via == "none" and "could not" in a.text


def test_model_spec_is_whitelisted(kavita, monkeypatch):
    calls = {}

    def fake(prompt, section, schema=None, sensitive=False, **kw):
        calls.update(section=section, sensitive=sensitive)
        return ai.Explanation(text='{"filters": [["side", "=", "SHORT"]], "group_by": "weekday",'
                                   ' "compare": null, "label": "short trades by weekday"}')
    monkeypatch.setattr(ai, "complete", fake)
    a = journal.ask("Do I do better on calm or on volatile days?", kavita)
    assert a.via == "model" and a.spec.group_by == "weekday"
    assert calls == {"section": "Journal", "sensitive": True}
    monkeypatch.setattr(ai, "complete", lambda *a, **k: ai.Explanation(
        text='{"filters": [["1; DROP TABLE journal", "=", 1]], "label": "x"}'))
    assert journal.ask("hack me", kavita).via == "none"


def test_spec_validation_and_sql_quoting():
    with pytest.raises(query.QueryError):
        query.QuerySpec(filters=[["password", "=", "x"]]).validate()
    s = query.QuerySpec(filters=[["setup", "=", "O'Neil"]])
    assert "'O''Neil'" in s.to_sql()
    assert query.QuerySpec.from_json(s.to_json()).filters == s.filters


def test_weekly_review_tiles_last_week_and_queries(kavita):
    r = review.build(kavita, "2026-09-09")
    assert (r.start, r.end) == ("2026-09-07", "2026-09-13")
    labels = [t["label"] for t in r.tiles()]
    assert labels == ["TRADES", "RESULT", "CHARGES", "NET", "ADHERENCE", "BREAKS COST"]
    e = detectors.enrich(kavita)
    wk = e.filter(pl.col("date").is_between(pl.lit("2026-09-07"), pl.lit("2026-09-13")))
    assert r.this.n == wk.height and r.this.followed + r.this.broke == wk.height
    last = e.filter(pl.col("date").is_between(pl.lit("2026-08-31"), pl.lit("2026-09-06")))
    assert r.last.n == last.height
    assert "date >= '2026-09-07'" in r.queries["q1"]
    assert any(f.label.startswith("Re-entry") for f in r.patterns)


def test_generate_save_and_last_decision(kavita, monkeypatch, lab_home):
    seen = {}

    def fake_explain(obj, q=None, section="Research", sensitive=False):
        seen.update(section=section, sensitive=sensitive)
        return ai.Explanation(text="narration", sources=obj.facts())
    monkeypatch.setattr(ai, "explain", fake_explain)
    r = review.build(kavita)
    assert review.generate(r).text == "narration"
    assert seen == {"section": "Journal", "sensitive": True}
    review.save(r, "narration", "No trades before 09:30.")
    assert review.build(kavita).last_decision == "No trades before 09:30."


def test_pinned_question_runs_in_the_week(kavita, lab_home):
    a = journal.ask("How did I do on trades I opened soon after a loss?", kavita,
                    use_model=False)
    review.pin(a)
    r = review.build(kavita, "2026-09-09", pinned=review.pinned_specs())
    assert len(r.pinned) == 1
    assert all(i in a.rows for i in r.pinned[0].rows)


def test_replay_session_facts_and_handoff(kavita):
    day = kavita["date"][0]
    rep = journal.replay.session(kavita, day)
    assert rep.trades.height == kavita.filter(pl.col("date") == day).height
    h = rep.handoff()
    assert h["speed"] == 5 and h["tag"] == "REPLAY"
    assert len(h["fills"]) == 2 * rep.trades.height
    assert rep.facts()[0].startswith(f"Session {day}")
