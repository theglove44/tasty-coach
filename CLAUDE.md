# CLAUDE.md — Tasty-Coach Agent Instructions

## Global Memory

Read ~/.claude/CLAUDE.md for memory rules and topic files.

## What This Project Is

Tasty-coach is a Python 3.10+ options-trading assistant for a single Tastytrade
account. It scans watchlists for high-IVR opportunities, screens vertical/iron
condor strategy candidates, tracks positions and risk, calculates roll
scenarios, computes gamma exposure (GEX), and now includes an AI coach
(`claude-agent-sdk`) plus a local FastAPI web dashboard. It does not place
live orders itself — see Trading Safety Rules below.

Stack: `tastytrade` SDK **11.1.0** (pinned in `requirements.txt`; installed
version confirmed 11.1.0 — if you see a memory note claiming "SDK v12+",
that is stale/incorrect), `python-dotenv`, `pandas`, `rich`,
`claude-agent-sdk`, `fastapi` + `uvicorn` + `jinja2` + `sse-starlette` for the
dashboard.

## Relationship to AGENTS.md

- **AGENTS.md** is the terse, mechanical reference: build/test commands,
  mandatory skill triggers (`$trade-verification`, `$position-check`,
  `$backtest-runner`, `$log-analyzer`), and compatibility rules. Keep it in
  sync with this file when commands or safety rules change — AGENTS.md
  should never contradict this file.
- **CLAUDE.md** (this file) is the fuller picture: workflow philosophy, the
  full file/agent inventory, and the trading safety rules that both files
  must agree on.
- If the two ever drift, this file wins for safety rules; AGENTS.md wins for
  exact skill-trigger syntax.

## Workflow

### Plan Mode Default
- Enter plan mode for any non-trivial task (new strategies, significant code changes)
- Write specs upfront before implementing
- If something goes wrong, stop and re-plan — don't push through

### Subagent Strategy
- Use subagents for research, exploration, parallel analysis
- Keep main context clean for trading logic

### Self-Improvement Loop
- After any mistake or bug: update project memory (`~/.claude/projects/<mapped-path>/memory/MEMORY.md`) with the pattern
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

## Trading-Specific Rules (Safety-Critical — do not remove or weaken)

- Never execute real trades without explicit user approval — this codebase
  has no order-placement path today; if one is ever added, it must default
  to confirmation-required
- Document strategy changes in memory
- Review P/L after each session
- Respect PDT rule (max 3 day trades per 5 days for sub-$25k accounts)
- `agents/manager.py` RiskManager blocks execution when BP usage > 50%;
  only override with `--force` deliberately, not by default
- Credentials (Tastytrade OAuth client secret/refresh token, and any
  Anthropic/Claude OAuth token) live in `.env` — never read, print, commit,
  or paste its contents; refer to variables by name only

## Build, Test, Run (verified against the live repo)

```bash
# Activate environment
source venv/bin/activate

# Run the full test suite (556 tests collected as of this writing)
python -m pytest tests/

# Interactive launcher / menu
python main.py --menu

# Scan a watchlist for high-IVR candidates + strategy screening
python main.py --watchlist "My Watchlist"
python main.py --watchlist "My Watchlist" --force   # override RiskManager BP block

# On-demand single-symbol options research (bypasses IVR gate)
python main.py --research SYMBOL --format json

# Best trade ideas across watchlists
python main.py --best-trades --top 3

# AI coach (one-shot briefing or interactive chat)
python main.py --coach
python main.py --chat

# Web dashboard (FastAPI + chat sidebar)
python main.py --serve --host 127.0.0.1 --port 8766

# Debug logging
python main.py --debug --watchlist "Test Watchlist"

# Position monitor (standalone alerting daemon)
python position_monitor.py
```

Notes on the above:
- There is **no `--dry-run` flag** in `main.py`'s argument parser. An older
  doc referenced `--watchlist ... --dry-run`; that flag does not exist —
  don't use or re-document it. `--force` (override RiskManager blocks) is
  the closest real flag of that shape.
- `python -m pytest tests/` was confirmed to structurally collect (556
  tests) with no `pytest.ini`/`pyproject.toml` needed — plain pytest
  discovery in `tests/`.
- Full CLI surface is large (`--history`, `--transactions`, `--orders`,
  `--sync`, `--trades`, `--performance*`, `--pl-*`, `--equity-curve`,
  `--review-position`, `--timeline`, `--dashboard`, `--alerts`, `--account`,
  etc.) — run `python main.py --menu` or read `setup_argument_parser()` in
  `main.py` for the authoritative, current list rather than trusting any
  doc snapshot, including this one.

