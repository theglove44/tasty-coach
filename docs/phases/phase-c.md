# Phase C — Concentration Analysis + Position Action Guidance

## Scope

- Extend **agents/manager.py** to surface `by_underlying` as % NLV + flag above configurable threshold
- Hardcoded sector/ETF correlation bucket map
- **agents/advisor.py** with `suggest_action(position)` returning hold/roll/close/defend using:
  - Existing roll_calculator
  - DTE
  - P&L % credit
  - Assignment proximity
- Surface in drilldown + dashboard

## Out of scope

- Machine learning / predictive models
- Custom correlation matrices
- Multi-leg position detection beyond verticals/condors

## Dependencies

Phase A (settings framework)

## Linked task

TCMVP-3
