# UI build contract — PlugAI-Trade v2 (FastAPI + React)

Repo: `/Users/bhanumahesh/book/Trading/plugai-trade`. Read, in order:
1. `docs/DESIGN.md` — the design system (Book/Desk themes, type, principles). Follow it exactly.
2. This file.
3. The finished reference screens: `web/src/pages/screens/options.tsx`, `paper-desk.tsx`,
   `backtest-report.tsx`, `web/src/pages/Home.tsx`, and their routes in
   `src/plugai_trade/api/routes/{options,paper,backtest,core}.py`.
4. The shared kit: `web/src/components/{ui,kit,facts,charts,shell,theme}.tsx`, `web/src/lib/*`.
5. For each of your screens, the **classic Streamlit page** `src/plugai_trade/app/pages/<module>.py`
   and the engine modules it calls. **Feature parity is required**: every tab, button, tile, table,
   input and flow in the classic page must exist in the new screen, with the same names (the book
   prints them). Also read the book chapter's `#in-lab(...)` walkthroughs for your screens
   (`grep -n "<Screen name>" /Users/bhanumahesh/book/Trading/manuscript/chapters/*.typ`) — each
   numbered step must be doable in the new UI.

## Architecture
- **API**: one module per area in `src/plugai_trade/api/routes/<area>.py` exposing
  `router = APIRouter()`; it is included automatically. Paths `/api/<area>/...`. Pydantic request
  models. Return JSON-safe data via `from .. import clean` (`clean(obj)`). Errors:
  `HTTPException(400, "plain-English reason")`. Routes are thin: call the engine modules
  (`plugai_trade.<module>`), never re-implement maths. Store writes go through the same engine
  functions the classic page uses.
- **UI**: one file per screen at `web/src/pages/screens/<slug>.tsx` with a default-export
  component; the router and the sidebar's "new design" dot pick it up automatically. Slugs are
  in `web/src/screens.ts` (do not change them). Area-specific components go in
  `web/src/components/<area>/`.
- Data fetching with TanStack Query (`useQuery` / `useMutation`, `get`/`post` from `@/lib/api`).
  Market from `useMarket()` (`@/components/shell`). Money with `money(x, market)`.

## Design rules (from DESIGN.md — the review checks these)
- Numbers first: the figure the chapter teaches is the biggest thing on screen (a `FactTile big`).
- Every AI output uses `ExplainPanel` with `facts` from the engine (`.facts()`), so citations light
  the matching `FactTile` (tile label must equal the text before `:` in the fact). Wrap the screen
  in `<FactsProvider>`.
- Nothing the AI proposes is applied until the user clicks **Accept**.
- Every backtest / paper / simulated chart or result shows `<Hypothetical />`.
- Colour semantics: bull/bear only for P&L or direction; saffron/navy only for market; indigo is
  the only action colour. Use `Badge`, `Callout`, `DataTable`, `EmptyState`, `Switch`, `Segmented`,
  `Select`, `Textarea`, `Dialog`, `useToast`, `EChart`/`chartTokens`, `ScreenGrid` from `kit.tsx`.
- Sentence-case labels. No ALL-CAPS eyebrows, no "A · B · C" middle-dot meta strings, no "→" on
  buttons, no monospace data labels, no decorative gradients, no emoji.
- Buttons name the action ("Save to journal", "Place paper order"); toasts repeat it ("Saved to journal").
- Empty states tell the user what to do next. Errors say what happened and how to fix it.
- Paper only: never a "Buy"/"Sell" button that could read as a real order — use "Place paper order".
- Responsive down to 1024 px; keyboard focus visible; no layout shift on data load.

## Files you may edit
Only: your `api/routes/<area>.py`, your `web/src/pages/screens/<slug>.tsx` files, new files in
`web/src/components/<area>/`, and `tests/test_api_<area>.py`. **Do not edit** shared files
(`api/__init__.py`, other areas' routes, `components/{ui,kit,facts,charts,shell,theme}.tsx`,
`main.tsx`, `screens.ts`, `styles.css`, `vite.config.ts`, engine modules, `pyproject.toml`). If
you need a shared change, work around it locally and list it under "SHARED CHANGES NEEDED".
Do **not** run `vite build` (it writes the shared bundle); the integrator builds.

## QA (mandatory before you report)
1. `tests/test_api_<area>.py` with FastAPI `TestClient` covering every route (offline; the suite's
   conftest sets `PLUGAI_TRADE_OFFLINE=1` and a temp lab folder). `.venv/bin/pytest -q` green.
2. `cd web && npx tsc -p tsconfig.app.json --noEmit` — zero errors.
3. Visual check with your **own ports** (given in your task):
   ```bash
   PLUGAI_TRADE_OFFLINE=1 PLUGAI_TRADE_HOME=<scratch>/lab .venv/bin/uvicorn plugai_trade.api:app --port <API_PORT> &
   cd web && PLUGAI_API=http://127.0.0.1:<API_PORT> WEB_PORT=<WEB_PORT> npx vite --host 127.0.0.1 &
   .venv/bin/python scripts/shot.py http://127.0.0.1:<WEB_PORT>/<slug> <scratch>/<slug>-book.png [--click "Button"]
   .venv/bin/python scripts/shot.py http://127.0.0.1:<WEB_PORT>/<slug> <scratch>/<slug>-desk.png --dark
   ```
   **Look at every screenshot** (Read tool), in both themes and after the main actions. Fix
   overlaps, clipped text, empty panels, misaligned numbers, console errors printed by shot.py.
   Stop your servers when done.
4. Final report: screens built, routes, parity checklist per screen (classic feature → new
   location), tests, SHARED CHANGES NEEDED.
