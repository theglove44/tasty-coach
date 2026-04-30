# tasty-coach: Best Trades Today Brief

> Implementation brief for Codex / Claude Code.

## Goal
Turn tasty-coach into an account-aware trade recommendation tool that scans the watchlist, runs quality gates, scores viable setups, and returns the top 3 trades for today with reasons.

## Outcome
A user can ask:

> "What are the best 3 trades from my watchlist today?"

…and the tool will:
1. read the watchlist
2. inspect market regime
3. screen each symbol for tradeability
4. generate candidate structures
5. run quality gates
6. score the survivors
7. check fit against the live account
8. return the top 3 with an explanation

## Core behaviour
The tool must be:
- account-aware
- rule-based first, not vibes-based
- transparent about why a trade ranked well or got rejected
- strict about bad liquidity, event risk, oversized exposure, and bad account fit
- useful even when the market is messy

## Required outputs
For each top trade:
- symbol
- structure
- expiry / DTE
- credit or debit
- max risk
- breakeven(s)
- score out of 100
- reasons it ranked well
- account-fit notes

Also show:
- rejected candidates
- rejection reasons
- current account warnings that influenced ranking

## Decision gates
Hard-filter or heavily penalise trades that have:
- earnings too close
- weak liquidity / wide spreads
- poor open interest / volume
- excessive size vs NLV
- correlation or concentration overlap
- event risk
- poor theta / BP trade-off
- bad market session conditions
- ugly assignment / exercise risk

## Scoring categories
Use a visible score breakdown, e.g.:
- market regime fit
- liquidity quality
- volatility edge
- event risk
- structure quality
- account fit
- concentration penalty
- risk-adjusted reward

## Logging requirement
The tool must log at entry:
- market regime
- VIX / IV / IVR / expected move
- symbol, structure, expiry, strikes
- size, credit/debit, max risk
- delta/theta/BP impact
- why the trade passed

And at exit:
- P/L
- hold time
- whether the thesis worked
- what actually killed it
- lesson tags

## Learning requirement
The tool should accumulate trade history in a way that later ranking can use:
- winning patterns
- losing patterns
- recurring bad conditions
- what structures fit the account
- what gets rejected often and why

This is not a separate AI memory project yet. It is a structured evidence trail for future ranking.

## Suggested shape
- one trade log entry per trade
- one lesson/summary file per repeated pattern
- one index page for navigation
- optional daily regime log

## Definition of done
The feature is done when the tool can reliably return a ranked top 3 from the watchlist with:
- sensible quality gates
- account-aware filtering
- plain-English reasons
- reproducible scoring
- logging for later learning
