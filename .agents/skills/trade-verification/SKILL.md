---
name: trade-verification
description: Run verification checks when changes affect entry/exit logic, strategy parameters, or scanner behavior. Trigger before committing changes to agents/strategy.py, agents/scanner.py, or any trading logic.
---

# Trade Verification

Validates trading logic changes before they go live.

## When to Run

- Changes to `agents/strategy.py` (entry/exit logic)
- Changes to `agents/scanner.py` (opportunity detection)
- Changes to `agents/manager.py` (position sizing, risk)
- Any parameter changes affecting trade decisions

## Verification Steps

1. **Syntax & Import Check**
   ```bash
   python -c "import agents.strategy; import agents.scanner; import agents.manager"
   ```

2. **Run Tests**
   ```bash
   python -m pytest tests/ -v
   ```

3. **Dry Run Validation**
   ```bash
   python main.py --dry-run --debug --watchlist "Test Watchlist" 2>&1 | head -50
   ```

4. **Review Changes**
   - Check that entry conditions are still valid
   - Verify position sizing logic
   - Confirm stop/target levels make sense
   - Ensure no hardcoded values that should be config

## Pass Criteria

- All imports succeed
- Tests pass
- Dry run completes without errors
- No obvious logic issues in diff

## Fail Actions

If any check fails:
1. Report the specific failure
2. Do NOT mark work as complete
3. Fix the issue before proceeding

## Output

Provide a verification summary:
```
✓ Imports: OK
✓ Tests: X passed, 0 failed
✓ Dry run: Completed
✓ Logic review: No issues found

VERIFICATION: PASSED
```
