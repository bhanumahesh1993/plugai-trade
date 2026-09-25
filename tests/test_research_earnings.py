"""Earnings Desk: lab calendar, digest Change column, guidance chip, implied move, alerts."""

from datetime import date

import pytest

from plugai_trade import alerts, config, docdesk, earnings
from plugai_trade.earnings import calendar
from plugai_trade.earnings.pricing import bs_price, straddle
from plugai_trade.store import default as store


@pytest.fixture(autouse=True)
def offline_ai():
    config.set_value("ai.ollama_host", "http://127.0.0.1:9")


def test_nifty_expiry_weekday_comes_from_reference():
    evs = calendar.expiry_events("IN", date(2026, 10, 1), date(2026, 10, 31))
    weekly = [e for e in evs if e.title == "NIFTY weekly expiry"]
    assert weekly and all(e.date.weekday() == 1 for e in weekly)  # Tuesday
    assert all("Contract Table" in e.source for e in weekly)


def test_macro_and_results_rows_have_sources():
    rows = calendar.events("US", date(2026, 10, 1), date(2026, 12, 31), ["SYN-US-006"])
    kinds = {e.kind for e in rows}
    assert {"macro", "expiry", "results"} <= kinds
    assert all(e.source and e.stamped for e in rows)
    assert calendar.results_dates("NIFTY", "IN", date(2026, 1, 1), date(2026, 12, 31)) == []


def test_results_calendar_overlap_column():
    rows = earnings.results_calendar(
        ["SYN-IN-004"], "IN", date(2026, 10, 1), 60, macro=True, positions=["SYN-IN-004"]
    )
    flagged = [r for r in rows if r["Overlap"]]
    days = {r["Date"] for r in flagged}
    for d in days:
        assert sum(1 for r in rows if r["Date"] == d) > 1


def test_figures_and_change():
    assert earnings.figures("Revenue was ₹468 crore against ₹409 crore") == [
        (468.0, "₹ crore"),
        (409.0, "₹ crore"),
    ]
    assert earnings.change(468, 409, "₹ crore") == "+14.4%"
    assert earnings.change(13.6, 14.8, "%") == "-1.2 pp"
    assert earnings.change(81, 78, "days") == "+3"


@pytest.mark.parametrize(
    "before, after, chip",
    [
        (
            "We are confident of mid-to-high-teens growth in FY27.",
            "For the full year we continue to guide for mid-teens revenue growth.",
            "wording softer",
        ),
        (
            "For the full year we continue to guide for mid-teens revenue growth.",
            "Outlook: we now guide for low-to-mid-teens revenue growth for FY27, "
            "subject to the monsoon.",
            "wording softer",
        ),
        ("We guide for mid-teens growth.", "We guide for mid-teens growth.", "unchanged"),
        (
            "We guide for mid-teens growth.",
            "We are confident of high-teens growth.",
            "wording firmer",
        ),
    ],
)
def test_guidance_chip(before, after, chip):
    assert earnings.guidance_chip(before, after) == chip


def test_digest_computes_change_and_saves_history():
    d = earnings.digest(
        docdesk.sample("Kaveri_Q2-FY27_results"),
        "Kaveri Pumps",
        prior={
            "quote": "For the full year we continue to guide for mid-teens revenue growth.",
            "cite": "[Q1 p. 4]",
        },
    )
    rows = {r["Item"]: r for r in d.rows}
    assert rows["Revenue"]["Change"] == "+14.4%" and rows["Revenue"]["Page"] == "[p. 2]"
    assert rows["EBITDA margin"]["Change"] == "-1.2 pp"
    assert rows["Net profit"]["Change"] == "+6.1%" and rows["Receivable days"]["Change"] == "+3"
    assert d.chip == "wording softer"
    earnings.add_consensus(d, "Revenue", 455, "my notes", "2026-10-20")
    assert d.consensus[0]["Difference"] == "+2.9%"
    earnings.save_digest(d, "IN")
    assert earnings.last_guidance("Kaveri Pumps")["quote"] == d.guidance_now
    again = earnings.digest(docdesk.sample("Kaveri_Q2-FY27_results"), "Kaveri Pumps")
    assert again.chip == "unchanged"


def test_black_scholes_parity_and_straddle():
    c, p = bs_price("call", 100, 100, 0.25, 0.2), bs_price("put", 100, 100, 0.25, 0.2)
    assert c == pytest.approx(p) and c == pytest.approx(3.99, abs=0.01)
    assert straddle(100, 100, 0.25, 0.2)[2] == pytest.approx(c + p)


def test_implied_move_tiles_scenarios_and_split():
    im = earnings.implied_move("SYN-US-006", "US", asof=date(2026, 9, 25))
    assert im is not None and im.expiry > im.event_date
    assert im.implied_move_pct == pytest.approx(im.straddle / im.spot * 100)
    assert set(im.tiles()) == {
        "Straddle",
        "Implied move",
        "Average move (last 8)",
        "Median",
        "Largest",
    }
    assert len(im.moves) == 8 and all("from" in m and "to" in m for m in im.moves)
    sc = im.scenarios()
    assert sc["Move"].to_list() == ["-10%", "-5%", "+0%", "+5%", "+10%"]
    assert sc.filter(sc["Move"] == "+0%")["Change"][0] < 0  # IV crush at no move
    split = im.event_split()
    assert split["event-day move %"] >= 0 and split["sessions to expiry"] > 1


def test_not_in_fo_list_has_no_implied_move():
    name = next(
        f"SYN-IN-{i:03d}" for i in range(1, 50) if not earnings.in_fo_list(f"SYN-IN-{i:03d}", "IN")
    )
    assert earnings.implied_move(name, "IN", asof=date(2026, 9, 25)) is None


def test_send_to_alerts_and_journal_round_trip():
    rows = earnings.results_calendar(["SYN-US-006"], "US", date(2026, 10, 1), 90)
    ids = earnings.send_to_alerts(rows[:2], "US")
    got = [a for a in alerts.load_all() if a.id in ids]
    assert len(got) == 2 and all(a.status == "proposed" and a.kind == "event" for a in got)
    im = earnings.implied_move("SYN-US-006", "US", asof=date(2025, 1, 2))
    earnings.save_move_to_journal(im)
    assert earnings.fill_actual_moves(asof=date(2026, 9, 25)) == 1
    note = store().all("notes", tag="journal")[0]
    assert note["actual_move_pct"] is not None and "actual move" in note["text"]
    earnings.open_in_options_builder(im)
    legs = store().all("notes", tag="options_prefill")[0]["legs"]
    assert {leg["kind"] for leg in legs} == {"call", "put"} and all(
        leg["side"] == "buy" for leg in legs
    )
