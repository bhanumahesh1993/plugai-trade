"""Free data connectors + Settings › Data Sources / Keys — all offline (httpx.MockTransport)."""

from __future__ import annotations

import base64
import io
import json
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import polars as pl
import pytest
from streamlit.testing.v1 import AppTest
from typer.testing import CliRunner

from plugai_trade import config, data, keys, paper_guard
from plugai_trade.data import catalog, httpkit

pytestmark = pytest.mark.mocknet

DAY = date(2026, 5, 29)  # a Friday

UDIFF_CSV = (
    "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,"
    "FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,"
    "PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,TtlTrfVal\n"
    "2026-05-29,2026-05-29,CM,NSE,STK,2885,INE002A01018,RELIANCE,EQ,,,,,RELIANCE IND,1400.5,"
    "1420,1395.25,1411.1,1411,1398,,,,,5123456,7200000000\n"
    "2026-05-29,2026-05-29,CM,NSE,STK,2885,INE002A01018,RELIANCE,BL,,,,,RELIANCE IND,1,1,1,1,"
    "1,1,,,,,10,10\n"
)
LEGACY_CSV = (
    "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,LAST,PREVCLOSE,TOTTRDQTY,TOTTRDVAL,TIMESTAMP,"
    "TOTALTRADES,ISIN,\n"
    "RELIANCE,EQ,1000,1010,990,1005,1004,998,300000,300000000,04-JAN-2010,1200,INE002A01018,\n"
)
INDEX_CSV = (
    '"Index Name","Index Date","Open Index Value","High Index Value","Low Index Value",'
    '"Closing Index Value","Points Change","Change(%)","Volume","Turnover (Rs. Cr.)","P/E",'
    '"P/B","Div Yield"\n'
    '"Nifty 50","29-05-2026","24700.10","24850.55","24650.00","24810.35","110.2","0.45",'
    '"250000000","25000","22.1","3.5","1.3"\n'
    '"Nifty Bank","29-05-2026","52000","52400","51900","52300","300","0.58","90000000",'
    '"9000","15.2","2.4","0.9"\n'
)


def _zip(csv: str, name: str = "file.csv") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, csv)
    return buf.getvalue()


@pytest.fixture
def net(monkeypatch):
    """Route every httpkit request through a handler table; records requests."""
    monkeypatch.delenv("PLUGAI_TRADE_OFFLINE", raising=False)
    routes: list[tuple[str, object]] = []
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        url = str(request.url)
        for needle, reply in routes:
            if needle in url:
                return reply(request) if callable(reply) else reply
        return httpx.Response(404)

    monkeypatch.setattr(httpkit, "TRANSPORT", httpx.MockTransport(handler))

    class Net:
        requests = seen

        @staticmethod
        def route(needle: str, reply) -> None:
            routes.append((needle, reply))

    return Net


@pytest.fixture
def vault(monkeypatch):
    """An in-memory OS keychain."""
    store: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(keys.keyring, "set_password", lambda s, n, v: store.__setitem__((s, n), v))
    monkeypatch.setattr(keys.keyring, "get_password", lambda s, n: store.get((s, n)))
    monkeypatch.setattr(keys.keyring, "delete_password", lambda s, n: store.pop((s, n), None))
    return store


# ------------------------------------------------------------------ NSE / BSE bhavcopy
def test_nse_udiff_equity_bar_and_raw_cache(net, lab_home):
    net.route("BhavCopy_NSE_CM_0_0_0_20260529", httpx.Response(200, content=_zip(UDIFF_CSV)))
    df = data.get("RELIANCE", "IN", DAY, DAY, source="nse", fallback=False)
    assert df.height == 1 and df["close"][0] == 1411.1 and df["volume"][0] == 5123456
    assert df["source"][0] == "nse_bhavcopy" and df["license_class"][0] == "personal-use"
    assert (lab_home / "raw" / "nse" / "cm" / "cm_20260529.csv.zip").exists()
    assert net.requests[0].headers["User-Agent"].startswith("Mozilla/5.0")
    n = len(net.requests)
    data.get("RELIANCE", "IN", DAY, DAY, source="nse_bhavcopy", use_cache=False, fallback=False)
    assert len(net.requests) == n  # second read comes from the raw file cache


