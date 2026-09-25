"""Daily Briefing: ✓/? flags set by code, cutoff filter, events, editions, Schedule."""

from datetime import date, datetime, time

import pytest

from plugai_trade import briefing, config
from plugai_trade.store import default as store

TUE = date(2026, 10, 13)  # a NIFTY weekly-expiry Tuesday in the reference table


@pytest.fixture(autouse=True)
def offline_ai():
    config.set_value("ai.ollama_host", "http://127.0.0.1:9")


def _at(hh, mm, d=TUE):
    return datetime.combine(d, time(hh, mm), tzinfo=briefing.TZ["IN"])


def test_filter_flags_and_cutoff():
    items = [
        briefing.NewsItem("US close lower", "Wire", _at(1, 30)),
        briefing.NewsItem("GIFT Nifty lower", "Forward", None),
        briefing.NewsItem("After the cutoff", "Wire", _at(9, 5)),
        briefing.NewsItem("Old story", "Wire", _at(10, 0, date(2026, 10, 9))),
        briefing.NewsItem("OTHERCO board meeting", "NSE", _at(7, 0), symbol="?"),
        briefing.NewsItem("SYN-IN-004 results date", "NSE", _at(7, 5), symbol="?"),
    ]
    keep, dropped = briefing.filter_news(items, "IN", TUE, "08:45", ["SYN-IN-004"])
    by = {ln.text: ln for ln in keep}
    assert by["US close lower"].sourced and by["US close lower"].flag == "✓"
    assert not by["GIFT Nifty lower"].sourced and by["GIFT Nifty lower"].reason == "no timestamp"
    assert "SYN-IN-004 results date" in by and "OTHERCO board meeting" not in by
    assert any("after the cutoff" in d for d in dropped)
    assert any("older than the previous close" in d for d in dropped)


def test_generate_briefing_offline():
    b = briefing.generate(["NIFTY", "SYN-IN-004"], "IN", "08:45", day=TUE, source="synthetic")
    assert b.cutoff == "08:45" and "cutoff 08:45 IST" in b.header()
    assert all(ln.sourced for ln in b.panel("Watchlist"))
    assert any("NIFTY weekly expiry" in ln.text for ln in b.panel("Events today"))
    assert any("expiry rule" in q for q in b.questions) and 1 <= len(b.questions) <= 4
    ok, unsourced = b.counts()
    assert unsourced == 1 and ok == len(b.lines) - 1
    assert not any(k in ("buy", "sell", "target") for k in vars(b))
    text = " ".join(b.facts()).lower()
    assert " buy " not in text and "target" not in text


def test_editions_on_refresh():
    first = briefing.generate(["NIFTY"], "IN", day=TUE, source="synthetic")
    second = briefing.generate(["NIFTY"], "IN", "09:15", day=TUE, source="synthetic")
    assert (first.edition, second.edition) == (1, 2)
    assert [e["edition"] for e in briefing.editions("IN", TUE)] == [2, 1]


def test_yesterday_strip_reads_the_journal():
    store().add(
        "notes",
        {"screen": "Trades", "text": "Entered at 09:17, before my 09:30 rule"},
        tag="journal",
    )
    b = briefing.generate(["NIFTY"], "IN", day=TUE, source="synthetic", save=False)
    assert b.yesterday.startswith("Entered at 09:17")


def test_unreachable_source_is_flagged_not_dropped(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("offline")

    monkeypatch.setattr(briefing.data, "get", boom)
    lines = briefing.watchlist_lines(["NIFTY"], "IN", TUE)
    assert not lines[0].sourced and lines[0].reason.startswith("source unreachable")


def test_rss_failure_falls_back_to_sample(monkeypatch):
    import httpx

    def fail(*a, **k):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(briefing.httpx, "get", fail)
    b = briefing.generate(["NIFTY"], "IN", day=TUE, online=True, source="synthetic", save=False)
    assert any("feeds unreachable" in s for s in b.sources)


def test_schedule_saves_a_job():
    briefing.schedule("IN", "07:30", "08:45", ["Dashboard", "Telegram"], "08:15")
    job = store().all("jobs", tag="briefing")[0]
    assert job["days"] == "NSE trading days" and job["news_cutoff"] == "08:45"
    assert job["delivery"] == ["Dashboard", "Telegram"] and job["model"] == "local"
