"""Tax › Tax Export: India (Classify / Turnover / AIS check / Export) and US wash sales, 1256, 8949.

Everything here is a Draft for your CA / CPA. Code classifies and adds up; the local
model only explains (sensitive=True, section Tax).
"""

from __future__ import annotations

import polars as pl
import streamlit as st

from plugai_trade import journal, tax
from plugai_trade.app import ui
from plugai_trade.app.pages.journal_common import money, to_pandas
from plugai_trade.journal import importers
from plugai_trade.journal.schema import empty_trades
from plugai_trade.tax import india, rates, us

ROWS = "tax_rows"
SAMPLES = {"IN": ("meera", "farhan"), "US": ("dan",)}


def _draft_banner() -> None:
    st.warning("**DRAFT FOR YOUR CA / CPA** — PlugAI-Trade sorts and adds up; it does not tell "
               "you how to file. Rows marked ASK CA are never guessed.")


def _source_panel(market: str) -> pl.DataFrame:
    with st.expander("Import tradebook", expanded=st.session_state.get(ROWS) is None):
        brokers = [*(journal.INDIA_BROKERS if market == "IN" else journal.US_BROKERS),
                   "Generic CSV"]
        c1, c2 = st.columns(2)
        broker = c1.selectbox("Broker or exchange", brokers, key="tx_broker")
        account = c2.text_input("Account name", "Main" if market == "IN" else "Taxable",
                                key="tx_account")
        up = st.file_uploader("Tradebook / trade history CSV", type=["csv"], key="tx_file")
        if st.button("Import tradebook", disabled=up is None):
            try:
                res = journal.import_tradebook(up.getvalue(), broker, account, market=market)
            except importers.ImportError_ as exc:
                st.error(str(exc))
            else:
                old = st.session_state.get(ROWS)
                st.session_state[ROWS] = _append(old, res.trades)
                st.success(f"{res.trades.height} round trips added from {res.broker}.")
        c3, c4 = st.columns(2)
        if c3.button("Use Journal › Trades rows"):
            st.session_state[ROWS] = _append(None, journal.trades(market=market,
                                                                  include_simulated=False))
        for name in SAMPLES[market]:
            if c4.button(f"Load lesson sample ({name.title()}, synthetic)", key=f"tx_s_{name}"):
                st.session_state[ROWS] = _append(st.session_state.get(ROWS),
                                                 journal.sample(name))
        if st.session_state.get(ROWS) is not None and st.button("Clear rows"):
            st.session_state.pop(ROWS, None)
            st.rerun()
    rows = st.session_state.get(ROWS)
    return rows if rows is not None else empty_trades()


def _append(old: pl.DataFrame | None, new: pl.DataFrame) -> pl.DataFrame:
    """Add rows (renumbered after the existing ones); cached results are cleared."""
    for k in ("tx_classified", "tx_wash", "tx_itr", "tx_8949", "tx_rec"):
        st.session_state.pop(k, None)
    if old is None or old.is_empty():
        return new
    return pl.concat([old, new.with_columns(trade_id=pl.col("trade_id") + old["trade_id"].max())])


# ------------------------------------------------------------------ India
def _classify_tab(t: pl.DataFrame) -> india.Classified | None:
    if st.button("Classify", type="primary"):
        st.session_state["tx_classified"] = india.classify(t)
    c: india.Classified | None = st.session_state.get("tx_classified")
    if c is None:
        st.caption("Click Classify: each round trip gets a bucket and the rule that put it there.")
        return None
    counts = c.counts()
    cols = st.columns(6)
    for col, b in zip(cols, (india.SPECULATIVE, india.NON_SPECULATIVE, india.STCG, india.LTCG,
                             india.VDA, india.ASK_CA)):
        col.metric(india.BUCKET_NAMES[b].split(" (")[0], counts.get(b, 0))
    st.dataframe(to_pandas(c.rows.select("trade_id", "fy", "symbol", "side", "gross", "bucket",
                                         "rule", "section_old", "section_new", "ask_ca")),
                 hide_index=True, use_container_width=True)
    if c.excluded_simulated:
        st.caption(f"{c.excluded_simulated} PAPER / REPLAY / BLOCKED rows left out.")
    with st.expander("Old ↔ new section numbers (1961 Act ↔ Income-tax Act 2025)"):
        st.dataframe(india.section_map().to_pandas(), hide_index=True, use_container_width=True)
        st.caption("As printed in Chapter 32 (Sep 2026). Cross-check against the bare Act.")
    _vda(c)
    ui.ai_block(c, "tx_cls", section="Tax", sensitive=True)
    return c


