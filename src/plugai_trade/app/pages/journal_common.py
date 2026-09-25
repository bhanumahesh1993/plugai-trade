"""Helpers shared by the Journal and Tax screens (not a screen itself)."""

from __future__ import annotations

from datetime import date

import pandas as pd
import polars as pl
import streamlit as st

from ... import journal
from ...journal.detectors import RuleCard

LESSON_SAMPLE = {"IN": "kavita", "US": "marcus"}


def money(x: float | None, market: str) -> str:
    """₹12,345 / −$1,234 with a real minus sign."""
    if x is None:
        return "n/a"
    cur = "₹" if market == "IN" else "$"
    return f"{'−' if x < 0 else ''}{cur}{abs(x):,.0f}"


def load_sample_button(market: str, key: str) -> None:
    """Load the Chapter 14 synthetic journal for this market into the session (not the store)."""
    name = LESSON_SAMPLE[market]
    if st.button(f"Load lesson 14 sample ({name.title()}, synthetic)", key=key):
        st.session_state[f"journal_sample_{market}"] = journal.sample(name)
        st.rerun()


def journal_frame(market: str) -> tuple[pl.DataFrame, str]:
    """Saved journal rows for the market, else a loaded lesson sample. (frame, label)."""
    saved = journal.trades(market=market)
    if saved.height:
        return saved, "your journal"
    sample = st.session_state.get(f"journal_sample_{market}")
    if sample is not None:
        return sample, f"lesson 14 sample · {LESSON_SAMPLE[market].title()} · synthetic"
    return saved, ""


def rule_card() -> RuleCard:
    return RuleCard.from_store()


def to_pandas(df: pl.DataFrame) -> pd.DataFrame:
    """Streamlit-friendly copy (lists joined, datetimes kept)."""
    out = df
    for c, t in df.schema.items():
        if isinstance(t, pl.List):
            out = out.with_columns(pl.col(c).list.join(", "))
    return out.to_pandas()


def today() -> str:
    return date.today().isoformat()
