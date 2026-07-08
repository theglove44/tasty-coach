# AGENTS.md — tasty-coach

This is the terse, mechanical reference (build/test commands, mandatory
skill triggers, compatibility rules). For the full picture — workflow
philosophy, the complete `agents/`/`utils/`/`server/` inventory, and the
authoritative trading safety rules — see `CLAUDE.md` in this same directory.
If this file and CLAUDE.md ever disagree, CLAUDE.md's safety rules win.

## Project Overview

Tasty-coach is a Python assistant for a single Tastytrade account. It scans
watchlists for opportunities, screens strategies, manages/monitors
positions, and (as of the AI-coach + dashboard additions) offers a
Claude-Agent-SDK coach and a local FastAPI web dashboard. See CLAUDE.md for
the current 17-file `agents/` inventory and the `server/` dashboard layout.

**Core Code:**
- `main.py` — Entry point, CLI args (run `python main.py --menu` or read
  `setup_argument_parser()` for the current, authoritative flag list)
- `agents/` — Strategy + coach components (scanner, portfolio, reviewer,
  strategy, manager, gex, coach, options_researcher, trade_ranker, etc. —
  see CLAUDE.md for the full list)
- `utils/` — Infrastructure (tasty_client, dx_feed, market_schedule, roll_calculator, settings, db, journal, ...)
- `server/` — FastAPI web dashboard (`app.py`, `templates/`, `static/chat.js`)
- `position_monitor.py` — Automated position monitoring

**Config:**
- `.env` — Tastytrade OAuth credentials and Claude OAuth token (never commit, never read/print contents)
- Cron jobs manage start/stop

## Mandatory Skill Usage

- Run `$trade-verification` before committing changes to `agents/strategy.py`, `agents/scanner.py`, or entry/exit logic
- Run `$position-check` when debugging position discrepancies or unexpected fills
- Use `$log-analyzer` when reviewing trade logs or diagnosing issues in `tasty_auto.log`
- Run `$backtest-runner` after strategy parameter changes

## Build and Test

```bash
# Activate environment
source venv/bin/activate

# Run tests
python -m pytest tests/

# Run scanner
python main.py --watchlist "My Watchlist"

# Run with debug logging
python main.py --debug --watchlist "Test Watchlist"

# Check positions
python position_monitor.py
```

Note: there is no `--dry-run` flag in `main.py` — an earlier version of this
doc referenced one that never existed in the argument parser. Use `--force`
to override RiskManager BP-usage blocks when you explicitly mean to; there
is no separate simulate-only mode for the scanner today.

## Trading Rules (Critical)

- **Never execute real trades without explicit user approval**
- **Paper trade strategy changes before live deployment**
- **Respect PDT rule** (max 3 day trades per 5 days for sub-$25k accounts)
- **Log every order attempt** with timestamp and rationale
- **Validate position size** against buying power before entry

## Code Standards

- All functions must have docstrings
- Error handling for all API calls
- Type hints for function parameters
- Never commit credentials or API keys
- Use environment variables for sensitive data

## Compatibility Rules

- Preserve existing CLI argument behavior
- Don't break cron job interfaces
- Maintain log format consistency for monitoring
- Test OAuth flow after any auth changes

## Key Patterns

- Scanner returns opportunities → Strategy filters → Manager sizes → Execution
- All orders logged to `tasty_auto.log`
- Position monitor runs independently, alerts via Telegram
- Use `utils/tasty_client.py` for all API calls (handles OAuth refresh)

## When to Ask User

- Before executing any real trades
- When strategy logic changes affect risk
- When uncertain about position sizing
- Before modifying cron schedules
