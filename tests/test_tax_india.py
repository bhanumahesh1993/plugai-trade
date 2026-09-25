"""India tax: classification, the Chapter 32 turnover example, audit, ledger, advance tax, AIS."""

from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

from plugai_trade import journal
from plugai_trade.journal.samples import _fo
from plugai_trade.tax import india, rates

FIX = Path(__file__).parent / "fixtures" / "tax"


@pytest.fixture
def meera():
    return india.classify(journal.sample("meera"))


def test_turnover_worked_example_chapter_32(meera):
    t = india.turnover(meera)
    assert t.fo["trades"] == 10
    assert t.fo["net"] == -1105.0
    assert (t.fo["gains"], t.fo["losses"]) == (19240.0, 20345.0)
    assert t.fo["turnover"] == 39585.0                 # Σ |P&L| per trade
    assert t.old_method_fo == 51675.0                  # + ₹12,090 premium on two option sales
    assert t.per_contract_fo == 39585.0                # "same here; can differ"
    assert 97e5 < t.notional_fo < 99e5                 # "close to ₹98 lakh": not turnover
    assert t.deemed_profit == 2375.1                   # 6% (s.44AD / s.58)
    assert t.annualised(12) == 475020.0


def test_per_contract_view_can_differ():
    d = datetime(2026, 2, 2, 10)
    rows = [("NIFTY26FEBFUT", "NIFTY", "FUT", "LONG", 65, 24850, 24930, d, d),
            ("NIFTY26FEBFUT", "NIFTY", "FUT", "SHORT", 65, 25010, 25120, d, d)]
    t = india.turnover(india.classify(_fo(rows, "IN", "M", "t")))
    assert t.fo["turnover"] == 5200 + 7150
    assert t.per_contract_fo == abs(5200 - 7150)


def test_four_buckets_and_ask_ca():
    d = lambda mo, day, h=10: datetime(2026, mo, day, h)  # noqa: E731
    rows = [("INFY", "INFY", "EQ", "LONG", 10, 1500, 1510, d(5, 4), d(5, 4, 14)),
            ("INFY", "INFY", "EQ", "LONG", 10, 1500, 1600, d(5, 4), d(9, 1)),
            ("TCS", "TCS", "EQ", "LONG", 5, 3000, 3300, datetime(2025, 5, 1), d(6, 1)),
            ("NIFTY26SEPFUT", "NIFTY", "FUT", "LONG", 65, 24800, 24900, d(9, 1), d(9, 1, 14)),
            ("BTCINR", "BTC", "CRYPTO", "LONG", 1, 100, 110, d(9, 1), d(9, 3)),
            ("SBIN", "SBIN", "EQ", "SHORT", 10, 820, 800, d(9, 1), d(9, 2)),
            ("GOLDBEES", "GOLDBEES", "ETF", "LONG", 10, 60, 61, d(9, 1), d(9, 2))]
    c = india.classify(_fo(rows, "IN", "A", "t"))
    got = {(r["symbol"], r["entry_time"].year, r["exit_time"].day): r["bucket"]
           for r in c.rows.iter_rows(named=True)}
    assert got == {("INFY", 2026, 4): india.SPECULATIVE, ("INFY", 2026, 1): india.STCG,
                   ("TCS", 2025, 1): india.LTCG, ("NIFTY26SEPFUT", 2026, 1): india.NON_SPECULATIVE,
                   ("BTCINR", 2026, 3): india.VDA, ("SBIN", 2026, 2): india.ASK_CA,
                   ("GOLDBEES", 2026, 2): india.ASK_CA}
    assert int(c.rows["ask_ca"].sum()) == 2
    assert c.rows.filter(pl.col("bucket") == india.STCG)["section_new"][0] == "s.196"
    assert set(c.rows["fy"].to_list()) == {"2026-27"}


def test_simulated_rows_are_left_out_of_tax(meera):
    t = journal.sample("meera").with_columns(
        tags=pl.Series([["PAPER"]] + [[]] * 9, dtype=pl.List(pl.Utf8)))
    c = india.classify(t)
    assert c.rows.height == 9 and c.excluded_simulated == 1


