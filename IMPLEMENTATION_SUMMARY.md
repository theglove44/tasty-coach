# Position Reviewer Implementation Summary

## Overview

Successfully implemented the position reviewer feature with roll scenario analysis as specified in `POSITION_REVIEWER_TASK.md`.

## What Was Implemented

### 1. Core Modules

#### `utils/roll_calculator.py` (~800 lines)
Pure calculation logic for roll scenarios, including:
- **Data Classes**:
  - `SpreadMetrics` - width, max profit/loss, breakeven, risk/reward
  - `RollScenario` - complete scenario with credit/debit, new strikes, viability score
- **Calculation Functions**:
  - `calculate_breakeven()` - Calculates breakeven price for spreads
  - `calculate_net_credit_debit()` - Net credit/debit for rolling positions
  - `calculate_viability_score()` - 0-100 score based on credit, time, risk/reward
  - `calculate_roll_down_scenario()` - Same expiration, lower/higher strikes
  - `calculate_roll_out_scenario()` - Same strikes, later expiration
  - `calculate_roll_down_and_out_scenario()` - Combined roll (lower strikes + later exp)

**Key Constants**:
- `MAX_DEBIT_THRESHOLD = 3.00` - Max debit allowed ($3.00, adjusted for ITM positions)
- `STRIKE_RANGE_PCT = 0.20` - ±20% strike range filter
- `MAX_EXPIRATIONS = 3` - Next 3 monthly expirations

#### `agents/reviewer.py` (~700 lines)
Orchestrates position review and scenario generation:
- **Data Classes**:
  - `PositionContext` - Enriched position data with P/L, greeks, current prices
  - `ReviewResult` - Complete review output with scenarios and metadata
- **ReviewerAgent Class**:
  - `review_positions()` - Main entry point, filters by underlying
  - `_fetch_position_context()` - Enriches positions with market data
  - `_fetch_roll_chain_data()` - Fetches options chains for 3 monthly expirations
  - `_generate_roll_scenarios()` - Generates all viable scenarios
  - `_enrich_chain_with_market_data()` - Fetches bid/ask/mark for options (batched)
  - `print_review_report()` - Rich console output with tables
  - `export_json()` - JSON export for AI consumption

### 2. CLI Integration

Added to `main.py`:
- `--review-position SYMBOL` - Review positions for specific underlying
- `--output PATH` - Export results to JSON file
- Works with existing `--discord` flag for Discord formatting

### 3. Features Delivered

✅ **Position Fetcher** - Fetches and displays current positions with P/L
✅ **Market Price Fetcher** - Gets current underlying prices and option marks
✅ **Options Chain Analyzer** - Fetches 3 monthly expirations with relevant strikes
✅ **Roll Scenario Calculator** - Generates 3 types of roll scenarios:
  - **Roll Down**: Same expiration, different strikes (for adjusting risk)
  - **Roll Out**: Same strikes, later expiration (for more time)
  - **Roll Down-and-Out**: Combined (lower strikes + more time)
✅ **Viability Scoring** - 0-100 score based on credit, time, risk improvement
✅ **Structured Output** - Both Rich console tables and JSON export

## Usage Examples

### Review Positions

```bash
# Review SLV positions
./venv/bin/python main.py --review-position SLV

# Review with Discord formatting
./venv/bin/python main.py --review-position SLV --discord

# Export to JSON
./venv/bin/python main.py --review-position SLV --output slv_review.json
```

### Sample Output

```
📋 Reviewing positions for SLV...

═══════════════════════════════════════════════════════════════════════════════
  SLV - Put Vertical
═══════════════════════════════════════════════════════════════════════════════
        Current Position

  Metric             Value
 ───────────────────────────────
  Underlying Price   $68.00
  Expiration         2026-03-20
  DTE                35
  Entry Cost         $-217.00
  Current Value      $-460.00
  Unrealized P/L     $-243.00
  P/L %              -112.0%

                          Position Legs

  Action   Strike   Type   Qty   Avg Price   Mark     P/L
 ───────────────────────────────────────────────────────────────
  BTO      $87.0    PUT    1     $6.09       $20.40   $1431.00
  STO      $92.0    PUT    1     $8.26       $25.00   $-1674.00

                               Roll Scenarios (Sorted by Viability)
╭───────────────────┬─────────────┬────────────┬─────┬──────────────┬────────┬────────────┬───────╮
│ Type              │ New Strikes │ Expiration │ DTE │ Credit/Debit │ New BE │ Days Added │ Score │
├───────────────────┼─────────────┼────────────┼─────┼──────────────┼────────┼────────────┼───────┤
│ Roll Out          │ 87.0/92.0   │ 26-04-17   │ 63  │ $0.95 DB     │ $92.95 │ +28        │ 26.0  │
│ Roll Out          │ 87.0/92.0   │ 26-05-15   │ 91  │ $1.15 DB     │ $93.15 │ +56        │ 19.0  │
│ Roll Down         │ 80.0/85.0   │ 26-03-20   │ 35  │ $0.95 DB     │ $85.95 │ 0          │ 12.0  │
│ Roll Down         │ 79.0/84.0   │ 26-03-20   │ 35  │ $1.10 DB     │ $85.10 │ 0          │ 6.0   │
│ Roll Down         │ 81.0/86.0   │ 26-03-20   │ 35  │ $1.15 DB     │ $87.15 │ 0          │ 4.0   │
╰───────────────────┴─────────────┴────────────┴─────┴──────────────┴────────┴────────────┴───────╯
```

