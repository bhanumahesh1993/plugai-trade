"""Settings › Data Sources.

Three tiers (No signup · Free key · Your broker) with a status dot per source
(filled = working, hollow = not set up), Connect / Save to keychain / Test
connection, + Add key, Live stream and Remind me, the fallback strip per
market, and the Compare sources sub-screen (Chapters 5 and 13).
"""

from __future__ import annotations

from datetime import date, time

import pandas as pd
import streamlit as st

from plugai_trade import config, data, keys
from plugai_trade.app import ui
from plugai_trade.data import brokers, catalog

STRIPS = {"IN": [("IN-eod", "IN · END OF DAY"), ("IN-intraday", "IN · INTRADAY")],
          "US": [("US-eod", "US · END OF DAY"), ("US-intraday", "US · INTRADAY")]}
OTHER_STRIPS = [("FX", "FX"), ("crypto", "CRYPTO")]
COMPARE_DEFAULTS = {"IN": ("NIFTY", "nse_bhavcopy", "yfinance"),
                    "US": ("SPY", "alpaca", "yfinance")}
LICENCE_NOTE = (
    "**Provenance.** Every stored bar carries a tag: its source, when it was fetched, and a "
    "licence class — *public* (SEC EDGAR, FRED, synthetic), *personal-use* (NSE/BSE files, "
    "yfinance, keyed vendors) or *broker* (your broker's API). When the router falls back, the "
    "tag names the source that answered. **Licences.** Downloading for your own analysis is "
    "what free sources are for; passing the data itself to other people is where licences "
    "bite. NSE owns its end-of-day data, so this app ships no NSE prices — `plugai-trade fetch` "
    "downloads them on your machine. Never re-serve personal-use or broker data on a website "
    "or app. SEC EDGAR data is public information and may be shared.")


def _by_tier() -> dict[str, list[data.SourceInfo]]:
    order = list(catalog.LABELS)
    out: dict[str, list[data.SourceInfo]] = {t: [] for t in catalog.TIERS}
    for info in data.sources():
        out.setdefault(info.tier, []).append(info)
    for tier in out:
        out[tier].sort(key=lambda s: order.index(s.name) if s.name in order else 99)
    return out


def _dot(name: str) -> str:
    return "●" if catalog.is_working(name) else "○"


def _expiry_note(name: str) -> str:
    if name != "upstox" or not catalog.is_set_up("upstox"):
        return ""
    from plugai_trade.data import upstox
    exp = upstox.token_expiry()
    if not exp:
        return ""
    left = (exp - date.today()).days
    return f" · token expired {exp}" if left < 0 else f" · token · {left} days left (to {exp})"


# ---------------------------------------------------------------- one source
def _key_form(name: str) -> None:
    url = catalog.CONNECT_URLS.get(name)
    if url:
        st.link_button(f"Open the {catalog.label(name)} page", url)
    st.caption("Paste here — never into a chatbot. Stored in your OS keychain; only the "
               "last four characters are shown.")
    values = {k: st.text_input(lbl, type="password", key=f"ds_{name}_{k}")
              for k, lbl in catalog.KEY_FIELDS[name]}
    if st.button("Save to keychain", key=f"ds_{name}_save", type="primary"):
        try:
            saved = catalog.save_keys(name, values)
        except keys.KeyRefused as exc:
            st.error(str(exc))
            return
        if saved:
            st.success("Saved: " + ", ".join(f"{k} {keys.masked(k)}" for k in saved))
        else:
            st.warning("Nothing to save — paste a value first.")


def _edgar_contact() -> None:
    contact = st.text_input("EDGAR contact (name and email)",
                            value=str(config.get("data.edgar_contact", "") or ""),
                            key="ds_edgar_contact",
                            help="The SEC asks every program to identify itself.")
    if st.button("Save contact", key="ds_edgar_save"):
        config.set_value("data.edgar_contact", contact.strip())
        st.success("Saved. It is sent only to sec.gov, in the User-Agent header.")


def _show_probe(name: str) -> None:
    result: catalog.Probe | None = st.session_state.get(f"ds_probe_{name}")
    if result is None:
        return
    (st.success if result.ok else st.error)(f"{catalog.label(name)}: {result.message}")
    info = next((s for s in data.sources() if s.name == name), None)
    tag = catalog.label(name) + (" · IEX" if name == "alpaca" else "")
    for what, df in result.frames.items():
        if df.height:
            st.caption(f"{what} · tag **{tag}** · licence {info.license_class if info else '-'}")
            st.dataframe(df.tail(3).to_pandas(), hide_index=True, use_container_width=True)
    daily = result.frames.get("Daily")
    if result.ok and info is not None and daily is not None and daily.height:
        ui.set_data_status(data.normalise(daily, name, info.license_class))


