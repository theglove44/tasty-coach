---
name: log-analyzer
description: Analyze trade logs to diagnose issues, review execution quality, or understand trading behavior. Use when reviewing tasty_auto.log or debugging unexpected fills, missed entries, or error patterns.
---

# Log Analyzer

Interprets trade logs to find issues and patterns.

## When to Use

- Debugging why a trade didn't execute
- Understanding unexpected fills or prices
- Reviewing session activity
- Finding error patterns
- Checking if strategies triggered correctly

## Log Location

Primary log: `tasty_auto.log`

## Analysis Steps

1. **Get Recent Activity**
   ```bash
   tail -200 tasty_auto.log
   ```

2. **Find Errors**
   ```bash
   grep -i "error\|exception\|failed" tasty_auto.log | tail -20
   ```

3. **Find Order Activity**
   ```bash
   grep -i "order\|fill\|entry\|exit" tasty_auto.log | tail -30
   ```

4. **Check Session Health**
   ```bash
   grep -i "session\|auth\|token\|connect" tasty_auto.log | tail -20
   ```

5. **Time-based Analysis**
   ```bash
   # Last hour
   grep "$(date +%Y-%m-%d)" tasty_auto.log | tail -100
   ```

## What to Look For

- **Session Issues**: Token refresh failures, connection drops
- **Order Issues**: Rejections, partial fills, wrong prices
- **Strategy Issues**: Entry conditions not met, scanner returning empty
- **Timing Issues**: Trades outside market hours, delayed execution

## Output Format

```
📋 Log Analysis Summary

Period: [start] to [end]
Total entries: X

🔴 Errors Found:
- [error description]

📊 Order Activity:
- Entries: X
- Exits: X  
- Rejections: X

⚠️ Warnings:
- [any concerning patterns]

💡 Recommendations:
- [suggested fixes]
```

## Follow-up

After analysis, recommend:
- Specific code changes if bug found
- Config adjustments if parameter issue
- Further investigation if unclear