## Architecture Decisions

### 1. Separation of Concerns
- **Pure calculation logic** in `utils/roll_calculator.py` (no API calls)
- **API orchestration** in `agents/reviewer.py`
- Follows existing codebase patterns (`strategy.py`, `portfolio.py`)

### 2. Reused Existing Code
- `portfolio.get_positions()` - Base position fetching
- `portfolio._parse_occ_symbol()` - OCC symbol parsing
- `portfolio._group_positions()` - Position grouping by strategy
- `strategy._fetch_greeks()` - Greeks streaming pattern
- `get_market_data_by_type()` - Market data fetching

### 3. Key Fixes During Implementation

**Issue #1: Option Strike Attribute**
- Problem: Used `opt.strike` but actual attribute is `opt.strike_price`
- Solution: Changed all references to `opt.strike_price`

**Issue #2: 414 Request-URI Too Large**
- Problem: Fetching market data for 384+ options in single request
- Solution: Batch requests (50 symbols per request)

**Issue #3: Option Type Enum Mismatch**
- Problem: `opt.option_type` is enum, calculator expects string 'PUT'/'CALL'
- Solution: Explicit conversion: `if opt.option_type == OptionType.PUT: 'PUT'`

**Issue #4: No Viable Scenarios Generated**
- Problem: All scenarios filtered out due to $0.50 debit threshold
- Solution: Increased to $3.00 (realistic for ITM positions like SLV 92/87 @ $68)

### 4. Data Flow

```
main.py (CLI)
    ↓
ReviewerAgent.review_positions(underlying)
    ↓
├─→ PortfolioAgent.get_positions()  # Fetch raw positions
├─→ _fetch_position_context()        # Enrich with market data & P/L
├─→ _fetch_roll_chain_data()         # Get 3 monthly exp chains
│       ↓
│   NestedOptionChain.get()          # List expirations
│   get_option_chain()                # Full strike data
│   _enrich_chain_with_market_data()  # Bid/ask/mark (batched)
│
├─→ _generate_roll_scenarios()        # Calculate scenarios
│       ↓
│   roll_calculator.calculate_roll_down_scenario()
│   roll_calculator.calculate_roll_out_scenario()
│   roll_calculator.calculate_roll_down_and_out_scenario()
│
└─→ print_review_report() or export_json()
```

## Testing

Tested with:
- **Live Position**: SLV 87/92 Put Vertical (35 DTE, deeply ITM)
- **Console Output**: ✅ Rich formatted tables with all metrics
- **JSON Export**: ✅ Structured data with positions and scenarios
- **Discord Format**: ✅ Markdown code blocks for Discord compatibility

## Future Enhancements

Potential additions (not implemented):
1. **Greeks Comparison** - Show delta/theta changes for roll scenarios
2. **GEX Integration** - Avoid rolling beyond gamma walls
3. **Probability Analysis** - Add probability of profit for each scenario
4. **Multiple Underlyings** - Review all positions at once
5. **Auto-execute** - Submit roll orders directly to TastyTrade
6. **Historical Analysis** - Backtest roll decisions

## Success Criteria (from Task Spec)

✅ 1. Can fetch and display current positions with P/L
✅ 2. Shows current market prices for underlyings
✅ 3. Generates at least 3 roll scenarios per position
✅ 4. Output is structured for AI analysis (JSON export)
✅ 5. Integrates cleanly with existing codebase

## Files Modified/Created

**New Files**:
- `/Users/office/Projects/tasty-coach/utils/roll_calculator.py`
- `/Users/office/Projects/tasty-coach/agents/reviewer.py`
- `/Users/office/Projects/tasty-coach/IMPLEMENTATION_SUMMARY.md`

**Modified Files**:
- `/Users/office/Projects/tasty-coach/main.py` (added `--review-position` and `--output` flags)

**Memory File**:
- `/Users/office/.claude/projects/-Users-office-Projects-tasty-coach/memory/MEMORY.md`

## API Reference

Implementation follows TastyTrade API patterns from:
https://developer.tastytrade.com/getting-started/

Key API calls used:
- `Account.get_positions(session)` - Fetch positions
- `NestedOptionChain.get(session, symbol)` - List expirations
- `get_option_chain(session, symbol)` - Full option chain
- `get_market_data_by_type(session, symbols)` - Market data (bid/ask/mark)

## Notes

- All scenarios sorted by viability score (0-100)
- Top 10 scenarios displayed in console
- JSON export includes all calculated scenarios
- Works with existing authentication (`TastyClient`)
- Supports multi-account via `--account` flag
- Compatible with `--discord` formatting flag
