# PlugAI-Trade — design system (v2 UI)

## Brief
A research, planning and paper-trading lab for retail traders in India and the US who are new
to AI. Primary job: make the numbers the lab computes easy to read and easy to trust, and keep
the AI in the role of explainer. It must feel like a serious trading tool (the reader already
uses Kite, Groww, Robinhood, TradingView) but never like a trading *terminal that sells*.
Paper only — no screen may look like it can send a real order.

## The one memorable thing
**Cited explanations.** Every number is a *fact tile*. When the AI explains, each sentence carries
small citation chips (`1`, `2`…) and hovering a chip lights up the exact tile it came from. The
"model explains, the lab computes" rule becomes something you can see. Everything else stays
quiet and disciplined.

## Themes (switchable, same tokens)
| Token | Book (light) | Desk (dark) | Use |
|---|---|---|---|
| `bg` | `#F4F6FB` cool paper | `#0F1A2B` night ink (navy, not black) | app background |
| `panel` | `#FFFFFF` | `#152338` | panels, tiles |
| `line` | `#DCE3EE` | `#233451` | borders, grid |
| `ink` | `#1B2437` (book ink) | `#E7EDF6` | text |
| `muted` | `#5B6780` | `#8FA0BA` | secondary text |
| `indigo` | `#4F46E5` | `#8B8FFF` | primary action, focus, AI |
| `bull` | `#15803D` | `#34C27A` | profit / up only |
| `bear` | `#DC2626` | `#F2626A` | loss / down only |
| `saffron` | `#E8710A` | `#F59A3C` | India market |
| `navy` | `#1E3A8A` | `#7AA2F7` | US market |

Rules: bull/bear only ever mean P&L or direction. Saffron/navy only ever mean market. Indigo is
the single interactive colour. No gradients as decoration; the only gradient is none.

## Type
- **IBM Plex Sans** (UI, labels, all numbers with `tabular-nums`) — finance-born, crisp at small
  sizes, distinct from the book's Inter so the app has its own voice.
- **Source Serif 4** (AI explanations and lesson prose only) — the same serif as the book body,
  so "reading" text looks like the book and "data" text looks like a tool.
- Scale (px): 12 · 13 · 14 (base UI) · 16 · 20 · 26 · 34 (hero figures). Weights 400/500/600.
- Labels in sentence case. No tracked-out caps eyebrows. No monospace data labels.

## Layout
```
┌──────────┬───────────────────────────────────────────────────────────┐
│ PlugAI   │  Options Strategy Builder          [IN|US] data ● AI ● $  │  top bar
│ Today    ├───────────────────────────────────────────────────────────┤
│ Research │  legs panel      │  payoff / chart (hero)   │ fact tiles   │
│ Strategy │  (inputs)        │                          │ + Explain    │
│ …        │                  │                          │   drawer     │
│ Settings │                  ├──────────────────────────┤              │
│ theme ◐  │                  │  scenarios / table       │              │
└──────────┴───────────────────────────────────────────────────────────┘
```
- Left-aligned everything; numbers right-aligned in tables, tiles left-aligned label over value.
- Radius hierarchy: 4px inputs/chips, 8px tiles, 12px panels. Hairline 1px borders; shadows only
  on floating layers (menus, drawer).
- Density: the Desk theme uses 8px grid with compact rows; Book theme 1.25× spacing.

## Principles
1. **Numbers first, words second.** The biggest thing on a screen is the figure the chapter teaches
   (breakeven, drawdown, R, cost), never a heading.
2. **Provenance is visible.** Data status shows the source and age; every AI sentence cites.
3. **Paper is obvious.** Paper Desk has a persistent "Paper" band in the ticket; buttons say
   "Place paper order", never "Buy".
4. **Calm motion.** Only motion that answers an action (drawer opens, tile highlights on citation
   hover). Respect reduced motion.
5. **Same words as the book.** Screen, tab and button names are exactly the book's.

## Review against generic defaults (what changed)
- First draft used a near-black `#0B0B0B` dark theme with a single acid-green accent → replaced by
  navy "night ink" and the book's indigo so the app visibly belongs to the book.
- First draft had caps eyebrow labels on every panel → removed; panel titles are sentence case.
- First draft used a mono face for figures → replaced by Plex Sans tabular numerals.
- Identical SaaS cards everywhere → tiles, panels and the chart hero now differ in radius, fill and
  weight by their role.
