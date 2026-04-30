# tasty-coach Project Scope

## Goal
Turn tasty-coach into a practical decision-support tool for options traders: fast, clear, and actually useful.

## Current State
The app already has a lot of the right plumbing. It is *not* starting from zero.

### Already in place
- CLI entry point with a broad command set
- Interactive terminal launcher
- Portfolio health checks
- Performance reporting (weekly / monthly / yearly)
- Trade history / order history / transaction history
- Position review with roll scenario analysis
- Watchlist IVR scanning
- Strategy screening for verticals and iron condors
- Gamma exposure (GEX) analysis
- Market-quality dashboard (separate from the account dashboard)
- Local trade DB / grouping / analytics support

### Main gaps
- No single unified coaching dashboard that ties everything together
- No proper settings page for user-configurable thresholds and alert preferences
- No correlation-aware concentration analysis
- No position-level "what now?" guidance layer
- No polished event timeline that makes assignments/exercises/rolls obvious at a glance

## Problem
Right now the app can answer *parts* of the question, but it does not clearly answer:
- What do I own?
- What’s the risk?
- What should I do next?

## MVP

### 1) Portfolio Health Dashboard
Show a clear top-level summary:
- Net liq
- Cash balance
- Buying power / equity BP
- Portfolio delta
- Portfolio theta
- Win rate
- Profit factor
- Avg holding time
- Total P/L
- Fees paid

### 2) Position Sizing + Concentration Warnings
Flag risk that’s too large or too concentrated:
- any leg above a configurable % of NLV
- exposure by underlying
- overlapping risk across correlated positions
- plain-English warnings

### 3) Position Drilldown
For each open position, show:
- strategy type
- strikes / expiration
- entry details
- current P/L
- P/L as % of NLV
- delta / theta exposure
- assignment / exercise risk
- suggested action: hold / roll / close / defend

### 4) Performance Analytics
Add views for:
- monthly P/L
- weekly P/L
- yearly performance
- performance by strategy
- winners vs losers
- average win / average loss
- largest win / largest loss

### 5) Trade History Timeline
Make history readable and useful:
- fills
- closes
- rolls
- assignments
- exercises
- cancellations
- major account events

### 6) Risk Alerts
Surface obvious account-level warnings:
- oversized positions
- low theta vs target
- market closed / liquidity warning
- assignment / exercise events
- concentration in one underlying or basket

## Non-Goals
Do not build:
- auto-trading
- broker execution
- signal generation
- a full research platform

## AI Layer (added 2026-04-28)
Originally listed as a non-goal; now in scope. The AI coach is an advisor, not an autotrader:
- Drives existing rule-based agents as tools via the Anthropic Agent SDK (`claude-agent-sdk`).
- Subscription billing via `CLAUDE_CODE_OAUTH_TOKEN` (Claude Max). API key is fallback only.
- Surfaces: `--coach` (one-shot daily briefing), `--chat` (REPL), and a localhost web dashboard with chat sidebar.
- Account-aware: every recommendation is filtered against live BP, position concentration, sector overlap, and personalized sizing rules.
- Hard rule: the coach never places trades. User approval still required for execution.

## UX Structure
- **Dashboard** — account summary, risk score, warnings, top positions, recent events
- **Positions** — table + filters + drilldown
- **Performance** — monthly / weekly / yearly + strategy breakdown
- **History** — chronological feed of trades and events
- **Settings** — risk thresholds and alert preferences

## Acceptance Criteria
Done when:
- a user can understand account health in under 10 seconds
- oversized positions are flagged automatically
- performance by strategy is visible
- assignments / exercises are clearly shown
- every open position has a quick next-step view
- the app makes account risk obvious without manual digging

## Phase 2 Ideas
If MVP lands, add:
- volatility regime awareness
- expected move / IV context
- correlation cluster detection
- strategy playbooks
- adjustment guidance
- scenario simulation

## One-line Summary
**tasty-coach should help a trader answer three questions fast: what do I own, what’s the risk, and what should I do next?**
