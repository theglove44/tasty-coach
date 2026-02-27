# Tastytrade IVR Watchlist Scanner - Project Plan

## Overview
Create a Python application that connects to your tastytrade account, retrieves symbols from an existing watchlist, and flags any symbols with an IVR (Implied Volatility Rank) over 25%.

## Project Structure
```
tasty-coach/
├── agents/
│   ├── scanner.py          # IVR scanning & watchlist resolution
│   ├── portfolio.py        # Position tracking & reporting
│   ├── strategy.py         # Strategy screening (verticals, iron condors)
│   ├── reviewer.py         # Position review & roll scenario analysis
│   ├── manager.py          # Risk management & portfolio health
│   └── gex.py             # Gamma Exposure (GEX) analysis
├── utils/
│   ├── tasty_client.py     # OAuth authentication & session management
│   ├── roll_calculator.py  # Pure roll scenario calculations
│   ├── market_schedule.py  # Market session & hours checking
│   └── dx_feed.py         # Real-time data streaming (dxLink)
├── tests/
│   └── test_risk_manager.py
├── main.py                 # Entry point & CLI orchestrator
├── position_monitor.py     # Automated position monitoring
├── requirements.txt
├── .env                    # OAuth credentials (not committed)
├── .agents                 # Agent automation configuration
└── README.md
```

## Implementation Phases

### Phase 1: Setup and Authentication ✅
**Objective**: Establish secure connection to tastytrade API

**Tasks**:
- Install `tastytrade` SDK (`pip install tastytrade`)
- Create project directory structure
- Implement secure authentication using OAuth credentials
- Setup OAuth app on tastytrade website to get client secret and refresh token
- Create session management with automatic token refresh
- Add connection validation

**Key Files**:
- `utils/tasty_client.py` - OAuth authentication & session management
- `.env` - Secure credential storage
- `requirements.txt` - Project dependencies

**Success Criteria**:
- Successful authentication to tastytrade API
- Persistent session handling
- Secure credential management

### Phase 2: Watchlist Integration ✅
**Objective**: Access and process existing watchlists

**Tasks**:
- Implement watchlist retrieval using `PrivateWatchlist.get()`
- Extract symbols and instrument types from watchlist entries
- Add watchlist validation and error handling
- Support multiple watchlist selection
- Filter for equity symbols only (options IVR handled separately)

**Key Files**:
- `agents/scanner.py` - Watchlist & IVR scanning

**Success Criteria**:
- Retrieve symbols from existing watchlists
- Validate symbol accessibility
- Handle missing or empty watchlists gracefully

### Phase 3: Market Data & IVR Calculation ✅
**Objective**: Calculate IVR for watchlist symbols

**Tasks**:
- Fetch current market data using `get_market_data()`
- Retrieve option chains using `NestedOptionChain.get()`
- [x] Integrate historical IV retrieval
- [x] Implement IVR calculation (52-week high/low) using official metrics
- [x] Align DXLink Streamer with accurate protocol (compact format, greeks)
- [x] Add caching for market data to improve performance
- [x] Verify IVR calculations against tastytrade platform
- Calculate current IV percentile rank
- Apply 25% threshold filter
- Add caching to reduce API calls
- Handle symbols without options

**Key Files**:
- `agents/scanner.py` - Market data and IVR calculations
- `utils/dx_feed.py` - Real-time data streaming

**Success Criteria**:
- Accurate IVR calculations
- Efficient API usage with caching
- Proper handling of non-optionable stocks

### Phase 4: Scanning Logic & Output ✅
**Objective**: Combine all components into working scanner

**Tasks**:
- Implement main scanning workflow in `scanner.py`
- Combine watchlist data with IVR calculations
- Filter and rank results by IVR value
- Create formatted output (console, CSV, JSON)
- Add progress indicators for long-running scans
- Implement error recovery and logging

**Key Files**:
- `agents/scanner.py` - Main scanning logic
- `main.py` - Entry point and CLI interface

**Success Criteria**:
- Complete end-to-end scanning workflow
- Clear, actionable output
- Robust error handling

### Phase 5: Enhancement & Optimization ⏳ (Current)
**Objective**: Add advanced features and optimizations

**Completed**:
- ✅ Position Reviewer with roll scenario analysis (`agents/reviewer.py`, `utils/roll_calculator.py`)
- ✅ Risk Management with BP monitoring (`agents/manager.py`)
- ✅ Strategy Screening for verticals & iron condors (`agents/strategy.py`)
- ✅ Gamma Exposure (GEX) analysis (`agents/gex.py`)
- ✅ Market schedule checking (`utils/market_schedule.py`)
- ✅ Position monitoring with alerts (`position_monitor.py`)
- ✅ Multi-account support
- ✅ Discord output formatting

**Remaining / Future**:
- GEX integration into main scan workflow (partially done)
- Historical IVR trending
- Probability of profit calculations
- Auto-execute roll orders via API
- Email/SMS alert functionality

## Technical Requirements

### Dependencies
```
tastytrade>=8.0.0
python-dotenv>=1.0.0
pandas>=2.0.0
requests>=2.31.0
```

### Environment Variables
```
TASTYTRADE_CLIENT_SECRET=your_client_secret
TASTYTRADE_REFRESH_TOKEN=your_refresh_token
TASTY_ACCOUNT_NUMBER=your_account_number
TASTYTRADE_IS_TEST=false
IVR_THRESHOLD=25
LOG_LEVEL=INFO
```

### API Considerations
- **Rate Limiting**: Implement delays between API calls
- **Error Handling**: Robust retry logic for network issues
- **Data Caching**: Cache market data to reduce API usage
- **Session Management**: Handle session expiration gracefully

### IVR Calculation Notes
- IVR = (Current IV - 52-week IV Low) / (52-week IV High - 52-week IV Low) * 100
- Requires historical implied volatility data
- May need to implement custom IV calculation if not provided by API
- Consider using 30-day IV for consistency

### Security Best Practices
- Store credentials in environment variables
- Never commit sensitive information to version control
- Use secure session handling
- Implement proper error logging without exposing credentials

## Success Metrics
1. **Accuracy**: Correctly identify high IVR symbols
2. **Performance**: Process watchlist within reasonable time
3. **Reliability**: Handle API errors and network issues gracefully
4. **Usability**: Clear output and easy configuration
5. **Security**: Secure credential handling

## Risk Mitigation
- **API Changes**: Use official SDK when available
- **Rate Limits**: Implement exponential backoff
- **Data Quality**: Validate all market data inputs
- **Authentication**: Fallback authentication methods
- **Dependencies**: Pin dependency versions

## Timeline Estimate
- **Phase 1**: 1-2 days
- **Phase 2**: 1 day
- **Phase 3**: 2-3 days (IVR calculation complexity)
- **Phase 4**: 1 day
- **Phase 5**: 2-3 days (optional enhancements)

**Total**: 7-10 days for full implementation

## Next Steps
1. Set up development environment
2. Install dependencies and create project structure
3. Implement authentication (Phase 1)
4. Test connection to tastytrade API
5. Begin watchlist integration (Phase 2)