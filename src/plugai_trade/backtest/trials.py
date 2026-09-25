"""The trial counter (Chapter 11, check 5): every distinct variant you test is counted.

Trials live in the store table ``trials`` tagged with the strategy *family* (the
idea, not its settings). Re-running an identical spec does not add a trial;
changing any setting that changes the result does. Agent and plugin runs count
exactly like yours.
"""

from __future__ import annotations

from typing import Any

from ..store import default as store


def record(family: str, digest: str, sharpe: float, sharpe_daily: float, n_obs: int,
           detail: dict[str, Any] | None = None) -> int:
    """Add one trial unless this exact variant was already counted. Returns the family count."""
    st = store()
    if not any(r.get("digest") == digest for r in st.all("trials", tag=family)):
        st.add("trials", {"family": family, "digest": digest, "sharpe": sharpe,
                          "sharpe_daily": sharpe_daily, "n_obs": n_obs, **(detail or {})},
               tag=family)
    return count(family)


def count(family: str) -> int:
    """Number of distinct variants tried in this family (0 if none)."""
    return store().count("trials", tag=family)


def sharpes(family: str) -> list[float]:
    """Per-period (daily) Sharpe ratios of every trial in the family, for the deflated score."""
    return [float(r["sharpe_daily"]) for r in store().all("trials", tag=family)
            if r.get("sharpe_daily") is not None]


def reset(family: str) -> int:
    """Delete a family's trials (lessons only: *Reset lesson*). Returns rows removed."""
    st = store()
    rows = st.all("trials", tag=family)
    for r in rows:
        st.delete("trials", r["id"])
    return len(rows)
