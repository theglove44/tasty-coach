# Phase B — Unified Dashboard View

## Scope

- **utils/dashboard_ui.py** with rich Live layout:
  - KPI row: net liq, cash, BP, Δ, Θ
  - Performance row: win rate, PF, total P&L, fees, avg hold
  - Top-5 positions with flags
  - Alert strip
  - Recent events feed
- Wire as launcher action + `--dashboard` CLI flag in main.py
- Pulls from existing agents — no new math

## Out of scope

- Persistent dashboard state
- Custom dashboard templates
- Export / reporting

## Dependencies

Phase A (settings framework)

## Linked task

TCMVP-2
