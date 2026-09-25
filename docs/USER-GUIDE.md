# PlugAI-Trade user guide

A screen-by-screen guide keyed to the chapters of *Trading with AI – For All Levels*. Names are
spelled exactly as on screen. Every screen works offline on synthetic sample data. For each
chapter, `plugai-trade lesson N` opens the matching lesson.

**Paper only.** No screen can place a real order; the app contains no order code.

## Everywhere in the app

| Element | What it does | Ch. |
|---|---|---|
| Market switch `IN \| US` | Changes watchlists, calendars, costs, tax rules and currency | 4 |
| Data status | Source and age of the prices on screen (green / amber / red) | 5 |
| AI status | Model name with a Local or Cloud badge; open Settings › AI Models to switch | 1, 2 |
| Cost meter | Cloud spend this month; at the monthly budget the lab falls back to the local model | 2, 4 |
| Explain · Show sources · Second opinion | On every AI output: plain words, the numbers used, an adversarial review | all |
| Accept / Reject | Nothing the AI proposes is applied until you click Accept | all |
| HYPOTHETICAL | Watermark on every chart and backtest | 11 |
| UNTRUSTED | Pasted text is fenced so instructions inside it are ignored | 3 |

## Home — first-run wizard and dashboard (Chapter 4)

**First-run wizard**, five screens (press **Next** through them):

1. **Check your computer** — RAM, free disk and whether Ollama is running. If it says
   "Ollama not found", install it from ollama.com and click **Check again**.
2. **Local model** — a size suggested from your RAM (8 GB: a small 4B model; 16 GB: a 9B model;
   32 GB or more: a larger model) with a Fit check bar. **Pull model** downloads it with a progress
   bar; click it again to resume.
3. **Cloud key (optional)** — paste a Gemini, Groq, OpenRouter, OpenAI, Anthropic or DeepSeek key
   (stored in the OS keychain), or **Skip for now**.
4. **Sample data** — choose IN or US and **Load sample data** (synthetic NIFTY / BANKNIFTY / SENSEX
   or SPY / QQQ / DIA).
5. **Self-test** — **Run self-test**: sample data loaded, average computed, model quoted it,
   keychain ready, paper ledger empty, no order code. If a line fails, **Check again** or
   **Copy diagnostic** (no keys or journal rows in it), then **Open dashboard**.

**Dashboard** — the session clock (09:15–15:30 IST, 09:30–16:00 ET, open/closed now), the sample
watchlists for both markets, a chart of the market's index sample, your pinned screens (from
Settings › Workspace) and quick links. **Run the first-run wizard again** restarts it.

## Today

| Screen | Main controls | Ch. |
|---|---|---|
| Daily Briefing | Watchlist, Overnight news, Events today, Questions for you; ✓ / ? flags; Generate briefing; Schedule | 4, 7 |

## Research

| Screen | Main controls | Ch. |
|---|---|---|
| Document Desk | Drop a PDF / paste a link or text; Ask (This document / Ask my documents); Extract to table; Compare; Tone count; Export CSV; My library | 8, 31 |
| Screener | Describe your screen; Presets; Rules preview; Run; triage tags; Save as watchlist (Reason, Review by); Schedule | 9, 17, 21 |
| Score-Tester | Import vendor score CSV; column mapper; Point-in-time test; Report; Warnings | 9 |
| Chart Helper | Describe (numbers mode); Levels (incl. Intraday); Add timeframe; Screenshot mode (unreliable) | 10, 21 |
| Earnings Desk | Results calendar; Results digest; Implied vs historical move | 19 |
| IPO Dashboard | RHP digest; Subscription; GMP · unofficial; SME checker; Listing-day plan | 20 |

## Strategy

