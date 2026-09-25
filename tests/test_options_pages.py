"""Options Strategy Builder and Contract Table screens: book walkthrough clicks."""

from streamlit.testing.v1 import AppTest


def _app(module: str) -> AppTest:
    at = AppTest.from_string(f"from plugai_trade.app.pages import {module} as m\nm.render()\n",
                             default_timeout=60)
    at.run()
    assert not at.exception
    return at


def _click(at: AppTest, label: str) -> None:
    next(b for b in at.button if b.label == label).click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]


def _metrics(at: AppTest) -> dict:
    return {m.label: m.value for m in at.metric}


def test_builder_ch22_walkthrough():
    at = _app("options_builder")
    m = _metrics(at)
    assert m["Breakeven"] == "25,089" and m["Max loss"] == "₹5,785" and m["Theta/day"] == "−₹1,057"
    assert m["IV rank"] == "29" and m["IV percentile"] == "61"
    at.number_input(key="ob_gap").set_value(-300.0)
    _click(at, "Gap")
    m = _metrics(at)
    assert m["Value"] == "₹15.5" and m["P&L per lot"] == "−₹4,778"
    _click(at, "Scenarios")
    assert len(at.dataframe[-1].value) == 6
    _click(at, "Explain")
    assert any("Breakeven: 25,089" in i.value for i in at.info)


def test_builder_income_preset_save_and_send():
    at = _app("options_builder")
    _click(at, "Iron condor")
    m = _metrics(at)
    assert m["Credit"] == "₹3,971.50" and m["2nd Breakeven"] == "25,461.10"
    assert m["Margin estimate"] == "≈ ₹41,235"
    _click(at, "Save to plan")
    _click(at, "Send to Paper Desk")
    from plugai_trade import store
    s = store.default()
    assert s.count("plans", tag="options") == 1
    assert s.count("paper_orders", tag="pending") == 1


def test_builder_new_strategy_add_leg():
    at = _app("options_builder")
    _click(at, "New strategy")
    assert any("New strategy" in i.value for i in at.info)
    _click(at, "Sell")
    _click(at, "Put")
    assert _metrics(at)["Delta"] == "0.48"


def test_contract_table_filters():
    at = _app("contract_table")
    df = at.dataframe[0].value
    assert {"Settlement", "Exposure required", "As of"} <= set(df.columns)
    assert "Exposure required" in set(df["Exposure required"])
    at.selectbox(key="ct_market").set_value("All")
    at.selectbox(key="ct_currency").set_value("USD")
    at.run()
    assert set(at.dataframe[0].value["Currency"]) == {"USD"}
    assert any("plugai-trade update" in c.value for c in at.caption)
