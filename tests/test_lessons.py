"""All 34 lessons load, their exercises compute and their checks run, offline."""

import pytest
from streamlit.testing.v1 import AppTest

from plugai_trade import ai, config, lessons, privacy
from plugai_trade.app.registry import SCREENS
from plugai_trade.lessons import parse_number

SLUGS = {s[4] for s in SCREENS} | {"home"}
TOC_TITLES = {1: "What AI Actually Is — For a Trader", 22: "Options Buying — Know What You're "
              "Paying For", 34: "Your AI Trading System — Putting It All Together"}


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    monkeypatch.setattr(ai, "ollama_ok", lambda timeout=1.5: False)


def test_one_lesson_per_chapter():
    assert [x.n for x in lessons.all_lessons()] == list(range(1, 35))
    for n, title in TOC_TITLES.items():
        assert lessons.get(n).title == title
    with pytest.raises(KeyError):
        lessons.get(35)


@pytest.mark.parametrize("n", range(1, 35))
def test_lesson_loads_and_checks_run(n):
    les = lessons.get(n)
    assert les.goal and les.levels and 3 <= len(les.steps) <= 7 and les.checks
    assert all(s.slug in SLUGS for s in les.steps if s.slug)
    for market in ("IN", "US"):
        if les.exercise:
            ex = les.exercise(market)
            assert ex.facts()
        results = lessons.check(n, {}, market, save=False)
        assert len(results) == len(les.checks)
        for c in les.checks:
            if c.kind == "number":
                want = c.expected(market)
                ok = lessons.evaluate(c, str(want), market)
                assert ok.passed, (n, c.key, ok.detail)
                wrong = lessons.evaluate(c, str(want + 10 * c.tol + 1), market)
                assert not wrong.passed


BOOK_VALUES = {  # values printed in the book's Check my work boxes
    (3, "kaveri"): 12.9, (3, "northwind"): 7.3, (7, "pct"): 0.42, (8, "receivables"): 25.7,
    (8, "apple"): 2.0, (12, "lots"): 1, (17, "stop"): 597.32, (17, "size"): 145,
    (19, "implied"): 7.7, (19, "avg"): 5.9, (20, "ofs"): 60, (20, "pe"): 33.7,
    (20, "odds"): 9.96, (21, "toll"): 16.78, (22, "be"): 25_089, (22, "sigma"): 406,
    (23, "maxloss"): 9_028.50, (24, "mtm"): -14_300, (25, "day"): 154, (25, "annual"): 71.8,
    (26, "hl"): 6.1, (28, "net"): 11.5, (32, "turnover"): 39_585, (33, "compound"): 1_619,
}


@pytest.mark.parametrize("key,value", BOOK_VALUES.items())
def test_book_numbers_are_recomputed_in_code(key, value):
    n, k = key
    c = next(x for x in lessons.get(n).checks if x.key == k)
    assert lessons.evaluate(c, value, "IN").passed


def test_progress_badge_and_reset():
    assert lessons.badge(22) == "Not started"
    lessons.check(22, {"be": "25,089"}, "IN")
    assert lessons.progress(22)["be"] is True
    assert lessons.badge(22) == "In progress"
    lessons.check(22, {"be": "₹25,089", "sigma": "406", "lot": True}, "IN")
    assert lessons.badge(22) == "Done"
    assert lessons.reset(22) > 0
    assert lessons.badge(22) == "Not started"


def test_state_checks_follow_settings():
    c = next(x for x in lessons.get(2).checks if x.key == "local")
    assert lessons.evaluate(c, None, "IN").passed
    privacy.set_toggle("journal_local_only", False)
    config.set_value("ai.use_for.Journal", "Cloud allowed")
    assert not lessons.evaluate(c, None, "IN").passed


@pytest.mark.parametrize("text,value", [("₹9,028.50", 9028.5), ("12.9%", 12.9),
                                        ("−14,300", -14300), ("$0.42", 0.42), ("abc", None)])
def test_parse_number(text, value):
    assert parse_number(text) == value


def test_sample_loaders_degrade_gracefully():
    lines = lessons.load_sample(14, "IN")
    assert any("kavita" in x for x in lines)
    assert any("SYN-A" in x for x in lessons.load_sample(26, "US"))


def test_env_lesson(monkeypatch):
    monkeypatch.setenv("PLUGAI_TRADE_LESSON", "22")
    assert lessons.from_env() == 22
    monkeypatch.setenv("PLUGAI_TRADE_LESSON", "99")
    assert lessons.from_env() is None


def test_lessons_page_check_my_work(monkeypatch):
    monkeypatch.setenv("PLUGAI_TRADE_LESSON", "22")
    at = AppTest.from_string("from plugai_trade.app.pages import lessons as m\nm.render()\n",
                             default_timeout=60).run()
    assert not at.exception
    assert any("Chapter 22" in m.value for m in at.markdown)
    at.text_input(key="les_22_be").input("25,089")
    at.text_input(key="les_22_sigma").input("400")
    next(b for b in at.button if b.label == "Check my work").click()
    at.run()
    assert any("matches the lab" in s.value for s in at.success)
    assert any("the lab computes 406" in w.value for w in at.warning)
    next(b for b in at.button if b.label == "Reset lesson").click()
    at.run()
    assert not at.exception
    assert lessons.badge(22) == "Not started"