| Screen | Main controls | Ch. |
|---|---|---|
| Strategy Builder | Describe your idea → rule cards → Read back in English → Chart check → Backtest; Trials counter | 11, 30 |
| Backtest Report | Equity curve + drawdown; Costs; Walk-forward; Report Card (Robust / Fragile / Likely overfit) | 11, 18 |
| Trend Lab | MA crossover, Time-series momentum, Rotation presets; Volatility sizing; Parameter heatmap | 16, 18 |
| Pairs Lab | Find pairs; Check link; Spread z-score; Half-life; lesson pair SYN-A / SYN-B | 26 |

## Plan & Risk

| Screen | Main controls | Ch. |
|---|---|---|
| Trade Plan | New plan; Critique; Send to Paper Desk; Save to journal | 12, 17 |
| Position Sizer | Fixed risk % / ATR stop / Vol target / Hedge; Size it; Use in plan | 12, 17, 26 |
| Rule Card | Written rules / Checklist / Go / no-go / Monthly audit; New version; Sync limits | 12, 21, 34 |

## Paper Trading

| Screen | Main controls | Ch. |
|---|---|---|
| Paper Desk | Place paper order; Positions; LIVE / Replay; Cost preview; Kill switch; Daily loss limit; Compare with backtest | 13, 21 |
| Alerts | New alert (From plan, From Crypto Monitor); Attach paper order; Send test; Quiet hours; SIMULATED | 13, 17, 25 |

## Derivatives

| Screen | Main controls | Ch. |
|---|---|---|
| Options Strategy Builder | Add leg; Income presets; What you're paying for tiles; Days left; Scenarios (Gap, IV spike) | 22, 23 |
| Futures & Roll | Contract / Basis / Roll calendar / Margin & MTM; Replay path; Add shock; Set roll alert | 24 |
| Contract Table | Dated lot sizes, expiry days, sessions, fees, settlement | 22–24, 26 |

## Portfolio, Journal, Tax

| Screen | Main controls | Ch. |
|---|---|---|
| Portfolio Reviewer | Import holdings; Overlap; Costs; Concentration; Allocation; ETF check; Income; SIP planner; Thesis tracker | 15, 16 |
| Crypto Monitor | Watch / Funding rates / Alerts / India VDA ledger | 25 |
| Forecast Journal | Add forecast; Hide price until I commit; Resolve; Brier score (US only) | 26 |
| Trades | Import tradebook; Match plans; tags; R-multiples; Replay | 14, 21 |
| Weekly Review | Generate review; Rule breaks; Show query; Save review | 14, 34 |
| Ask My Journal | Chat; every number links to its query | 14 |
| Tax Export | Classify / Turnover / AIS check / Export; Wash-sale check; 1256 tagging; Draft for your CA / CPA | 25, 32 |

## Automate (Builder track)

| Screen | Main controls | Ch. |
|---|---|---|
| Scheduler | Add job; Run now; View log; Pause all; Catch up missed runs; Health alert | 28, 31, 34 |
| News Pipeline | Sources / Score / Event study; Fetch now; Compare scorers | 28 |
| ML Lab | Dataset; Label; Split in time; Train baseline; Shuffle test; Scenarios | 29 |
| Agents | Team picker; As-of; Mask names; Budget; Run / Stop; proposal card | 30 |
| Plugins | New from template; Install; Open folder; Run checks; Run; Enable | 27, 30 |

## Lessons

**Lessons › Lessons** (all chapters). Pick a chapter (or run `plugai-trade lesson N`). Each lesson
shows its goal and levels (Starter, Explorer, Builder), three to seven steps with links to the
screens they use, and a hands-on exercise computed in code on synthetic data (with Explain / Show
sources / Second opinion). **Load lesson sample** loads the chapter's sample (for example
Kavita's and Marcus's journals in lesson 14, or the SYN-A / SYN-B pair in lesson 26).
**Check my work** compares each answer with the value the lab computes at that moment, or checks
the lab's own settings (for example "Journal and Portfolio are Local only"); a few items are ticks
only you can confirm. Progress shows as Not started / In progress / Done. **Reset lesson** clears
your answers and results, for example to repeat the lesson on the other market.

