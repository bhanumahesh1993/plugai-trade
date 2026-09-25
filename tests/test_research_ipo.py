"""IPO Dashboard: Example Ltd tiles, subscription, allotment odds, SME checks, plan, lock-ins."""

import pytest

from plugai_trade import alerts, config, docdesk, ipo
from plugai_trade.store import default as store


@pytest.fixture(autouse=True)
def offline_ai():
    config.set_value("ai.ollama_host", "http://127.0.0.1:9")


def test_rhp_tiles_match_the_book():
    t = ipo.digest_tiles(ipo.example())
    assert t["Issue size (upper)"] == "₹994.0 cr"
    assert t["Fresh / OFS"] == "40% / 60%"
    assert t["P/E · pre-issue"] == "29.6×"
    assert t["P/E · post-issue"] == "33.7× (32.1× at lower band)"
    assert t["Peer median P/E"] == "35.2×"
    assert t["Promoters"] == "78.0% → 55.3%"
    assert t["Anchor book"] == "₹298.2 cr"
    assert t["General corporate purposes"] == "20.1% of fresh issue"


def test_rhp_digest_quotes_eight_items():
    dg = ipo.rhp_digest(ipo.example())
    assert len(dg.rows) == 8 and all(r.cite.startswith("[p.") for r in dg.rows)
    assert "offer for sale" in dg.quote_for("Fresh / OFS")


def test_subscription_excludes_anchors():
    x = ipo.example()
    rows = {r["Category"]: r for r in ipo.subscription(x, ipo.sample_bids(x, 3))}
    assert rows["QIB (ex-anchor)"]["Times"] == 142.6 and rows["Retail"]["Times"] == 11.8
    assert rows["Overall (excl. anchors)"]["Times"] == 59.14
    assert rows["Anchors (shown separately)"]["Times"] is None


def test_allotment_odds_from_applications():
    odds = ipo.allotment_odds(ipo.example(), applications=2_460_000, applicants=1)
    assert odds.lots_available == 245_000
    assert round(odds.p * 100, 2) == 9.96 and not odds.applications_is_estimate
    three = ipo.allotment_odds(ipo.example(), applications=2_460_000, applicants=3)
    assert three.at_least_one == pytest.approx(1 - (1 - odds.p) ** 3)
    assert three.money_blocked == 3 * 50 * 284
    est = ipo.allotment_odds(ipo.example())
    assert est.applications_is_estimate and "(estimate)" in est.facts()[1]


def test_gmp_panel_is_labelled_and_separate():
    panel = ipo.gmp_panel({"Site A": 22, "Site B": 35})
    assert panel["banner"] == "UNOFFICIAL · UNREGULATED · NOT A FORECAST" and panel["spread"] == 13
    assert "gmp" not in " ".join(ipo.digest_tiles(ipo.example())).lower()


def test_sme_checks_meet_fail_and_not_found():
    good = ipo.sme_checks(docdesk.sample("Example-SME-Ltd_RHP"))
    assert [c.status for c in good] == ["meets"] * 4 and all(c.cite for c in good)
    bad = docdesk.load_text(
        "Restated EBITDA was ₹0.4 crore in FY26, ₹0.6 crore in FY25 and "
        "₹1.1 crore in FY24. The offer for sale is 35% of the issue.",
        "SME B",
    )
    status = {c.rule.split()[0]: c.status for c in ipo.sme_checks(bad)}
    assert status["Operating"] == "does not meet" and status["Offer"] == "does not meet"
    assert status["Minimum"] == "not found"
    liq = ipo.liquidity(ipo.example_sme(), docdesk.sample("Example-SME-Ltd_RHP"))
    assert (
        liq["Minimum application"].startswith("₹216,000") and "Market Makers" in liq["Market maker"]
    )


def test_listing_plan_values_and_critique():
    plan = ipo.listing_plan(ipo.example(), 50)
    assert [r["Price"] for r in plan] == [355.0, 312.4, 284.0, 255.6]
    assert plan[0]["Value"] == 17750 and plan[0]["Change"] == 3550 and plan[3]["Change"] == -1420
    crit = ipo.critique(plan)
    assert "Every scenario row needs a written action." in crit and "no averaging down" in crit


def test_lock_in_calendar_and_journal():
    rows = {r["Holder"]: r for r in ipo.lock_in_calendar(ipo.example())}
    assert rows["Anchors, first half"]["% of all shares"] == 4.6
    assert rows["Pre-IPO holders"]["% of all shares"] == 14.0
    assert rows["Promoters above minimum"]["% of all shares"] == 35.3
    assert rows["Anchors, first half"]["Unlocks"] == "2026-11-08"
    ipo.add_lock_ins_to_alerts(ipo.example())
    assert all(a.status == "proposed" for a in alerts.load_all())
    ipo.save_plan_to_journal(ipo.example(), 50, ipo.listing_plan(ipo.example(), 50))
    note = store().all("notes", tag="journal")[0]
    assert note["post_listing_review"] == "2026-11-12"
    assert any("Post-listing review" in a.name for a in alerts.load_all())
