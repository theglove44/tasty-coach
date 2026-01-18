# Tastytrade IVR Watchlist Scanner - Project Plan

## Overview
Create a Python application that connects to your tastytrade account, retrieves symbols from an existing watchlist, and flags any symbols with an IVR (Implied Volatility Rank) over 25%.

## Project Structure
```
tastytrade-ivr-scanner/
├── src/
│   ├── __init__.py
│   ├── auth.py           # Authentication and session management
│   ├── watchlist.py      # Watchlist operations
│   ├── market_data.py    # Market data and IVR calculations
│   ├── scanner.py        # Main scanning logic
│   └── config.py         # Configuration management
├── requirements.txt
├── .env                  # Environment variables for credentials
├── main.py              # Entry point
├── .agents              # Agent automation configuration
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
- `src/auth.py` - Authentication logic
- `src/config.py` - Configuration management
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
- `src/watchlist.py` - Watchlist operations

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
- `src/market_data.py` - Market data and IVR calculations

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
- `src/scanner.py` - Main scanning logic
- `main.py` - Entry point and CLI interface

**Success Criteria**:
- Complete end-to-end scanning workflow
- Clear, actionable output
- Robust error handling

### Phase 5: Enhancement & Optimization
**Objective**: Add advanced features and optimizations

**Tasks**:
- Add email/SMS alert functionality
- Implement scheduled scanning
- Create new watchlists from filtered results
- Add historical IVR trending
- Performance optimization and batch processing
- Add configuration file support
- Create detailed logging and metrics

**Optional Features**:
- Web dashboard interface
- Database storage for historical tracking
- Multiple threshold alerts
- Integration with other trading platforms

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
TASTY_ACCOUNT_ID=your_account_id
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