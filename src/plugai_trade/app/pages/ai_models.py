"""Settings › AI Models (Chapters 2, 4 and 31).

Local (Ollama) and Cloud (your keys) sections with the Default marker; Test model
(speed and prompt reading time); Pull model with the Fit check bar; Context
length; Add local server (LM Studio at http://localhost:1234/v1); Add cloud
model; Drafting vs Journal and portfolio model; "Use for" routing per sidebar
section (Local only / Cloud allowed; Tax and Documents default Local only);
Monthly budget (cloud calls pause at it); Embeddings with its own Pull model.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from plugai_trade import ai, config, keys, privacy, wizard
from plugai_trade.app import ui
from plugai_trade.app.registry import SECTIONS

POLICIES = ("Local only", "Cloud allowed")
ROUTED = tuple(s for s in SECTIONS if s not in ("Lessons", "Settings")) + ("Documents",)
CONTEXTS = (2048, 4096, 8192, 16384, 32768)
PROVIDERS = {"Gemini": "gemini", "Groq": "groq", "OpenRouter": "openrouter", "OpenAI": "openai",
             "Anthropic": "anthropic", "DeepSeek": "deepseek"}
LM_STUDIO = "http://localhost:1234/v1"


def _badge(where: str) -> str:
    return "🔒 Local" if where == "Local" else "☁ Cloud"


def _local() -> None:
    st.markdown("#### Local (Ollama)")
    default = config.get("ai.local_model")
    names = list(dict.fromkeys([default, *wizard.installed_models()]))
    rows = [{"Model": n, "Where": _badge("Local"), "Default": "Default" if n == default else ""}
            for n in names]
    rows += [{"Model": url, "Where": _badge("Local") + " · local server", "Default": ""}
             for url in config.get("ai.local_servers", []) or []]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    if not wizard.ollama_reachable():
        st.caption("Ollama not found: start the Ollama app (or `ollama serve`), then reload.")
    pick = st.selectbox("Default local model", names, index=0, key="aim_default")
    if pick != default and st.button("Set as Default", key="aim_set_default"):
        wizard.set_local_model(pick)
        st.rerun()
    if st.button("Test model", key="aim_test"):
        st.session_state["aim_test_res"] = wizard.test_model(pick)
    res: wizard.ModelTest | None = st.session_state.get("aim_test_res")
    if res is not None:
        (st.success if res.ok else st.warning)(" · ".join(res.facts()))
    with st.expander("Add local server"):
        url = st.text_input("Server address (OpenAI-compatible)", LM_STUDIO, key="aim_server")
        if st.button("Add local server", key="aim_add_server") and url.strip():
            servers = list(dict.fromkeys([*(config.get("ai.local_servers", []) or []), url.strip()]))
            config.set_value("ai.local_servers", servers)
            st.success(f"Added {url.strip()} — marked {_badge('Local')}.")


def _pull_and_fit(ram: float | None) -> None:
    st.markdown("#### Pull model · Fit check")
    ctx = st.select_slider("Context length", CONTEXTS,
                           value=int(config.get("ai.context_length", 8192)), key="aim_ctx",
                           format_func=lambda x: f"{x // 1024}k")
    if ctx != config.get("ai.context_length"):
        config.set_value("ai.context_length", int(ctx))
    for m in wizard.MODELS:
        fit = wizard.fit_check(m, int(ctx), ram=ram)
        dot = {"green": "🟢", "amber": "🟠", "red": "🔴"}[fit.colour]
        st.progress(min(1.0, fit.share),
                    text=f"{dot} {m.label} · {m.tag} · {fit.facts()[-1]}")
    st.caption("An estimate: model file + context scratchpad + what your system already uses.")
    labels = [f"{m.label} · {m.tag}" for m in wizard.MODELS]
    choice = st.selectbox("Model size", labels, index=wizard.MODELS.index(wizard.suggest(ram)),
                          key="aim_pull_pick")
    if st.button("Pull model", key="aim_pull"):
        _pull(wizard.MODELS[labels.index(choice)].tag, set_default=True)


def _pull(tag: str, set_default: bool) -> None:
    bar = st.progress(0.0, text=f"Pulling {tag}…")
    try:
        for p in wizard.pull_model(tag):
            bar.progress(p.fraction, text=f"{tag}: {p.status}")
    except Exception as exc:
        st.error(f"Pull model did not finish: {exc}. Start Ollama and click Pull model again; "
                 "it resumes.")
        return
    if set_default:
        wizard.set_local_model(tag)
    st.success(f"{tag} is ready.")


def _cloud() -> None:
    st.markdown("#### Cloud (your keys)")
    clouds = list(config.get("ai.cloud_models", []) or [])
    if not clouds:
        st.caption("No cloud model. Nothing in the book needs one.")
    for m in clouds:
        c1, c2 = st.columns([4, 1])
        c1.markdown(f"`{m}` · {_badge('Cloud')}")
        if c2.button("Remove", key=f"aim_rm_{m}"):
            config.set_value("ai.cloud_models", [x for x in clouds if x != m])
            st.rerun()
    with st.expander("Add cloud model"):
        prov = st.selectbox("Provider", list(PROVIDERS), key="aim_prov")
        name = st.text_input("Model name (as the provider lists it)", key="aim_cloud_name",
                             placeholder="e.g. gemini-flash")
        key_name = f"{PROVIDERS[prov]}_api_key"
        st.caption(f"Key: {keys.masked(key_name)} (add it in Settings › Keys)")
        if st.button("Add cloud model", key="aim_add_cloud") and name.strip():
            if not keys.get_key(key_name):
                st.warning(f"No {prov} key in the keychain yet; add it in Settings › Keys first.")
            else:
                full = f"{PROVIDERS[prov]}/{name.strip()}"
                config.set_value("ai.cloud_models", list(dict.fromkeys([*clouds, full])))
                st.success(f"Added {full} — marked {_badge('Cloud')}.")


def _roles() -> None:
    st.markdown("#### Which model does which job")
    local = config.get("ai.local_model")
    locals_ = list(dict.fromkeys([local, *wizard.installed_models()]))
    clouds = list(config.get("ai.cloud_models", []) or [])
    draft_opts = locals_ + clouds
    cur = config.get("ai.drafting_model") or local
    d = st.selectbox("Drafting", draft_opts, index=draft_opts.index(cur) if cur in draft_opts
                     else 0, key="aim_draft")
    j_cur = config.get("ai.journal_model") or local
    j = st.selectbox("Journal and portfolio (local only)", locals_,
                     index=locals_.index(j_cur) if j_cur in locals_ else 0, key="aim_journal")
    if st.button("Save models", key="aim_save_roles"):
        config.set_value("ai.drafting_model", "" if d == local else d)
        config.set_value("ai.journal_model", "" if j == local else j)
        st.success("Saved.")


def _use_for() -> None:
    st.markdown("#### Use for")
    use = dict(config.get("ai.use_for", {}) or {})
    forced = set(privacy.local_only_sections())
    cols = st.columns(3)
    changed = {}
    for i, sec in enumerate(ROUTED):
        cur = "Local only" if sec in forced else use.get(sec, "Local only")
        with cols[i % 3]:
            val = st.radio(sec, POLICIES, index=POLICIES.index(cur), key=f"aim_use_{sec}",
                           horizontal=True, disabled=sec in forced,
                           help="Kept Local only by Settings › Privacy" if sec in forced else None)
        if val != use.get(sec):
            changed[sec] = val
    if changed:
        config.set_value("ai.use_for", {**use, **changed})
    st.caption("Sections set to Local only never reach the privacy gate at all.")


def _budget() -> None:
    st.markdown("#### Monthly budget")
    s = ai.status()
    cur = "₹" if ui.market() == "IN" else "$"
    b = st.number_input(f"Monthly budget for cloud calls (cost meter counts in {cur}; stored as "
                        "USD)", min_value=0.0, value=float(config.get("ai.monthly_budget", 5.0)),
                        step=1.0, key="aim_budget")
    if b != config.get("ai.monthly_budget"):
        config.set_value("ai.monthly_budget", float(b))
    st.progress(min(1.0, s["spend_this_month"] / b) if b else 0.0,
                text=f"This month ${s['spend_this_month']:.2f} of ${b:.2f} · cloud calls pause "
                     "at the limit and fall back to the local model")


def _embeddings() -> None:
    st.markdown("#### Embeddings")
    emb = st.text_input("Embedding model (Document Desk search by meaning)",
                        config.get("ai.embedding_model", wizard.EMBEDDING.tag), key="aim_emb")
    if emb != config.get("ai.embedding_model"):
        config.set_value("ai.embedding_model", emb)
    st.caption(f"Small default: {wizard.EMBEDDING.tag} ≈ {wizard.EMBEDDING.download_gb:g} GB.")
    if st.button("Pull model", key="aim_pull_emb"):
        _pull(emb, set_default=False)


def render() -> None:
    ui.page_header("AI Models", "Settings",
                   caption="The model explains numbers; code computes them.")
    ram, free = wizard.ram_gb(), wizard.free_ram_gb()
    st.caption(f"Memory: {ram:.0f} GB total" if ram else "Memory: unknown")
    if free is not None:
        st.caption(f"Free right now: {free:.1f} GB")
    _local()
    _pull_and_fit(ram)
    _cloud()
    _roles()
    _use_for()
    _budget()
    _embeddings()
