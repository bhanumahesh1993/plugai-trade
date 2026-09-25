"""Research › IPO Dashboard: RHP digest, Subscription, GMP, SME checker, Listing-day plan."""

from __future__ import annotations

import polars as pl
import streamlit as st

from plugai_trade import docdesk, ipo
from plugai_trade.app import ui


def _add_ipo() -> None:
    with st.popover("Add IPO"):
        name = st.text_input("Company")
        board = st.radio("Board", ["Mainboard", "SME"], horizontal=True)
        platform = st.text_input("Platform", "NSE / BSE" if board == "Mainboard" else "NSE Emerge")
        c1, c2, c3 = st.columns(3)
        lo = c1.number_input("Price band low", 0.0, value=100.0)
        hi = c2.number_input("Price band high", 0.0, value=105.0)
        lot = c3.number_input("Lot size", 1, value=140)
        link = st.text_input("RHP link (opens in the Document Desk)")
        if st.button("Add IPO", type="primary") and name:
            ipo.add_ipo(
                ipo.Issue(
                    name=name,
                    board=board,
                    platform=platform,
                    price_low=lo,
                    price_high=hi,
                    lot=int(lot),
                    fresh_shares=0,
                    ofs_shares=0,
                    pre_issue_shares=0,
                    promoter_pre_shares=0,
                    promoter_sell_shares=0,
                    pat_cr=0.0,
                    peer_pe=[],
                    anchor_shares=0,
                    objects_cr={},
                    offered={"Retail": float(lot)},
                ),
                link,
            )
            st.success("Added. Fill the figures from the RHP digest.")


def _rhp_tab(x: ipo.Issue) -> None:
    if st.button("Extract to table", key="ipo_extract"):
        st.session_state["ipo_digest"] = ipo.rhp_digest(x)
    dg: ipo.RHPDigest | None = st.session_state.get("ipo_digest")
    if dg is None or dg.issue.name != x.name:
        st.caption(
            "Runs the RHP digest template in the Document Desk: eight items as quotes with "
            "page chips; tiles computed in code."
        )
        return
    cols = st.columns(4)
    for i, (k, v) in enumerate(dg.tiles.items()):
        cols[i % 4].metric(k, v)
    tile = st.selectbox("See the quote behind a tile", list(dg.tiles))
    st.caption(dg.quote_for(tile))
    st.dataframe(
        pl.DataFrame(
            [{"Item": r.field, "Quote": r.quote or "not found", "Page": r.cite} for r in dg.rows]
        ),
        hide_index=True,
    )
    ui.ai_block(
        dg,
        "ipo_rhp",
        section="Research",
        on_accept=lambda _t: ipo.save_record(x, "rhp_digest", {"tiles": dg.tiles}),
    )


def _subscription_tab(x: ipo.Issue) -> None:
    day = st.select_slider("Day", [1, 2, 3], value=3)
    st.caption(
        "Source: fictional sample bids · anchors shown on their own line, excluded from multiples"
    )
    st.dataframe(pl.DataFrame(ipo.subscription(x, ipo.sample_bids(x, day))), hide_index=True)
    if st.button("Allotment odds"):
        st.session_state["ipo_odds_on"] = True
    if not st.session_state.get("ipo_odds_on"):
        return
    cat = "Retail" if "Retail" in x.offered else list(x.offered)[-1]
    apps = st.number_input(
        "Valid applications (0 = use the lab's estimate)", 0, value=0, step=10000
    )
    n = st.number_input(
        "Applicants",
        1,
        20,
        1,
        help="Genuinely separate investors, each with their own PAN and demat.",
    )
    odds = ipo.allotment_odds(x, apps or None, int(n), cat, min_lots=2 if x.board == "SME" else 1)
    c1, c2, c3 = st.columns(3)
    c1.metric(
        "Chance of a lot" + (" (estimate)" if odds.applications_is_estimate else ""),
        f"{odds.p * 100:.2f}%",
    )
    c2.metric(f"At least one of {odds.applicants}", f"{odds.at_least_one * 100:.2f}%")
    c3.metric("Money blocked", f"₹{odds.money_blocked:,.0f}")
    ui.ai_block(
        odds,
        "ipo_odds",
        section="Research",
        question="Explain why more lots do not mean better odds, quoting the numbers. "
        "Do not suggest how to apply.",
    )


def _gmp_tab() -> None:
    st.error(ipo.GMP_BANNER)
    with st.expander("Show grey-market figures", expanded=False):
        df = st.data_editor(
            pl.DataFrame(
                {"Source": ["Site A", "Site B", "Forwarded message"], "GMP (₹)": [22.0, 35.0, 48.0]}
            ).to_pandas(),
            num_rows="dynamic",
            key="ipo_gmp",
        )
        panel = ipo.gmp_panel(dict(zip(df["Source"], df["GMP (₹)"])))
        st.metric(
            "Spread between sources",
            f"₹{panel['spread']:,.0f}" if panel["spread"] is not None else "—",
        )
        st.caption(panel["note"] + " The AI is told never to use it.")


