# Codex Task: Integrate GEX into Strategy Selection

## Objective
Incorporate Gamma Exposure (GEX) analysis from `agents/gex.py` into the strategy screening workflow in `agents/strategy.py` and orchestrator (`main.py`).

## Context
- `GEXAgent.calculate_gex()` returns a `GEXResult` with:
  - `total_gex`: Net gamma exposure in millions
  - `call_wall`, `put_wall`: Key gamma levels (resistance/support)
  - `zero_gamma_level`: Where dealer hedging flips
  - `strategy`: Dict with `signal` (MEAN_REVERSION, ACCELERATION, MAGNET_PIN)
  
- `StrategyAgent.screen_strategies()` finds vertical spreads and iron condors at ~30 delta, 45 DTE

## Requirements

### 1. Add GEX to StrategyTarget dataclass
In `agents/strategy.py`, extend `StrategyTarget`:
```python
@dataclass
class StrategyTarget:
    # ... existing fields ...
    
    # NEW: GEX context
    gex_regime: Optional[str] = None  # "positive" | "negative"
    gex_signal: Optional[str] = None  # "MEAN_REVERSION" | "ACCELERATION" | "MAGNET_PIN"
    gamma_call_wall: Optional[float] = None
    gamma_put_wall: Optional[float] = None
    gex_warning: Optional[str] = None  # e.g., "Short strike beyond put wall"
```

### 2. Create GEX-aware screening method
Add to `StrategyAgent`:
```python
async def screen_strategies_with_gex(
    self, 
    symbol: str, 
    current_ivr: float,
    gex_result: Optional[GEXResult] = None
) -> List[StrategyTarget]:
    """Screen strategies with GEX context applied."""
    # Get base strategies
    strategies = await self.screen_strategies(symbol, current_ivr)
    
    if not gex_result or gex_result.error:
        return strategies
    
    # Enrich and filter based on GEX
    enriched = []
    for strat in strategies:
        strat.gex_regime = "positive" if gex_result.total_gex > 0 else "negative"
        strat.gex_signal = gex_result.strategy.get('signal') if gex_result.strategy else None
        strat.gamma_call_wall = gex_result.call_wall
        strat.gamma_put_wall = gex_result.put_wall
        
        # Check if short strikes are beyond gamma walls
        warnings = []
        for leg in strat.legs:
            if leg.get('side') == 'short':
                strike = leg.get('strike')
                if gex_result.put_wall and strike < gex_result.put_wall:
                    warnings.append(f"Short put {strike} below put wall {gex_result.put_wall}")
                if gex_result.call_wall and strike > gex_result.call_wall:
                    warnings.append(f"Short call {strike} above call wall {gex_result.call_wall}")
        
        if warnings:
            strat.gex_warning = "; ".join(warnings)
        
        enriched.append(strat)
    
    return enriched
```

### 3. Update main.py orchestrator
Modify the main workflow to:
1. Run GEX analysis for SPY/SPX before scanning strategies
2. Pass GEX result to strategy screening
3. Display GEX regime info in output

```python
# After risk check, before strategy screening:
print("\n📊 Analyzing Market Gamma Exposure...")
from agents.gex import GEXAgent
gex_agent = GEXAgent(session)
# Use SPY as market proxy (faster than SPX)
gex_result = asyncio.run(gex_agent.calculate_gex('SPY', max_dte=7))
print(gex_agent.analyze_regime(gex_result))

# Then in strategy screening loop:
strategy_targets = asyncio.run(
    strategy.screen_strategies_with_gex(t.symbol, t.iv_rank, gex_result)
)
```

### 4. Update report output
In `StrategyAgent.generate_strategy_report()`, include GEX context:
- Show regime (positive/negative gamma)
- Highlight warnings if short strikes beyond walls
- Add color coding: green for positive gamma (favorable for short premium), yellow/red for negative

### 5. Optional: Add regime filter
Add CLI flag `--gex-filter` that:
- In **positive gamma**: Proceed normally (good for selling premium)
- In **negative gamma**: Add warning banner, optionally require `--force` to proceed

## Files to Modify
1. `agents/strategy.py` - Add GEX fields to StrategyTarget, add screen_strategies_with_gex()
2. `main.py` - Integrate GEX analysis into workflow
3. `agents/gex.py` - No changes needed, already complete

## Testing
After implementation:
```bash
python main.py -w "High IV" --debug
```

Should show:
1. GEX regime analysis before strategy screening
2. Each StrategyTarget enriched with GEX context
3. Warnings if short strikes beyond gamma walls

## Acceptance Criteria
- [ ] StrategyTarget includes GEX fields
- [ ] GEX analysis runs before strategy screening  
- [ ] Short strikes beyond gamma walls trigger warnings
- [ ] Report shows GEX regime context
- [ ] No breaking changes to existing functionality
