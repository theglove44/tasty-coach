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
- After any mistake or bug: update `memory/projects/tasty-coach.md` with the pattern
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

- Always use paper_trades.csv for tracking
- Never execute real trades without explicit user approval
- Document strategy changes in memory
- Review P/L after each session
- Respect PDT rule (max 3 day trades per 5 days for sub-$5k accounts)

## Key Files

- `main.py` — Entry point, CLI args
- `agents/scanner.py` — IVR scanning, watchlist resolution
- `agents/portfolio.py` — Position tracking
- `agents/reviewer.py` — Position review and roll suggestions
- `paper_trades.csv` — Trade history

## Memory

- Update `memory/projects/tasty-coach.md` with lessons learned
- Document API quirks, rate limits, session issues
- Track strategy performance metrics
