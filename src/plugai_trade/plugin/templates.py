"""Files that ``plugin.new`` writes: manifest, code skeleton, tests, house rules."""

from __future__ import annotations

MANIFEST = """# plugins/{name}/plugin.toml
name    = "{name}"
kind    = "{kind}"{pad}# report | strategy | screen
markets = ["IN", "US"]
entry   = "plugin.py:{name}"
network = []                     # no internet access at all
licence = "Apache-2.0"
"""

REPORT = '''import polars as pl
from plugai_trade import plugin


@plugin.report(title="{title}", markets=("IN", "US"))
def {name}(bars: pl.DataFrame, threshold_pct=1.0):
    """Sessions whose close moved at least threshold_pct from the previous close."""
    prev = pl.col("close").shift(1)                    # yesterday's close
    change = (pl.col("close") / prev - 1) * 100        # change, in percent
    out = bars.with_columns(prev_close=prev, change_pct=change)
    keep = out.filter(pl.col("change_pct").abs() >= threshold_pct)
    return keep.select("date", "prev_close", "close", "change_pct")
'''

STRATEGY = '''import polars as pl
from plugai_trade import plugin


@plugin.strategy(title="{title}", markets=("IN", "US"))
def {name}(bars: pl.DataFrame, n=50) -> pl.Series:
    """1 = hold, 0 = flat, for every row. The lab calls this with a window that
    ends at the last completed bar and reads only the last value."""
    average = pl.col("close").rolling_mean(n)          # average of the last n closes
    signal = (pl.col("close") > average).cast(pl.Int8)  # 1 when the close is above it
    return bars.select(signal.alias("signal"))["signal"]
'''

SCREEN = '''import polars as pl
from plugai_trade import plugin


@plugin.screen(title="{title}", markets=("IN", "US"))
def {name}(bars: pl.DataFrame, n=20):
    """A small table for a new page: the close and its n-day average."""
    average = pl.col("close").rolling_mean(n)          # average of the last n closes
    out = bars.with_columns(average=average)
    return out.select("date", "close", "average").tail(60)
'''

TEST_REPORT = '''import polars as pl
from {name}.plugin import {name}


def three_sessions():      # hand-made bars you can check with a calculator
    return pl.DataFrame({{
        "date":  ["2026-05-26", "2026-05-27", "2026-05-28"],
        "open":  [100.0, 101.0, 102.5],
        "high":  [101.0, 102.5, 103.0],
        "low":   [99.0, 100.5, 102.0],
        "close": [100.0, 102.0, 102.5]}})


def test_change_uses_yesterdays_close():
    out = {name}(three_sessions(), threshold_pct=1.0)
    assert out["date"].to_list() == ["2026-05-27"]   # 102/100-1 = 2.0%
    assert round(out["change_pct"][0], 2) == 2.00
'''

TEST_SCREEN = '''import polars as pl
from {name}.plugin import {name}


def test_average_of_last_two_closes():
    bars = pl.DataFrame({{"date": ["2026-05-26", "2026-05-27", "2026-05-28"],
                         "close": [100.0, 102.0, 102.5]}})
    out = {name}(bars, n=2)
    assert out["average"].to_list()[1:] == [101.0, 102.25]   # (100+102)/2, (102+102.5)/2
'''

TEST_STRATEGY = '''import numpy as np
import polars as pl
from plugai_trade import plugin
from {name}.plugin import {name}


def test_signal_is_zero_or_one():
    sig = {name}(plugin.sample_bars(300))
    assert set(sig.drop_nulls().to_list()) <= {{0, 1}}


def test_scramble_the_future():
    """Signal for day 200 must not change when every later bar is replaced by noise."""
    bars = plugin.sample_bars(300)
    before = {name}(bars)[200]
    rng = np.random.default_rng(1)
    noisy = {{c: bars[c].to_numpy().copy() for c in ("open", "high", "low", "close")}}
    for c in noisy:
        noisy[c][201:] = rng.uniform(50, 150, len(noisy[c]) - 201)
    scrambled = bars.with_columns(**{{c: pl.Series(v) for c, v in noisy.items()}})
    assert {name}(scrambled)[200] == before
'''

AGENTS_MD = """# House rules for this folder (AGENTS.md)

Coding assistants: read this before every session and follow it in every session.

1. Never write code that places, modifies or cancels an order, or that
   calls a broker's order API. Paper trading only, inside PlugAI-Trade.
2. Never write a key, token or password into any file. Never open .env
   or keychain files. If code needs a key, stop and ask me.
3. Never add a package or a web address I did not ask for. Ask first.
4. Never use a value from a later bar in a decision. No negative shifts.
5. Never change or skip a test to make it pass. Explain the failure instead.
6. Before running any command that installs, deletes or sends anything,
   show it to me and wait for "yes".
7. Do not say whether any trade, security or strategy is good.

The lab supplies the data (a window ending at the last completed bar), the
costs and the AI narration. This plugin only computes. Allowed packages:
polars, numpy, pandas, plugai_trade and the Python standard library's maths
and dates modules. `plugai-trade plugin test {name}` runs the Plugin check.
"""

GITIGNORE = """# .gitignore: never commit these
.env
*.key
data/
exports/
"""

CODE = {"report": REPORT, "strategy": STRATEGY, "screen": SCREEN}
TESTS = {"report": TEST_REPORT, "strategy": TEST_STRATEGY, "screen": TEST_SCREEN}
