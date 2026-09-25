"""News Pipeline (Chapter 28): clocks, fetch, scorers, compare, event study, snippets [20]/[21]."""

import json
import textwrap
from datetime import UTC, datetime
from pathlib import Path

import httpx
import polars as pl
import pytest

from plugai_trade import ai, news
from plugai_trade.news import clock, scoring
from plugai_trade.store import default as store


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    """Keep tests deterministic even if Ollama happens to run on this machine."""
    monkeypatch.setattr(ai, "ollama_ok", lambda *a, **k: False)


def _snippet(i: int) -> str:
    snips = json.loads((Path(__file__).parent / "book_snippets.json").read_text())
    return textwrap.dedent(snips[i]["code"])


# ---------------------------------------------------------------- clocks
def test_after_close_filing_is_tradable_next_open():
    seen = datetime(2026, 5, 12, 10, 30, tzinfo=UTC)  # 16:00 IST, after 15:30
    assert clock.local_str(clock.tradable_from(seen, "IN"), "IN") == "2026-05-13 09:15 IST"
    seen_us = datetime(2026, 5, 12, 20, 35, tzinfo=UTC)  # 16:35 ET (UTC-4 in May)
    assert clock.local_str(clock.tradable_from(seen_us, "US"), "US") == "2026-05-13 09:30 ET"


def test_pre_open_weekend_and_in_session():
    pre = datetime(2026, 5, 12, 2, 0, tzinfo=UTC)  # 07:30 IST Tue
    assert clock.local_str(clock.tradable_from(pre, "IN"), "IN") == "2026-05-12 09:15 IST"
    fri = datetime(2026, 5, 15, 21, 0, tzinfo=UTC)  # Fri 17:00 ET
    assert clock.local_str(clock.tradable_from(fri, "US"), "US") == "2026-05-18 09:30 ET"
    mid = datetime(2026, 5, 12, 6, 0, 30, tzinfo=UTC)  # 11:30:30 IST
    assert clock.local_str(clock.tradable_from(mid, "IN"), "IN") == "2026-05-12 11:31 IST"


def test_zone_less_times_are_never_guessed():
    assert clock.parse_time("12 May 2026 16:21") is None
    assert clock.parse_time("12 May 2026") is None
    assert clock.parse_time("12 May 2026 16:21", "Asia/Kolkata") is not None
    assert clock.parse_time("20260512T162100Z") == datetime(2026, 5, 12, 16, 21,
                                                            tzinfo=UTC)
    assert clock.parse_time("Tue, 12 May 2026 16:21:00 +0530").hour == 10


# ---------------------------------------------------------------- fetch
def test_offline_fetch_uses_labelled_synthetic_set_with_three_clocks():
    heads = news.fetch(["nse-rss", "bse-rss"], market="IN", start="2026-01-01",
                       end="2026-05-29")
    assert heads.height > 150
    assert heads["source"].str.contains("synthetic").all()
    assert {"published", "seen", "tradable_from"} <= set(heads.columns)
    assert heads["tradable_from"].str.ends_with("IST").all()
    assert (heads["tradable_from_utc"] >= heads["seen_utc"]).all()
    tray = news.unstamped("IN")
    assert tray.height >= 1 and tray["reason"].str.len_chars().min() > 0
    assert "offline" in news.last_status()["nse-rss"]


def test_hindi_rows_keep_original_and_translation():
    heads = news.fetch(["gdelt"], market="IN", start="2026-01-01", end="2026-05-29")
    hi = heads.filter(pl.col("lang") == "hi")
    assert hi.height > 0
    row = hi.row(0, named=True)
    assert row["original"] != row["headline"]
    assert any("ऀ" <= ch <= "ॿ" for ch in row["original"])
    scored = news.score(hi, scorer="finbert")
    assert set(scored["path"]) == {"translated"}