def test_nse_legacy_format():
    from plugai_trade.data import nse_bhavcopy
    df = nse_bhavcopy.parse_cm(_zip(LEGACY_CSV, "cm04JAN2010bhav.csv"), date(2010, 1, 4))
    assert df.row(0, named=True)["close"] == 1005.0
    assert "historical/EQUITIES/2010/JAN/cm04JAN2010bhav.csv.zip" in \
        nse_bhavcopy.cm_urls(date(2010, 1, 4))[0]


def test_nse_index_close_and_holiday_learning(net):
    from plugai_trade.data import nse_bhavcopy
    net.route("ind_close_all_29052026", httpx.Response(200, text=INDEX_CSV))
    df = data.get("NIFTY", "IN", date(2026, 5, 28), DAY, source="nse")
    assert df.height == 1 and df["close"][0] == 24810.35  # 28 May had no file (404)
    assert date(2026, 5, 28) in nse_bhavcopy.holidays()
    n = len(net.requests)
    data.get("BANKNIFTY", "IN", date(2026, 5, 28), DAY, source="nse")
    assert len(net.requests) == n  # the holiday is not asked for again; index file reused


def test_nse_refuses_huge_range_before_downloading(net):
    from plugai_trade.data import nse_bhavcopy
    with pytest.raises(RuntimeError, match="daily files"):
        nse_bhavcopy._fetch("RELIANCE", "IN", date(2025, 1, 1), DAY)
    assert net.requests == []


def test_bse_udiff(net):
    csv = UDIFF_CSV.replace("RELIANCE,EQ", "RELIANCE,A").replace(",2885,", ",500325,")
    net.route("BhavCopy_BSE_CM_0_0_0_20260529", httpx.Response(200, text=csv))
    df = data.get("500325", "IN", DAY, DAY, source="bse", fallback=False)
    assert df["close"][0] == 1411.1 and df["source"][0] == "bse_bhavcopy"


# ------------------------------------------------------------------ router
def test_router_falls_back_to_cache_then_synthetic(net):
    net.route("ind_close_all_29052026", httpx.Response(200, text=INDEX_CSV))
    first = data.get("NIFTY", "IN", DAY, DAY)  # default IN-eod chain: NSE answers first
    assert first["source"][0] == "nse_bhavcopy"

    config.set_value("data.offline", True)  # now nothing live works …
    again = data.get("NIFTY", "IN", DAY, DAY)
    assert again["source"][0] == "nse_bhavcopy" and again.height == 1  # … local cache answers
    fresh = data.get("BANKNIFTY", "IN", date(2026, 5, 1), DAY)
    assert fresh["source"][0] == "synthetic"  # nothing cached: offline last resort


def test_alias_nse_and_offline_env(monkeypatch):
    monkeypatch.setenv("PLUGAI_TRADE_OFFLINE", "1")
    with pytest.raises(data.DataUnavailable, match="nse_bhavcopy: offline"):
        data.get("NIFTY", "IN", DAY, DAY, source="nse", fallback=False)


def test_book_snippet_ch05_with_mocks(net):
    """The Chapter 5 script: NSE vs a second source, flags from data.compare."""
    net.route("ind_close_all_", httpx.Response(200, text=INDEX_CSV))
    a = data.get("NIFTY", market="IN", start=DAY, end=DAY, source="nse", fallback=False)
    b = a.with_columns((pl.col("close") * 1.01).alias("close"))
    diff = data.compare(a, b, tol=0.005)
    assert diff["status"].to_list() == ["disagree"]


# ------------------------------------------------------------------ SEC EDGAR
def _edgar_routes(net):
    net.route("company_tickers.json", httpx.Response(
        200, json={"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}))
    net.route("submissions/CIK0000320193.json", httpx.Response(200, json={"filings": {"recent": {
        "filingDate": ["2026-05-01", "2026-02-01"], "form": ["10-Q", "8-K"],
        "accessionNumber": ["0000320193-26-000010", "0000320193-26-000004"],
        "primaryDocument": ["aapl-10q.htm", "aapl-8k.htm"], "reportDate": ["2026-03-28", ""]}}}))
    net.route("companyfacts/CIK0000320193.json", httpx.Response(200, json={"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [{"end": "2026-03-28", "val": 95000000000, "form": "10-Q",
                                        "fp": "Q2", "filed": "2026-05-01"}]}}}}}))


