"""`plugai-trade` command line (the commands printed in the book)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import typer

from . import BOOK_EDITION, __version__, config

app = typer.Typer(add_completion=False, no_args_is_help=False,
                  help="PlugAI-Trade — research, plan, paper-trade and review. Paper only.")
plugin_app = typer.Typer(help="Create and test plugins (Chapter 27).")
app.add_typer(plugin_app, name="plugin")

MAIN = Path(__file__).parent / "app" / "main.py"


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


@app.command()
def start(port: int = typer.Option(8501, help="Port for the dashboard."),
          page: str = typer.Option("", help="Open a specific page slug, e.g. lessons."),
          headless: bool = typer.Option(False, help="Do not open a browser."),
          classic: bool = typer.Option(False, help="Open the classic (Streamlit) view.")) -> None:
    """Launch the dashboard at http://localhost:PORT."""
    env = dict(os.environ)
    if page:
        env["PLUGAI_TRADE_START_PAGE"] = page
    url = f"http://localhost:{port}/{page}"
    typer.echo(f"PlugAI-Trade {__version__} → {url}   (Ctrl+C to stop)")
    if classic:
        cmd = [sys.executable, "-m", "streamlit", "run", str(MAIN), "--server.port", str(port),
               "--browser.gatherUsageStats", "false", "--server.headless", str(headless).lower()]
        raise typer.Exit(subprocess.call(cmd, env=env))
    if not headless:
        import threading
        import webbrowser
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    import uvicorn
    host = "0.0.0.0" if os.environ.get("PLUGAI_TRADE_HOME") == "/data" else "127.0.0.1"
    uvicorn.run("plugai_trade.api:app", host=host, port=port, log_level="warning")


@app.command()
def doctor() -> None:
    """Print versions and check data sources, models and the keychain."""
    from . import ai, data, keys, paper_guard
    typer.echo(f"PlugAI-Trade  {__version__}   ({BOOK_EDITION}: matches book edition ✓)")
    typer.echo(f"Python        {sys.version.split()[0]}")
    typer.echo(f"Lab folder    {config.home()}")
    st = ai.status()
    typer.echo(f"Ollama        {'reachable' if st['reachable'] else 'not found'} · model {st['model']}")
    typer.echo(f"Keychain      {'ready' if keys.keychain_ok() else 'NOT available'}")
    for s in data.sources():
        typer.echo(f"Data source   {s.name:<14} {s.tier:<11} needs: {s.needs}")
    ok = data.get("NIFTY", "IN", source="synthetic").height > 0
    typer.echo(f"Self-test     sample data {'OK' if ok else 'FAILED'}")
    typer.echo(f"Order code    {paper_guard.scan_package()}")


@app.command()
def lesson(n: int = typer.Argument(..., help="Chapter number, 1–34."),
           port: int = 8501) -> None:
    """Open the lesson for chapter N."""
    os.environ["PLUGAI_TRADE_LESSON"] = str(n)
    start(port=port, page="lessons", headless=False)


@app.command()
def fetch(source: str = typer.Argument(..., help="e.g. nse-bhavcopy, sec-edgar, yfinance"),
          date: str = typer.Option("", "--date", help="Trading date (YYYY-MM-DD) for file sources."),
          ticker: str = typer.Option("", "--ticker", help="Symbol / ticker."),
          market: str = typer.Option("IN", "--market")) -> None:
    """Download one data file or series into the local cache."""
    from . import data
    name = source.replace("-", "_")
    try:
        df = data.get(ticker or "NIFTY", market=market, start=date or None, end=date or None,
                      source=name, fallback=False)
    except data.DataUnavailable as exc:
        typer.echo(f"{name}: {exc}")
        raise typer.Exit(1)
    typer.echo(f"{name}: {df.height} rows · licence {df['license_class'][0] if df.height else '-'}")


@app.command()
def mcp() -> None:
    """Run the read-only / paper-only MCP server (for Claude Desktop)."""
    from . import mcp_server
    mcp_server.main()


@app.command()
def update() -> None:
    """Update dated reference tables; show what changed."""
    from . import updater
    updater.run(echo=typer.echo)


@app.command()
def backup(to: str = typer.Option("", "--to", help="Folder to write an encrypted backup."),
           restore: str = typer.Option("", "--restore", help="Backup file to restore.")) -> None:
    """Encrypted backup of the lab folder (keys are never included)."""
    from . import backup as bk
    if restore:
        typer.echo(bk.restore(Path(restore)))
    elif to:
        typer.echo(bk.create(Path(to)))
    else:
        typer.echo("Use --to FOLDER or --restore FILE")


@plugin_app.command("new")
def plugin_new(name: str, kind: str = typer.Option("report", "--kind",
                                                   help="report | strategy | screen")) -> None:
    """Create a plugin folder from the template."""
    from . import plugin
    typer.echo(plugin.new(name, kind))


@plugin_app.command("test")
def plugin_test(name: str) -> None:
    """Run a plugin's tests and the Plugin check."""
    from . import plugin
    report = plugin.check(name)
    typer.echo(report.text())
    raise typer.Exit(0 if report.passed else 1)


@app.command()
def version() -> None:
    typer.echo(__version__)


if __name__ == "__main__":
    app()