def _vda(c: india.Classified) -> None:
    v = india.vda_ledger(c)
    if v.rows.is_empty():
        return
    st.markdown("**India VDA ledger** — gains and losses kept apart, never netted")
    k = st.columns(4)
    k[0].metric("Gains", money(v.gains, "IN"))
    k[1].metric("Losses (no set-off)", money(v.losses, "IN"))
    k[2].metric("Taxable VDA income", money(v.gains, "IN"))
    k[3].metric("TDS 1% (credit)", money(v.tds, "IN"))
    st.dataframe(v.rows.to_pandas(), hide_index=True, use_container_width=True)
    up = st.file_uploader("Form 26AS / AIS TDS rows (CSV)", type=["csv"], key="tx_tds")
    if st.button("Reconcile TDS", disabled=up is None):
        rec = india.reconcile_tds(v, up.getvalue())
        _mismatch_table(rec)


def _turnover_tab(c: india.Classified | None) -> None:
    if c is None:
        st.caption("Classify first.")
        return
    t = india.turnover(c)
    months = st.number_input("Months in these rows (to annualise for the audit check)", 1, 12,
                             12, key="tx_months")
    opted = st.text_input("Year you opted for s.44AD / s.58, if ever (e.g. 2024-25)",
                          key="tx_opted")
    annual = t.fo["turnover"] * 12 / months + t.speculative["turnover"] * 12 / months
    audit = india.audit_check(annual, presumptive_opted_fy=opted or None,
                              declared_profit=t.fo["net"], deemed_profit=t.deemed_profit)
    ledger = india.CarryForwardLedger.load()
    k = st.columns(3)
    k[0].metric("F&O NET RESULT", money(t.fo["net"], "IN"), help=f"{t.fo['trades']} round trips")
    k[1].metric("F&O TURNOVER (ICAI)", money(t.fo["turnover"], "IN"), help="Σ |P&L| per trade")
    k[2].metric("AUDIT CHECK", audit.status, help=audit.detail)
    k = st.columns(3)
    k[0].metric("PER-CONTRACT VIEW", money(t.per_contract_fo, "IN"),
                help="Zerodha's segment-wise method; use tradewise for filing")
    k[1].metric("s.58 / 44AD STATUS", audit.lock_in.split(":")[0])
    left = sum(e.left for e in ledger.entries)
    k[2].metric("CARRY FORWARD", money(left, "IN"), help="if filed on time")
    st.caption(f"Speculative turnover (kept separate): {money(t.speculative['turnover'], 'IN')} · "
               f"pre-2022 method {money(t.old_method_fo, 'IN')} · notional (NOT turnover) "
               f"{money(t.notional_fo, 'IN')}")
    st.caption(india.presumptive_note(t))
    st.caption(f"Audit thresholds from the dated table (as of {rates.as_of()}; "
               f"₹1 crore limit: {rates.source('india.tax.audit_threshold_inr')}).")
    st.dataframe(t.per_trade.to_pandas(), hide_index=True, use_container_width=True)
    ui.ai_block(t, "tx_turn", section="Tax", sensitive=True)
    _ledger(ledger, c)
    _advance()