def test_edgar_needs_contact(net):
    from plugai_trade.data import sec_edgar
    with pytest.raises(httpkit.NeedsKey, match="contact"):
        sec_edgar.filings("AAPL")


def test_edgar_filings_facts_and_user_agent(net):
    from plugai_trade.data import sec_edgar
    _edgar_routes(net)
    config.set_value("data.edgar_contact", "Asha Rao asha@example.com")
    assert sec_edgar.filings("AAPL", forms=("10-Q",)).height == 1
    assert sec_edgar.facts("AAPL")["value"][0] == 95000000000
    assert all("asha@example.com" in r.headers["User-Agent"] for r in net.requests)
    df = data.get("AAPL", "IN", DAY, DAY, source="sec-edgar", fallback=False)  # CLI default market is IN
    assert df.height == 2 and df["license_class"][0] == "public"


def test_cli_fetch_commands(net):
    from plugai_trade.cli import app
    _edgar_routes(net)
    net.route("BhavCopy_NSE_CM_0_0_0_20260529", httpx.Response(200, content=_zip(UDIFF_CSV)))
    net.route("ind_close_all_29052026", httpx.Response(200, text=INDEX_CSV))
    config.set_value("data.edgar_contact", "Asha Rao asha@example.com")
    runner = CliRunner()
    out = runner.invoke(app, ["fetch", "nse-bhavcopy", "--date", "2026-05-29"])
    assert out.exit_code == 0 and "nse_bhavcopy: 1 rows · licence personal-use" in out.output
    out = runner.invoke(app, ["fetch", "sec-edgar", "--ticker", "AAPL"])
    assert out.exit_code == 0 and "sec_edgar:" in out.output and "licence public" in out.output


# ------------------------------------------------------------------ FX, macro, AMFI
def test_frankfurter(net):
    net.route("api.frankfurter.dev/v1/2026-05-28..2026-05-29", httpx.Response(200, json={
        "base": "USD", "rates": {"2026-05-28": {"INR": 85.1}, "2026-05-29": {"INR": 85.3}}}))
    df = data.get("USD/INR", "FX", date(2026, 5, 28), DAY, source="fx")
    assert df["close"].to_list() == [85.1, 85.3] and df["license_class"][0] == "public"


def test_fred_keyless_csv_then_keyed_api(net, vault):
    net.route("fredgraph.csv", httpx.Response(
        200, text="observation_date,DGS10\n2026-05-28,4.41\n2026-05-29,.\n"))
    df = data.get("DGS10", "MACRO", date(2026, 5, 28), DAY, source="fred")
    assert df["close"].to_list() == [4.41]  # "." (missing) dropped
    keys.set_key("fred_api_key", "fredkey1234")
    net.route("api.stlouisfed.org", httpx.Response(200, json={"observations": [
        {"date": "2026-05-29", "value": "4.45"}]}))
    df = data.get("DGS10", "MACRO", DAY, DAY, source="fred", fallback=False)
    assert df["close"].to_list() == [4.45]


def test_amfi_parse_header_driven():
    from plugai_trade.data import amfi_nav
    text = ("Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;"
            "Net Asset Value;Date\n\nOpen Ended Schemes(Equity Scheme - ELSS)\n\nSome AMC\n"
            "120503;INF846K01EW2;-;Demo ELSS Fund - Direct Growth;98.7654;29-May-2026\n"
            "120504;INF846K01EX0;-;Other Fund;N.A.;29-May-2026\n")
    df = amfi_nav.parse(text)
    assert df.height == 1 and df["nav"][0] == 98.7654 and df["date"][0] == DAY
    assert amfi_nav.pick_scheme(df, "demo elss").height == 1
    new = ("Scheme Code;NAV Name;Plan;Option;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;"
           "Net Asset Value;Date\n\nSome AMC\n135762;Demo Fund - Growth;;;;;29.6475;29-May-2026\n")
    assert amfi_nav.parse(new).row(0, named=True)["scheme_name"] == "Demo Fund - Growth"


