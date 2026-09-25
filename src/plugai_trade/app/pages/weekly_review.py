"""Journal › Weekly Review: tiles vs last week, Rule breaks, 'not yet a rule', narration."""

from __future__ import annotations

from datetime import date

import altair as alt
import polars as pl
import streamlit as st

from plugai_trade import journal
from plugai_trade.app import ui
from plugai_trade.app.pages.journal_common import journal_frame, load_sample_button, rule_card
from plugai_trade.journal import review as rv
from plugai_trade.journal.detectors import n_label
from plugai_trade.store import default as store


def _account_filter(t: pl.DataFrame, choice: str) -> pl.DataFrame:
    sim = journal.detectors.simulated_mask()
    if choice == "Real":
        return t.filter(~sim)
    if choice == "Paper":
        return t.filter(sim)
    return t


def _tiles(r: rv.WeeklyReview) -> None:
    cols = st.columns(6)
    for col, tile in zip(cols, r.tiles()):
        col.metric(tile["label"], tile["value"])
        col.caption(f"{tile['sub']} · {tile['last']} · {tile['q']}")


def _breaks(r: rv.WeeklyReview, e: pl.DataFrame) -> None:
    st.markdown(f"**Rule breaks** · vs Rule Card {r.card.version}")
    any_break = False
    for f in r.rule_breaks:
        if not f.n:
            continue
        any_break = True
        with st.expander(f"{f.label} — rows {', '.join(map(str, f.rows))} · {f.total_r:+.2f}R"):
            for row in f.rows:
                ids = [row - 1, row] if row - 1 in e["trade_id"].to_list() else [row]
                st.dataframe(e.filter(pl.col("trade_id").is_in(ids)).select(
                    "trade_id", "entry_time", "exit_time", "side", "r", "gap_minutes",
                    "rules_broken").to_pandas(), hide_index=True, use_container_width=True)
            st.caption(f.query)
    if not any_break:
        st.caption("No Rule Card line broken this week.")
    st.markdown("**Detector · not yet a rule**")
    for f in r.patterns:
        if f.n:
            st.markdown(f"- {f.label}: rows {', '.join(map(str, f.rows))} · {f.total_r:+.2f}R "
                        f"· _{n_label(f.n)}_")


def _r_bars(e: pl.DataFrame, r: rv.WeeklyReview) -> None:
    w = e.filter(pl.col("date").is_between(pl.lit(r.start), pl.lit(r.end)))
    if w.is_empty():
        return
    df = w.select("trade_id", "r", "broke_rule").to_pandas()
    ch = alt.Chart(df).mark_bar().encode(
        x=alt.X("trade_id:O", title="row"), y=alt.Y("r:Q", title="R"),
        color=alt.condition("datum.r >= 0", alt.value("#15803D"), alt.value("#DC2626")),
        stroke=alt.condition("datum.broke_rule", alt.value("#0F172A"), alt.value(None)))
    st.markdown(f"**R per trade** · rows {df['trade_id'].min()}–{df['trade_id'].max()}")
    st.altair_chart(ch, use_container_width=True)


def _accept_change(text: str, week: str) -> None:
    """Accept: the one change becomes the Rule Card's next version, dated."""
    change = st.session_state.get("wr_change", "").strip()
    if not change:
        return
    rows = store().all("rule_cards", limit=1)
    body = {k: v for k, v in (rows[0] if rows else {}).items() if k not in ("id", "created", "tag")}
    key = next((k for k in ("rules", "lines", "written_rules") if isinstance(body.get(k), list)),
               "lines")
    lines = list(body.get(key, []))
    lines.append(change if all(isinstance(x, str) for x in lines)
                 else {"text": change, "date": date.today().isoformat()})
    body[key] = lines
    v = body.get("version")
    body["version"] = v + 1 if isinstance(v, int) else (len(store().all("rule_cards")) + 1)
    body.update({"changed_on": date.today().isoformat(), "change_source": f"Weekly Review {week}"})
    store().add("rule_cards", body)
    st.session_state["wr_decision"] = change


def render() -> None:
    ui.page_header("Weekly Review", "Journal")
    market = ui.market()
    t, label = journal_frame(market)
    if t.is_empty():
        st.info("No journal rows yet. Import a tradebook in Journal › Trades, or load the "
                "lesson sample.")
        load_sample_button(market, "wr_sample")
        return
    c1, c2 = st.columns(2)
    last_day = date.fromisoformat(str(t["date"].max()))
    week_of = c1.date_input("Week of", last_day, key="wr_week")
    acct = c2.segmented_control("Account", ["Real", "Paper", "Both"], default="Both",
                                key="wr_acct") or "Both"
    t = _account_filter(t, acct)
    card = rule_card()
    r = rv.build(t, week_of.isoformat(), card, rv.pinned_specs())
    st.caption(f"{label} · week {r.start} – {r.end} · Rule Card {card.version} · 🔒 LOCAL")
    if r.last_decision:
        st.info(f"Last week you decided: {r.last_decision}")
    st.caption("If the trade count or gross total does not match your broker, stop here and "
               "fix the import in Journal › Trades.")
    _tiles(r)
    e = journal.detectors.enrich(t, card)
    left, right = st.columns([1, 1])
    with left:
        _breaks(r, e)
    with right:
        _r_bars(e, r)
    for a in r.pinned:
        st.markdown(f"**Pinned:** {a.spec.label} — {a.text}")
    b1, b2, b3 = st.columns(3)
    if b1.button("Generate review", type="primary"):
        st.session_state["wr_ai_exp"] = rv.generate(r)
    if b2.button("Show query"):
        st.session_state["wr_showq"] = not st.session_state.get("wr_showq", False)
    if st.session_state.get("wr_showq"):
        st.code("\n\n".join(f"-- {k}\n{v}" for k, v in r.queries.items()), language="sql")
    st.text_input("One change for next week (a Rule Card line or checklist item)",
                  key="wr_change")
    ui.ai_block(r, "wr_ai", section="Journal", sensitive=True,
                on_accept=lambda text: _accept_change(text, r.start))
    if b3.button("Save review"):
        exp = st.session_state.get("wr_ai_exp")
        rv.save(r, exp.text if exp else "", st.session_state.get("wr_decision")
                or st.session_state.get("wr_change", ""))
        st.success("Review saved with its tiles, narration and decision.")