def test_audit_check_uses_dated_thresholds():
    assert india.audit_check(475020).status == "Below limit"
    assert india.audit_check(5e7).status == "Below limit"          # ≤ ₹10 crore, digital
    assert india.audit_check(5e7, cash_share_ok=False).status == "Audit likely"
    assert india.audit_check(2e8).status == "Audit likely"
    lock = india.audit_check(475020, presumptive_opted_fy="2024-25", current_fy="2026-27",
                             declared_profit=-1105, deemed_profit=2375.1)
    assert "ASK CA" in lock.lock_in and lock.status.startswith("Audit likely")
    assert rates.get("india.tax.audit_threshold_digital_inr") == 100000000


def test_presumptive_note_numbers(meera):
    note = india.presumptive_note(india.turnover(meera))
    assert "₹2,375.10" in note and "₹-1,105.00" in note


def test_advance_tax_book_example():
    plan = india.advance_tax(60000, "2026-27")
    assert plan.rows["cumulative"].to_list() == [9000, 27000, 45000, 60000]
    assert plan.rows["instalment"].to_list() == [9000, 18000, 18000, 15000]
    assert plan.rows["due_date"].to_list() == ["2026-06-15", "2026-09-15", "2026-12-15",
                                               "2027-03-15"]
    assert plan.due and not india.advance_tax(5000, "2026-27").due


def test_carry_forward_ledger_rules(lab_home):
    led = india.CarryForwardLedger()
    led.add("2025-26", india.SPECULATIVE, 10000)
    led.add("2025-26", india.NON_SPECULATIVE, 5000)
    led.add("2025-26", "LTCL", 3000)
    with pytest.raises(ValueError, match="VDA"):
        led.add("2025-26", india.VDA, 100)
    assert led.entries[0].expires == "2029-30"         # speculative: 4 years
    assert led.entries[1].expires == "2033-34"         # F&O: 8 years
    used = led.apply("2026-27", india.NON_SPECULATIVE, 7000)
    assert [(e.bucket, amt) for e, amt in used] == [(india.NON_SPECULATIVE, 5000)]
    assert led.apply("2026-27", india.STCG, 1000) == []                 # LTCL can't touch STCG
    assert led.apply("2030-31", india.SPECULATIVE, 1000) == []          # expired
    led.save()
    again = india.CarryForwardLedger.load()
    assert again.rows()["used"].to_list() == [0.0, 5000.0, 0.0]


def test_losses_from_classified(meera):
    assert india.losses_from(meera) == [("2025-26", india.NON_SPECULATIVE, 1105.0)]


def test_vda_ledger_chapter_25():
    v = india.vda_ledger(india.classify(journal.sample("farhan")))
    assert (v.gains, v.losses, v.tds, v.tax_before_cess) == (62000, 20000, 3720, 18600)
    rec = india.reconcile_tds(v, (FIX / "form26as_vda.csv").read_bytes())
    assert rec.matched.height == 2
    assert rec.mismatches.height == 1 and rec.mismatches["security"][0] == "BTCINR"


def test_reconcile_ais_lists_mismatches_with_reasons():
    c = india.classify(journal.sample("farhan"))
    rec = india.reconcile_ais(india.broker_rows(c), (FIX / "ais.csv").read_bytes())
    assert rec.matched.height == 1                                      # BTC 2,00,000
    reasons = dict(zip(rec.mismatches["security"], rec.mismatches["reason"]))
    assert "gross vs net" in reasons["ETH"]
    assert "dividend" in reasons["INFY"]
    assert "Mismatches: 4" in rec.facts()                              # ETH both sides, BTC


def test_itr_export_is_stamped_on_every_row(meera):
    text = india.export_itr_csv(meera, "2025-26")
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    assert text.startswith("# DRAFT FOR YOUR CA / CPA")
    assert all(ln.startswith("Draft for your CA / CPA") for ln in lines[1:])
    assert any("TOTAL" in ln and "39585.00" in ln for ln in lines)


def test_section_map_and_translate():
    assert india.section_map().height == 12
    assert india.translate("44AD") == [("Presumptive taxation", "s.44AD", "s.58")]
    assert india.translate("s.113")[0][1] == "s.73"
