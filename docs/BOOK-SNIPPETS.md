# Every code block printed in the book
The app must make each Python block run (tests/test_book_snippets.py).

### [0] ch04.typ (bash)
```bash
uv tool install plugai-trade
plugai-trade start
```

### [1] ch04.typ (bash)
```bash
docker run -p 8501:8501 plugai/plugai-trade
```

### [2] ch04.typ (bash)
```bash
docker run -p 8501:8501 -v plugai-data:/data \
  -e OLLAMA_HOST=http://host.docker.internal:11434 \
  plugai/plugai-trade
```

### [3] ch04.typ (bash)
```bash
plugai-trade lesson 4
```

### [4] ch04.typ (python)
```python
  from plugai_trade import data
  nifty = data.get("NIFTY", market="IN", start="2026-01-01", end="2026-05-29")
  spy   = data.get("SPY",   market="US", start="2026-01-01", end="2026-05-29")
  print(nifty.tail(3))   # last three synthetic NIFTY bars
  print(spy.height)      # number of SPY bars loaded
  ```

### [5] ch04.typ (bash)
```bash
plugai-trade doctor
```

### [6] ch04.typ (bash)
```bash
plugai-trade update
```

### [7] ch05.typ (python)
```python
  from plugai_trade import data
  a = data.get("NIFTY", market="IN", start="2026-05-01",
               end="2026-05-29", source="nse")
  b = data.get("NIFTY", market="IN", start="2026-05-01",
               end="2026-05-29", source="yfinance")
  diff = data.compare(a, b, tol=0.005)   # rows > 0.5% apart, or missing
  print(diff)                            # every row keeps its provenance tag
  ```

### [8] ch05.typ (bash)
```bash
plugai-trade fetch nse-bhavcopy --date 2026-05-29
plugai-trade fetch sec-edgar --ticker AAPL
plugai-trade doctor
```

### [9] ch10.typ (python)
```python
  from plugai_trade import data, ai
  import polars as pl
  bars = data.get("NIFTY", market="IN", start="2025-01-01", end="2026-05-29")
  bars = bars.with_columns(
      sma20=pl.col("close").rolling_mean(20),
      hi20=pl.col("high").rolling_max(20),
      lo20=pl.col("low").rolling_min(20),
  )
  print(bars.tail(3).select("date", "close", "sma20", "hi20", "lo20"))
  ai.explain(bars.tail(60))   # narration with sources; no new numbers
  ```

### [10] ch11.typ (python)
```python
  from plugai_trade import data, backtest, ai
  bars = data.get("NIFTY", market="IN", start="2021-01-01", end="2025-12-31")
  spec = backtest.rules("Buy at the next open on the first close above the "
                        "50-day average; sell at the next open when the "
                        "close is below the 20-day average")
  print(spec.read_back())          # check 1: plain English
  res = backtest.run(spec, bars, costs="IN-equity-delivery")
  res.report()                     # the Report Card
  ai.explain(res)                  # narration with sources
  ```

### [11] ch18.typ (python)
```python
  from plugai_trade import data, backtest
  bars = data.get("NIFTY", market="IN",
                  start="2011-01-01", end="2025-12-31")
  for fast, slow in [(20, 150), (50, 200), (100, 250)]:
      spec = backtest.rules(
          f"Hold while the {fast}-day average is above the "
          f"{slow}-day average; check Fridays; fill next open; "
          "size to 12% volatility, 10% buffer, no borrowing")
      res = backtest.run(spec, bars, costs="IN-equity-delivery")
      res.report()      # every run adds to the trial count
  ```

### [12] ch22.typ (python)
```python
  from plugai_trade import options
  opt = options.leg("NIFTY", kind="call", strike=25000, expiry="weekly", side="buy")
  print(opt.tiles())       # the six "What you're paying for" tiles
  print(opt.greeks())      # delta, gamma, theta, vega, per unit and per lot
  for d in (5, 4, 3, 2, 1):
      print(d, opt.at(days_left=d).price)    # the Days left slider
  print(opt.scenario(gap=-300, iv=-3))       # a gap and an IV crush
  print(options.iv_rank("NIFTY", window=252))
  ```

### [13] ch23.typ (python)
```python
  from plugai_trade import options
  spec = [("put", 24100, "buy"), ("put", 24300, "sell"),
          ("call", 25400, "sell"), ("call", 25600, "buy")]
  legs = [options.leg("NIFTY", kind=k, strike=s,
                      expiry="monthly", side=d) for k, s, d in spec]
  ic = options.strategy(legs)
  ic.summary()           # credit, max loss, breakevens, margin
  ic.stress(gap=-0.05, iv_to=0.24)        # repriced after 1 day
  ic.attribution(spot=24560, iv=0.15, days=5)
  ```

### [14] ch26.typ (python)
```python
  import numpy as np
  from plugai_trade import data
  get = lambda t: data.get(t, market="US")["close"].to_numpy()
  a, b = get("SYN-A"), get("SYN-B")
  F = 250                                    # formation sessions
  beta, alpha = np.polyfit(np.log(b[:F]), np.log(a[:F]), 1)
  spread = np.log(a) - alpha - beta * np.log(b)
  z = (spread - spread[:F].mean()) / spread[:F].std(ddof=1)
  lam = np.polyfit(spread[:F-1], np.diff(spread[:F]), 1)[0]
  half_life = -np.log(2) / np.log(1 + lam)   # in sessions
  ```