# ------------------------------------------------------------------ keyed sources
def test_alpaca_bars_pagination_and_headers(net, vault):
    with pytest.raises(data.DataUnavailable, match="Alpaca key ID is not set"):
        data.get("SPY", "US", DAY, DAY, source="alpaca", fallback=False)
    keys.set_key("alpaca_key_id", "PKTESTID0001")
    keys.set_key("alpaca_secret", "secretABCD")
    pages = iter([
        {"bars": [{"t": "2026-05-28T04:00:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10}],
         "next_page_token": "p2"},
        {"bars": [{"t": "2026-05-29T04:00:00Z", "o": 2, "h": 3, "l": 1.5, "c": 2.5, "v": 20}],
         "next_page_token": None}])
    net.route("data.alpaca.markets/v2/stocks/SPY/bars",
              lambda req: httpx.Response(200, json=next(pages)))
    df = data.get("SPY", "US", date(2026, 5, 28), DAY, source="alpaca")
    assert df["close"].to_list() == [1.5, 2.5] and df["license_class"][0] == "broker"
    req = net.requests[-1]
    assert req.headers["APCA-API-KEY-ID"] == "PKTESTID0001" and req.url.params["feed"] == "iex"
    assert req.url.params["page_token"] == "p2"


def _jwt(exp: datetime) -> str:
    claims = base64.urlsafe_b64encode(json.dumps({"exp": int(exp.timestamp())}).encode())
    return "eyJhbGciOiJIUzI1NiJ9." + claims.decode().rstrip("=") + ".sig"


def test_upstox_candles_and_token_expiry(net, vault):
    from plugai_trade.data import upstox
    token = _jwt(datetime.now(UTC) + timedelta(days=200))
    keys.set_key("upstox_analytics_token", token)
    net.route("api.upstox.com/v3/historical-candle/", httpx.Response(200, json={
        "status": "success", "data": {"candles": [
            ["2026-05-29T00:00:00+05:30", 24700.1, 24850.5, 24650, 24810.3, 0, 0],
            ["2026-05-28T00:00:00+05:30", 24600, 24720, 24550, 24700.2, 0, 0]]}}))
    df = data.get("NIFTY", "IN", date(2026, 5, 28), DAY, source="upstox")
    assert df["close"].to_list() == [24700.2, 24810.3] and df["source"][0] == "upstox"
    req = net.requests[-1]
    assert req.headers["Authorization"] == f"Bearer {token}"
    assert "NSE_INDEX%7CNifty%2050/days/1/2026-05-29/2026-05-28" in str(req.url)
    left = (upstox.token_expiry() - date.today()).days
    assert 198 <= left <= 201


def test_fyers_and_breeze(net, vault):
    keys.set_key("fyers_app_id", "APP-100")
    keys.set_key("fyers_token", "tok-xyz")
    stamp = int(datetime(2026, 5, 29, 3, 45, tzinfo=UTC).timestamp())
    net.route("api-t1.fyers.in/data/history", httpx.Response(200, json={
        "s": "ok", "candles": [[stamp, 1, 2, 0.5, 1.5, 100]]}))
    df = data.get("NIFTY", "IN", DAY, DAY, source="fyers", fallback=False)
    assert df["date"][0] == DAY and net.requests[-1].url.params["symbol"] == "NSE:NIFTY50-INDEX"
    with pytest.raises(data.DataUnavailable, match="ICICI Breeze API key is not set"):
        data.get("NIFTY", "IN", DAY, DAY, source="breeze", fallback=False)


def test_keyed_errors_never_show_the_key(net, vault):
    keys.set_key("finnhub_api_key", "SUPERSECRETKEY9")
    net.route("finnhub.io", httpx.Response(401, json={"error": "Invalid API key"}))
    with pytest.raises(data.DataUnavailable) as err:
        data.get("SPY", "US", DAY, DAY, source="finnhub", fallback=False)
    assert "SUPERSECRETKEY9" not in str(err.value) and "401" in str(err.value)


def test_tiingo_and_massive(net, vault):
    keys.set_key("tiingo_api_key", "t0k")
    keys.set_key("massive_api_key", "m0k")
    net.route("api.tiingo.com", httpx.Response(200, json=[
        {"date": "2026-05-29T00:00:00.000Z", "open": 1, "high": 2, "low": 0.5, "close": 1.5,
         "volume": 9}]))
    ms = int(datetime(2026, 5, 29, 4, tzinfo=UTC).timestamp() * 1000)
    net.route("api.massive.com", httpx.Response(200, json={"results": [
        {"t": ms, "o": 1, "h": 2, "l": 0.5, "c": 1.6, "v": 9}]}))
    assert data.get("SPY", "US", DAY, DAY, source="tiingo", fallback=False)["close"][0] == 1.5
    assert data.get("SPY", "US", DAY, DAY, source="massive", fallback=False)["close"][0] == 1.6


def test_all_sources_registered_and_no_order_code():
    names = {s.name for s in data.sources()}
    assert set(data._SOURCE_MODULES) <= names
    root = Path(data.__file__).parent
    assert paper_guard.scan_path(root) == []


def test_probe_records_status(net, vault, monkeypatch):
    net.route("ind_close_all_", httpx.Response(200, text=INDEX_CSV))
    assert not catalog.is_set_up("upstox") and catalog.is_set_up("nse_bhavcopy")
    monkeypatch.setitem(catalog.OPTIONAL_PACKAGES, "yfinance", "no_such_package_xyz")
    assert not catalog.is_set_up("yfinance")  # extra not installed → hollow dot
    result = catalog.probe("upstox", "IN")
    assert not result.ok and "Analytics Token" in result.message
    assert not catalog.is_working("upstox")


# ------------------------------------------------------------------ pages
def _page(module: str) -> AppTest:
    at = AppTest.from_string(f"from plugai_trade.app.pages import {module} as m\nm.render()\n",
                             default_timeout=60)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_data_sources_page_tiers_and_strip(monkeypatch):
    monkeypatch.setenv("PLUGAI_TRADE_OFFLINE", "1")
    at = _page("data_sources")
    text = " ".join(m.value for m in at.markdown)
    for word in ("NO SIGNUP", "FREE KEY", "YOUR BROKER", "**NSE bhavcopy → ", "local cache**"):
        assert word in text
    labels = [e.label for e in at.expander]
    assert "● Synthetic" in labels and "○ Upstox" in labels
    for name in ("Connect", "Test connection", "+ Add key", "Compare sources"):
        assert any(b.label == name for b in at.button)
    at.button(key="ds_strip_IN-eod_front").click().run()  # "Move to front" on first pick
    assert not at.exception


def test_data_sources_upstox_connect_and_test(monkeypatch, vault):
    monkeypatch.setenv("PLUGAI_TRADE_OFFLINE", "1")
    at = _page("data_sources")
    at.button(key="ds_upstox_connect").click().run()
    at.text_input(key="ds_upstox_upstox_analytics_token").input("abc.def.ghi1234").run()
    at.button(key="ds_upstox_save").click().run()
    assert any("••••1234" in s.value for s in at.success)
    at.button(key="ds_upstox_test").click().run()
    assert not at.exception and any("offline" in e.value for e in at.error)


def test_compare_sources_subscreen(monkeypatch):
    monkeypatch.setenv("PLUGAI_TRADE_OFFLINE", "1")
    at = _page("data_sources")
    at.button(key="ds_compare").click().run()
    assert any(b.label == "Run" for b in at.button)
    at.button(key="ds_cmp_run").click().run()  # NSE vs yfinance offline → clear error
    assert at.error and not at.exception
    at.selectbox(key="ds_cmp_a_IN").set_value("synthetic").run()
    at.selectbox(key="ds_cmp_b_IN").set_value("synthetic").run()
    at.button(key="ds_cmp_run").click().run()
    assert any("rows compared" in m.value for m in at.markdown)
    at.button(key="ds_cmp_ai_explain").click().run()
    at.button(key="ds_cmp_save").click().run()
    assert not at.exception
    from plugai_trade.store import default as store
    assert store().count("journal", tag="data-check") == 1


def test_keys_page_add_refuse_remove(vault):
    at = _page("keys_page")
    at.button(key="keys_add").click().run()
    at.selectbox(key="keys_name").set_value("exchange_key").run()
    at.text_input(key="keys_value").input("exch-key-9876").run()
    at.multiselect(key="keys_perms").set_value(["read", "trade"]).run()
    at.button(key="keys_save").click().run()
    assert any("Refused" in e.value for e in at.error) and keys.listed() == []
    at.multiselect(key="keys_perms").set_value(["read"]).run()
    at.button(key="keys_save").click().run()
    assert keys.listed() == ["exchange_key"]
    at.run()
    assert any("••••9876" in m.value for m in at.markdown)
    assert not any("exch-key-9876" in m.value for m in at.markdown)
    at.button(key="keys_rm_exchange_key").click().run()
    assert keys.listed() == []
