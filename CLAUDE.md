# CLAUDE.md — Tasty-Coach Agent Instructions

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
- `utils/tasty_client.py` — OAuth authentication and session management
- `utils/roll_calculator.py` — Roll scenario calculations
- `utils/market_schedule.py` — Market session timing
- `utils/dx_feed.py` — Real-time data streaming (dxLink)
- `position_monitor.py` — Automated position monitoring and alerts

## Memory

- Update `MEMORY.md` (auto-memory, persists across conversations)
- Document API quirks, rate limits, session issues
- Track strategy performance metrics