**Lessons › Prompt Library** (Chapter 3; Appendix B). All 40 prompts, printed exactly as in their
chapters. Use the **Search** box and the filter chips **Research / Plan / Journal / Review** (plus
Options, Investing, Tax, Safety). On a card: **Fill in** turns each `[PLACEHOLDER]` into a field and
shows the ready-to-paste prompt (anything pasted into a "paste…" field is fenced as UNTRUSTED);
**Send to Document Desk** hands the prompt and any pasted source to Research › Document Desk;
**Save my version** keeps your edited copy, tagged **MY VERSION**, above the book's version.

## Settings

**Data Sources** (Ch. 5, 13) — tiers No signup · Free key · Your broker; Connect; Save to keychain;
Test connection; fallback strip; Live stream; Compare sources.

**AI Models** (Ch. 2, 4, 31) —
- *Local (Ollama)*: installed models with the **Default** marker; **Test model** reports speed
  (tokens per second), prompt reading time and whether the model invented a number;
  **Add local server** (LM Studio: `http://localhost:1234/v1`).
- **Pull model** with a *Fit check* bar per size (model file + context scratchpad + memory in use;
  green / amber / red) and **Context length**.
- *Cloud (your keys)*: **Add cloud model** (the provider's key must be in Settings › Keys).
- *Drafting* vs *Journal and portfolio* model.
- *Use for*: Local only / Cloud allowed per sidebar section; Tax and Documents default to Local
  only; Journal and Portfolio are held Local only while the Privacy toggles are on.
- **Monthly budget**: cloud calls pause at it and fall back to the local model.
- *Embeddings*: the embedding model for Document Desk search and its own **Pull model**.

**Keys** (Ch. 4, 25) — Add key / Save / Remove; OS keychain; last four characters shown;
keys with trade or withdraw permission refused.

**MCP Server** (Ch. 6) — tools tagged READ or PAPER; paper_order toggle; Copy config for Claude
Desktop; Tool-call log.

**Privacy** (Ch. 2, 4) — toggles: journal and tradebook local-only; holdings local-only;
**Ask before sending to cloud**; remove account numbers and PAN/SSN before cloud calls; share
anonymous crash reports (off). A preview shows what a cloud call would send after stripping.
**Education lag**: default 90 days (minimum 30) for named Indian securities in lessons and AI
explanations; indices, synthetic data and your own tradebook are unaffected.

**Security** (Ch. 33) —
- **Security checklist**: automatic checks (keys in the OS keychain only, no trade / withdraw keys,
  MCP tools READ + PAPER, cloud calls strip PAN / SSN, tables up to date) and manual ticks (2FA,
  backup codes on paper, OTP / TPIN never shared, broker numbers from the official site).
- **Registration check**: choose IN or US and the type; the lab opens the official register
  (SEBI intermediaries, RBI, FINRA BrokerCheck, SEC adviser search, NFA BASIC). It never judges a
  registration itself.
- **Check a pitch**: runs the chapter's scam-check prompt on your model; a red-flag scan computed in
  code (returns, technology, regulation, custody, urgency, plus the "% a day" calculator test)
  always runs, and is the whole answer when no model is connected.
- **Audit log** with filters (All, Cloud, Keys, MCP, AI, Data) and **Export log** (CSV).

**Workspace** (Ch. 34) — **Apply template** (Investor / Swing / Intraday / Options / Mixed; market IN,
US or both), **Preview changes** (pinned screens, Scheduler jobs — Daily Briefing, Weekly Review,
nightly backup, monthly update check — starter Rule Card lines and rhythm reminders), **Accept** on
each group separately (Rule Card lines arrive as suggestions), **Export workspace** (settings,
schedules and pins; never keys or the journal).

## When something looks wrong

Run `plugai-trade doctor` first, then see the book's Appendix F. On Home, the self-test's
**Copy diagnostic** gives a short report you can paste into the install-helper prompt or a GitHub
issue.
