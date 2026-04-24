# Phase D — Event Timeline + Assignment/Exercise Capture

## Scope

- Backfill assignment/exercise classification in **agents/history.py** from already-synced transaction types
- Rich timeline renderer (fills/closes/rolls/assignments/exercises/cancellations):
  - Icons
  - Linked to trade groups via `parent_group_id`
- Launcher action + `--timeline` CLI flag

## Out of scope

- Historical data scraping
- Custom event type filtering
- Export to CSV/Excel

## Dependencies

None

## Linked task

TCMVP-4
