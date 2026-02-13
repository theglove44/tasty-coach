# Position Reviewer Feature - Task Spec

## Overview
Build a position review feature for tasty-coach that enables AI-assisted analysis of open positions with roll/management recommendations.

## API Reference
Ensure all code uses the latest TastyTrade API patterns from:
https://developer.tastytrade.com/getting-started/

The project uses `tastytrade` SDK v12+ with async patterns.

## Feature Requirements

### 1. Position Fetcher (`-r` flag)
Add a `-r` or `--review` flag to `main.py` that:
- Authenticates via existing `TastyClient`
- Fetches all open positions
- Parses OCC symbols to extract: underlying, expiration, strike, type (P/C)
- Calculates P/L per position
- Groups positions by underlying and identifies spreads
- Outputs structured JSON for AI consumption

### 2. Market Price Fetcher
For each underlying in positions:
- Fetch current market price (real-time quote)
- Calculate how far ITM/OTM each leg is
- Include in position output

### 3. Options Chain Analyzer
For selected underlying:
- Fetch options chains for multiple expirations (current + next 3 monthly)
- Include bid/ask, delta, IV for each strike
- Focus on strikes relevant for rolling (near current position strikes)

### 4. Roll Scenario Calculator
Model common roll strategies:
- **Roll down**: Same expiration, lower strike
- **Roll out**: Same strike, later expiration  
- **Roll down-and-out**: Lower strike + later expiration
- **Close and redeploy**: Close current, open new position

For each scenario, calculate:
- Credit/debit required
- New breakeven
- Max profit/loss change
- Days added

### 5. Output Format
Structured JSON output that includes:
```json
{
  "positions": [...],
  "underlying_prices": {...},
  "roll_scenarios": {
    "position_id": {
      "roll_down": {...},
      "roll_out": {...},
      "roll_down_and_out": {...}
    }
  },
  "recommendations": [...]
}
```

## Architecture Notes

### Existing Code to Leverage
- `utils/tasty_client.py` - Authentication (uses refresh token)
- `agents/portfolio.py` - Position fetching (has `get_positions()`)
- `agents/scanner.py` - Has IV rank fetching patterns
- `agents/strategy.py` - Options chain fetching patterns

### New Modules Needed
- `agents/reviewer.py` - Main position review logic
- `utils/occ_parser.py` - OCC symbol parsing utilities
- `utils/roll_calculator.py` - Roll scenario math

## Example Usage
```bash
# Review all positions
./venv/bin/python main.py -r

# Review specific underlying
./venv/bin/python main.py -r --symbol SLV

# Output to file
./venv/bin/python main.py -r --output positions.json
```

## Testing
- Test with real positions (SLV put spread currently open)
- Verify roll calculations match TastyTrade platform values
- Handle edge cases: spreads, single legs, different underlyings

## Success Criteria
1. Can fetch and display current positions with P/L
2. Shows current market prices for underlyings
3. Generates at least 3 roll scenarios per position
4. Output is structured for AI analysis
5. Integrates cleanly with existing codebase
