#import "../theme.typ": *

// ---------- Appendix E local helpers (prefix appE-) ----------
#let appE-t(n, t) = block(above: 1.5em, below: 0.45em, sticky: true)[
  #text(font: sans, size: 8.3pt, weight: "bold", fill: slate-dk)[Table E.#n]
  #h(5pt)
  #text(font: sans, size: 8.3pt, weight: "semibold", fill: ink)[#t]
]
#let appE-foot(body) = block(above: 0.55em, below: 1.2em)[
  #set text(font: sans, size: 7.6pt, fill: ink-soft)
  #set par(justify: false, leading: 0.55em)
  #body
]
#let sec(t) = text(font: sans, weight: "bold", fill: slate-dk, t)
#let ktbl(..args) = block(breakable: false, tbl(..args))

#chapter(
  num: "E",
  kind: "Appendix",
  title: [PlugAI-Trade Screen & Command Reference],
  subtitle: [Every sidebar section, screen, button, command and Python call used in the book, with the chapter that teaches it],
  color: slate, color-dk: slate-dk, color-bg: slate-bg,
)

#show table: set par(justify: false)
#show table: set text(hyphenate: false)
#set table.cell(breakable: false)

PlugAI-Trade is the book's free, open-source (Apache-2.0) companion app. It runs on your own computer, opens in the browser at `localhost:8501`, and is a research, planning, paper-trading and review lab. It *never places real orders*: there is no order code in it, and the word "order" appears only as "paper order". The model explains numbers; code computes them.

This appendix is the map. Names are spelled exactly as they appear on screen, so you can search for them. The number in the last column is the chapter that walks through the screen step by step. Screens and buttons can move between releases; `plugai-trade doctor` tells you whether your installed version matches this edition of the book.

== Everywhere in the app

