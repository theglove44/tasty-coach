---
name: position-check
description: Verify current position state against expected positions. Use when debugging position discrepancies, unexpected fills, or reconciling local state with broker state.
---

# Position Check

Validates position state between local tracking and broker.

## When to Use

- Position count doesn't match expectations
- P/L seems wrong
- After manual trades outside the bot
- Debugging fill issues
- Morning reconciliation

## Check Steps

1. **Get Broker Positions**
   ```bash
   python -c "
   from utils.tasty_client import get_client
   client = get_client()
   positions = client.get_positions()
   for p in positions:
       print(f'{p.symbol}: {p.quantity} @ {p.average_open_price}')
   "
   ```

2. **Get Local State**
   ```bash
   python position_monitor.py --status
   ```

3. **Compare & Report**
   - Match positions by symbol
   - Flag any discrepancies
   - Check quantities match
   - Verify P/L calculations

## What to Check

- **Count Match**: Same number of positions
- **Symbol Match**: Same underlying symbols
- **Quantity Match**: Same contract counts
- **Side Match**: Long/short alignment
- **Greeks**: Delta/theta exposure

## Output Format

```
📊 Position Reconciliation

Broker Positions: X
Local Tracking: Y

✓ Matched:
- SPY: 2 contracts ✓
- QQQ: 1 contract ✓

⚠️ Discrepancies:
- AAPL: Broker shows 3, local shows 2

💰 Summary:
- Total Delta: X
- Total Theta: X
- Buying Power Used: X%

Status: [RECONCILED | DISCREPANCY FOUND]
```

## Fix Actions

If discrepancy found:
1. Check recent log for missed fills
2. Verify no manual trades occurred
3. Sync local state to broker (if broker is truth)
4. Document the discrepancy cause