def _ledger(ledger: india.CarryForwardLedger, c: india.Classified) -> None:
    st.markdown("**Carry-forward ledger** — one line per year per bucket")
    with st.form("tx_ledger_form"):
        f = st.columns(4)
        fy = f[0].text_input("Tax year (FY)", "2025-26")
        bucket = f[1].selectbox("Bucket", india.LOSS_BUCKETS)
        amount = f[2].number_input("Loss (₹)", 0.0, step=1000.0)
        on_time = f[3].checkbox("Return filed on time", True)
        if st.form_submit_button("Add loss"):
            ledger.add(fy, bucket, amount, on_time)
            ledger.save()
    suggested = india.losses_from(c)
    if suggested and st.button("Add this year's losses from the classified rows"):
        for fy, b, amt in suggested:
            ledger.add(fy, b, amt)
        ledger.save()
    st.dataframe(ledger.rows().to_pandas(), hide_index=True, use_container_width=True)
    st.caption("Speculative: 4 years, speculative profit only · F&O: 8 years · capital: 8 years · "
               "VDA: no set-off, no carry-forward (dated table).")


def _advance() -> None:
    st.markdown("**Advance-tax planner**")
    a = st.columns(3)
    est = a[0].number_input("Your estimated tax for the year (₹)", 0.0, value=60000.0,
                            step=1000.0, key="tx_est")
    fy = a[1].text_input("Tax year", "2026-27", key="tx_fy")
    paid = a[2].number_input("Paid so far (₹)", 0.0, step=1000.0, key="tx_paid")
    plan = india.advance_tax(est, fy, paid)
    st.dataframe(plan.rows.to_pandas(), hide_index=True, use_container_width=True)
    if not plan.due:
        st.caption("Below the advance-tax threshold: not due.")
    ui.ai_block(plan, "tx_adv", section="Tax", sensitive=True)


def _mismatch_table(rec) -> None:
    st.session_state["tx_rec"] = rec
    if rec.mismatches.height:
        st.markdown(f":orange[**{rec.mismatches.height} mismatches**] · {rec.matched.height} "
                    "matched")
        st.dataframe(rec.mismatches.to_pandas().style.set_properties(
            **{"background-color": "#FEF3C7"}), hide_index=True, use_container_width=True)
    else:
        st.success(f"All {rec.matched.height} rows matched.")


def _ais_tab(c: india.Classified | None) -> None:
    broker_up = st.file_uploader("Broker tax P&L (CSV) — or leave empty to use the classified "
                                 "rows", type=["csv"], key="tx_bpnl")
    ais_up = st.file_uploader("AIS or Form 26AS export (CSV)", type=["csv"], key="tx_ais")
    if st.button("Reconcile AIS", disabled=ais_up is None or (broker_up is None and c is None)):
        left = broker_up.getvalue() if broker_up is not None else india.broker_rows(c)
        _mismatch_table(india.reconcile_ais(left, ais_up.getvalue()))
    rec = st.session_state.get("tx_rec")
    if rec is not None:
        ui.ai_block(rec, "tx_ais_ai", section="Tax", sensitive=True)


def _export_tab_in(c: india.Classified | None) -> None:
    fmt = st.radio("Format", ["ITR-shaped CSV"], horizontal=True, key="tx_fmt_in")
    if c is None:
        st.caption("Classify first.")
        return
    fys = sorted(set(c.rows["fy"].drop_nulls().to_list())) if c.rows.height else []
    fy = st.selectbox("Tax year", ["all", *fys], key="tx_exp_fy")
    if st.button("Export", type="primary"):
        st.session_state["tx_itr"] = india.export_itr_csv(c, None if fy == "all" else fy)
    data = st.session_state.get("tx_itr")
    if data:
        st.download_button(f"Download {fmt} (Draft for your CA / CPA)", data,
                           "plugai_itr_draft.csv", "text/csv")
        st.code(data[:1500], language=None)


def _india(t: pl.DataFrame) -> None:
    tabs = st.tabs(["Classify", "Turnover", "AIS check", "Export"])
    with tabs[0]:
        c = _classify_tab(t)
    with tabs[1]:
        _turnover_tab(c)
    with tabs[2]:
        _ais_tab(c)
    with tabs[3]:
        _export_tab_in(c)


# ------------------------------------------------------------------ US
def _accounts(t: pl.DataFrame) -> None:
    st.markdown("**Accounts** — tag each as Taxable, IRA or Spouse")
    with st.form("tx_acct"):
        a = st.columns(3)
        names = sorted(set(t["account"].drop_nulls().to_list())) if t.height else []
        name = a[0].text_input("Account name", names[0] if names else "Taxable")
        kind = a[1].selectbox("Type", us.ACCOUNT_TYPES)
        if st.form_submit_button("Add account"):
            us.add_account(name, kind)
    st.caption(" · ".join(f"{k}: {v}" for k, v in us.account_types().items()) or "No accounts "
               "tagged yet: untagged accounts count as Taxable.")


