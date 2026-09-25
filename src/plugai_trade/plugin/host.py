"""The plugin host: runs a checked plugin in its own process, with no keys.

The lab (this process) fetches the bars and applies costs; the child process
only imports ``plugin.py`` and computes. Strategy plugins are called through
:func:`plugai_trade.plugin.window_signals`, so each signal is computed from a
window that ends at the last completed bar; the backtester then fills at the
next open with costs on.

    python -m plugai_trade.plugin.host <folder> <bars.parquet> <out.parquet> '<params json>'
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from ..store import default as store

PROFILE = {"IN": "IN-equity-delivery", "US": "US-equity"}


@dataclass
class RunResult:
    """What a plugin run produced: a table, and for strategies a HYPOTHETICAL backtest."""

    name: str
    kind: str
    table: pl.DataFrame
    bars: pl.DataFrame
    backtest: Any = None

    def facts(self) -> list[str]:
        from ..ai import facts_from
        out = [f"Plugin {self.name} ({self.kind}) returned {self.table.height} rows"]
        out += facts_from(self.table)[1:]
        if self.backtest is not None:
            out += list(self.backtest.facts())
        return out


class SignalStrategy:
    """Backtester adapter: reads a precomputed window signal for the current bar."""

    def __init__(self, signals: pl.DataFrame, symbol: str):
        self.symbol = symbol
        self.by_date = dict(zip(signals["date"].to_list(), signals["signal"].to_list()))

    def decide(self, views: dict[str, Any], state: Any) -> dict[str, float] | None:
        w = float(self.by_date.get(views[self.symbol].today, 0.0) or 0.0)
        return {self.symbol: max(0.0, min(1.0, w))}


def _load(root: Path) -> tuple[Any, dict[str, Any]]:
    import tomllib
    man = tomllib.loads((root / "plugin.toml").read_text())
    file, _, func = str(man["entry"]).partition(":")
    sys.path.insert(0, str(root.parent))
    spec = importlib.util.spec_from_file_location(f"{root.name}.plugin", root / file)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[spec.name] = mod  # type: ignore[union-attr]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return getattr(mod, func), man


def child(root: Path, bars_path: Path, out_path: Path, params: dict[str, Any]) -> None:
    """Runs inside the plugin process."""
    from . import window_signals
    fn, man = _load(root)
    bars = pl.read_parquet(bars_path)
    if man["kind"] == "strategy":
        out = window_signals(fn, bars, **params)
    else:
        out = fn(bars, **params)
        if not isinstance(out, pl.DataFrame):
            out = pl.DataFrame(out)
    out.write_parquet(out_path)


def run(name: str, symbol: str = "NIFTY", market: str = "IN", start: str | None = None,
        end: str | None = None, bars: pl.DataFrame | None = None,
        params: dict[str, Any] | None = None, timeout: int = 180,
        require_check: bool = True) -> RunResult:
    """Run a plugin that passed the Plugin check, in its own process, on lab-supplied bars."""
    from . import folder, manifest, status
    from .check import safe_env
    root = folder(name)
    if require_check and not status(root.name).get("passed"):
        raise PermissionError(f"{root.name} has not passed the Plugin check; run the check first.")
    man = manifest(root)
    if market not in man.get("markets", []):
        raise ValueError(f"{root.name} declares markets {man.get('markets')}, not {market}")
    if bars is None:
        from .. import data
        bars = data.get(symbol, market=market, start=start, end=end)
    clean = bars.select([c for c in ("date", "open", "high", "low", "close", "volume")
                         if c in bars.columns])
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "bars.parquet", Path(tmp) / "out.parquet"
        clean.write_parquet(src)
        proc = subprocess.run(
            [sys.executable, "-m", "plugai_trade.plugin.host", str(root), str(src), str(dst),
             json.dumps(params or {})],
            env=safe_env(root.parent), capture_output=True, text=True, timeout=timeout,
            check=False)
        if proc.returncode != 0:
            raise RuntimeError(f"{root.name} failed in its process:\n{proc.stderr[-1500:]}")
        table = pl.read_parquet(dst)
    store().audit("plugin_run", {"name": root.name, "symbol": symbol, "market": market,
                                 "rows": table.height})
    result = None
    if man["kind"] == "strategy":
        from .. import backtest
        result = backtest.run_strategy(SignalStrategy(table, symbol), bars,
                                       costs=PROFILE.get(market, "IN-equity-delivery"),
                                       symbol=symbol)
    return RunResult(name=root.name, kind=man["kind"], table=table, bars=bars, backtest=result)


if __name__ == "__main__":  # pragma: no cover - exercised through subprocess
    child(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), json.loads(sys.argv[4]))
