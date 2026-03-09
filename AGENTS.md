# AGENTS.md — tasty-coach

## Project Overview

Tasty-coach automates Antivestor trading strategies on tastytrade. It scans for opportunities, manages positions, and monitors trades.

**Core Code:**
- `main.py` — Entry point, CLI args
- `agents/` — Strategy components (scanner, portfolio, reviewer, strategy, manager, gex)
- `utils/` — Infrastructure (tasty_client, dx_feed, market_schedule, roll_calculator)
- `position_monitor.py` — Automated position monitoring

**Config:**
- `.env` — API credentials (never commit)
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

# Run scanner (dry run)
python main.py --watchlist "My Watchlist" --dry-run

# Run with debug logging
python main.py --debug --watchlist "Test Watchlist"

# Check positions
python position_monitor.py
```

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