@pytest.mark.mocknet
def test_live_rss_is_stamped_and_appended(monkeypatch):
    from plugai_trade.data import httpkit
    rss = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>NSE</title>
    <item><title>KAVERI PUMPS LTD - Outcome of Board Meeting</title>
      <link>https://example.invalid/a</link><pubDate>12-May-2026 15:47:00</pubDate></item>
    <item><title>No time item</title><link>https://example.invalid/b</link>
      <pubDate>12 May 2026</pubDate></item>
    </channel></rss>"""
    monkeypatch.setattr(httpkit, "TRANSPORT",
                        httpx.MockTransport(lambda req: httpx.Response(200, content=rss)))
    heads = news.fetch(["nse-rss"], market="IN", start="2026-05-01", end="2026-05-31")
    assert heads.height == 1
    row = heads.row(0, named=True)
    assert row["published"] == "2026-05-12 15:47 IST" and row["source"] == "nse-rss"
    assert news.unstamped("IN").height == 1
    again = news.fetch(["nse-rss"], market="IN", start="2026-05-01", end="2026-05-31")
    assert again["seen"][0] == row["seen"]  # first Seen time is kept, never overwritten


@pytest.mark.mocknet
def test_edgar_needs_contact(monkeypatch):
    from plugai_trade.data import httpkit
    monkeypatch.setattr(httpkit, "TRANSPORT",
                        httpx.MockTransport(lambda req: httpx.Response(200, content=b"")))
    heads = news.fetch(["sec-8k"], market="US", start="2026-01-01", end="2026-02-01")
    assert "contact" in news.last_status()["sec-8k"]
    assert heads["source"].str.contains("synthetic").all()


# ---------------------------------------------------------------- scorers
def test_lexicon_and_rules_read_finance_differently():
    assert scoring.lexicon_label("Kaveri Pumps loss narrows to ₹12 crore")[0] == "negative"
    assert scoring.rules_label("Kaveri Pumps loss narrows to ₹12 crore")[0] == "positive"
    assert scoring.lexicon_label("Capital expenditure plan unchanged; tax cost")[0] == "neutral"


def test_score_labels_fallbacks_clearly():
    heads = news.fetch(["nse-rss"], market="IN", start="2026-02-01", end="2026-02-28")
    fb = news.score(heads, scorer="finbert")
    llm = news.score(heads, scorer="llm")
    assert set(fb["label"]) <= set(scoring.LABELS)
    if not scoring.finbert_available():
        assert fb["scorer_used"][0].startswith("Lexicon")
    assert llm["scorer_used"][0].startswith("Rules")
    with pytest.raises(ValueError):
        news.score(heads, scorer="magic")


def test_compare_counts_add_up():
    heads = news.fetch(["nse-rss", "bse-rss"], market="IN", start="2026-01-01",
                       end="2026-05-29")
    cmp = news.compare(news.score(heads, "finbert"), news.score(heads, "llm"))
    t = cmp.table()
    assert int(t["total"].sum()) == cmp.n == heads.height
    diag = sum(int(t[lab][i]) for i, lab in enumerate(t[t.columns[0]]))
    assert abs(diag / cmp.n - cmp.agreement) < 1e-9
    d = cmp.disagreements()
    assert d.height == cmp.n - diag and d["opposite"][0] == (cmp.opposite() > 0)
    assert (cmp.agreed("positive")["label"] == "positive").all()


# ---------------------------------------------------------------- event study
def test_event_study_costs_trials_and_date_only_join():
    heads = news.fetch(["nse-rss", "bse-rss"], market="IN", start="2026-01-01",
                       end="2026-05-29")
    cmp = news.compare(news.score(heads, "finbert"), news.score(heads, "llm"))
    before = store().count("trials", tag="news-event-study")
    es = news.event_study(cmp.agreed("positive"), window=(-5, 10), benchmark="NIFTY")
    assert es.n > 20 and es.day0() > 0.5
    ct = es.cost_table()
    gross = ct["Result per event (bps)"][0]
    assert ct.filter(pl.col("cost_bps") == 20)["Result per event (bps)"][0] == \
        pytest.approx(gross - 20, abs=0.11)
    assert es.trials == before + 1
    again = news.event_study(cmp.agreed("positive"), window=(-5, 10), benchmark="NIFTY")
    assert again.trials == es.trials  # same variant is not a new trial
    naive = news.event_study(cmp.agreed("positive"), entry="published_date")
    assert naive.trials == es.trials + 1 and naive.day0() != es.day0()
    assert any("HYPOTHETICAL" in f for f in es.facts())
    assert "Cost table" in es.report(echo=False)
    neg = news.event_study(cmp.agreed("negative"))
    assert neg.side == "short" and neg.day0() < 0


# ---------------------------------------------------------------- book snippets
def test_book_snippets_20_and_21_run_offline(capsys):
    ns: dict = {}
    exec(compile(_snippet(20), "snippet-20", "exec"), ns)  # noqa: S102 - book snippet
    exec(compile(_snippet(21), "snippet-21", "exec"), ns)  # noqa: S102 - book snippet
    out = capsys.readouterr().out
    assert "finbert \\ llm" in out and "EVENT STUDY" in out and "Trials in this family" in out
