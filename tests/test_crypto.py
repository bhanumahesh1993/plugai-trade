"""Crypto Monitor: funding, liquidation distance, alerts and the India VDA ledger (Chapter 25)."""

import pytest
from streamlit.testing.v1 import AppTest

from plugai_trade import crypto


@pytest.mark.parametrize("lev, pct", [(2, 49.5), (5, 19.5), (10, 9.5), (20, 4.5), (50, 1.5)])
def test_liquidation_distance_book(lev, pct):
    assert round(crypto.liquidation_distance(lev, 0.005) * 100, 2) == pct


def test_liquidation_price():
    assert crypto.liquidation_price(60_000, 10) == pytest.approx(54_300)
    assert crypto.liquidation_price(60_000, 10, "short") == pytest.approx(65_700)
    with pytest.raises(ValueError):
        crypto.liquidation_distance(0)


def test_funding_tiles_match_screenshot():
    pos = crypto.Position("BTC", "long", 500_000, 10, 60_000)
    rate = crypto.sample_funding()["rate"][crypto.SCREENSHOT_PRINT - 1]
    tiles = crypto.funding_tiles(pos, rate).tiles()
    assert tiles == {"Funding/8h": "0.0656%", "Annualised": "≈ 71.8%", "30-day cost": "₹29,520",
                     "To liquidation": "−9.5%", "Notional": "₹500,000", "Leverage": "10×"}


def test_funding_arithmetic():
    assert crypto.funding_payment(500_000, 0.0001) == pytest.approx(50)
    assert crypto.cost_over(500_000, 0.0002, days=1) == pytest.approx(300)
    assert crypto.funding_payment(500_000, 0.0001, "short") == pytest.approx(-50)


def test_sample_month_totals():
    rates = crypto.sample_funding()["rate"].to_numpy()
    cum = crypto.cumulative_cost(500_000, rates)
    assert len(rates) == 90
    assert round(cum[-1]) == 6_630
    assert round(cum[2]) == 154  # day 1 by hand


def test_funding_history_offline(monkeypatch):
    df, prov = crypto.funding_history("BTC")
    assert prov.startswith("Synthetic") and df.height == 90


def test_basis_and_quote():
    assert crypto.basis(101, 100) == pytest.approx(0.01)
    spot, perp, prov = crypto.quote("BTC")
    assert spot > 0 and perp > spot and prov


def test_alert_proposals():
    from plugai_trade import alerts
    pos = crypto.Position("BTC", "long", 500_000, 10, 60_000)
    proposed = crypto.propose_alerts(pos)
    assert [crypto.alert_type(a) for a in proposed] == list(crypto.ALERT_TYPES)
    assert all(a.status == "proposed" for a in proposed)
    liq = proposed[1]
    assert liq.level2 == pytest.approx(54_300) and liq.breakthrough
    assert proposed[0].level == pytest.approx(0.0003) and not proposed[2].breakthrough
    ids = crypto.send_to_alerts(proposed)
    assert len(ids) == 4 and len(alerts.load_all("proposed")) == 4


def test_vda_ledger_book():
    led = crypto.sample_ledger(cess=0.04)
    assert led.gains == 62_000 and led.losses == -20_000
    assert led.tax() == pytest.approx(19_344)
    assert led.tds_total == 3_720 and led.remaining == pytest.approx(15_624)
    assert led.tax(netted=True) == pytest.approx(13_104)
    assert led.tax() - led.tax(netted=True) == pytest.approx(6_240)
    f = led.frame()
    assert f["Gains"].sum() == 62_000 and f["Losses"].sum() == -20_000


def test_vda_rates_from_reference():
    row = crypto.VdaRow("X", "BTC", 100, 1_000)
    assert row.expected_tds == pytest.approx(10)


def test_reconcile_tds():
    led = crypto.sample_ledger()
    rec = crypto.reconcile_tds(led, [2_000, 600, 1_120])
    assert rec["Status"].to_list() == ["matched"] * 3
    rec = crypto.reconcile_tds(led, [2_000, 600, 999])
    assert rec["Status"].to_list().count("MISMATCH · ask CA") == 2


def test_csv_parsers():
    rows = crypto.parse_trades_csv("trade,asset,bought,sold,tds\nA,BTC,150000,200000,2000\n")
    assert rows[0].result == 50_000
    assert crypto.parse_statement_csv("Date,TDS deposited\n2026-05-01,\"2,000\"\n") == [2000.0]
    with pytest.raises(ValueError):
        crypto.parse_statement_csv("a,b\n1,2\n")


def test_page_flows():
    at = AppTest.from_string(
        "import streamlit as st\nst.session_state.setdefault('market', 'IN')\n"
        "from plugai_trade.app.pages import crypto_monitor as m\nm.render()\n", default_timeout=60)
    at.run()
    assert not at.exception
    labels = {b.label for b in at.button}
    assert {"Add position", "Send to Alerts", "Import tradebook", "Reconcile TDS"} <= labels
    assert {m.label for m in at.metric} >= {"Funding/8h", "Annualised", "30-day cost",
                                            "To liquidation", "Notional", "Leverage"}
    at.button(key="cm_send_alerts").click().run()
    at.button(key="cm_reconcile").click().run()
    assert not at.exception
    from plugai_trade.store import default as store
    assert store().count("alerts", tag="proposed") == 4
