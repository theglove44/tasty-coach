# IVR Data Limitations and Solutions

## The Problem

**The tastytrade SDK does not provide access to historical implied volatility data or pre-calculated IVR values.** This is a fundamental limitation that affects the accuracy of our IVR scanner.

## What is IVR?

Implied Volatility Rank (IVR) is calculated as:
```
IVR = (Current IV - 52-week IV Low) / (52-week IV High - 52-week IV Low) * 100
```

This requires:
- Current implied volatility (available via Greeks stream)
- 252 trading days of historical IV data (NOT available via SDK)

## What We Have vs. What We Need

### Available through tastytrade SDK:
✅ Current stock prices and market data
✅ Option chains and strikes
✅ Real-time Greeks data (including current IV)
✅ Historical price data

### NOT Available through tastytrade SDK:
❌ Historical implied volatility data
❌ Pre-calculated IVR values
❌ IV percentile data
❌ Tastytrade's proprietary volatility metrics

## Current Implementation Status

### What Works:
- ✅ Authentication and session management
- ✅ Watchlist retrieval and symbol extraction
- ✅ Real-time IV fetching via Greeks stream (when available)
- ✅ Market data and option chain analysis

### What's Limited:
- ⚠️ IVR calculation returns `None` (no historical data)
- ⚠️ Fallback to placeholder calculations when real Greeks unavailable
- ⚠️ Cannot match tastytrade's actual IVR values

## Solutions and Alternatives

### Option 1: Use Current IV Only
Instead of IVR, scan for symbols with high current implied volatility:
```python
# Modify threshold to use absolute IV instead of IVR
if current_iv > 0.30:  # 30% IV threshold
    print(f"{symbol} has high IV: {current_iv:.1%}")
```

### Option 2: Third-Party Data Sources
Integrate with services that provide historical IV data:
- **IEX Cloud** - Historical options data
- **Alpha Vantage** - Options analytics
- **Quandl/Nasdaq Data Link** - Financial datasets
- **CBOE** - Volatility indices and data

### Option 3: Calculate Historical IV
Build your own historical IV database by:
1. Collecting daily IV snapshots over time
2. Storing in local database (SQLite/PostgreSQL)
3. Computing IVR from accumulated data

### Option 4: Use tastytrade Platform Directly
For accurate IVR data, continue using:
- tastytrade's web platform for screening
- This SDK for execution and order management

## Recommended Approach

For immediate use:
1. **Use current IV as primary metric** instead of IVR
2. **Set IV thresholds** (e.g., > 30% for high volatility)
3. **Monitor Greeks data quality** and implement retry logic
4. **Document limitations clearly** in user-facing output

For production use:
1. **Integrate third-party IV data** if budget allows
2. **Build historical IV collection** for long-term accuracy
3. **Hybrid approach**: Use SDK for execution, external data for screening

## Code Changes Made

1. **Enhanced IV calculation** - Now attempts to fetch real IV via Greeks stream
2. **Honest IVR reporting** - Returns `None` when real data unavailable
3. **Clear documentation** - Explains limitations in code comments
4. **Fallback handling** - Graceful degradation when real data unavailable

## User Communication

The scanner now clearly indicates when:
- Real IV data is successfully retrieved
- Fallback calculations are being used
- IVR data is not available due to SDK limitations

This ensures users understand the data quality and can make informed trading decisions.