def _us(t: pl.DataFrame) -> None:
    tabs = st.tabs(["Classify", "Wash sales", "1099-B check", "Export"])
    with tabs[0]:
        _accounts(t)
        if st.button("1256 tagging"):
            st.session_state["tx_1256"] = True
        if st.session_state.get("tx_1256") and t.height:
            tagged = [{"instrument": u, "type": i, **dict(zip(("sec_1256", "reason", "ask_ca"),
                                                          us.tag_1256(u, i)))}
                      for u, i in sorted(set(zip(t["underlying"].to_list(),
                                                 t["instrument"].to_list())))]
            st.dataframe(pl.DataFrame(tagged).to_pandas(), hide_index=True,
                         use_container_width=True)
            st.caption("The IRS publishes no product list: confirm with the 1099-B's "
                       "regulated-futures section.")
    with tabs[1]:
        crypto = st.toggle("Crypto wash-sale check", value=bool(
            rates.us().get("wash_sale_covers_crypto", False)), key="tx_crypto")
        st.caption(f"Default off: rules as of {rates.as_of()} (H.R. 9172 is not law).")
        pairs_txt = st.text_input("Pairs you consider possibly identical (e.g. SPY/VOO, "
                                  "QQQ/QQQM)", key="tx_pairs")
        pairs = [tuple(p.strip().upper() for p in x.split("/")) for x in pairs_txt.split(",")
                 if "/" in x]
        c1, c2 = st.columns(2)
        if c1.button("Wash-sale check", type="primary"):
            st.session_state["tx_wash"] = us.wash_sales(t, crypto=crypto, identical_pairs=pairs)
        if c2.button("Substantially identical warnings"):
            st.session_state["tx_wash"] = us.wash_sales(t, crypto=crypto, identical_pairs=pairs)
        w: us.WashSaleResult | None = st.session_state.get("tx_wash")
        if w is not None:
            st.dataframe(w.hits.to_pandas(), hide_index=True, use_container_width=True)
            if w.warnings.height:
                st.warning("Substantially identical — warnings, never determinations:")
                st.dataframe(w.warnings.to_pandas(), hide_index=True, use_container_width=True)
            ui.ai_block(w, "tx_wash_ai", section="Tax", sensitive=True)
    w = st.session_state.get("tx_wash") or (us.wash_sales(t) if t.height else None)
    f = us.form_8949(w) if w is not None else None
    with tabs[2]:
        up = st.file_uploader("1099-B / 1099-DA (CSV)", type=["csv"], key="tx_1099")
        if st.button("Compare with 1099-B", disabled=up is None or f is None):
            _mismatch_table(us.compare_1099b(f, up.getvalue()))
    with tabs[3]:
        fmt = st.radio("Format", ["8949-shaped CSV"], horizontal=True, key="tx_fmt_us")
        if f is not None and f.rows.height:
            st.dataframe(f.rows.to_pandas(), hide_index=True, use_container_width=True)
            for flag in f.flags:
                st.caption(flag)
        if st.button("Export", type="primary", disabled=f is None, key="tx_exp_us"):
            st.session_state["tx_8949"] = us.export_8949_csv(f)
        data = st.session_state.get("tx_8949")
        if data:
            st.download_button(f"Download {fmt} (Draft for your CA / CPA)", data,
                               "plugai_8949_draft.csv", "text/csv")


def render() -> None:
    ui.page_header("Tax Export", "Tax")
    market = ui.market()
    _draft_banner()
    t = _source_panel(market)
    st.caption(f"{t.height} round trips loaded · rates and rules from the dated table, as of "
               f"{rates.as_of()} · 🔒 Local only")
    ui.dated_note()
    if market == "IN":
        _india(t)
    else:
        _us(t)
    st.caption(f"Every sheet is a {tax.DRAFT}.")