### [15] ch27.typ (python)
```python
import polars as pl
from plugai_trade import plugin
@plugin.report(title="Opening-gap report", markets=("IN", "US"))
def gap_report(bars: pl.DataFrame, threshold_pct=0.5):
    """Sessions that opened far from yesterday's close."""
    prev = pl.col("close").shift(1)            # yesterday's close
    gap = (pl.col("open") / prev - 1) * 100    # gap, in percent
    filled = (pl.when(gap > 0)
              .then(pl.col("low") <= prev)     # up: low got back
              .otherwise(pl.col("high") >= prev))  # down: high did
    out = bars.with_columns(prev_close=prev, gap_pct=gap,
                            filled=filled)
    keep = out.filter(pl.col("gap_pct").abs() >= threshold_pct)
    return keep.select("date", "prev_close", "open",
                       "gap_pct", "filled")
```

### [16] ch27.typ (python)
```python
import polars as pl, requests
from plugai_trade import data

KEY = "kite_7Hq2...9xT"                        # [4] key in code
bars = data.get("NIFTY", start="2024-06-01")   # [1] market? end?
bars = bars.with_columns(
    gap=pl.col("open") / pl.col("close") - 1,  # [2] TODAY's close
    ret=pl.col("close") / pl.col("open") - 1)  # open to close
trades = bars.filter(pl.col("gap") < -0.005)
print("Win rate:", (trades["ret"] > 0).mean())
print("Average:", trades["ret"].mean())        # [3] no costs
requests.post("https://api.broker.example/orders",   # [4] order
              headers={"Authorization": KEY})
```

### [17] ch27.typ (python)
```python
import polars as pl
from gap_report.plugin import gap_report
def three_sessions():      # hand-made, synthetic NIFTY-like bars
    return pl.DataFrame({
        "date":  ["2026-05-26", "2026-05-27", "2026-05-28"],
        "open":  [24700.0, 24950.0, 24880.0],
        "high":  [24850.0, 25010.0, 24990.0],
        "low":   [24650.0, 24790.0, 24860.0],
        "close": [24800.0, 24900.0, 24960.0]})

def test_gap_uses_yesterdays_close():
    out = gap_report(three_sessions(), threshold_pct=0.5)
    assert out["date"].to_list() == ["2026-05-27"]  # one gap
    assert round(out["gap_pct"][0], 2) == 0.60   # 24950/24800-1
    assert out["filled"][0]                      # 24790 <= 24800
```

### [18] ch27.typ (bash)
```bash
plugai-trade plugin test gap_report
```

### [19] ch27.typ (text)
```text
Manifest ............ ok (report · IN, US · network: none)
Tests (pytest) ...... 1 passed in 0.16 s
Order code .......... none ✓
Keys in code ........ none ✓
Packages ............ polars, plugai_trade ✓
Look-ahead scan ..... no negative shift ✓
Plugin check passed: ready to enable.
```

### [20] ch28.typ (python)
```python
  from plugai_trade import news
  heads = news.fetch(["nse-rss", "bse-rss"], market="IN",
                     start="2026-01-01", end="2026-05-29")
  fb  = news.score(heads, scorer="finbert")
  llm = news.score(heads, scorer="llm")        # your local model
  cmp = news.compare(fb, llm)
  print(cmp.table())                           # agreement counts
  cmp.disagreements().head(20)                 # read these yourself
  ```

### [21] ch28.typ (python)
```python
  from plugai_trade import news
  es = news.event_study(cmp.agreed("positive"), window=(-5, 10),
                        benchmark="NIFTY", entry="tradable_from",
                        costs="IN-equity-delivery")
  es.report()          # average path, bands, cost table, trials
  ```

### [22] ch29.typ (python)
```python
  from plugai_trade import data, ml, ai
  bars = data.get("NIFTY", market="IN", start="2010-01-01", end="2026-05-29")
  ds = ml.dataset(bars, label="high_vol_next_10", noise_column=True,
                  features=["range_5", "vol_20", "vol_5", "ret_5", "ret_20",
                            "dist_ma50", "volume_z", "weekday"])
  split = ml.time_split(ds, train=0.6, valid=0.2, test=0.2)  # purge = 10
  model = ml.boosting(split)            # gradient boosting, defaults
  card = ml.report(model, split, baselines=["majority", "vol_20 > 1"])
  card.show()        # scores vs baselines, importance, overfit curve
  ai.explain(card)   # narration with sources; no new numbers
  ```

### [23] ch30.typ (toml)
```toml
# ~/.plugai-trade/agents/tradingagents.toml  (written by the Agents screen)
[agent]
plugin   = "tradingagents"        # pinned GitHub tag, not PyPI
process  = "separate"
model    = "local"                # routed through Settings › AI Models
tools    = ["get_bars", "get_news", "get_filings", "run_backtest"]
as_of    = "2026-05-29"           # data after this date is invisible
mask_names = true                 # hide tickers and dates from the model
[budget]
max_steps = 40
max_cost  = 0.50                  # USD; the run stops, it does not overrun
[output]
kind = "rule_proposal"            # never an order, never a paper order
```

### [24] ch30.typ (python)
```python
from plugai_trade import agents, data, backtest, ai
team = agents.load("tradingagents", model="local",
                   as_of="2026-05-29", mask_names=True,
                   budget={"max_steps": 40, "max_cost": 0.50})
prop = team.propose("NIFTY", market="IN")   # a note + rules, never an order
print(prop.note)                            # bull, bear and risk sections
bars = data.get("NIFTY", market="IN", start="2016-01-01", end="2026-05-29")
res  = backtest.run(prop.rules, bars, costs="IN-equity-delivery")
res.report()        # Report Card; trials include the agent's own tests
print(prop.cost, prop.steps)                # what the run used
ai.explain(res)     # narration with sources
```

### [25] ch34.typ (bash)
```bash
plugai-trade update     # app + dated reference tables
plugai-trade doctor     # health check: "matches book edition ✓"
```

