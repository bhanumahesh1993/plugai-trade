"""HTTP API for the React UI. Thin: every number comes from the engine modules.

Run with ``plugai-trade start`` (serves the built UI and this API on one port).
"""

from __future__ import annotations

import math
import warnings
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__

# Synthetic fallback is expected offline; the UI shows the source instead of a warning.
warnings.filterwarnings("ignore", message=".*live sources unavailable.*")

app = FastAPI(title="PlugAI-Trade", version=__version__, docs_url="/api/docs",
              openapi_url="/api/openapi.json")
DIST = Path(__file__).resolve().parent.parent / "web_dist"


def clean(x: Any) -> Any:
    """JSON-safe: numpy scalars → float, NaN/inf → None, dates → iso."""
    if isinstance(x, dict):
        return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if isinstance(x, (date, datetime)):
        return x.isoformat()
    if hasattr(x, "item") and not isinstance(x, (str, bytes)):
        try:
            x = x.item()
        except Exception:
            return str(x)
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    return x



# Every module in api/routes/ exposes `router`; each screen area owns one module.
import importlib as _importlib
import pkgutil as _pkgutil

from . import routes as _routes

for _m in sorted(_pkgutil.iter_modules(_routes.__path__), key=lambda m: m.name):
    app.include_router(_importlib.import_module(f"{__name__}.routes.{_m.name}").router)


# ------------------------------------------------------------------ static UI
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = DIST / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
