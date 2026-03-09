---
name: backtest-runner
description: Run backtests after strategy parameter changes to validate performance. Trigger when modifying entry/exit thresholds, position sizing, or adding new strategy logic.
---

# Backtest Runner

Validates strategy changes against historical data.

## When to Run

- After changing entry/exit parameters
- After modifying position sizing logic
- When adding new strategy filters
- Before deploying strategy changes to live

## Prerequisites

- Historical data available
- Strategy parameters defined
- Baseline results for comparison (if available)

## Backtest Steps

1. **Define Test Parameters**
   - Date range (suggest: last 30-90 trading days)
   - Strategy to test
   - Comparison baseline

2. **Run Backtest**
   ```bash
   python -m src.backtest --strategy orb30 --start 2026-01-01 --end 2026-03-01
   ```

3. **Collect Metrics**
   - Win rate
   - Average win/loss
   - Max drawdown
   - Sharpe ratio
   - Total P/L

4. **Compare to Baseline**
   - Is win rate maintained or improved?
   - Is drawdown acceptable?
   - Does risk/reward make sense?

## Output Format

```
📈 Backtest Results

Strategy: [name]
Period: [start] to [end]
Trades: X

Performance:
- Win Rate: X%
- Avg Win: $X
- Avg Loss: $X
- Profit Factor: X
- Max Drawdown: X%
- Total P/L: $X

vs Baseline:
- Win Rate: +X% ✓
- Drawdown: -X% ✓

Recommendation: [DEPLOY | REVIEW | REJECT]
```

## Decision Criteria

**DEPLOY** if:
- Win rate >= baseline
- Drawdown <= baseline
- At least 30 trades in sample

**REVIEW** if:
- Mixed results (some better, some worse)
- Small sample size
- Edge cases to consider

**REJECT** if:
- Win rate significantly worse
- Drawdown significantly higher
- Logic errors found

## Notes

- Backtests are not guarantees
- Consider market regime
- Paper trade before live deployment
