"""Research › Document Desk."""

from __future__ import annotations

import streamlit as st

from plugai_trade.app import ui


def render() -> None:
    ui.page_header("Document Desk", "Research")
    ui.todo(["Screen under construction."])
