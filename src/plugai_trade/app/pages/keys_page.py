"""Settings › Keys.

Add key / Save / Remove. Keys live in the operating-system keychain (Keychain
on macOS, Credential Manager on Windows, Secret Service on Linux); only the last
four characters are ever shown. Exchange keys that can trade or withdraw are
refused — the lab only reads (Chapters 4 and 25).
"""

from __future__ import annotations

import streamlit as st

from plugai_trade import keys
from plugai_trade.app import ui

OTHER = "Other…"
PERMISSIONS = ["read", "trade", "withdraw", "transfer"]


def _stored() -> None:
    names = keys.listed()
    if not names:
        st.info("No keys saved yet. Everything in the lab works without them.")
        return
    for name in names:
        c1, c2, c3 = st.columns([2, 1.2, 0.8])
        c1.markdown(f"`{name}`")
        c2.markdown(keys.masked(name))
        if c3.button("Remove", key=f"keys_rm_{name}"):
            keys.remove_key(name)
            st.success(f"Removed {name} from the keychain.")
            st.rerun()


def _add_form() -> None:
    choice = st.selectbox("Key", [*keys.KNOWN, OTHER], key="keys_name")
    name = (st.text_input("Key name", key="keys_custom").strip().lower().replace(" ", "_")
            if choice == OTHER else choice)
    value = st.text_input("Value", type="password", key="keys_value",
                          help="Paste it here only — never into a chatbot or a file.")
    perms = st.multiselect("Permissions this key has", PERMISSIONS, default=["read"],
                           key="keys_perms",
                           help="For exchange keys, tick exactly what the provider's page shows.")
    if st.button("Save", key="keys_save", type="primary"):
        if not name or not value.strip():
            st.warning("Choose a key name and paste a value.")
            return
        try:
            keys.set_key(name, value.strip(), permissions=perms)
        except keys.KeyRefused as exc:
            st.error(str(exc) + " Create a read-only key on the provider's site instead.")
            return
        st.session_state["keys_add_open"] = False
        st.success(f"Saved {name} {keys.masked(name)} to the OS keychain.")


def render() -> None:
    ui.page_header("Keys", "Settings")
    st.caption("Stored in your operating system's keychain, never in files or chats. "
               "Only the last four characters are shown. Backups never include keys.")
    if not keys.keychain_ok():
        st.error("No OS keychain found — keys cannot be saved on this machine.")
    _stored()
    if st.button("Add key", key="keys_add"):
        st.session_state["keys_add_open"] = True
    if st.session_state.get("keys_add_open"):
        _add_form()
    st.caption("Exchange keys with trade, withdraw or transfer permission are refused: "
               "PlugAI-Trade only reads.")
