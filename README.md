# PlugAI-Trade

**The free companion lab for the book *Trading with AI – For All Levels*.**
Research, plan, paper-trade and review, for India and US markets, on your own computer.

> **Paper only.** PlugAI-Trade never places, modifies or cancels a real order. It has no
> order-placement code at all, and a test (`paper_guard`) scans the whole package on every build
> to keep it that way. Broker connections are read-only. The word "order" appears only as
> "paper order".

PlugAI-Trade gathers data, computes numbers in code and lets an AI model *explain* them. The model
never computes a number; every figure it quotes is one the lab computed, and **Show sources**
reveals it. Nothing the AI proposes is applied until you click **Accept**.

It opens in your browser at `http://localhost:8501`, runs offline on synthetic sample data, and
uses a local model through [Ollama](https://ollama.com) by default. Cloud models are optional.

## Screenshots

Screenshots are added with each release. Planned set:

1. Home — first-run wizard (memory check, suggested model, self-test)
2. Home — dashboard with sample watchlists and session clock
3. Today › Daily Briefing with ✓ / ? flags and Show sources
4. Strategy › Backtest Report with the HYPOTHETICAL watermark and Report Card
5. Derivatives › Options Strategy Builder — What you're paying for tiles
6. Paper Trading › Paper Desk — paper order ticket, kill switch
7. Journal › Weekly Review
8. Lessons › Lessons — Check my work
9. Lessons › Prompt Library
10. Settings › AI Models — Fit check and Use for routing
11. Settings › Security — checklist and audit log

## Install

PlugAI-Trade runs on Windows 10/11, macOS and Linux. The installer, [uv](https://docs.astral.sh/uv/),
downloads Python for you.

```bash
# once the package is on PyPI
uv tool install plugai-trade

# until then, straight from GitHub
uv tool install git+https://github.com/bhanumahesh1993/plugai-trade

plugai-trade start            # opens http://localhost:8501
```

Optional extras: `uv tool install "plugai-trade[cloud]"` (cloud models through LiteLLM),
`[yahoo]` (yfinance), `[crypto]` (CCXT), `[ml]` (scikit-learn), or `[all]`.

The first start runs a five-screen **first-run wizard**: it checks your RAM, disk and Ollama,
suggests a local model (8 GB → a small 4B model, 16 GB → a 9B model, 32 GB or more → a larger
one), offers an optional cloud key (**Skip for now** is fine), loads synthetic sample data and runs
a ten-second **self-test** (sample data loaded, average computed, model quoted it, keychain ready,
paper ledger empty, no order code).

### Docker

```bash
docker run -p 8501:8501 -v plugai-data:/data ghcr.io/bhanumahesh1993/plugai-trade
```

Your lab folder lives in the `/data` volume. To use Ollama on the host, the image sets
`OLLAMA_HOST=http://host.docker.internal:11434`; on Linux add
`--add-host=host.docker.internal:host-gateway`. Update with `docker pull` and restart.

## Commands

| Command | Does |
|---|---|
| `plugai-trade start` | Launch the dashboard at `localhost:8501` |
| `plugai-trade start --port 8502` | Launch on another port if 8501 is busy |
| `plugai-trade start --page lessons` | Open a specific screen |
| `plugai-trade doctor` | Print versions; check data sources, models and the keychain; "matches book edition ✓" |
| `plugai-trade lesson 22` | Open the lesson for a chapter (here 22) |
| `plugai-trade fetch nse-bhavcopy --date 2026-05-29` | Download one NSE bhavcopy |
| `plugai-trade fetch sec-edgar --ticker AAPL` | Download one company's EDGAR facts |
| `plugai-trade mcp` | Run the read-only / paper-only MCP server (Claude Desktop) |
| `plugai-trade update` | Update dated reference tables; print changed rows |
| `plugai-trade plugin new gap_report --kind report` | Create a plugin from a template |
| `plugai-trade plugin test gap_report` | Run a plugin's checks and tests |
| `plugai-trade backup --to <folder>` | One encrypted backup (keys are never included) |
| `plugai-trade backup --restore <file>` | Restore from a backup |

## Data sources and licences

Every bar carries a provenance tag (source, fetch time, licence class). Sources that disagree by
more than 0.5% are flagged. Only free sources are built in; tiers as shown in
**Settings › Data Sources**:

| Tier | Sources | Licence class |
|---|---|---|
| No signup | Synthetic (offline default), NSE bhavcopy, BSE bhavcopy, AMFI NAV, yfinance, SEC EDGAR, Frankfurter FX, Crypto public (CCXT), NSE/BSE announcements RSS, GDELT news | public / personal-use |
| Free key | Alpaca (US, paper account, IEX), FRED, Finnhub, Tiingo, Massive | per provider terms |
| Your broker (India, read-only) | Upstox, Fyers, Angel One SmartAPI, ICICI Breeze; Zerodha Kite, Dhan, Groww (paid data plans) | broker |

Personal-use and broker data stay on your computer and are never committed to git. Check each
provider's terms before you publish anything built on its data. Dated facts (lot sizes, fees, tax
rates, sessions) come from the reference tables that `plugai-trade update` refreshes.

## Safety design

- **No order code.** Paper trading only; `paper_guard` fails the build if order-placement calls appear.
- **The model never computes.** Numbers come from code; AI output passes an output filter that
  removes buy/sell/target language.
- **Keys in the OS keychain** (macOS Keychain, Windows Credential Manager, Linux Secret Service).
  Only the last four characters are shown; keys with trade or withdraw permission are refused.
- **Privacy defaults:** journal, holdings and tax use the local model only; the lab asks before any
  cloud call; account numbers, PAN, Aadhaar and SSN are stripped before cloud calls; crash reports off.
- **Friction on decisions, none on content:** nothing the AI proposes changes your plan, rules or
  journal until you click **Accept**.
- **HYPOTHETICAL** watermark on every chart and backtest; every alert is labelled SIMULATED.
- **Audit log** of every key use, data fetch, AI call and MCP call (Settings › Security).

## The book

*Trading with AI – For All Levels* by Bhanu Mahesh. Every chapter has a matching lesson
(`plugai-trade lesson N`), and every code block in the book runs against the tag `book-v1.0`.
See [docs/USER-GUIDE.md](docs/USER-GUIDE.md) for a screen-by-screen guide keyed to the chapters.

## Development

```bash
uv venv && uv pip install -e ".[dev]"
.venv/bin/pytest -q            # offline; no Ollama, keys or network needed
```

## Licence

Apache-2.0. See [LICENSE](LICENSE).

## Disclaimer

PlugAI-Trade is an education and research tool. **It is not investment advice** and does not
recommend buying, selling or holding any security. All backtests, paper trades and projections are
**hypothetical** and do not represent actual trading; past or simulated results do not guarantee
future results. Trading involves risk of loss. Tax outputs are drafts for your CA / CPA. Check
facts against official sources, and make your own decisions.
