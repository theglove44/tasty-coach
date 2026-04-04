# MI-2026-03-30-interactive-launcher

## Title
Replaced the prompt-only launcher with a keyboard-driven terminal UI.

## Trigger / symptom
The user wanted a less manual, more user-friendly way to launch commands than typing `python main.py ...` flags by hand.

## Scope inspected
- `main.py` entrypoint and launch behavior
- Existing Rich-based output patterns across the app
- Current CLI flags and workflow ordering

## Commands run
- `sed -n '1,260p' main.py`
- `rg -n "from rich|import rich|Prompt|Confirm|Panel|Table|Console" .`
- `python -m py_compile main.py utils/launcher_ui.py`

## Files changed
- `main.py`
- `utils/launcher_ui.py`
- `README.md`

## Findings
- The project already depended on `rich`, but not on a full TUI framework.
- A full-screen keyboard-driven UI could be built without changing the trading logic by wrapping the existing agent actions.
- The app can safely default into the launcher only when stdin/stdout are interactive.
- The second pass added live market-status refresh and a searchable watchlist picker without changing the underlying scan or snapshot code.
- The latest pass added fuzzy watchlist matching, symbol previews on the picker, and a split-pane live scan renderer.
- The next pass added symbol-based watchlist filtering plus a dedicated symbol picker for the review-position flow.
- The latest pass made the market snapshot flow use the same symbol picker so it can source from watchlists, positions, or manual entry.

## Direct answers / conclusions
- The interface was improved without removing the existing CLI flags.
- Arrow-key navigation and shortcut keys are now available in the terminal launcher.

## Proposed surgical fix
- Keep the CLI for automation.
- Add a Rich-based launcher screen with keyboard navigation and direct action shortcuts.
- Keep account selection and prompt-driven subflows inside the launcher.
- Refresh the home screen on a timer so the market status panel stays current.
- Replace free-text watchlist entry with a filtered picker for scan/snapshot actions.
- Use fuzzy scoring to rank similar watchlists ahead of exact substring matching.
- Show selected watchlist symbols in a preview pane before confirmation.
- Render scan progress and current targets in a split live pane as batches complete.
- Allow symbol search from watchlists and open positions before running position review.
- Reuse the symbol picker for market snapshot so it is no longer limited to watchlist-only entry.

## Validation status
- Passed: `python -m py_compile main.py utils/launcher_ui.py`
- Passed: `python main.py --help`

## Current status / next steps
- The launcher now opens by default in an interactive terminal.
- If desired, this can be extended later with symbol completion or a more visual scan grid.
