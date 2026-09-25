"""Links between screens by registry slug (Lessons steps, Home quick links, redirects).

Streamlit identifies a page by its ``url_path`` alone, so a small stand-in Page
with the same slug routes to the real screen registered in ``app/main.py``.
"""

from __future__ import annotations

import os

import streamlit as st

from .registry import SCREENS

TITLES: dict[str, str] = {slug: title for _s, title, _m, _i, slug in SCREENS}
ICONS: dict[str, str] = {slug: icon for _s, _t, _m, icon, slug in SCREENS}
SLUG_OF: dict[str, str] = {title: slug for slug, title in TITLES.items()}
TITLES["home"] = "Home"


def _noop() -> None:  # the registered page does the work; this only carries the slug
    return None


def page(slug: str) -> st.Page:
    return st.Page(_noop, title=TITLES.get(slug, slug), url_path=slug)


def link(slug: str, label: str | None = None, key: str | None = None) -> None:
    """A page link to a screen; falls back to a caption outside the multipage app."""
    label = label or TITLES.get(slug, slug)
    try:
        st.page_link(page(slug), label=label, icon=ICONS.get(slug))
    except Exception:
        st.caption(f"→ {label}")


def go(slug: str) -> None:
    """Switch to a screen now (used by redirects and Send to … buttons)."""
    try:
        st.switch_page(page(slug))
    except st.errors.StreamlitAPIException:
        st.info(f"Open {TITLES.get(slug, slug)} from the sidebar.")


def start_target() -> str | None:
    """Where ``plugai-trade start --page`` or ``plugai-trade lesson N`` asked to open."""
    if os.environ.get("PLUGAI_TRADE_LESSON", "").strip():
        return "lessons"
    slug = os.environ.get("PLUGAI_TRADE_START_PAGE", "").strip().strip("/")
    return slug if slug in TITLES and slug != "home" else None
