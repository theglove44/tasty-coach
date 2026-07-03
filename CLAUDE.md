# CLAUDE.md — Tasty-Coach Agent Instructions

## Development

### Run tests
```
venv/bin/python -m unittest discover tests
```
~590 tests across `tests/`, runs in ~5-6s. Run this after any change to `agents/*.py` or
`utils/*.py` before considering a task done (a `PostToolUse` hook also runs it automatically —
see `.claude/settings.local.json`).

### Run the app
```
./venv/bin/python main.py --test-connection    # verify API connectivity
./venv/bin/python main.py --best-trades        # rank best trade ideas across watchlists
./venv/bin/python main.py --serve              # run the web dashboard (FastAPI + chat sidebar), http://127.0.0.1:8766
./venv/bin/python main.py --help               # full flag reference
```
Other common flags: `--dashboard --html` (market quality dashboard, no account needed),
`--menu` (interactive command menu), `--coach` / `--chat` (AI coach briefing/REPL),
`--review-position SYMBOL` (roll scenarios), `--home` (unified account dashboard).

### Branch → PR → merge
- Create a feature branch per task: `git checkout -b <topic>`
- Commit as you go with focused messages
- Open a PR with `gh pr create`; merge with `gh pr merge` once checks/tests pass
- `gh pr view` to check status/comments before merging

## Workflow

### Plan Mode Default
- Enter plan mode for any non-trivial task (new strategies, significant code changes)
- Write specs upfront before implementing
- If something goes wrong, stop and re-plan — don't push through

### Subagent Strategy
- Use subagents for research, exploration, parallel analysis
- Keep main context clean for trading logic

### Self-Improvement Loop
- After any mistake or bug: update `MEMORY.md` (auto-memory) with the pattern
- Document what went wrong and how to prevent it
- Review relevant lessons before major work

### Verification Before Done
- Never mark complete without testing
- Run the code, check logs, verify correctness
- For strategy changes: backtest or paper trade first

### Demand Elegance
- If a fix feels hacky, ask "is there a cleaner way?"
- Skip for simple fixes — don't over-engineer

## Task Management

1. **Plan First**: Write what needs doing
2. **Verify**: Check approach before implementing
3. **Track**: Mark progress as you go
4. **Document**: Update memory after learnings

## Core Principles

- **Simplicity First**: Minimal code changes
- **No Hacky Fixes**: Find root causes
- **Test Before Deploy**: Paper trade first
- **Log Everything**: Record trade decisions and outcomes

## Trading-Specific Rules

- Never execute real trades without explicit user approval
- Document strategy changes in memory
- Review P/L after each session
- Respect PDT rule (max 3 day trades per 5 days for sub-$25k accounts)

## Key Files

- `main.py` — Entry point, CLI args
- `agents/scanner.py` — IVR scanning, watchlist resolution
- `agents/portfolio.py` — Position tracking
- `agents/reviewer.py` — Position review and roll suggestions
- `agents/strategy.py` — Strategy screening and entry logic
- `agents/manager.py` — Risk management (BP usage, position sizing)
- `agents/gex.py` — Gamma exposure analysis
- `agents/dashboard.py` — Market Quality Dashboard ("Should I Be Trading?")
- `agents/dashboard_html.py` — HTML rendering for the dashboard
- `agents/analytics.py` — Trading performance analytics (P/L, equity curve)
- `agents/history.py` — Account history / transaction review
- `agents/trade_ranker.py` — `--best-trades` / `--put-selector` ranking logic
- `agents/options_researcher.py` — `--research` options chain analysis
- `agents/advisor.py`, `agents/coach.py`, `agents/coach_context.py`, `agents/coach_tools.py` — AI coach (`--coach`/`--chat`)
- `agents/timeline.py`, `agents/alerts.py` — event timeline and persisted alerts
- `server/app.py` — FastAPI app backing `--serve` (web dashboard + chat sidebar)
- `utils/tasty_client.py` — OAuth authentication and session management
- `utils/roll_calculator.py` — Roll scenario calculations
- `utils/market_schedule.py` — Market session timing
- `utils/dx_feed.py` — Real-time data streaming (dxLink)
- `utils/db.py` — Local SQLite persistence (trade history sync)
- `utils/trade_grouper.py` — Groups raw transactions into trade lifecycles
- `utils/launcher_ui.py` — Interactive `--menu` command launcher
- `utils/dashboard_ui.py`, `utils/timeline_ui.py` — Rich-based terminal rendering
- `utils/settings.py` — User-configurable defaults (best-trades thresholds, etc.)
- `utils/redact.py` — Screenshot-safe output redaction
- `position_monitor.py` — Automated position monitoring and alerts

## Memory

- Update `MEMORY.md` (auto-memory, persists across conversations)
- Document API quirks, rate limits, session issues
- Track strategy performance metrics