def _live_controls(name: str, market: str) -> None:
    live = config.get(f"data.live.{name}", {}) or {}
    on = st.toggle("Live stream", value=bool(live.get("on")), key=f"ds_{name}_live")
    if on != bool(live.get("on")):
        live["on"] = on
        config.set_value(f"data.live.{name}", live)
        any_on = any((config.get(f"data.live.{n}", {}) or {}).get("on")
                     for n in catalog.LIVE_CAPABLE)
        config.set_value("data.live_stream", bool(any_on))
    if on:
        mkt = "US" if name == "alpaca" else "IN"
        watch = list((config.get("watchlists", {}) or {}).get(mkt, []))
        chosen = st.multiselect("Symbols to stream", sorted(set(watch + live.get("symbols", []))),
                                default=live.get("symbols") or watch, accept_new_options=True,
                                key=f"ds_{name}_symbols")
        if chosen != live.get("symbols"):
            config.set_value(f"data.live.{name}", {**live, "on": True, "symbols": chosen})
        if name == "alpaca":
            from plugai_trade.data.alpaca import FREE_STREAM_SYMBOLS
            used = len(chosen)
            st.caption(f"{used} of {FREE_STREAM_SYMBOLS} free IEX symbols used")
            if used > FREE_STREAM_SYMBOLS:
                st.warning("Alpaca's free plan streams at most 30 symbols.")
        st.caption("Outside market hours, Test connection shows the last recorded bar.")
    if brokers.reminder_needed(name):
        saved = config.get(f"data.remind_at.{name}", "08:55")
        when = st.time_input("Remind me", value=time.fromisoformat(saved), key=f"ds_{name}_remind",
                             help="This broker's login expires daily; get a nudge before "
                                  "the open (08:55 IST works for most traders).")
        if when.strftime("%H:%M") != saved:
            config.set_value(f"data.remind_at.{name}", when.strftime("%H:%M"))


def _source_card(info: data.SourceInfo, market: str) -> None:
    name = info.name
    title = f"{_dot(name)} {catalog.label(name)}{_expiry_note(name)}"
    with st.expander(title):
        st.caption(info.description)
        st.caption(f"Needs: {info.needs} · Licence: {info.license_class} · "
                   f"Markets: {', '.join(m for m in info.markets if m != 'ANY')}")
        last = catalog.last_test(name)
        if last:
            st.caption(f"Last test {last.get('at', '')[:16]} UTC: "
                       f"{'working' if last.get('ok') else last.get('message', 'failed')}")
        if name in catalog.KEY_FIELDS:
            if st.button("Connect", key=f"ds_{name}_connect"):
                st.session_state[f"ds_connect_{name}"] = True
            if st.session_state.get(f"ds_connect_{name}"):
                _key_form(name)
        if name == "sec_edgar":
            _edgar_contact()
        if name != "synthetic" and st.button("Test connection", key=f"ds_{name}_test"):
            with st.spinner(f"Asking {catalog.label(name)} for a small sample…"):
                st.session_state[f"ds_probe_{name}"] = catalog.probe(name, market)
        _show_probe(name)
        if name in catalog.LIVE_CAPABLE:
            _live_controls(name, market)


def _add_key() -> None:
    if st.button("+ Add key", key="ds_add_key"):
        st.session_state["ds_add_key_open"] = True
    if not st.session_state.get("ds_add_key_open"):
        return
    name = st.selectbox("Key", list(keys.KNOWN), key="ds_add_key_name")
    value = st.text_input("Value", type="password", key="ds_add_key_value")
    if st.button("Save to keychain", key="ds_add_key_save"):
        if not value.strip():
            st.warning("Paste a value first.")
            return
        try:
            keys.set_key(name, value.strip())
        except keys.KeyRefused as exc:
            st.error(str(exc))
            return
        config.set_value(f"data.saved_on.{name}", date.today().isoformat())
        st.success(f"Saved {name} {keys.masked(name)}")


def _tiers(market: str) -> None:
    groups = _by_tier()
    for tier, col in zip(catalog.TIERS, st.columns(3)):
        with col:
            st.markdown(f"**{tier.upper()}**")
            for info in groups.get(tier, []):
                _source_card(info, market)
            if tier == "Free key":
                _add_key()
            if tier == "Your broker":
                st.caption(f"○ {catalog.PAID_BROKERS} — paid data plans")


# ---------------------------------------------------------------- fallback strip
def _strip_text(key: str, chain: list[str]) -> str:
    names = catalog.STRIP_LABELS if key.startswith("IN") else catalog.LABELS
    shown = [n for n in chain if n in ("cache", "eod_replay") or catalog.is_set_up(n)]
    return " → ".join(names.get(n, n) for n in shown) or "(nothing set up)"


def _reorder(key: str) -> None:
    chain = list(config.get(f"data.fallback.{key}", []) or [])
    if not chain:
        return
    pick = st.selectbox("Source", chain, format_func=catalog.label, key=f"ds_strip_{key}_pick")
    i = chain.index(pick)
    c1, c2, c3, c4 = st.columns(4)
    moved = None
    if c1.button("Move to front", key=f"ds_strip_{key}_front"):
        moved = [pick] + [n for n in chain if n != pick]
    if c2.button("Move up", key=f"ds_strip_{key}_up") and i > 0:
        moved = chain[:i - 1] + [pick, chain[i - 1]] + chain[i + 1:]
    if c3.button("Move down", key=f"ds_strip_{key}_down") and i < len(chain) - 1:
        moved = chain[:i] + [chain[i + 1], pick] + chain[i + 2:]
    if c4.button("Reset", key=f"ds_strip_{key}_reset"):
        moved = list(config.DEFAULTS["data"]["fallback"][key])
    if moved is not None:
        config.set_value(f"data.fallback.{key}", moved)
        st.rerun()


