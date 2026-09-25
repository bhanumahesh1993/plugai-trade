"""Tax records (Chapter 32): classify, add up and reconcile in code; always a draft.

    from plugai_trade import journal, tax
    c = tax.india.classify(journal.sample("meera"))
    t = tax.india.turnover(c)          # ICAI: Σ |P&L| per trade → ₹39,585
    w = tax.us.wash_sales(journal.sample("dan"))

Rates come only from the dated reference (``tax.rates``). Every export is stamped
"Draft for your CA / CPA"; rows the rules cannot place are flagged ASK CA. Tax AI
calls use ``sensitive=True`` so they stay on the local model.
"""

from __future__ import annotations

from . import india, rates, reconcile, us

DRAFT = "Draft for your CA / CPA"
ASK_CA = "ASK CA"

__all__ = ["india", "us", "rates", "reconcile", "DRAFT", "ASK_CA"]
