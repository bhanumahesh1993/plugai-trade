"""US tax: the Chapter 32 wash sale, IRA and option replacements, 1256 tags, Form 8949 CSV."""

from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

from plugai_trade import journal
from plugai_trade.journal.samples import _fo
from plugai_trade.tax import us

FIX = Path(__file__).parent / "fixtures" / "tax"


def xyz(replacement_account="Taxable", replacement=("XYZ", "XYZ", "EQ", 100, 44, 47)):
    d = lambda mo, day: datetime(2026, mo, day, 10)  # noqa: E731
    sym, und, inst, qty, px_in, px_out = replacement
    mult = 100.0 if inst == "CALL" else 1.0
    rows = [("XYZ", "XYZ", "EQ", "LONG", 100, 50, 42, d(3, 2), d(3, 20), 1.0, "Taxable"),
            (sym, und, inst, "LONG", qty, px_in, px_out, d(4, 8), d(6, 15), mult,
             replacement_account)]
    return _fo(rows, "US", "Taxable", "test")


def test_wash_sale_worked_example_chapter_32():
    w = us.wash_sales(xyz(), accounts={"Taxable": "Taxable"})
    h = w.hits.row(0, named=True)
    assert (h["window_start"], h["window_end"]) == ("2026-02-18", "2026-04-19")
    assert h["days_from_sale"] == 19 and h["loss"] == 800 and h["disallowed"] == 800
    assert h["new_basis"] == 5200 and not h["permanent"]
    rows = {r["trade_id"]: r for r in w.rows.iter_rows(named=True)}
    assert rows[1]["code"] == "W" and rows[1]["wash_disallowed"] == 800 and rows[1]["gain"] == 0
    assert rows[2]["cost_basis"] == 5200 and rows[2]["gain"] == -500      # final loss
    assert rows[2]["holding_days"] == 18 + 68 == 86 and us.term(86) == "short"


def test_ira_replacement_loses_the_loss_permanently():
    w = us.wash_sales(xyz("IRA-1"), accounts={"Taxable": "Taxable", "IRA-1": "IRA"})
    h = w.hits.row(0, named=True)
    assert h["permanent"] and h["replacement_type"] == "IRA"
    ira_row = w.rows.filter(pl.col("trade_id") == 2).row(0, named=True)
    assert ira_row["cost_basis"] == 4400                                  # no basis added
    f = us.form_8949(w)
    assert f.excluded_ira == 1 and f.rows["code"].to_list() == ["W"]


def test_spouse_account_and_call_option_count_as_replacements():
    w = us.wash_sales(xyz("Spouse"), accounts={"Spouse": "Spouse"})
    assert w.hits.height == 1
    call = ("XYZ 260918C00045000", "XYZ", "CALL", 1, 2.0, 3.0)
    w = us.wash_sales(xyz(replacement=call), accounts={})
    assert w.hits.height == 1 and w.hits["disallowed"][0] == 8.0          # 1 of 100 shares


def test_outside_window_no_hit_and_crypto_switch():
    d = lambda mo, day: datetime(2026, mo, day, 10)  # noqa: E731
    rows = [("XYZ", "XYZ", "EQ", "LONG", 100, 50, 42, d(3, 2), d(3, 20)),
            ("XYZ", "XYZ", "EQ", "LONG", 100, 44, 47, d(4, 20), d(6, 15))]
    assert us.wash_sales(_fo(rows, "US", "T", "t"), accounts={}).hits.height == 0
    coins = [("BTC", "BTC", "CRYPTO", "LONG", 1, 60000, 50000, d(3, 2), d(3, 20)),
             ("BTC", "BTC", "CRYPTO", "LONG", 1, 51000, 52000, d(3, 25), d(4, 20))]
    t = _fo(coins, "US", "T", "t")
    assert us.wash_sales(t, accounts={}).hits.height == 0                 # default off
    on = us.wash_sales(t, accounts={}, crypto=True)
    assert on.hits.height == 1 and on.crypto_checked