def _fallback_strip(market: str) -> None:
    st.markdown("##### Fallback strip")
    st.caption("The router tries each source from left to right and tags every bar with the "
               "one that answered. Indian intraday never falls back to scraping the NSE site.")
    for key, head in STRIPS.get(market, []) + OTHER_STRIPS:
        st.caption(f"FALLBACK · {head}")
        st.markdown(f"**{_strip_text(key, config.get(f'data.fallback.{key}', []) or [])}**")
        with st.popover("Reorder", use_container_width=False):
            _reorder(key)


# ---------------------------------------------------------------- compare sources
def _compare_view(market: str) -> None:
    if st.button("← Back to Data Sources", key="ds_back"):
        st.session_state["ds_view"] = "sources"
        st.rerun()
    st.markdown("#### Compare sources")
    sym0, a0, b0 = COMPARE_DEFAULTS.get(market, COMPARE_DEFAULTS["IN"])
    names = [s.name for s in data.sources() if market in s.markets or s.name == "synthetic"]
    c1, c2, c3 = st.columns([1.2, 1, 1])
    symbol = c1.text_input("Symbol", value=sym0, key=f"ds_cmp_symbol_{market}").strip().upper()
    start = c2.date_input("From", value=date(2026, 5, 1), key="ds_cmp_from")
    end = c3.date_input("To", value=date(2026, 5, 29), key="ds_cmp_to")
    c4, c5 = st.columns(2)
    src_a = c4.selectbox("Source A", names, index=names.index(a0) if a0 in names else 0,
                         format_func=catalog.label, key=f"ds_cmp_a_{market}")
    src_b = c5.selectbox("Source B", names, index=names.index(b0) if b0 in names else 0,
                         format_func=catalog.label, key=f"ds_cmp_b_{market}")
    if st.button("Run", key="ds_cmp_run", type="primary"):
        try:
            st.session_state["ds_cmp"] = catalog.compare_sources(symbol, market, start, end,
                                                                 src_a, src_b)
        except Exception as exc:  # one source failed: say which, keep the screen alive
            st.session_state.pop("ds_cmp", None)
            st.error(f"Could not load both sources: {exc}")
    result: catalog.SourceComparison | None = st.session_state.get("ds_cmp")
    if result is None:
        return
    _compare_result(result)


def _compare_result(result: catalog.SourceComparison) -> None:
    st.markdown(f"**{result.summary()}**")
    view = result.table.to_pandas()
    event = st.dataframe(
        view.style.apply(lambda r: ["background-color: #FEF3C7" if r["status"] != "ok" else ""]
                         * len(r), axis=1),
        hide_index=True, use_container_width=True, on_select="rerun",
        selection_mode="single-row", key="ds_cmp_table")
    rows = getattr(getattr(event, "selection", None), "rows", []) or []
    if rows:
        day = pd.Timestamp(view.iloc[rows[0]]["date"]).date()
        prov = result.provenance(day)
        for side, src in (("A", result.source_a), ("B", result.source_b)):
            p = prov[side]
            st.caption(f"Source {side} · {catalog.label(src)}: " + (
                f"close {p['close']} · {p['source']} · fetched {p['fetched_at']} · "
                f"{p['license_class']}" if p else "no bar on this date"))
    ui.ai_block(result, "ds_cmp_ai", section="Research",
                question="Describe the likely cause of each flagged row (missing session, stale "
                         "value, adjustment) using only these facts. Do not calculate anything.")
    if st.button("Save to journal", key="ds_cmp_save"):
        ui.lab_store().add("journal", {
            "kind": "data-check", "date": date.today().isoformat(),
            "title": f"Compare sources: {result.symbol} "
                     f"{catalog.label(result.source_a)} vs {catalog.label(result.source_b)}",
            "text": result.summary(), "facts": result.facts()}, tag="data-check")
        st.success("Saved to your journal with today's date.")


# ---------------------------------------------------------------- page
def render() -> None:
    ui.page_header("Data Sources", "Settings")
    market = ui.market()
    if st.session_state.get("ds_view") == "compare":
        _compare_view(market)
        return
    c1, c2 = st.columns([3, 1])
    c1.caption("Status dots: ● working · ○ not set up. Synthetic always works offline; the "
               "no-signup sources for your market are added automatically.")
    if c2.button("Compare sources", key="ds_compare"):
        st.session_state["ds_view"] = "compare"
        st.rerun()
    _tiers(market)
    st.divider()
    _fallback_strip(market)
    with st.expander("Provenance and licences"):
        st.markdown(LICENCE_NOTE)