def _sme_tab(x: ipo.Issue) -> None:
    if x.board != "SME":
        st.caption("Pick an SME issue (NSE Emerge / BSE SME) from IPOs open.")
        return
    st.caption(
        f"{x.platform} · lot {x.lot} · rules as of {ipo.rules()['as_of']} "
        f"({ipo.rules()['sme']['source']})"
    )
    doc = docdesk.sample(x.rhp_sample) if x.rhp_sample else None
    if doc is None:
        st.info("Load this issue's RHP in the Document Desk first.")
        return
    if st.button("Run checks"):
        st.session_state["ipo_sme"] = ipo.sme_checks(doc)
    checks = st.session_state.get("ipo_sme")
    if checks:
        st.dataframe(
            pl.DataFrame(
                [
                    {
                        "Rule": c.rule,
                        "Quoted figure": c.quote or "—",
                        "Page": c.cite,
                        "Status": c.status,
                    }
                    for c in checks
                ]
            ),
            hide_index=True,
        )
        for c in checks:
            if c.status == "not found":
                st.caption(f"{c.rule}: pages searched {', '.join(c.searched)}")
        facts = {c.rule: f"{c.status} — {c.quote} {c.cite}" for c in checks}
        ui.ai_block(
            facts,
            "ipo_sme",
            section="Research",
            on_accept=lambda _t: ipo.save_record(x, "sme_check", {"checks": facts}),
        )
    with st.container(border=True):
        st.markdown("**Liquidity**")
        for k, v in ipo.liquidity(x, doc).items():
            st.markdown(f"- **{k}:** {v}")


def _plan_tab(x: ipo.Issue) -> None:
    shares = st.number_input("Shares allotted", 0, value=x.lot * (2 if x.board == "SME" else 1))
    st.caption(f"Issue price ₹{x.price_high:g} · listing date {x.listing_date or 'not set'}")
    base = pl.DataFrame(
        {
            "Opening vs issue price, %": list(ipo.DEFAULT_SCENARIOS),
            "Your action": [""] * len(ipo.DEFAULT_SCENARIOS),
        }
    )
    ed = st.data_editor(base.to_pandas(), hide_index=True, key="ipo_plan_rows")
    plan = ipo.listing_plan(
        x,
        int(shares),
        tuple(float(v) for v in ed["Opening vs issue price, %"]),
        [str(a or "") for a in ed["Your action"]],
    )
    st.dataframe(
        pl.DataFrame(plan)
        .to_pandas()
        .style.map(
            lambda v: (
                "color: #15803D"
                if isinstance(v, float) and v > 0
                else ("color: #DC2626" if isinstance(v, float) and v < 0 else "")
            ),
            subset=["Change"],
        ),
        hide_index=True,
    )
    st.caption("Values before brokerage, charges and tax. Your actions are your written rules.")
    c1, c2, c3 = st.columns(3)
    if c1.button("Critique"):
        cards = ui.lab_store().all("rule_cards", limit=1)
        st.session_state["ipo_crit"] = ipo.critique(plan, str(cards[0]) if cards else "")
    if c2.button("Lock-in calendar"):
        st.session_state["ipo_lock"] = ipo.lock_in_calendar(x)
        ipo.add_lock_ins_to_alerts(x)
    if c3.button("Save to journal"):
        ipo.save_plan_to_journal(x, int(shares), plan)
        st.success("Saved. A Post-listing review reminder is set for day 30.")
    if st.session_state.get("ipo_crit"):
        st.info(st.session_state["ipo_crit"])
    if st.session_state.get("ipo_lock"):
        st.dataframe(pl.DataFrame(st.session_state["ipo_lock"]), hide_index=True)
        st.caption("Unlock dates added to your plan and proposed in Paper Trading › Alerts.")


def render() -> None:
    ui.page_header(
        "IPO Dashboard",
        "Research",
        "Facts from the RHP with page chips; odds and tiles computed in code.",
    )
    mkt = ui.market()
    if mkt != "IN":
        st.info(
            "The IPO Dashboard follows India's IPO process (ASBA, categories, SME platforms). "
            "Switch the market to IN."
        )
    left, main = st.columns([1, 4])
    with left:
        st.caption("IPOs OPEN")
        issues = ipo.ipos_open()
        pick = st.radio("IPOs open", [i.name for i in issues], label_visibility="collapsed")
        _add_ipo()
    x = next(i for i in issues if i.name == pick)
    with main:
        st.caption(
            f"{x.name} · {x.board} · {x.platform} · ₹{x.price_low:g}–₹{x.price_high:g} · "
            f"lot {x.lot} · open {x.open_date}–{x.close_date} · fictional sample"
        )
        tabs = st.tabs(
            ["RHP digest", "Subscription", "GMP · unofficial", "SME checker", "Listing-day plan"]
        )
        with tabs[0]:
            _rhp_tab(x)
        with tabs[1]:
            _subscription_tab(x)
        with tabs[2]:
            _gmp_tab()
        with tabs[3]:
            _sme_tab(x)
        with tabs[4]:
            _plan_tab(x)
