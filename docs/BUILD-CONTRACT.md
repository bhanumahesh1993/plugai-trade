# Build contract for PlugAI-Trade v1.0 (read fully before writing code)

PlugAI-Trade is the companion app of the published book *Trading with AI – For All Levels*.
The book already describes every screen, button and command, so **the book is the spec**.
Repo root: `/Users/bhanumahesh/book/Trading/plugai-trade`. Book sources: `/Users/bhanumahesh/book/Trading/manuscript/`.

## Sources of truth (in priority order)
1. `docs/BOOK-SNIPPETS.md` — every code block in the book. Each Python block must run as printed
   (offline, with synthetic data, with no Ollama). Signatures are fixed by the book.
2. `docs/SPEC.md` (the book's app spec + the "Screens, controls and commands established by the
   chapters" list) and `docs/APPENDIX-E-reference.typ` (reader-facing screen & command reference).
3. The chapter text for your screens: `grep -n "Your Screen Name" /Users/bhanumahesh/book/Trading/manuscript/chapters/*.typ`
   and read the `#in-lab(...)` walkthroughs — every numbered step there must be doable in the UI
   with the same button names (`#ui[Button]`).

## Architecture (already built — use it, do not rewrite it)
- `plugai_trade.config` — settings (JSON in the lab folder). `config.get("a.b")`, `config.set_value`.
- `plugai_trade.store.default()` — SQLite store. Tables listed in `store.TABLES`
  (watchlists, plans, rule_cards, journal, paper_orders, paper_positions, alerts, alert_log,
  audit_log, trials, backtests, briefings, documents, theses, forecasts, ipos, jobs, job_log,
  proposals, plugins, reviews, tax_accounts, notes, lessons, cost_log, workspaces, pilot_plans).
  `add(table, dict, tag)`, `all(table, tag=None)`, `get`, `update`, `delete`, `count`, `audit(kind, detail)`.
- `plugai_trade.data` — `get(symbol, market, start, end, interval, source)`, `compare`, `sources()`,
  `register(SourceInfo(...))`, `normalise`, `education_cutoff`. Synthetic data always works offline.
- `plugai_trade.costs` — `india_round_trip`, `us_round_trip`, `round_trip(profile, …)`, `rate(profile)`,
  profiles `IN-equity-delivery, IN-equity-intraday, IN-futures, IN-options, US-equity, US-options`.
- `plugai_trade.reference` — dated tables (`lookup("india.charges.stt")`, `lot_size`, `multiplier`, `as_of`).
- `plugai_trade.ai` — `explain(obj, question, section)`, `complete(prompt, section, schema)`,
  `second_opinion`, `output_filter`, `fence_untrusted`, `facts_from`, `extract_json`, `status()`.
  **Numbers are always computed in code; the model only narrates them.** Give result objects a
  `facts()` method returning short strings like `"Breakeven: 25,089"` so `ai.explain` can cite them.
  Everything must work when no model is reachable (ai returns a deterministic fallback text).
- `plugai_trade.indicators` — sma, ema, rsi, atr, macd, bollinger, vwap, realised_vol, high_n.
- `plugai_trade.app.ui` — `page_header(title, section)` (call first on every page), `market()`,
  `ai_block(obj, key, section, on_accept=...)` (Explain / Show sources / Second opinion / Accept),
  `line_chart`, `candles`, `hypothetical_chart` (HYPOTHETICAL watermark — required on every
  backtest/paper chart), `dated_note`, `paper_only_note`, `set_data_status`.
- Pages: `src/plugai_trade/app/pages/<module>.py` each exposing `render()`; registry in
  `app/registry.py` (do not rename screens).
- CLI: `src/plugai_trade/cli.py` already defines all commands; it calls `mcp_server.main()`,
  `updater.run(echo)`, `backup.create(Path)/restore(Path)`, `plugin.new(name, kind)`,
  `plugin.check(name)` (returns an object with `.passed` and `.text()`).

## Hard rules
1. **Paper only.** No code that can place, modify or cancel a real order, anywhere. No broker
   order endpoints. `paper_guard.scan_path` runs in tests. Broker adapters are read-only.
2. **The model never computes.** All numbers from code. AI output passes `ai.output_filter`.
3. **Offline first.** Every screen and every book snippet works with synthetic data, no network,
   no Ollama. Network sources are optional and must fail gracefully (clear message, fall back).
4. **Names match the book exactly** (screens, tabs, buttons, tiles, commands). When the book shows
   a button, the UI has a `st.button` with that exact label.
5. **Dated facts** come only from `reference` tables — never hard-code a rate, lot or date.
6. **Keys** only through `plugai_trade.keys` (OS keychain). Never log or print keys.
7. **Privacy:** journal, holdings and tax data use `sensitive=True` / sections that are Local only.
8. **No recommendations.** No buy/sell/target language in UI copy or AI prompts.
9. Keep dependencies to those in `pyproject.toml`; optional extras (`yfinance`, `ccxt`,
   `scikit-learn`, `litellm`) must be imported lazily with a friendly message if missing.

## Files you may edit
Only the files your task lists, plus new files under your own module names and
`tests/test_<yourarea>_*.py`. **Do not edit** `config.py, store.py, keys.py, ai/__init__.py,
data/__init__.py, data/synthetic.py, costs.py, reference/*, indicators.py, app/ui.py,
app/registry.py, app/main.py, cli.py, paper_guard.py, pyproject.toml`. If you need a change
there, describe it under "CORE CHANGES NEEDED" in your final report (and work around it locally).

## Quality bar
- Type-hinted, docstrings on public functions, small functions, no dead code.
- Tests: pytest, offline (monkeypatch httpx / use fixtures), fast (< 20 s for your file).
- Every page must pass `tests/test_app_smoke.py` (AppTest renders with no exception) — run it.
- Run the whole suite before you finish: `.venv/bin/pytest -q` must be green.
- Use `.venv/bin/python` / `.venv/bin/pytest` (already installed, editable).

## Final report
Files created/changed, what each screen does, test count, any book snippet you could not
satisfy exactly, CORE CHANGES NEEDED.
