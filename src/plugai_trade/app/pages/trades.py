"""Journal › Trades: Import tradebook, Match plans, Accept, tags, R-multiples, Replay."""

from __future__ import annotations

import altair as alt
import pandas as pd
import polars as pl
import streamlit as st

from plugai_trade import ai, journal
from plugai_trade.app import ui
from plugai_trade.app.pages.journal_common import (journal_frame, load_sample_button, money,
                                                   rule_card, to_pandas)
from plugai_trade.journal import importers

PENDING = "trades_pending"


def _broker_choices(market: str) -> list[str]:
    brokers = journal.INDIA_BROKERS if market == "IN" else journal.US_BROKERS
    return [*brokers, "Generic CSV"]


def _mapper(data: bytes) -> dict[str, str]:
    """Generic CSV column mapper: pick which of your columns holds each field."""
    rows, _ = importers.read_rows(data)
    header = [""] + list(rows[0].keys())
    st.caption("Generic CSV: map your columns (time, symbol, side, qty and price are required).")
    cols = st.columns(5)
    mapping = {}
    for i, f in enumerate(importers.GENERIC_FIELDS):
        guess = f if f in header else ""
        mapping[f] = cols[i % 5].selectbox(f, header, index=header.index(guess), key=f"map_{f}")
    return mapping


def _import_panel(market: str) -> None:
    with st.expander("Import tradebook", expanded=st.session_state.get(PENDING) is None):
        c1, c2 = st.columns(2)
        broker = c1.selectbox("Broker", _broker_choices(market), key="tr_broker")
        account = c2.text_input("Account name", "Main", key="tr_account")
        up = st.file_uploader("Tradebook CSV (strip client ID, PAN / SSN first)", type=["csv"],
                              key="tr_file")
        mapping = _mapper(up.getvalue()) if up is not None and broker == "Generic CSV" else None
        st.download_button("Generic CSV template", importers.generic_template(),
                           "plugai_generic_tradebook.csv", "text/csv")
        paper = st.checkbox("These are PAPER trades", key="tr_paper")
        if st.button("Import tradebook", type="primary", disabled=up is None):
            try:
                res = journal.import_tradebook(up.getvalue(), broker, account, mapping, market,
                                               tags=["PAPER"] if paper else None)
            except importers.ImportError_ as exc:
                st.error(str(exc))
                return
            st.session_state[PENDING] = res
            st.rerun()


def _pending_panel(market: str) -> None:
    res: journal.ImportResult | None = st.session_state.get(PENDING)
    if res is None:
        return
    t = res.trades
    st.markdown(f"**Import from {res.broker}** — {res.fills} fills → {t.height} round trips · "
                f"{res.unpaired.height} fills could not be paired (open positions)")
    gross, charges = float(t["gross"].sum() or 0), float(t["charges"].sum() or 0)
    c = st.columns(4)
    c[0].metric("Round trips", t.height)
    c[1].metric("Gross P&L", money(gross, market))
    c[2].metric("Charges", money(charges, market))
    c[3].metric("Net", money(gross - charges, market))
    st.caption("Compare these totals with your broker's P&L statement for the same dates. "
               "Charges marked 'cost table' were priced from the dated reference.")
    ui.dated_note()
    if st.button("Match plans"):
        matched, unmatched = journal.match_plans(t)
        res.trades, res.unmatched_plans = matched, unmatched
        st.session_state[PENDING] = res
    if res.unmatched_plans:
        st.warning(f"{len(res.unmatched_plans)} trades have no planned stop. Type the stop "
                   "(points per unit) in the table to get their R.")
    edited = st.data_editor(
        to_pandas(res.trades.select("trade_id", "date", "symbol", "side", "qty", "entry_price",
                                    "exit_price", "gross", "charges", "charges_source",
                                    "stop_distance", "r_multiple", "setup", "tags", "source")),
        disabled=["trade_id", "date", "symbol", "side", "qty", "entry_price", "exit_price",
                  "gross", "charges", "charges_source", "r_multiple", "source"],
        key="tr_pending_editor", hide_index=True, use_container_width=True)
    c1, c2 = st.columns(2)
    if c1.button("Accept", type="primary"):
        final = _apply_edits(res.trades, edited)
        n = journal.save(final)
        st.session_state.pop(PENDING, None)
        st.success(f"Locked {n} round trips into the journal.")
    if c2.button("Discard import"):
        st.session_state.pop(PENDING, None)
        st.rerun()


def _apply_edits(t: pl.DataFrame, edited: pd.DataFrame) -> pl.DataFrame:
    stops = dict(zip(edited["trade_id"], edited["stop_distance"]))
    setups = dict(zip(edited["trade_id"], edited["setup"]))
    tags = dict(zip(edited["trade_id"], edited["tags"]))
    out = t.with_columns(
        stop_distance=pl.col("trade_id").map_elements(
            lambda i: None if pd.isna(stops.get(i)) else float(stops.get(i)),
            return_dtype=pl.Float64),
        setup=pl.col("trade_id").map_elements(
            lambda i: None if pd.isna(setups.get(i)) else str(setups.get(i)), return_dtype=pl.Utf8),
        tags=pl.col("trade_id").map_elements(
            lambda i: [x.strip() for x in str(tags.get(i) or "").split(",") if x.strip()],
            return_dtype=pl.List(pl.Utf8)))
    return journal.with_r(out)


