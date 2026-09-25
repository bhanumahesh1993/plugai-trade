"""Plugins: AI-written code that lives inside the lab, under the lab's rules (Chapter 27).

    import polars as pl
    from plugai_trade import plugin

    @plugin.report(title="Opening-gap report", markets=("IN", "US"))
    def gap_report(bars: pl.DataFrame, threshold_pct=0.5): ...

A plugin is a folder ``<lab>/plugins/<name>/`` with ``plugin.toml`` (what it may
touch), ``plugin.py`` (the code), ``tests/`` and ``AGENTS.md`` (house rules for
coding agents). ``plugin.new`` creates one from a template; ``plugin.check``
runs the Plugin check. The lab, not the plugin, fetches data, applies costs and
talks to the AI model; plugins run in their own process, never receive keys and
have no order code to call. Strategy plugins only ever see a window that ends at
the last completed bar.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from .. import config
from ..store import default as store
from .check import CheckItem, CheckReport, check
from .host import run
from .templates import AGENTS_MD, CODE, GITIGNORE, MANIFEST, TESTS

KINDS = ("report", "strategy", "screen")
_NAME = re.compile(r"^[a-z][a-z0-9_]{1,40}$")

__all__ = [
    "KINDS",
    "REGISTRY",
    "CheckItem",
    "CheckReport",
    "PluginMeta",
    "check",
    "enable",
    "folder",
    "installed",
    "manifest",
    "new",
    "report",
    "run",
    "sample_bars",
    "screen",
    "status",
    "strategy",
    "window_signals",
]


@dataclass
class PluginMeta:
    """What a decorator records about a plugin function."""

    kind: str
    title: str
    markets: tuple[str, ...]
    func: Callable[..., Any]
    extra: dict[str, Any] = field(default_factory=dict)


REGISTRY: dict[str, PluginMeta] = {}


def _decorator(kind: str, title: str, markets: tuple[str, ...], **extra: Any
               ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
        meta = PluginMeta(kind=kind, title=title, markets=tuple(markets), func=fn, extra=extra)
        fn.__plugai__ = meta  # type: ignore[attr-defined]
        REGISTRY[fn.__name__] = meta
        return fn
    return wrap


def report(title: str, markets: tuple[str, ...] = ("IN", "US"), **extra: Any
           ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Mark ``fn(bars, **params) -> pl.DataFrame`` as a report plugin.

    A report describes sessions that are over, so it may use each day's whole bar.
    """
    return _decorator("report", title, markets, **extra)


def strategy(title: str = "", markets: tuple[str, ...] = ("IN", "US"), **extra: Any
             ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Mark ``fn(bars, **params)`` as a strategy plugin.

    The function returns a signal per row (1 = hold, 0 = flat, or a weight
    0–1). When the lab runs it, the function only ever receives a window ending
    at the last completed bar, and only the window's last value is used
    (:func:`window_signals`); fills happen at the next open in the backtester.
    """
    return _decorator("strategy", title, markets, **extra)


def screen(title: str, markets: tuple[str, ...] = ("IN", "US"), **extra: Any
           ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Mark ``fn(bars, **params) -> pl.DataFrame`` as a screen plugin (a new page's table)."""
    return _decorator("screen", title, markets, **extra)


def _last(value: Any) -> float:
    if isinstance(value, pl.Series):
        value = value[-1] if value.len() else None
    elif isinstance(value, pl.DataFrame):
        value = value[value.columns[-1]][-1] if value.height else None
    return 0.0 if value is None or (isinstance(value, float) and np.isnan(value)) else float(value)


def window_signals(fn: Callable[..., Any], bars: pl.DataFrame, warmup: int = 1,
                   **params: Any) -> pl.DataFrame:
    """Call a strategy with windows that end at each completed bar; keep the last value.

    Row *t* of the result was computed from ``bars[: t + 1]`` only, so a strategy
    cannot see a later bar however it is written.
    """
    out = []
    for t in range(bars.height):
        sig = _last(fn(bars.head(t + 1), **params)) if t + 1 >= warmup else 0.0
        out.append(sig)
    return pl.DataFrame({"date": bars["date"], "signal": out})


def sample_bars(n: int = 300, seed: int = 7, start: float = 100.0) -> pl.DataFrame:
    """Synthetic daily bars for plugin tests (no network, no pattern built in)."""
    rng = np.random.default_rng(seed)
    close = start * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    open_ = np.concatenate([[start], close[:-1]]) * np.exp(rng.normal(0, 0.003, n))
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.006, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.006, n))
    dates = pl.date_range(pl.date(2020, 1, 1), pl.date(2030, 1, 1), "1d", eager=True)
    dates = dates.filter(dates.dt.weekday() <= 5).head(n)
    return pl.DataFrame({"date": dates, "open": open_, "high": high, "low": low, "close": close,
                         "volume": rng.integers(1_000, 5_000, n).astype(float)})


