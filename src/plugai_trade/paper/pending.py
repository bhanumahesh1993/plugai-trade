"""Pending paper orders: drafted elsewhere, applied only by your click.

Other screens (Trade Plan › Send to Paper Desk, Alerts › Attach paper order,
Options/Pairs › Send to Paper Desk) and the MCP ``paper_order`` tool write a row
to the store table ``paper_orders`` with tag ``pending``. The Paper Desk lists
them; nothing becomes even a paper position until you click Accept.
"""

from __future__ import annotations

from typing import Any

from ..store import default as store
from .engine import ENTRY_KINDS

FIELDS = ("symbol", "market", "side", "qty", "kind", "price", "stop", "target", "plan_id",
          "risk_money")


def draft_pending(order: dict[str, Any], source: str) -> int:
    """Create a pending paper order (never a fill). Returns its row id."""
    body = {k: order.get(k) for k in FIELDS}
    body["kind"] = body.get("kind") or "market"
    body["side"] = (body.get("side") or "buy").lower()
    body["source"] = source
    body["status"] = "PENDING"
    body["note"] = order.get("note", "")
    if not body.get("symbol") or not body.get("qty"):
        raise ValueError("A pending paper order needs a symbol and a quantity.")
    return store().add("paper_orders", body, tag="pending")


def pending(market: str | None = None) -> list[dict[str, Any]]:
    rows = store().all("paper_orders", tag="pending")
    return [r for r in rows if market is None or (r.get("market") or market) == market]


def _set(row_id: int, tag: str, **extra: Any) -> dict[str, Any]:
    st = store()
    row = st.get("paper_orders", row_id)
    if row is None:
        raise KeyError(f"No paper order {row_id}")
    body = {k: v for k, v in row.items() if k not in ("id", "created", "tag")}
    body.update(status=tag.upper(), **extra)
    st.update("paper_orders", row_id, body, tag=tag)
    return body


def accept(row_id: int, desk: Any) -> Any:
    """Accept a pending paper order: it goes through the desk's guardrails like any ticket.

    Multi-leg strategies (e.g. from the Options Strategy Builder) are marked accepted for
    tracking and return ``None``: the bar fill model simulates single contracts only.
    """
    row = store().get("paper_orders", row_id)
    if row is None or row.get("tag") != "pending":
        raise KeyError(f"Paper order {row_id} is not pending")
    if not row.get("symbol") or not row.get("qty") or row.get("kind") not in (None, *ENTRY_KINDS):
        _set(row_id, "accepted", reason="strategy accepted for tracking; the bar fill model "
                                        "simulates single-contract paper orders only")
        return None
    o = desk.place_paper_order(
        symbol=row["symbol"], side=row.get("side", "buy"), qty=int(row["qty"]),
        kind=row.get("kind") or "market", price=row.get("price"), stop=row.get("stop"),
        target=row.get("target"), plan_id=row.get("plan_id"), risk_money=row.get("risk_money"),
        source=row.get("source", "pending"))
    _set(row_id, "blocked" if o.status == "BLOCKED" else "accepted", desk_order=o.id,
         reason=o.reason)
    return o


def reject(row_id: int, reason: str = "") -> None:
    _set(row_id, "rejected", reason=reason)


def cancel_all_pending(reason: str) -> int:
    rows = pending()
    for r in rows:
        _set(r["id"], "cancelled", reason=reason)
    return len(rows)


def load_ticket() -> dict[str, Any] | None:
    """The latest ticket handed over by Trade Plan › Send to Paper Desk (not yet used)."""
    rows = store().all("paper_orders", tag="ticket", limit=1)
    return rows[0] if rows else None


def hand_ticket(order: dict[str, Any], source: str) -> int:
    """Prefill the Paper Desk ticket (the trader still clicks Place paper order)."""
    body = {k: order.get(k) for k in FIELDS}
    body.update(source=source, status="TICKET")
    return store().add("paper_orders", body, tag="ticket")


def ticket_used(row_id: int) -> None:
    _set(row_id, "ticket-used")
