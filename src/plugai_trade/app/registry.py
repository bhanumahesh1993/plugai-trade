"""Every screen in the sidebar, in book order. Names match the book exactly."""

from __future__ import annotations

# (section, screen title, module under plugai_trade.app.pages, icon, url slug)
SCREENS: list[tuple[str, str, str, str, str]] = [
    ("Today", "Daily Briefing", "daily_briefing", ":material/wb_sunny:", "briefing"),
    ("Research", "Document Desk", "document_desk", ":material/description:", "documents"),
    ("Research", "Screener", "screener", ":material/filter_alt:", "screener"),
    ("Research", "Score-Tester", "score_tester", ":material/rule:", "score-tester"),
    ("Research", "Chart Helper", "chart_helper", ":material/candlestick_chart:", "chart-helper"),
    ("Research", "Earnings Desk", "earnings_desk", ":material/event:", "earnings"),
    ("Research", "IPO Dashboard", "ipo_dashboard", ":material/rocket_launch:", "ipo"),
    ("Strategy", "Strategy Builder", "strategy_builder", ":material/construction:", "strategy-builder"),
    ("Strategy", "Backtest Report", "backtest_report", ":material/analytics:", "backtest-report"),
    ("Strategy", "Trend Lab", "trend_lab", ":material/trending_up:", "trend-lab"),
    ("Strategy", "Pairs Lab", "pairs_lab", ":material/compare_arrows:", "pairs-lab"),
    ("Plan & Risk", "Trade Plan", "trade_plan", ":material/edit_note:", "trade-plan"),
    ("Plan & Risk", "Position Sizer", "position_sizer", ":material/straighten:", "position-sizer"),
    ("Plan & Risk", "Rule Card", "rule_card", ":material/fact_check:", "rule-card"),
    ("Paper Trading", "Paper Desk", "paper_desk", ":material/receipt_long:", "paper-desk"),
    ("Paper Trading", "Alerts", "alerts", ":material/notifications:", "alerts"),
    ("Derivatives", "Options Strategy Builder", "options_builder", ":material/show_chart:", "options"),
    ("Derivatives", "Futures & Roll", "futures_roll", ":material/sync_alt:", "futures"),
    ("Derivatives", "Contract Table", "contract_table", ":material/table_chart:", "contract-table"),
    ("Portfolio", "Portfolio Reviewer", "portfolio_reviewer", ":material/pie_chart:", "portfolio"),
    ("Portfolio", "Crypto Monitor", "crypto_monitor", ":material/currency_bitcoin:", "crypto"),
    ("Portfolio", "Forecast Journal", "forecast_journal", ":material/percent:", "forecasts"),
    ("Journal", "Trades", "trades", ":material/list_alt:", "trades"),
    ("Journal", "Weekly Review", "weekly_review", ":material/summarize:", "weekly-review"),
    ("Journal", "Ask My Journal", "ask_journal", ":material/forum:", "ask-journal"),
    ("Tax", "Tax Export", "tax_export", ":material/request_quote:", "tax"),
    ("Automate", "Scheduler", "scheduler", ":material/schedule:", "scheduler"),
    ("Automate", "News Pipeline", "news_pipeline", ":material/newspaper:", "news"),
    ("Automate", "ML Lab", "ml_lab", ":material/science:", "ml-lab"),
    ("Automate", "Agents", "agents", ":material/groups:", "agents"),
    ("Automate", "Plugins", "plugins", ":material/extension:", "plugins"),
    ("Lessons", "Lessons", "lessons", ":material/school:", "lessons"),
    ("Lessons", "Prompt Library", "prompt_library", ":material/library_books:", "prompts"),
    ("Settings", "Data Sources", "data_sources", ":material/database:", "data-sources"),
    ("Settings", "AI Models", "ai_models", ":material/smart_toy:", "ai-models"),
    ("Settings", "Keys", "keys_page", ":material/key:", "keys"),
    ("Settings", "MCP Server", "mcp_server", ":material/hub:", "mcp"),
    ("Settings", "Privacy", "privacy", ":material/lock:", "privacy"),
    ("Settings", "Security", "security", ":material/shield:", "security"),
    ("Settings", "Workspace", "workspace", ":material/dashboard_customize:", "workspace"),
]

SECTIONS: list[str] = []
for _s, *_ in SCREENS:
    if _s not in SECTIONS:
        SECTIONS.append(_s)
