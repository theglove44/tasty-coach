# MI-2026-03-30-history-utc-boundary

## Title
`--history` report was building New York-local midnights as naive datetimes and sending the wrong UTC window to tastytrade.

## Trigger / symptom
The `--history` path needed to be checked against the tastytrade docs and SDK structure to confirm the account history request matched the documented API shape.

## Scope inspected
- `main.py` CLI dispatch for `--history`
- `agents/history.py` report builder
- Local tastytrade docs in `/Users/christaylor/Projects/tastytrade-docs`
- Installed `tastytrade` SDK implementation for `get_net_liquidating_value_history` and `get_history`

## Commands run
- `rg -n "history|--history|api structure|api" .`
- `rg -n "history|net liquidating|get_history|get_net_liquidating_value_history|performance report|api" /Users/christaylor/Projects/tastytrade-docs`
- `python - <<'PY' ... inspect.getsource(...) ... PY`

## Files inspected
- `main.py`
- `agents/history.py`
- `/Users/christaylor/Projects/tastytrade-docs/api_guides_account_balances.md`
- `/Users/christaylor/Projects/tastytrade-docs/api_guides_account_transactions.md`
- `venv/lib/python3.14/site-packages/tastytrade/account.py`

## Findings
- The SDK builds `GET /accounts/{account_number}/net-liq/history`.
- `get_net_liquidating_value_history()` formats `start_time` as UTC `YYYY-MM-DDTHH:MM:SSZ` without converting timezone-aware datetimes.
- The original report code used naive New York-local midnights, so the request window was shifted by the local offset and the end-of-window filtering could exclude valid points near midnight.
- The transaction flow weighting had the same timezone risk when fallback timestamps were naive.

## Direct answers / conclusions
- The CLI wiring for `--history` was fine.
- The report builder needed UTC boundary handling, not a different endpoint.

## Proposed surgical fix
- Build period boundaries in America/New_York.
- Convert those boundaries to UTC before calling the SDK.
- Compare history points and cash flow timestamps in UTC only.

## Files changed
- `agents/history.py`
- `tests/test_history.py`
- `utils/dx_feed.py`

## Validation status
- Passed: `python -m unittest tests.test_history -v`
- Passed: `python -m py_compile agents/history.py utils/dx_feed.py tests/test_history.py`
- Partially blocked: `python -m unittest discover tests -v` fails in existing `tests/test_risk_manager.py` with `decimal.InvalidOperation` from `agents/manager.py:281`, unrelated to the history fix.

## Current status / next steps
- History path is patched and regression-tested.
- Separate `test_risk_manager` mock cleanup is needed if full-suite green status is required.