#appE-t(1)[The top bar]
#tbl(
  columns: (1fr, 2.4fr, 0.55fr),
  header: ([Element], [What it shows and does], [Ch.]),
  rows: (
    ([Market switch], [`IN | US`: changes watchlists, calendars, costs, tax rules and the currency of every screen], [4]),
    ([Data status], [Source and age (e.g. "Upstox · 2 min ago"); dot green / amber / red; hover for the provenance tag (source, fetch time, licence class)], [5]),
    ([AI status], [Model name with a *Local* or *Cloud* badge; click to open *Settings › AI Models*], [1, 2]),
    ([Cost meter], [₹ / \$ spent on cloud models this month; at the monthly cap the lab falls back to the local model], [2, 4]),
    ([Session clock], [The selected market's session (09:15–15:30 IST or 09:30–16:00 ET)], [4]),
    ([FX rates], [Daily USD/INR and EUR/USD reference rates, with their date, once #ui[Frankfurter FX] is on], [26]),
  ),
)

#appE-t(2)[Buttons and labels on every screen]
#tbl(
  columns: (1.15fr, 2.3fr, 0.55fr),
  header: ([Button or label], [Meaning], [Ch.]),
  rows: (
    ([#ui[Explain]], [The AI describes the result in plain words, citing the lab's numbers], [all]),
    ([#ui[Show sources]], [Reveals the rows, numbers or pages the AI used], [all]),
    ([#ui[Second opinion]], [A fresh model reviews the output adversarially], [all]),
    ([#ui[Accept] / #ui[Reject]], [Nothing the AI proposes is applied until you click #ui[Accept]], [all]),
    ([HYPOTHETICAL], [Watermark on every chart and backtest], [11]),
    ([PAPER · REPLAY], [Tags on simulated fills and replayed sessions in the Paper Desk and Journal], [13]),
    ([SIMULATED], [Label on every alert], [13]),
    ([Trials: N], [How many variants you have tested; feeds the Report Card], [11]),
    ([UNTRUSTED], [Pasted text is fenced off so instructions hidden in it are not followed], [3]),
    ([BLOCKED], [A paper order stopped by a Rule Card guardrail], [21]),
    ([PROPOSAL · NOT AN ORDER], [Output of an agent team; goes to Strategy Builder or is rejected], [30]),
    ([PROPOSED], [Tag on rule cards that came from an agent; they still need your read-back, test and #ui[Accept]], [30]),
    ([PILOT], [Tag on real trades imported from your broker during a pilot period], [34]),
    ([ASK CA], [A tax row the rules cannot classify; never guessed], [32]),
    ([Draft for your CA / CPA], [Stamp on every tax export], [32]),
  ),
)

== Sidebar sections and screens

#appE-t(3)[Sidebar map, part 1: Today to Paper Trading]
#tbl(
  columns: (0.95fr, 1.1fr, 3.1fr, 0.6fr),
  header: ([Section], [Screen], [Main controls and panels], [Ch.]),
  rows: (
    ([#sec[Today]], [Daily Briefing], [Watchlist, Overnight news, Events today, Questions for you; Yesterday strip; ✓ / ? flag on every line; #ui[Generate briefing]; #ui[Schedule] (market days, run time, news cutoff, delivery)], [7]),
    ([#sec[Research]], [Document Desk], [Drop a PDF or paste a link; Ask (#ui[This document] / #ui[Ask my documents]); citations with page numbers; #ui[Extract to table] with #ui[Edit fields]; #ui[Compare]; Tone count; #ui[Export CSV]; My library (#ui[Add folder])], [8, 31]),
    ([], [Screener], [Describe your screen; universe and As of date; Presets (Swing · Pullback, Swing · Breakout, Gap scan); rule cards; #ui[Run]; triage tags; #ui[Save as watchlist] (Reason, Review by); #ui[Schedule]], [9, 17, 21]),
    ([], [Score-Tester], [Import vendor score CSV; column mapper; Horizon; Include delisted; Point-in-time test; Report (5 buckets, spread, coverage, warnings)], [9]),
    ([], [Chart Helper], [Symbol, timeframe, #ui[Add timeframe]; Describe (numbers mode); Levels (incl. Intraday); #ui[Save levels to journal]; #ui[Send levels to Paper Desk]; "Screenshot mode (unreliable)" toggle], [10, 21]),
    ([], [Earnings Desk], [Results calendar (#ui[Import watchlist], #ui[Send to Alerts]); Results digest (#ui[Generate digest], guidance chips); Implied vs historical move (Event split, Scenarios, #ui[Open in Options Strategy Builder])], [19]),
    ([], [IPO Dashboard], [RHP digest; Subscription tracker; GMP · unofficial; SME checker; Listing-day plan; #ui[Add IPO], #ui[Allotment odds], #ui[Run checks], #ui[Critique], #ui[Lock-in calendar]], [20]),
    ([#sec[Strategy]], [Strategy Builder], [Describe your idea → rule cards (ENTRY, EXIT, FILL, SIZE · COST; "assumed" fields) → Read back in English → Chart check → Backtest; Trials counter], [11]),
    ([], [Backtest Report], [Equity curve + drawdown; buy-and-hold line; Costs (delivery / intraday toggle); Walk-forward; Trials counter; Report Card: Robust / Fragile / Likely overfit], [11, 18]),
    ([], [Trend Lab], [Presets: MA crossover, Time-series momentum, Rotation; Volatility sizing (target vol, buffer, cap, Weekly check); Parameter heatmap; #ui[Send to Backtest Report]], [16, 18]),
    ([], [Pairs Lab], [Pair finder (#ui[Find pairs], #ui[Check link]); Spread z-score; Half-life; sizing panel; #ui[Send to Backtest Report], #ui[Send to Paper Desk]], [26]),
    ([#sec[Plan & Risk]], [Trade Plan], [#ui[New plan]; templates (e.g. Weekend swing plan); #ui[Critique] (AI sceptic); #ui[Send to Paper Desk]; #ui[Save to journal]], [12, 17]),
    ([], [Position Sizer], [Tabs Fixed risk % / ATR stop / Vol target / #ui[Hedge]; #ui[Size it]; #ui[Use in plan]; #ui[Simulate streaks]; lot rounding; notional-exposure tile; position caps], [12, 17, 21, 26]),
    ([], [Rule Card], [Tabs Written rules / Checklist / Go / no-go / Monthly audit; #ui[New version]; Pre-market checklist; Intraday guardrails; #ui[Sync limits] (to Sizer caps and the Paper Desk daily loss limit); adherence score; #ui[Run check] (PASS / NOT YET, Paper or Pilot account); #ui[Save pilot plan]; #ui[Start audit]], [12, 14, 21, 34]),
    ([#sec[Paper Trading]], [Paper Desk], [Paper order ticket (#ui[Place paper order]); Positions; LIVE / Replay (1× / 5× / 20×); Cost preview; Kill switch; Daily loss limit; #ui[Close at next bar]; #ui[Compare with backtest]; #ui[Run shadow backtest]], [13, 21, 23, 24]),
    ([], [Alerts], [New alert (price, indicator, event; From plan; From Crypto Monitor); #ui[Attach paper order]; Desktop / Email / Telegram; #ui[Send test]; Quiet hours; alert log], [13, 17, 25]),
  ),
)

#appE-t(4)[Sidebar map, part 2: Derivatives to Settings]
#tbl(
  columns: (0.95fr, 1.1fr, 3.1fr, 0.6fr),
  header: ([Section], [Screen], [Main controls and panels], [Ch.]),
  rows: (
    ([#sec[Derivatives]], [Options Strategy Builder], [#ui[New strategy]; Add leg (Buy / Sell · Call / Put); Income presets; What you're paying for tiles (Breakeven, Max loss, Required move, Expected ±1σ, Theta/day, Delta); Days left slider; IV panel; Scenarios (#ui[Gap], #ui[IV spike]); Payoff chart; P&L attribution; #ui[Save to plan]; #ui[Send to Paper Desk]], [22, 23]),
    ([], [Futures & Roll], [Tabs Contract / Basis / Roll calendar / Margin & MTM; #ui[Replay path]; #ui[Add shock]; #ui[Set roll alert]; OI build-up; USDINR split; #ui[Send to Trend Lab]], [24]),
    ([], [Contract Table], [Dated lot sizes, expiry days, sessions, fees and settlement for NSE, BSE, MCX, CME and Cboe; filter by asset; Exposure required badge], [22–24, 26, App. A]),
    ([#sec[Portfolio]], [Portfolio Reviewer], [#ui[Import holdings] (CAS or broker CSV); Holdings; Allocation (Set target, Rebalance checklist); Overlap; Costs; Concentration; ETF check; Income; SIP planner; Thesis tracker (#ui[Add thesis], #ui[Check thesis])], [15, 16]),
    ([], [Crypto Monitor], [Tabs Watch / Funding rates / Alerts / India VDA ledger; #ui[Add position]; tiles Funding/8h, Annualised, 30-day cost, To liquidation], [25]),
    ([], [Forecast Journal], [#ui[Add forecast]; #ui[Hide price until I commit]; #ui[Resolve]; Brier score and calibration chart. US only; disabled for IN], [26]),
    ([#sec[Journal]], [Trades], [#ui[Import tradebook] (Zerodha, Upstox, Groww, Dhan, Angel One · IBKR, Schwab, Robinhood, Webull, generic CSV); #ui[Match plans]; tags; R-multiples; Replay], [14, 21]),
    ([], [Weekly Review], [#ui[Generate review]: stats computed in code + AI narration with row links; Rule breaks; last-week tiles; #ui[Show query]; #ui[Save review]], [14, 34]),
    ([], [Ask My Journal], [Chat; every number links to its query (#ui[Show query]); pin an answer to the Weekly Review], [14]),
    ([#sec[Tax]], [Tax Export], [#ui[Import tradebook]; tabs Classify / Turnover / AIS check / Export · #mkt("in") #ui[Classify], Turnover calculator, Carry-forward ledger, Advance-tax planner, #ui[Reconcile AIS], ITR-shaped CSV · #mkt("us") #ui[Add account], #ui[Wash-sale check], #ui[1256 tagging], #ui[Crypto wash-sale check] (off), 8949-shaped CSV · #ui[Export]], [25, 32]),
    ([#sec[Automate] (Builder)], [Scheduler], [#ui[Add job] (Daily Briefing, fetch, score, index documents, Weekly Review, Backup, monthly update check); #ui[Run now]; #ui[View log]; #ui[Pause all]; Catch up missed runs; #ui[Health alert]], [28, 31, 34]),
    ([], [News Pipeline], [Tabs Sources / Score / Event study; #ui[Fetch now]; scorer FinBERT or Local model; #ui[Compare scorers]; #ui[Run event study]; Unstamped tray], [28]),
    ([], [ML Lab], [Dataset; Label; Split in time (Purge, Embargo); #ui[Train baseline]; Results vs baselines; #ui[Shuffle test]; Scenarios (#ui[Volatility scenarios], #ui[Send to Position Sizer])], [29]),
    ([], [Agents], [Team picker; As-of; Mask names; Budget; Run / Stop; Transcript; proposal card; #ui[Send to Strategy Builder] or Reject], [30]),
    ([], [Plugins], [#ui[New from template] (Screen / Strategy / Report); #ui[Install] (pinned GitHub tag); #ui[Open folder]; #ui[Run checks]; #ui[Run]; #ui[Enable]], [27, 30]),
    ([#sec[Lessons]], [Chapter 1–34], [One lesson per chapter; #ui[Check my work]; #ui[Reset lesson] (see Appendix G)], [all]),
    ([], [Prompt Library], [Search; filter chips Research / Plan / Journal / Review; #ui[Fill in]; #ui[Send to Document Desk]; #ui[Save my version]], [3]),
    ([#sec[Settings]], [Data Sources], [Tiers No signup · Free key · Your broker; #ui[Connect]; #ui[Save to keychain]; #ui[Test connection]; #ui[\+ Add key]; fallback strip; Live stream; Compare sources], [5, 13]),
    ([], [AI Models], [Local (Ollama) and Cloud (your keys); #ui[Pull model] with Fit check; #ui[Test model] (speed); #ui[Add cloud model]; #ui[Add local server]; #ui[Context length]; Embeddings; Use for (per section); Monthly budget], [2, 4, 31]),
    ([], [Keys], [#ui[Add key] / #ui[Save] / #ui[Remove]; stored in the OS keychain, last 4 characters shown; refuses exchange keys that can trade or withdraw], [4, 25]),
    ([], [MCP Server], [Tools tagged READ or PAPER; paper_order toggle; #ui[Copy config for Claude Desktop]; Tool-call log], [6]),
    ([], [Privacy], [Journal and holdings local-only; Ask before sending to cloud; strip account numbers, PAN and SSN; crash reports off], [2, 4]),
    ([], [Security], [#ui[Security checklist]; #ui[Registration check]; #ui[Check a pitch]; #ui[Audit log] (filter #ui[Cloud]); #ui[Export log]], [33]),
    ([], [Workspace], [#ui[Apply template] (Investor / Swing / Intraday / Options / Mixed); #ui[Preview changes]; #ui[Accept] per group; #ui[Export workspace]], [34]),
    ([], [Education lag], [Default 90 days for named Indian securities (minimum 30)], [5]),
  ),
)

#note[
  *First-run wizard* (Chapter 4). #ui[Next] through five screens: memory check and suggested local model (#ui[Pull model]; about 4B parameters at 8 GB, 9B at 16 GB, larger at 32 GB), optional cloud key (#ui[Skip for now]), #ui[Load sample data] (NIFTY / BANKNIFTY / SENSEX and SPY / QQQ / DIA watchlists), #ui[Run self-test] (six checks), #ui[Open dashboard]. If a check fails, #ui[Check again] or #ui[Copy diagnostic].
]

== Commands

#appE-t(5)[Terminal commands]
#tbl(
  columns: (2.05fr, 2.1fr, 0.55fr),
  header: ([Command], [Does], [Ch.]),
  rows: (
    ([`uv tool install plugai-trade`], [Install (Windows, macOS, Linux); uv fetches Python itself], [4]),
    ([`plugai-trade start`], [Launch the dashboard at `localhost:8501`], [4]),
    ([`plugai-trade start --port 8502`], [Launch on another port if 8501 is busy], [4]),
    ([`docker run -p 8501:8501 plugai/plugai-trade`], [Run in Docker instead (mount a `/data` volume; set `OLLAMA_HOST` for a local model)], [4]),
    ([`docker pull plugai/plugai-trade`], [Get the latest Docker image], [4]),
    ([`plugai-trade doctor`], [Print versions; check data sources and models; confirm "matches book edition ✓"], [4, 5, 34]),
    ([`plugai-trade lesson 22`], [Open the lesson for a chapter (here 22)], [all]),
    ([`plugai-trade fetch nse-bhavcopy --date 2026-05-29`], [Download one NSE bhavcopy], [5]),
    ([`plugai-trade fetch sec-edgar --ticker AAPL`], [Download one company's EDGAR facts], [5]),
    ([`plugai-trade mcp`], [Run the read-only MCP server for Claude Desktop], [6]),
    ([`plugai-trade update`], [Update the app, connector fixes and dated reference tables; prints the changed rows and flags saved plans that used an old value], [5, 33, 34, A]),
    ([`plugai-trade plugin new gap_report --kind report`], [Create a plugin from a template], [27]),
    ([`plugai-trade plugin test gap_report`], [Run a plugin's checks and tests], [27]),
    ([`plugai-trade backup --to <folder>`], [Write one encrypted backup: journal, notes, Rule Card, templates, settings, job list. Keys are never included], [31]),
    ([`plugai-trade backup --restore <file>`], [Restore from a backup file], [31]),
  ),
)

#appE-t(6)[MCP server tools (`plugai-trade mcp`)]
#block(breakable: false)[
#ktbl(
  columns: (1.3fr, 0.6fr, 2.3fr),
  header: ([Tool], [Tag], [Does]),
  rows: (
    ([`get_watchlist`], [READ], [Returns your saved watchlists]),
    ([`get_journal`], [READ], [Returns journal rows, with the query used]),
    ([`get_backtest`], [READ], [Returns a saved Backtest Report]),
    ([`run_backtest`], [READ], [Runs a backtest with the lab's costs; counts as a trial]),
    ([`get_paper_positions`], [READ], [Returns open paper positions]),
    ([`paper_order`], [PAPER], [Creates a pending paper order in the Paper Desk for you to #ui[Accept] or #ui[Reject]; off unless you switch it on]),
  ),
)
#appE-foot[Agent plugins (Chapter 30) see a narrower set: `get_bars`, `get_news`, `get_filings` and `run_backtest`. No tool can place a real order, because the app contains no order code.]
]

== Python API (Builder track)

#appE-t(7)[The `plugai_trade` package: calls used in the book]
#tbl(
  columns: (2.2fr, 2.1fr, 0.5fr),
  header: ([Call], [Returns or does], [Ch.]),
  rows: (
    ([`data.get("NIFTY", market="IN", start=, end=, source=)`], [Bars as a DataFrame with a provenance column; `source=` pins one source], [5]),
    ([`data.compare(a, b, tol=0.005)`], [Rows more than 0.5% apart, or missing], [5]),
    ([`backtest.rules("Buy when …")`], [A rule spec from plain English; `spec.read_back()` prints it back], [11]),
    ([`backtest.run(spec, bars, costs="IN-equity-delivery")`], [Result; `costs="US-equity"` for the US; `res.report()` shows the Report Card], [11, 18]),
    ([`options.leg("NIFTY", kind="call", strike=25000, expiry="weekly", side="buy")`], [One leg; `.tiles()`, `.greeks()`, `.at(days_left=)`, `.scenario(gap=, iv=)`], [22]),
    ([`options.strategy(legs)`], [`.summary()`, `.stress(gap=, iv_to=)`, `.attribution(spot=, iv=, days=)`], [23]),
    ([`options.iv_rank("NIFTY", window=252)`], [IV rank and percentile], [22]),
    ([`journal.load("zerodha_tradebook.csv")`], [Journal rows from a broker tradebook], [14]),
    ([`ai.explain(obj)`], [Narration of a result or DataFrame, with sources], [10, 11]),
    ([`news.fetch(...)`, `news.score(heads, scorer="finbert")`], [Time-stamped headlines; scores by FinBERT or `"llm"`], [28]),
    ([`news.compare(a, b)`, `news.event_study(...)`], [Scorer agreement; event study with costs], [28]),
    ([`ml.dataset(...)`, `ml.time_split(...)`], [Features and label; purged time split (no shuffle)], [29]),
    ([`ml.boosting(split)`, `ml.report(...)`], [Baseline model; model card against baselines], [29]),
    ([`agents.load("tradingagents", model="local")`], [An agent team; `.propose("NIFTY", market="IN")` returns a note and rules, never an order], [30]),
    ([`@plugin.report(...)`, `@plugin.strategy(...)`], [Decorators that register a plugin], [27]),
  ),
)

#appE-t(8)[Files and folders]
#block(breakable: false)[
#ktbl(
  columns: (1.7fr, 2.4fr, 0.55fr),
  header: ([Path], [What it holds], [Ch.]),
  rows: (
    ([`DATA_SOURCES.md` (repo)], [Live status of every connector, from a nightly check], [5]),
    ([`plugin.toml`, `plugin.py`, `tests/`, `AGENTS.md`], [A plugin's manifest, code, tests and notes for an AI coding assistant], [27]),
    ([`~/.plugai-trade/agents/<plugin>.toml`], [Settings for an agent plugin], [30]),
  ),
)
#appE-foot[Repo: `github.com/plugai/plugai-trade`, book tag `book-v1.0`. Every lesson and snippet in the book runs against that tag.]
]
