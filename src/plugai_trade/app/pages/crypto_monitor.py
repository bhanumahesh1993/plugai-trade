"""Portfolio › Crypto Monitor (Chapter 25).

Tabs Watch / Funding rates / Alerts / India VDA ledger. Funding, liquidation
distance, basis and the VDA ledger are computed in ``plugai_trade.crypto``.
No exchange key is needed or accepted here: public data only, paper only.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from plugai_trade import crypto, portfolio as pf, reference
from plugai_trade.app import ui
from plugai_trade.store import default as store

AMBER = "background-color: #FEF3C7; color: #92400E"
VENUES = ("binance", "coinbase", "kraken", "Delta Exchange India", "CoinDCX", "synthetic")


def _cur(market: str) -> str:
    return "₹" if market == "IN" else "$"


def _positions(market: str) -> list[crypto.Position]:
    key = f"cm_positions_{market}"
    if key not in st.session_state:
        notional = 500_000.0 if market == "IN" else 5_000.0
        st.session_state[key] = [crypto.Position("BTC", "long", notional, 10, 60_000.0,
                                                 venue="synthetic")]
    return st.session_state[key]


def _add_position(market: str) -> None:
    if st.button("Add position", key="cm_add"):
        st.session_state["cm_adding"] = True
    if not st.session_state.get("cm_adding"):
        return
    with st.form("cm_add_form"):
        c = st.columns(3)
        venue = c[0].selectbox("Venue", VENUES)
        symbol = c[1].selectbox("Contract", ["BTC", "ETH"])
        kind = c[2].selectbox("Type", ["perpetual", "spot"])
        c = st.columns(4)
        side = c[0].selectbox("Side", ["long", "short"])
        notional = c[1].number_input(f"Notional ({_cur(market)})", 0.0,
                                     value=500_000.0 if market == "IN" else 5_000.0, step=1000.0)
        lev = c[2].number_input("Leverage", 1.0, 125.0, 10.0)
        mode = c[3].selectbox("Margin mode", ["isolated", "cross"])
        c = st.columns(2)
        entry = c[0].number_input("Entry price", 0.0, value=60_000.0)
        mm = c[1].number_input("Maintenance margin % (venue tier)", 0.0, 10.0,
                               crypto.DEFAULT_MAINTENANCE * 100, 0.1)
        if st.form_submit_button("Add"):
            _positions(market).append(crypto.Position(symbol, side, notional, lev if kind == "perpetual" else 1.0,
                                                      entry, mode, venue, kind, mm / 100))
            st.session_state["cm_adding"] = False
            st.rerun()


# ------------------------------------------------------------------ Watch
def _watch_tab(market: str) -> None:
    rows = []
    for p in _positions(market):
        spot, perp, prov = crypto.quote(p.symbol, p.venue if p.venue in ("binance", "coinbase", "kraken") else "binance")
        rows.append({"Symbol": p.symbol, "Type": p.kind, "Venue": p.venue, "Side": p.side,
                     "Spot": round(spot, 2), "Perp": round(perp, 2) if p.kind == "perpetual" else None,
                     "Basis": f"{crypto.basis(perp, spot):+.3%}" if p.kind == "perpetual" else "—",
                     "Notional": pf.money(p.notional, _cur(market)), "Leverage": f"{p.leverage:g}×",
                     "Margin mode": p.margin_mode, "Source": prov})
    for sym in ("BTC", "ETH"):
        if not any(r["Symbol"] == sym and r["Type"] == "spot" for r in rows):
            spot, perp, prov = crypto.quote(sym)
            rows.append({"Symbol": sym, "Type": "spot (watch)", "Venue": "—", "Side": "—",
                         "Spot": round(spot, 2), "Perp": round(perp, 2),
                         "Basis": f"{crypto.basis(perp, spot):+.3%}", "Notional": "—",
                         "Leverage": "—", "Margin mode": "—", "Source": prov})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("Basis = perp's gap to spot, the input behind the funding rate.")
    st.session_state["data_status"] = rows[0]["Source"] if rows else "Synthetic · offline"
    _add_position(market)
    if market == "IN":
        _fiu_check()


def _fiu_check() -> None:
    with st.expander("FIU-IND registration check"):
        st.markdown(f"Indian venues serving Indian users must register with FIU-IND. Check the "
                    f"official list before you deposit: [{crypto.FIU_IND_LIST_URL}]"
                    f"({crypto.FIU_IND_LIST_URL}). The lab does not judge any venue.")
        note = st.text_area("Your note (venue, date you checked, what the list showed)",
                            key="cm_fiu_note")
        if st.button("Save note", key="cm_fiu_save") and note.strip():
            store().add("notes", {"screen": "Crypto Monitor", "text": note.strip()}, tag="fiu_check")
            st.success("Saved.")
        for r in store().all("notes", tag="fiu_check", limit=3):
            st.caption(f"{r['created'][:10]} · {r['text']}")


# ------------------------------------------------------------------ Funding rates
def _funding_tab(market: str) -> None:
    cur = _cur(market)
    perps = [p for p in _positions(market) if p.kind == "perpetual"]
    if not perps:
        st.info("Add a perpetual position to see funding tiles.")
        return
    idx = st.selectbox("Position", range(len(perps)),
                       format_func=lambda i: f"{perps[i].symbol} perp · {perps[i].side} · "
                                             f"{pf.money(perps[i].notional, cur)} · {perps[i].leverage:g}×",
                       key="cm_pos")
    pos = perps[idx]
    hist, prov = crypto.funding_history(pos.symbol, "binance" if pos.venue == "synthetic" else pos.venue)
    st.caption(f"Funding source: {prov}")
    c1, c2 = st.columns(2)
    times = int(c1.number_input("Funding times per day", 1, 24, 3, key="cm_times"))
    default_print = crypto.SCREENSHOT_PRINT if prov.startswith("Synthetic") else hist.height
    at = int(c2.slider("Print", 1, hist.height, min(default_print, hist.height), key="cm_print"))
    rate = float(hist["rate"][at - 1])
    tiles = crypto.funding_tiles(pos, rate, times, cur)
    cols = st.columns(6)
    for col, (label, val) in zip(cols, tiles.tiles().items(), strict=True):
        col.metric(label, val)
    _funding_chart(hist, pos, at)
    ui.ai_block(tiles, "cm_funding", section="Portfolio", sensitive=True)
    level = st.number_input("Funding alert level (% per 8 h)", 0.0, 1.0, 0.03, 0.005, format="%.3f",
                            key="cm_level")
    if st.button("Send to Alerts", key="cm_send_alerts"):
        ids = crypto.send_to_alerts(crypto.propose_alerts(pos, level / 100, market=market))
        st.success(f"{len(ids)} alerts proposed in Paper Trading › Alerts (From Crypto Monitor). "
                   "Nothing is active until you click Accept there.")
    with st.expander("Leverage and the liquidation line"):
        st.dataframe(crypto.liquidation_table(entry=pos.entry, notional=pos.notional,
                                              maintenance=pos.maintenance).to_pandas(),
                     hide_index=True)
        st.caption("Model: isolated margin, maintenance as a share of entry notional, fees and "
                   "funding ignored. Funding paid comes out of margin, so the real line is closer.")


def _funding_chart(hist, pos: crypto.Position, at: int) -> None:
    df = hist.to_pandas()
    df["funding % per 8h"] = df["rate"] * 100
    df["cumulative paid"] = crypto.cumulative_cost(pos.notional, df["rate"].to_numpy(), pos.side)
    base = alt.Chart(df).encode(x=alt.X("print:Q", title="Funding print"))
    bars = base.mark_bar(color="#7C3AED").encode(y=alt.Y("funding % per 8h:Q"))
    thr = alt.Chart(pd.DataFrame({"y": [0.03]})).mark_rule(strokeDash=[4, 3], color="#F59E0B").encode(y="y:Q")
    now = alt.Chart(pd.DataFrame({"x": [at]})).mark_rule(color="#DC2626").encode(x="x:Q")
    cum = base.mark_line(color="#0F172A").encode(y=alt.Y("cumulative paid:Q"))
    st.altair_chart(alt.vconcat((bars + thr + now).properties(height=160),
                                cum.properties(height=120)), width="stretch")


# ------------------------------------------------------------------ Alerts
def _alerts_tab(market: str) -> None:
    st.caption("Crypto alert types: " + " · ".join(crypto.ALERT_TYPES) + ". Checked in code on "
               "completed prints and 4-hour closes; every message starts with SIMULATED.")
    st.caption("Quiet hours (set in Alerts): only Funding and Liquidation distance may sound "
               "between 23:00 and 06:00.")
    from plugai_trade import alerts

    rows = [a for a in alerts.load_all() if a.kind in ("funding", "liquidation", "price_band")
            or a.name.startswith("Exchange notice")]
    if rows:
        st.dataframe(pd.DataFrame([{"Type": crypto.alert_type(a), "Alert": a.describe(),
                                    "Quiet hours": "may sound" if a.breakthrough else "held",
                                    "Status": a.status} for a in rows]),
                     hide_index=True, width="stretch")
    else:
        st.info("No crypto alerts yet. Use Send to Alerts on the Funding rates tab.")
    pos = _positions(market)[0]
    kinds = st.multiselect("Propose", list(crypto.ALERT_TYPES), list(crypto.ALERT_TYPES), key="cm_kinds")
    if st.button("Send to Alerts", key="cm_send_alerts_tab"):
        chosen = [a for a in crypto.propose_alerts(pos, market=market) if crypto.alert_type(a) in kinds]
        crypto.send_to_alerts(chosen)
        st.success(f"{len(chosen)} proposed. Accept them in Paper Trading › Alerts.")


# ------------------------------------------------------------------ India VDA ledger
def _ledger_tab(market: str) -> None:
    if market != "IN":
        st.info("The India VDA ledger applies to Indian residents. US readers: Tax › Tax Export "
                "has the 1099-DA check (rows with basis not reported are flagged).")
        return
    if "cm_ledger" not in st.session_state:
        st.session_state["cm_ledger"] = crypto.sample_ledger().rows
    up = st.file_uploader("Exchange trade-history CSV (trade, asset, bought, sold, tds)", type=["csv"],
                          key="cm_trades_csv")
    if st.button("Import tradebook", key="cm_import") and up is not None:
        try:
            st.session_state["cm_ledger"] = crypto.parse_trades_csv(up.getvalue().decode("utf-8", "ignore"))
        except Exception as exc:
            st.error(f"Could not read the file: {exc}")
    cess_default = (pf.cess_rate() or 0.04) * 100
    cess = st.number_input("Cess %", 0.0, 10.0, cess_default, key="cm_cess")
    ledger = crypto.VdaLedger(st.session_state["cm_ledger"], cess / 100)
    st.dataframe(ledger.frame().to_pandas(), hide_index=True, width="stretch")
    st.caption("Gains and losses are kept apart and never netted: a VDA loss cannot be set off.")
    c = st.columns(3)
    c[0].metric("Taxable VDA income", pf.money(ledger.gains))
    c[1].metric("Losses (recorded, not set off)", pf.money(ledger.losses))
    c[2].metric("Tax at dated rate + cess", pf.money(ledger.tax()))
    c = st.columns(3)
    c[0].metric("TDS credit", pf.money(ledger.tds_total))
    c[1].metric("Remaining to pay", pf.money(ledger.remaining))
    c[2].metric("Cost of no set-off", pf.money(ledger.tax() - ledger.tax(netted=True)))
    st.caption("Draft for your CA · rates from the dated table "
               f"(VDA {reference.lookup('india.tax.vda_rate'):.0%}, TDS "
               f"{reference.lookup('india.tax.vda_tds'):.0%}).")
    stmt = st.file_uploader("Form 26AS / AIS export (CSV with a TDS column)", type=["csv"], key="cm_26as")
    if st.button("Reconcile TDS", key="cm_reconcile"):
        amounts = ([r.tds or r.expected_tds for r in ledger.rows] if stmt is None
                   else crypto.parse_statement_csv(stmt.getvalue().decode("utf-8", "ignore")))
        rec = crypto.reconcile_tds(ledger, amounts).to_pandas()
        st.dataframe(rec.style.apply(lambda r: [AMBER if r["Status"] != "matched" else ""] * len(r),
                                     axis=1), hide_index=True, width="stretch")
        if stmt is None:
            st.caption("No statement chosen: showing the ledger against itself. Import 26AS or AIS.")
    ui.ai_block(ledger, "cm_ledger_ai", section="Tax", sensitive=True)


def render() -> None:
    """Crypto Monitor."""
    ui.page_header("Crypto Monitor", "Portfolio", "Public data only · no exchange keys · paper only")
    market = ui.market()
    tabs = st.tabs(["Watch", "Funding rates", "Alerts", "India VDA ledger"])
    with tabs[0]:
        _watch_tab(market)
    with tabs[1]:
        _funding_tab(market)
    with tabs[2]:
        _alerts_tab(market)
    with tabs[3]:
        _ledger_tab(market)
    ui.paper_only_note()