# ---------------------------------------------------------------- folders
def plugins_dir() -> Path:
    p = config.home() / "plugins"
    p.mkdir(parents=True, exist_ok=True)
    return p


def folder(name: str | Path) -> Path:
    """The plugin folder for ``name`` (a name under ``<lab>/plugins`` or a path)."""
    if isinstance(name, Path) or "/" in name or "\\" in name:
        return Path(name)
    return plugins_dir() / name


def manifest(name: str | Path) -> dict[str, Any]:
    """The parsed ``plugin.toml`` (raises FileNotFoundError / tomllib.TOMLDecodeError)."""
    return tomllib.loads((folder(name) / "plugin.toml").read_text(encoding="utf-8"))


def installed() -> list[str]:
    """Names of plugin folders in the lab."""
    return sorted(p.name for p in plugins_dir().iterdir() if (p / "plugin.toml").exists())


def new(name: str, kind: str = "report") -> str:
    """Create ``<lab>/plugins/<name>/`` from the template. Returns a one-line message."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if not _NAME.match(name):
        raise ValueError("a plugin name uses lower-case letters, digits and _ (e.g. gap_report)")
    root = plugins_dir() / name
    if (root / "plugin.toml").exists():
        return f"{root} already exists; nothing changed."
    (root / "tests").mkdir(parents=True, exist_ok=True)
    title = name.replace("_", " ").capitalize()
    pad = " " * max(1, 21 - len(kind))
    (root / "plugin.toml").write_text(MANIFEST.format(name=name, kind=kind, pad=pad), encoding="utf-8")
    (root / "plugin.py").write_text(CODE[kind].format(name=name, title=title), encoding="utf-8")
    (root / "tests" / "test_plugin.py").write_text(TESTS[kind].format(name=name), encoding="utf-8")
    (root / "AGENTS.md").write_text(AGENTS_MD.format(name=name), encoding="utf-8")
    (root / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    store().audit("plugin_new", {"name": name, "kind": kind})
    return (f"Created {kind} plugin {name} in {root}: plugin.toml, plugin.py, tests/, AGENTS.md. "
            f"Next: plugai-trade plugin test {name}")


# ---------------------------------------------------------------- status
def status(name: str) -> dict[str, Any]:
    """Last Plugin check result and whether the plugin is enabled."""
    rows = store().all("plugins", tag=name, limit=1)
    return rows[0] if rows else {"name": name, "passed": False, "enabled": False, "checked": ""}


def enable(name: str, on: bool = True) -> str:
    """Enable a plugin whose last Plugin check passed (disable with ``on=False``)."""
    st = status(name)
    if on and not st.get("passed"):
        return f"{name} cannot be enabled: run the Plugin check until it passes."
    body = {k: v for k, v in st.items() if k not in ("id", "created", "tag")}
    body.update(name=name, enabled=on)
    store().add("plugins", body, tag=name)
    store().audit("plugin_enable", {"name": name, "enabled": on})
    return f"{name} {'enabled' if on else 'disabled'}."
