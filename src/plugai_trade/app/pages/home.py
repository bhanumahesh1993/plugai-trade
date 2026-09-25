"""Home: the first-run wizard (Chapter 4), then the dashboard.

Wizard buttons as printed: Next, Check again, Pull model, Skip for now, Load
sample data, Run self-test, Copy diagnostic, Open dashboard. After the wizard,
the dashboard shows the sample watchlists (IN NIFTY / BANKNIFTY / SENSEX, US
SPY / QQQ / DIA), the session clock in IST and ET, pinned screens from Settings ›
Workspace and quick links. ``plugai-trade lesson N`` and ``start --page`` land
here first and are redirected once per session.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import polars as pl
import streamlit as st

from plugai_trade import config, keys, reference, wizard, workspace
from plugai_trade.app import nav, ui

QUICK = ("briefing", "lessons", "prompts", "paper-desk", "trades", "ai-models", "security")


# ---------------------------------------------------------------- redirect
def _redirect() -> None:
    if st.session_state.get("_start_redirect_done"):
        return
    st.session_state["_start_redirect_done"] = True
    target = nav.start_target()
    if target:
        nav.go(target)


# ---------------------------------------------------------------- wizard screens
def _goto(n: int) -> None:
    st.session_state["wiz_step"] = wizard.set_step(n)
    st.rerun()


def _nav_row(n: int, next_label: str = "Next") -> None:
    c1, c2, _ = st.columns([1, 1, 4])
    if n > 0 and c1.button("Back", key=f"wiz_back_{n}"):
        _goto(n - 1)
    if next_label and c2.button(next_label, key=f"wiz_next_{n}", type="primary"):
        _goto(n + 1)


def _screen_machine() -> None:
    m = st.session_state.get("wiz_machine") or wizard.check_machine()
    st.session_state["wiz_machine"] = m
    for line in m.lines():
        st.markdown(f"- {line}")
    if not m.ollama:
        st.warning("Ollama not found. Ollama is a free app (MIT licence) that runs AI models on "
                   "your own computer. Install it like any other app, then click Check again.")
        st.link_button("Download Ollama", wizard.OLLAMA_DOWNLOAD)
    if st.button("Check again", key="wiz_check_again"):
        st.session_state["wiz_machine"] = wizard.check_machine()
        st.rerun()
    st.caption(f"Ollama address: {wizard.ollama_host()} (set OLLAMA_HOST for Docker).")
    _nav_row(0)


def _screen_model() -> None:
    m = st.session_state.get("wiz_machine") or wizard.check_machine()
    st.dataframe(pd.DataFrame([{"Your RAM": r, "Suggested local model": x.label,
                                "Download": f"≈ {x.download_gb:g} GB", "Good for": x.good_for}
                               for r, x in zip(("8 GB or less", "16 GB", "32 GB or more"),
                                               wizard.MODELS)]),
                 hide_index=True, width="stretch")
    sug = m.suggestion
    labels = [f"{x.label} · {x.tag}" for x in wizard.MODELS]
    pick = st.radio("Model to pull", labels, index=wizard.MODELS.index(sug), key="wiz_model")
    model = wizard.MODELS[labels.index(pick)]
    st.caption(f"Suggested for {m.ram_gb:.0f} GB RAM: {sug.label}." if m.ram_gb else
               "RAM unknown: the 9B default is suggested.")
    fit = wizard.fit_check(model, int(config.get("ai.context_length", 8192)), ram=m.ram_gb)
    st.progress(min(1.0, fit.share), text=f"Fit check · {fit.facts()[-1]}")
    if st.button("Pull model", key="wiz_pull", type="primary"):
        _pull(model.tag)
    _nav_row(1)


def _pull(tag: str) -> None:
    bar = st.progress(0.0, text=f"Pulling {tag}…")
    try:
        for p in wizard.pull_model(tag):
            bar.progress(p.fraction, text=f"{tag}: {p.status}")
        wizard.set_local_model(tag)
        st.success(f"{tag} is ready and set as the Default local model.")
    except Exception as exc:  # network, Ollama missing, disk full: say it plainly
        st.error(f"Pull model did not finish: {exc}. Start Ollama, then click Pull model again; "
                 "it resumes. On a slow link choose the smaller model first.")


def _screen_cloud() -> None:
    st.write("A cloud key is optional: nothing in the book needs one. Keys go to your operating "
             "system's keychain, never to a file.")
    prov = st.selectbox("Provider", wizard.CLOUD_PROVIDERS, key="wiz_provider")
    val = st.text_input("Key", type="password", key="wiz_key")
    if st.button("Save key", key="wiz_save_key") and val.strip():
        name = f"{prov.lower()}_api_key"
        try:
            keys.set_key(name, val.strip())
            st.success(f"Saved {prov} key {keys.masked(name)} to the keychain.")
        except Exception as exc:
            st.error(f"The keychain refused the key: {exc}")
    nav.link("keys", "Or open Settings › Keys")
    c1, c2, c3, _ = st.columns([1, 1.2, 1, 3])
    if c1.button("Back", key="wiz_back_2"):
        _goto(1)
    if c2.button("Skip for now", key="wiz_skip"):
        _goto(3)
    if c3.button("Next", key="wiz_next_2", type="primary"):
        _goto(3)


def _screen_sample() -> None:
    mkt = st.radio("Which market do you trade?", ["IN", "US"], horizontal=True,
                   index=["IN", "US"].index(ui.market()), key="wiz_market")
    if st.button("Load sample data", key="wiz_load", type="primary"):
        st.session_state["market"] = mkt
        st.session_state["wiz_loaded"] = wizard.load_sample_data(mkt)
    loaded = st.session_state.get("wiz_loaded")
    if loaded:
        st.success(f"Synthetic sample loaded for {loaded.market}.")
        for f in loaded.facts():
            st.markdown(f"- {f}")
    _nav_row(3)


def _screen_selftest() -> None:
    mkt = ui.market()
    if st.button("Run self-test", key="wiz_run", type="primary"):
        st.session_state["wiz_test"] = wizard.self_test(mkt)
    res: wizard.SelfTest | None = st.session_state.get("wiz_test")
    if res is not None:
        for c in res.checks:
            (st.success if c.passed else st.error)(f"{'✓' if c.passed else '✗'} {c.name} — "
                                                   f"{c.detail}")
        st.caption(f"Took {res.seconds:.1f} s.")
        if not res.passed:
            if st.button("Check again", key="wiz_retest"):
                st.session_state["wiz_test"] = wizard.self_test(mkt)
                st.rerun()
            if st.button("Copy diagnostic", key="wiz_diag"):
                st.session_state["wiz_diag_text"] = wizard.diagnostic(res)
    if st.session_state.get("wiz_diag_text"):
        st.caption("Copy with the icon at the top right. No keys or journal rows are included.")
        st.code(st.session_state["wiz_diag_text"], language=None)
    c1, c2, _ = st.columns([1, 1.4, 3])
    if c1.button("Back", key="wiz_back_4"):
        _goto(3)
    if c2.button("Open dashboard", key="wiz_open", type="primary"):
        wizard.mark_done()
        st.session_state.pop("wiz_step", None)
        st.rerun()


_SCREENS = (_screen_machine, _screen_model, _screen_cloud, _screen_sample, _screen_selftest)


def _wizard() -> None:
    n = st.session_state.setdefault("wiz_step", wizard.step())
    st.markdown(f"#### First-run wizard · screen {n + 1} of {len(wizard.STEPS)}: "
                f"{wizard.STEPS[n]}")
    st.progress((n + 1) / len(wizard.STEPS))
    _SCREENS[n]()


# ---------------------------------------------------------------- dashboard
def session_clock(now: datetime | None = None) -> list[dict[str, str]]:
    """Both sessions from the dated reference tables, with open/closed now."""
    now = now or datetime.now(ZoneInfo("UTC"))
    out = []
    for mkt, zone in (("IN", "IST"), ("US", "ET")):
        s = reference.lookup(f"{'india' if mkt == 'IN' else 'us'}.sessions.cash") or {}
        local = now.astimezone(ZoneInfo(s.get("tz", "UTC")))
        hm = local.strftime("%H:%M")
        is_open = local.weekday() < 5 and s.get("open", "") <= hm < s.get("close", "")
        out.append({"Market": mkt, "Session": f"{s.get('open')}–{s.get('close')} {zone}",
                    "Now": f"{local:%a %H:%M} {zone}", "Status": "open" if is_open else "closed"})
    return out


def watchlist_table(market: str) -> pl.DataFrame:
    """Sample watchlist with last close and day change, computed in code."""
    rows = []
    for s in config.get(f"watchlists.{market}") or config.DEFAULTS["watchlists"][market]:
        df = wizard.sample_bars(s, market)
        last, prev = float(df["close"][-1]), float(df["close"][-2])
        rows.append({"Symbol": s, "Last close": round(last, 2), "Change": round(last - prev, 2),
                     "Change %": round((last / prev - 1) * 100, 2), "Date": str(df["date"][-1]),
                     "Source": df["source"][-1]})
    return pl.DataFrame(rows)


def _dashboard() -> None:
    mkt = ui.market()
    st.dataframe(pd.DataFrame(session_clock()), hide_index=True, width="stretch")
    c1, c2 = st.columns([1.3, 1])
    with c1:
        st.markdown(f"##### Sample watchlist · {mkt}")
        st.dataframe(watchlist_table(mkt), hide_index=True, width="stretch")
        sym = "NIFTY" if mkt == "IN" else "SPY"
        df = wizard.sample_bars(sym, mkt)
        ui.set_data_status(df)
        ui.line_chart(df.select("date", "close").to_pandas(), "date", "close",
                      title=f"{sym} · synthetic sample")
        other = "US" if mkt == "IN" else "IN"
        with st.expander(f"Sample watchlist · {other}"):
            st.dataframe(watchlist_table(other), hide_index=True, width="stretch")
    with c2:
        st.markdown("##### Pinned screens")
        pins = workspace.pinned()
        if not pins:
            st.caption("None yet. Settings › Workspace › Apply template pins the screens for your "
                       "style.")
        for title in pins:
            if title in nav.SLUG_OF:
                nav.link(nav.SLUG_OF[title])
        st.markdown("##### Quick links")
        for slug in QUICK:
            nav.link(slug)
        test = config.get("wizard.self_test") or {}
        if test:
            st.caption("Self-test: passed ✓" if test.get("passed") else
                       f"Self-test: failed ({', '.join(test.get('failed', []))})")
        if st.button("Run the first-run wizard again", key="home_rerun_wizard"):
            wizard.mark_done(False)
            st.session_state["wiz_step"] = wizard.set_step(0)
            st.rerun()
    ui.paper_only_note()


def render() -> None:
    ui.page_header("PlugAI-Trade", "Today", caption="Research, plan, paper-trade and review. "
                   "Paper only: it never places real orders.")
    _redirect()
    if wizard.is_done():
        _dashboard()
    else:
        _wizard()
