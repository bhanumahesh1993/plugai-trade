"""Paper Trading › Paper Desk — a simulated account. Paper only: no real orders, ever.

    from plugai_trade import paper
    desk = paper.PaperDesk(market="IN", starting_balance=1_500_000, mode="REPLAY")
    o = desk.place_paper_order("NIFTY FUT", "buy", 65, kind="stop", price=24850, stop=24700)
    for bar in bars.iter_rows(named=True):
        desk.on_bar("NIFTY FUT", bar)      # fills only on bars after the paper order

Round trips are written to the journal tagged PAPER or REPLAY; blocked paper
orders are logged tagged BLOCKED.
"""

from __future__ import annotations

from .drift import (
    DriftReport,
    ShadowUnavailable,
    drift_report,
    paper_rows_for_drift,
    run_shadow,
    shadow_trades,
)
from .engine import PaperDesk, PaperOrder, PaperOrderBlocked, PaperPosition
from .instruments import CostPreview, Instrument, cost_preview, default_symbols, instrument
from .pending import accept, draft_pending, hand_ticket, load_ticket, pending, reject, ticket_used
from .replay import SPEEDS, Replay, live_status, session_bars

JOURNAL_TAGS = ("PAPER", "REPLAY", "PILOT", "BLOCKED")

__all__ = [
    "JOURNAL_TAGS",
    "SPEEDS",
    "CostPreview",
    "DriftReport",
    "Instrument",
    "PaperDesk",
    "PaperOrder",
    "PaperOrderBlocked",
    "PaperPosition",
    "Replay",
    "ShadowUnavailable",
    "accept",
    "cost_preview",
    "default_symbols",
    "draft_pending",
    "drift_report",
    "hand_ticket",
    "instrument",
    "live_status",
    "load_ticket",
    "paper_rows_for_drift",
    "pending",
    "reject",
    "run_shadow",
    "session_bars",
    "shadow_trades",
    "ticket_used",
]
