"""Automate › News Pipeline (Chapter 28): collect, stamp, score, measure."""

from __future__ import annotations

from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from plugai_trade import config, costs, news
from plugai_trade.app import ui
from plugai_trade.news import feeds, scoring
from plugai_trade.store import default as store

SECTION = "Automate"
INDEXES = {"IN": ["NIFTY", "SENSEX", "BANKNIFTY"], "US": ["SPY", "QQQ", "DIA"]}
SCORER_NAMES = {"finbert": "FinBERT", "llm": "Local model"}
RULES = ("Leave disagreements out of tests", "Use FinBERT's label", "Use the Local model's label",
         "Mark as unclear and read by hand")


def _heads_table(df) -> pd.DataFrame:
    out = df.select("source", "symbol", "headline", "original", "lang", "published", "seen",
                    "tradable_from").to_pandas()
    out["original"] = [o if lg != "en" else "" for o, lg in zip(out["original"], out["lang"])]
    return out.rename(columns={"source": "Source", "symbol": "Symbol", "headline": "Headline",
                               "original": "Original (Hindi)", "lang": "Lang",
                               "published": "Published", "seen": "Seen",
                               "tradable_from": "Tradable from"})


def _sources_tab(mkt: str) -> None:
    st.caption("Tick the feeds you want. Stamping happens before scoring: every row gets "
               "Published, Seen and Tradable from, in IST or ET.")
    chosen = [src for src, (label, m) in news.SOURCES.items()
              if m in (mkt, "ANY") and st.checkbox(label, value=True, key=f"np_src_{mkt}_{src}")]
    extra = st.text_input("Any other RSS feed (optional)", key=f"np_rss_{mkt}",
                          placeholder="https://publisher.example/business.rss")
    if extra.strip():
        chosen.append(f"rss:{extra.strip()}")
    watch = (config.get("watchlists", {}) or {}).get(mkt, [])
    st.multiselect("Match watchlists", watch, default=watch, key=f"np_watch_{mkt}")
    if "sec-8k" in chosen and "@" not in str(config.get("data.edgar_contact", "") or ""):
        c1, c2 = st.columns([3, 1])
        contact = c1.text_input("EDGAR contact (name and email, sent in the User-Agent)",
                                key="np_edgar_contact", placeholder="Asha Rao asha@example.com")
        if c2.button("Save contact", key="np_save_contact") and "@" in contact:
            config.set_value("data.edgar_contact", contact.strip())
            st.success("Saved. SEC EDGAR requests now carry your contact.")
    c1, c2 = st.columns(2)
    start = c1.date_input("From", value=date.today() - timedelta(days=30), key=f"np_from_{mkt}")
    end = c2.date_input("To", value=date.today(), key=f"np_to_{mkt}")
    if st.button("Fetch now", key="np_fetch", type="primary", disabled=not chosen):
        with st.spinner("Collecting and stamping…"):
            st.session_state[f"np_heads_{mkt}"] = news.fetch(chosen, market=mkt, start=start,
                                                             end=end)
        st.session_state.pop(f"np_scored_{mkt}", None)
        st.session_state.pop(f"np_cmp_{mkt}", None)
    for src, msg in news.last_status().items():
        st.caption(f"● {src}: {msg}")
    heads = st.session_state.get(f"np_heads_{mkt}")
    if heads is None:
        st.info("Click Fetch now. Offline, the lab uses a bundled synthetic set of headlines "
                "about fictional companies (Kaveri Pumps, Lakeshore Devices …).")
        return
    st.markdown(f"**{heads.height} stamped headlines**")
    st.dataframe(_heads_table(heads), hide_index=True, use_container_width=True, height=320)
    tray = news.unstamped(mkt)
    with st.expander(f"Unstamped · {tray.height} rows (never scored)"):
        if tray.height:
            st.dataframe(tray.to_pandas(), hide_index=True, use_container_width=True)
        else:
            st.caption("Rows without a usable time, and same-story duplicates, land here.")


