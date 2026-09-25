"""Streamlit entry point: `plugai-trade start` runs this file on localhost:8501."""

from __future__ import annotations

import importlib

import streamlit as st

from plugai_trade import __version__
from plugai_trade.app.registry import SCREENS

st.set_page_config(page_title="PlugAI-Trade", page_icon=":material/insights:", layout="wide")


def _runner(module: str):
    def run() -> None:
        mod = importlib.import_module(f"plugai_trade.app.pages.{module}")
        mod.render()
    run.__name__ = f"page_{module}"
    return run


def _home() -> None:
    importlib.import_module("plugai_trade.app.pages.home").render()


pages: dict[str, list] = {"": [st.Page(_home, title="Home", icon=":material/home:",
                                       url_path="home", default=True)]}
for section, title, module, icon, slug in SCREENS:
    pages.setdefault(section, []).append(st.Page(_runner(module), title=title, icon=icon,
                                                 url_path=slug))

nav = st.navigation(pages)
with st.sidebar:
    st.caption(f"PlugAI-Trade {__version__} · paper only · never places real orders")
nav.run()
