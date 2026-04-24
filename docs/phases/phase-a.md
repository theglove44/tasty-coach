# Phase A — Settings + Alerts Foundation

## Scope

- **utils/settings.py** + `~/.tasty-coach/config.json` for user-configurable thresholds:
  - Position % NLV
  - BP ceiling
  - Theta target
  - Concentration %
  - Alert toggles
- **agents/alerts.py** to collect structured Alert objects from checks currently inline in manager.py
  - Dedupe alerts
  - Expose `get_active_alerts()` interface
- No UI, no persistence

## Out of scope

- Dashboard UI
- Alert persistence / storage
- Launcher integration

## Dependencies

None

## Linked task

TCMVP-1
