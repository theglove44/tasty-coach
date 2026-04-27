# tasty-coach Settings Reference

All settings live in `~/.tasty-coach/config.json` and can be edited via:

```bash
./venv/bin/python main.py --menu        # then press 's' for Settings
```

The interactive editor shows a one-line description for each key as you go through. This document is the canonical reference.

Two paths to change a value:

1. **Interactive (recommended)** — `--menu` → `s`. Each key shows its description and current value; press Enter to keep, type a new value to change.
2. **Direct** — edit `~/.tasty-coach/config.json` and save. The app reads this on startup; no restart needed across runs.

Validation at the boundary: negative numbers, non-numeric strings, and (for integer keys) non-whole floats are rejected with a useful error before being persisted.

---

## Phase A — risk management

These predate Best-Trades-Today and apply across the whole app's risk views.

| Key | Default | Type | What it does |
|---|---|---|---|
| `position_pct_nlv_warn` | `0.05` | float | Warns when any single position exceeds this fraction of NLV. `0.05` = 5%. |
| `bp_usage_warn` | `0.50` | float | Warns when buying-power usage exceeds this fraction. |
| `bp_usage_block` | `0.50` | float | Blocks new trades (`--watchlist` flow) when BP usage exceeds this fraction. Override with `--force`. |
| `concentration_pct_nlv_warn` | `0.15` | float | Warns when concentration in one underlying exceeds this fraction of NLV. |
| `theta_target` | `null` | float \| null | Target portfolio theta. Set `none` in the editor (or `null` in JSON) to disable the alert. |

---

## Best-Trades-Today — quality gates

These are hard rejects applied to candidates before scoring. Each rejected candidate appears in the result's `rejected` list with a reason.

| Key | Default | Type | What it does | When to tune |
|---|---|---|---|---|
| `bt_earnings_blackout_days` | `7` | int | Reject candidates with earnings within this many days (forward only). | Lower (e.g. `5`) if you trade through earnings; raise (e.g. `14`) for a wider buffer. |
| `bt_min_dte` | `21` | int | Reject candidates with DTE below this number. | Lower for shorter-duration setups (e.g. weekly trades); raise to enforce monthly cycles only. |
| `bt_max_dte` | `60` | int | Reject candidates with DTE above this number. | Raise to allow longer-dated trades; lower to keep theta decay tight. |
| `bt_min_open_interest` | `200` | int | Reject if any leg's open interest is below this floor. | Lower for less-liquid names (e.g. `50`); raise (`500+`) for very strict liquidity. |
| `bt_max_spread_pct` | `0.10` | float | Reject if worst leg's bid-ask spread divided by mid exceeds this fraction. `0.10` = 10%. | Tighten (`0.05`) for premium liquidity; relax (`0.20`) when you must accept wider markets. |

---

## Best-Trades-Today — account fit

These only run when you pass `--account ACCOUNT_NUMBER`. They look at live NLV, BP usage, and existing exposures to reject trades that would worsen account state.

| Key | Default | Type | What it does | When to tune |
|---|---|---|---|---|
| `bt_max_pct_nlv_per_trade` | `0.05` | float | Reject candidates whose max-loss exceeds this fraction of NLV. `0.05` = 5%. | Smaller accounts: lower (`0.02`-`0.03`). Larger / aggressive: raise (`0.07`-`0.10`). |
| `bt_bp_cap_for_new` | `0.50` | float | Reject if post-trade buying-power usage would exceed this fraction. | Lower (`0.30`-`0.40`) to leave more dry powder; raise to allow fuller deployment. |
| `bt_concentration_overlap_block_pct` | `0.25` | float | Reject if combined exposure to one underlying (existing + new) exceeds this fraction of NLV. | Lower (`0.15`) for tight diversification; raise to allow heavier underlying tilt. |

> **Known v1 limitation:** `existing_exposures` is empty in production wiring (per-position max-loss math isn't computed yet). This means concentration only fires when a single new candidate exceeds the cap, not on already-crowded underlyings. Documented in the TCBT-5 PR.

---

## Best-Trades-Today — scan + research performance

These control how the orchestrator scans and researches symbols. Tuning here trades off speed vs. API load vs. coverage.

| Key | Default | Type | What it does | When to tune |
|---|---|---|---|---|
| `bt_min_ivr` | `30.0` | float | Pre-filter watchlist symbols by IVR. Symbols below this percentage are skipped *before* the expensive Greeks research call. | Raise (`50`-`70`) for selective high-IV setups; lower (`10`-`20`) to research more symbols (slower runs). |
| `bt_max_per_symbol` | `3` | int | Cap on candidate count per symbol from the researcher. | Lower (`1`-`2`) to reduce duplicates per symbol; raise (`5`-`10`) to see more variants. |
| `bt_research_concurrency` | `5` | int | Number of symbols researched in parallel. | Raise (`8`-`10`) for faster runs at the cost of more API load; lower (`2`-`3`) if you hit rate limits or websocket instability. |
| `bt_research_timeout_seconds` | `45` | int | Per-symbol hard timeout. Symbols exceeding this become `research_timeout` rejections instead of hanging the run. | Raise (`60`-`90`) if you see lots of timeouts on liquid names with big chains; lower (`20`) to fail faster during testing. |

### Sizing your run

Approximate wall-clock time = `(symbols_passing_IVR_filter / concurrency) × ~5s`.

Examples:
- 60 symbols × concurrency 5 = ~60s
- 30 symbols × concurrency 5 = ~30s
- 60 symbols × concurrency 1 (sequential) = ~5 minutes

---

## Alert toggles

These control which categories of alerts appear in the dashboard / `--alerts` view.

| Toggle | Default | What it gates |
|---|---|---|
| `alert_toggles.position_size` | `true` | Position-size warnings (over `position_pct_nlv_warn`). |
| `alert_toggles.bp` | `true` | BP-usage warnings. |
| `alert_toggles.theta` | `true` | Theta-target warnings (only when `theta_target` is non-null). |
| `alert_toggles.market` | `true` | Market-session warnings (e.g. closed market, low liquidity windows). |
| `alert_toggles.concentration` | `true` | Concentration warnings (over `concentration_pct_nlv_warn`). |
| `alert_toggles.assignment` | `true` | Assignment / exercise event alerts. |

In the menu editor these are yes/no prompts. In JSON they're booleans inside the `alert_toggles` object.

---

## Editing JSON directly

Example minimum config that overrides just the IVR threshold and research timeout:

```json
{
  "bt_min_ivr": 50.0,
  "bt_research_timeout_seconds": 90
}
```

Any keys not present fall back to the defaults documented above.

---

## Validation rules

- All `bt_max_*_pct`, `bt_*_pct_*`, `bt_min_ivr`, `bt_max_spread_pct`, `position_*`, `bp_*`, `concentration_*` are **non-negative floats**. Negatives or non-numeric strings are rejected.
- All `bt_*_dte`, `bt_min_open_interest`, `bt_max_per_symbol`, `bt_earnings_blackout_days`, `bt_research_concurrency`, `bt_research_timeout_seconds` are **non-negative integers**. Floats that aren't whole numbers, booleans, and non-numeric strings are rejected.
- `theta_target` accepts a non-negative float OR `null` (use `none` in the editor).
- CLI flags that flow into these (`--top`) get the same boundary validation: `--top -1` exits with a useful error.