## Key Files

### Entry points
- `main.py` — CLI orchestrator; all flags defined in `setup_argument_parser()`
- `position_monitor.py` / `position_monitor.sh` — standalone position alerting daemon (runs during market hours, alerts via Telegram)

### `agents/` — one class per concern (17 modules)
- `scanner.py` — watchlist resolution & IVR filtering
- `portfolio.py` — position tracking & reporting (async `init()`)
- `strategy.py` — vertical/iron-condor screening & entry logic
- `manager.py` — RiskManager: BP usage, NLV, day-trade excess, portfolio delta/theta; blocks execution above 50% BP usage (async `init()`)
- `gex.py` — Gamma Exposure (GEX): call/put walls, zero-gamma level, GEX_REVERSION_THRESHOLD signals
- `reviewer.py` — position review & roll-scenario generation
- `advisor.py` — per-position action advisor
- `alerts.py` — alert collection & filtering for risk management
- `analytics.py` — performance metrics & equity curve from local trade history
- `history.py` — account history: performance reporting, transaction/order management
- `timeline.py` — event classification & roll annotation for the position timeline
- `options_researcher.py` — on-demand symbol research (bypasses IVR gate); powers `--research` and `--best-trades`
- `trade_ranker.py` — watchlist-wide trade ranking orchestrator; powers `--best-trades`
- `dashboard.py` — "Should I Be Trading Today?" market-quality scoring (5 pillars: Volatility, Trend, Breadth, Momentum, Macro)
- `dashboard_html.py` — HTML renderer for the Market Quality Dashboard (standalone dark-themed export, distinct from `server/`)
- `coach.py` — AI coach: Claude Agent SDK driving tasty-coach as in-process tools; one-shot briefing (`--coach`) and REPL (`--chat`)
- `coach_context.py` — shared runtime context for the AI coach (live session, resolved account, journal path)
- `coach_tools.py` — tool wrappers exposing existing tasty-coach agents to the Claude Agent SDK
- `agents/prompts/` — prompt templates used by the coach agents

### `utils/` — infrastructure
- `tasty_client.py` — OAuth authentication & session management (reads Tastytrade credentials from `.env`)
- `roll_calculator.py` — pure roll-scenario calculations (down/out/down-and-out), no API calls
- `market_schedule.py` — market session timing
- `dx_feed.py` — real-time data streaming (dxLink/DXLinkStreamer)
- `db.py` — local trade-history database
- `journal.py` — trade journal (recommendations persisted via `--journal`)
- `trade_grouper.py` — groups raw transactions into logical trades
- `alert_store.py` — persisted alert storage backing `--alerts`
- `settings.py` — runtime-tunable settings (exposed via dashboard `/api/settings`)
- `launcher_ui.py`, `dashboard_ui.py`, `timeline_ui.py` — terminal UI rendering for `--menu`, `--dashboard`, `--timeline`
- `correlation_buckets.py`, `sector_map.py` — exposure/correlation grouping for risk checks
- `redact.py` — log/output redaction helper

### `server/` — FastAPI web dashboard
- `server/app.py` — FastAPI app (`create_app()`); routes include `/`, `/api/snapshot`, `/api/watchlists`, `/api/scan/start`+`/api/scan/status` (best-trades scan), `/api/briefing` (SSE), `/api/chat`+`/api/chat/reset` (SSE), `/api/settings`(+`/reset`), `/api/journal`; token-gated except for loopback requests; started via `python main.py --serve`
- `server/snapshot.py` — snapshot data assembly for the dashboard
- `server/templates/dashboard.html` — Jinja2 template for the dashboard shell
- `server/static/chat.js` — frontend chat/SSE client for the coach sidebar
- `server/static/style.css` — dashboard styling

### `.agents/skills/` — mandatory skills referenced from AGENTS.md
- `trade-verification/` (with `scripts/verify.sh`), `position-check/`, `backtest-runner/`, `log-analyzer/` — see AGENTS.md for when each is required

### Tests
- `tests/` — pytest suite, plain discovery (no `pytest.ini`/`pyproject.toml`), run with `python -m pytest tests/`

## Memory

- Project memory lives outside the repo at
  `~/.claude/projects/-Users-office-Projects-tasty-coach/memory/MEMORY.md`
  (and `project_best_trades.md` for the Best-Trades initiative) — treat it
  as more current than this file for API quirks, thresholds, and constants,
  and pull anything durable forward into this file when you touch it.
- Document API quirks, rate limits, session issues there
- Track strategy performance metrics there