def test_substantially_identical_is_a_warning_only():
    d = lambda mo, day: datetime(2026, mo, day, 10)  # noqa: E731
    rows = [("SPY", "SPY", "EQ", "LONG", 10, 560, 540, d(3, 2), d(3, 20)),
            ("VOO", "VOO", "EQ", "LONG", 10, 500, 505, d(3, 25), d(4, 20))]
    w = us.wash_sales(_fo(rows, "US", "T", "t"), accounts={}, identical_pairs=[("SPY", "VOO")])
    assert w.hits.height == 0
    assert w.warnings.height == 1 and "QUESTION FOR CPA" in w.warnings["note"][0]


def test_1256_tags_from_the_dated_table():
    assert us.tag_1256("SPX", "CALL")[0] is True
    assert "broad-based index option → nonequity option → 1256" in us.tag_1256("SPX", "CALL")[1]
    assert us.tag_1256("SPY", "CALL")[0] is False
    assert us.tag_1256("QQQ", "PUT")[0] is False
    assert us.tag_1256("MES", "FUT")[0] is True
    assert us.tag_1256("RUT", "PUT")[0] is True and us.tag_1256("VIX", "CALL")[0] is True
    assert us.tag_1256("SPY", "EQ")[0] is False
    assert us.split_1256(10000) == (6000.0, 4000.0)


def test_year_end_mark_to_market():
    pos = pl.DataFrame([{"symbol": "SPX 261218C06000000", "underlying": "SPX",
                         "instrument": "CALL", "side": "BUY", "qty": 1.0, "price": 50.0,
                         "multiplier": 100.0}])
    out = us.mark_to_market(pos, {"SPX 261218C06000000": 80.0}, 2026)
    r = out.row(0, named=True)
    assert r["marked_on"] == "2026-12-31" and r["gain"] == 3000
    assert (r["long_term_60"], r["short_term_40"]) == (1800, 1200)
    assert us.last_business_day(2027).isoformat() == "2027-12-31"


def test_form_8949_boxes_code_w_and_6781():
    w = us.wash_sales(journal.sample("dan"), accounts={"Taxable": "Taxable"})
    f = us.form_8949(w)
    assert f.rows["box"].to_list() == ["A", "A", "A"]
    assert f.rows["code"].to_list() == ["W", "", ""]
    assert f.form_6781.height == 1 and f.form_6781["long_term_60"][0] == 6000
    text = us.export_8949_csv(f)
    body = [ln for ln in text.splitlines() if ln and not ln.startswith(("#", "stamp"))]
    assert all(ln.startswith("Draft for your CA / CPA") for ln in body)
    assert ",W,800.00,0.00," in text


def test_box_letters_including_digital_assets():
    assert us.box_letter(True, False, True) == "A"
    assert us.box_letter(False, False, False) == "E"
    assert us.box_letter(True, True, False) == "H"
    assert us.box_letter(False, True, None) == "L"
    d = lambda y, mo, day: datetime(y, mo, day, 10)  # noqa: E731
    coins = [("BTC", "BTC", "CRYPTO", "LONG", 1, 30000, 60000, d(2024, 1, 5), d(2026, 3, 1))]
    f = us.form_8949(us.wash_sales(_fo(coins, "US", "T", "t"), accounts={}))
    assert f.rows["box"][0] == "K" and "basis not reported" in f.rows["flag"][0]


def test_accounts_store_and_1099b_compare(lab_home):
    us.add_account("Roth", "IRA")
    us.add_account("Roth", "IRA")
    with pytest.raises(ValueError):
        us.add_account("X", "Brokerage")
    assert us.account_types() == {"Roth": "IRA"}
    f = us.form_8949(us.wash_sales(journal.sample("dan"), accounts={}))
    rec = us.compare_1099b(f, (FIX / "form_1099b.csv").read_bytes())
    assert rec.matched.height == 3 and rec.mismatches.height == 0