def _score_tab(mkt: str) -> None:
    heads = st.session_state.get(f"np_heads_{mkt}")
    if heads is None or not heads.height:
        st.info("Fetch headlines in the Sources tab first.")
        return
    c1, c2 = st.columns(2)
    use_fb = c1.checkbox("FinBERT", value=True, key="np_use_fb")
    c1.caption("FinBERT (transformers)" if scoring.finbert_available() else
               "transformers not installed → Loughran–McDonald-style word list, labelled")
    use_llm = c2.checkbox("Local model", value=True, key="np_use_llm")
    c2.caption("JSON labels at temperature 0; with no model reachable, phrase rules, labelled")
    if st.button("Score", key="np_score", type="primary", disabled=not (use_fb or use_llm)):
        scored = {}
        with st.spinner("Scoring…"):
            for key, on in (("finbert", use_fb), ("llm", use_llm)):
                if on:
                    scored[key] = news.score(heads, scorer=key)
        st.session_state[f"np_scored_{mkt}"] = scored
        st.session_state.pop(f"np_cmp_{mkt}", None)
    scored = st.session_state.get(f"np_scored_{mkt}") or {}
    if not scored:
        return
    base = next(iter(scored.values()))
    view = base.select("symbol", "headline", "original", "lang").to_pandas()
    view["original"] = [o if lg != "en" else "" for o, lg in zip(view["original"], view["lang"])]
    for key, df in scored.items():
        view[SCORER_NAMES[key]] = df["label"].to_list()
        view[f"{SCORER_NAMES[key]} path"] = df["path"].to_list()
        st.caption(f"{SCORER_NAMES[key]}: {df['scorer_used'][0]}")
    st.dataframe(view, hide_index=True, use_container_width=True, height=280)
    if st.button("Compare scorers", key="np_compare", disabled=len(scored) < 2):
        st.session_state[f"np_cmp_{mkt}"] = news.compare(scored["finbert"], scored["llm"])
    cmp = st.session_state.get(f"np_cmp_{mkt}")
    if cmp is None:
        return
    st.markdown(f"**Agreement {cmp.agreement:.0%}** on {cmp.n} headlines · "
                f"{cmp.opposite()} opposite labels (read these first)")
    st.dataframe(cmp.table().to_pandas(), hide_index=True, use_container_width=True)
    st.dataframe(cmp.disagreements().to_pandas(), hide_index=True, use_container_width=True,
                 height=260)
    rule = st.radio("Your rule for disagreements", RULES, key="np_rule")
    note = st.text_input("Why (optional)", key="np_rule_note")
    if st.button("Save rule", key="np_save_rule"):
        store().add("notes", {"kind": "news disagreement rule", "rule": rule, "note": note,
                              "market": mkt, "agreement": round(cmp.agreement, 3)},
                    tag="news-rule")
        st.success("Rule saved. Apply it to every headline, before any event study.")
    ui.ai_block(cmp, key="np_cmp_ai", section=SECTION,
                question="Explain what this agreement table says and which rows to read first.")


def _events(mkt: str, group: str):
    cmp = st.session_state.get(f"np_cmp_{mkt}")
    if cmp is None:
        return None
    return cmp.agreed(group.split()[-1])


def _chart(es) -> None:
    df = es.path.to_pandas()
    for c in ("car", "lo", "hi"):
        df[c] = df[c] * 100
    band = alt.Chart(df).mark_area(opacity=0.18, color="#0EA5E9").encode(
        x=alt.X("day:Q", title="sessions relative to day 0"),
        y=alt.Y("lo:Q", title="average cumulative abnormal return (%)"), y2="hi:Q")
    line = alt.Chart(df).mark_line(color="#0369A1", point=True).encode(x="day:Q", y="car:Q")
    zero = alt.Chart(pd.DataFrame({"day": [0]})).mark_rule(strokeDash=[4, 3],
                                                             color="#64748B").encode(x="day:Q")
    st.altair_chart(ui.hypothetical_chart(alt.layer(band, line, zero).properties(height=280)),
                    use_container_width=True)


def _event_tab(mkt: str) -> None:
    if st.session_state.get(f"np_cmp_{mkt}") is None:
        st.info("Score with both scorers and click Compare scorers first: the event groups are "
                "the headlines both scorers agreed on.")
        return
    c1, c2 = st.columns(2)
    group = c1.selectbox("Event group", ["Both agreed: positive", "Both agreed: negative"],
                         key="np_group")
    window = c2.slider("Window (sessions)", -10, 20, (-5, 10), key="np_window")
    c3, c4, c5 = st.columns(3)
    bench = c3.selectbox("Index", INDEXES[mkt], key=f"np_bench_{mkt}")
    presets = [p for p in costs.PROFILES if p.startswith(mkt)]
    preset = c4.selectbox("Cost preset", presets, key=f"np_cost_{mkt}")
    entry = c5.radio("Day 0", ["tradable_from", "published_date"], key="np_entry",
                     format_func=lambda x: "Tradable from" if x == "tradable_from"
                     else "Published date (date-only join)")
    if st.button("Run event study", key="np_run_es", type="primary"):
        ev = _events(mkt, group)
        with st.spinner("Computing in code…"):
            st.session_state[f"np_es_{mkt}"] = news.event_study(
                ev, window=window, benchmark=bench, entry=entry, costs=preset)
    es = st.session_state.get(f"np_es_{mkt}")
    if es is None:
        return
    m1, m2, m3 = st.columns(3)
    m1.metric("Events", es.n)
    m2.metric("Day 0 average", f"{es.day0():+.2f}%")
    m3.metric("Trials", es.trials, help="Every variant you try is counted (Chapter 11).")
    _chart(es)
    st.markdown("**Cost table** — average drift-window result per event (day 0 close → "
                "day +2 close). HYPOTHETICAL; before taxes.")
    st.dataframe(es.cost_table().drop("cost_bps").to_pandas(), hide_index=True,
                 use_container_width=True)
    if es.skipped:
        st.caption("Skipped: " + "; ".join(es.skipped[:5]))
    ui.ai_block(es, key="np_es_ai", section=SECTION,
                question="Explain this event study in plain English, quoting the table, and list "
                         "how the result could still mislead.")


def render() -> None:
    ui.page_header("News Pipeline", SECTION,
                   "Collect → stamp → score → measure. The model never sees prices; nothing here "
                   "places an order.")
    mkt = ui.market()
    sources, score, study = st.tabs(["Sources", "Score", "Event study"])
    with sources:
        _sources_tab(mkt)
    with score:
        _score_tab(mkt)
    with study:
        _event_tab(mkt)
    st.caption(f"GDELT: about one request every {feeds.GDELT_INTERVAL:.0f} s · store headline, "
               "time and link, not full articles.")
