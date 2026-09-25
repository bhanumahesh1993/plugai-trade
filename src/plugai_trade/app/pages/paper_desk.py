"""Paper Trading › Paper Desk."""

from __future__ import annotations

import streamlit as st

from plugai_trade.app import ui


def render() -> None:
    ui.page_header("Paper Desk", "Paper Trading")
    ui.todo(["Screen under construction."])