def _journal_panel(market: str) -> None:
    t, label = journal_frame(market)
    if t.is_empty():
        st.info("No trades yet. Import a tradebook above, or load the lesson sample.")
        load_sample_button(market, "tr_sample")
        return
    st.caption(f"Showing {label}.")
    show_paper = st.toggle("Show PAPER / REPLAY / BLOCKED rows", value=True, key="tr_show_paper")
    view = t if show_paper else t.filter(~journal.detectors.simulated_mask())
    gross, charges = float(view["gross"].sum() or 0), float(view["charges"].sum() or 0)
    c = st.columns(5)
    c[0].metric("Round trips", view.height)
    c[1].metric("Gross", money(gross, market))
    c[2].metric("Charges", money(charges, market))
    c[3].metric("Net", money(gross - charges, market))
    c[4].metric("Total R", f"{float(view['r_multiple'].sum() or 0):+.2f}R")
    edited = st.data_editor(
        to_pandas(view.select("trade_id", "date", "entry_time", "exit_time", "symbol", "side",
                              "qty", "entry_price", "exit_price", "gross", "charges", "net",
                              "stop_distance", "r_multiple", "setup", "tags", "account")),
        disabled=["trade_id", "date", "entry_time", "exit_time", "symbol", "side", "qty",
                  "entry_price", "exit_price", "gross", "charges", "net", "r_multiple",
                  "account"], key="tr_journal_editor", hide_index=True, use_container_width=True)
    saved = label == "your journal"
    if st.button("Save tags", disabled=not saved,
                 help="Tags: setup, mistake, market mood, PAPER / PILOT"):
        for r in edited.itertuples():
            tags = [x.strip() for x in str(r.tags or "").split(",") if x.strip()]
            stop = None if pd.isna(r.stop_distance) else float(r.stop_distance)
            journal.set_tags(int(r.trade_id), tags,
                             None if pd.isna(r.setup) else str(r.setup), stop)
        st.success("Tags saved.")
    _r_chart(view)
    _replay(view, market)


def _r_chart(t: pl.DataFrame) -> None:
    rep = journal.detect(t, rule_card())
    h = rep.histogram.to_pandas()
    if h.empty:
        return
    st.markdown("**R-multiples** (bins of 0.5R, before charges)")
    ch = alt.Chart(h).mark_bar().encode(
        x=alt.X("bin:O", title="R"), y=alt.Y("n:Q", title="trades"),
        color=alt.condition("datum.bin < 0", alt.value("#DC2626"), alt.value("#15803D")))
    st.altair_chart(ch, use_container_width=True)
    st.caption(f"{rep.beyond_stop.text()} · average winner {rep.avg_winner_r}R")


def _replay(t: pl.DataFrame, market: str) -> None:
    st.markdown("**Replay a session**")
    days = sorted(set(t["date"].to_list()), reverse=True)
    day = st.selectbox("Session", days, key="tr_replay_day")
    if st.button("Replay"):
        rep = journal.replay.session(t, day, rule_card())
        st.session_state["tr_replay"] = rep
        st.session_state["paper_replay_request"] = rep.handoff(speed=5)
    rep = st.session_state.get("tr_replay")
    if rep is None:
        return
    st.info(f"Session {rep.day} sent to Paper Trading › Paper Desk in Replay mode at 5× "
            "(tag REPLAY).")
    if rep.trades.height:
        df = rep.trades.select("trade_id", "entry_time", "exit_time", "entry_price",
                               "exit_price", "r").to_pandas()
        pts = pd.concat([
            df.rename(columns={"entry_time": "time", "entry_price": "price"})
              .assign(kind="entry")[["trade_id", "time", "price", "kind"]],
            df.rename(columns={"exit_time": "time", "exit_price": "price"})
              .assign(kind="exit")[["trade_id", "time", "price", "kind"]]])
        ch = alt.Chart(pts).mark_point(filled=True, size=70).encode(
            x=alt.X("time:T", title=None), y=alt.Y("price:Q", scale=alt.Scale(zero=False)),
            color="kind:N", tooltip=["trade_id", "kind", "price"])
        st.altair_chart(ui.hypothetical_chart(ch), use_container_width=True)
    if st.button("Generate review"):
        st.session_state["tr_rev_exp"] = ai.explain(
            rep, "Review this session from the numbers only; cite rows; end with one question.",
            section="Journal", sensitive=True)
    ui.ai_block(rep, "tr_rev", section="Journal", sensitive=True)


def render() -> None:
    ui.page_header("Trades", "Journal")
    market = ui.market()
    st.caption("🔒 Journal data stays local: AI calls here use the local model only.")
    _import_panel(market)
    _pending_panel(market)
    st.divider()
    _journal_panel(market)
