# Tastytrade IVR Scanner

A Python application that scans your tastytrade watchlists and identifies symbols with high Implied Volatility Rank (IVR). This tool helps options traders quickly find potential trading opportunities by flagging symbols with elevated implied volatility.

## Features

- 🔐 Secure authentication with tastytrade API
- 📊 Automated IVR calculation for watchlist symbols
- ⚡ Configurable IVR threshold filtering (default: 25%)
- 📋 Support for multiple watchlists
- 🔄 Session management with remember tokens
- 📝 Comprehensive logging and error handling

## Quick Start

### Prerequisites

- Python 3.10+ (this repo includes a venv)
- A tastytrade account (production or certification)
- tastytrade API access

### Installation

1. Clone this repository:
```bash
git clone <repository-url>
cd tastytrade-ivr-scanner
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up your environment variables:
```bash
cp .env.example .env
# Edit .env with your tastytrade credentials
```

4. Test your connection:
```bash
./venv/bin/python main.py --test-connection
```

## Configuration

Create a `.env` file in the project root with your tastytrade credentials:

```bash
# Tastytrade Credentials
TASTYTRADE_USERNAME=your_username
TASTYTRADE_PASSWORD=your_password
TASTYTRADE_IS_TEST=false

# Scanner Configuration
IVR_THRESHOLD=25
LOG_LEVEL=INFO

# Optional Settings
CACHE_DURATION=300
MAX_RETRIES=3

# Account Selection (recommended if you have multiple accounts)
TASTY_ACCOUNT_NUMBER=5WW46136
```

### Configuration Options

| Variable | Description | Default |
|----------|-------------|---------|
| `TASTYTRADE_USERNAME` | Your tastytrade username | Required |
| `TASTYTRADE_PASSWORD` | Your tastytrade password | Required |
| `TASTYTRADE_IS_TEST` | Use certification environment | `false` |
| `IVR_THRESHOLD` | IVR percentage threshold | `25` |
| `LOG_LEVEL` | Logging level (DEBUG/INFO/WARNING/ERROR) | `INFO` |
| `CACHE_DURATION` | Data cache duration in seconds | `300` |
| `MAX_RETRIES` | Maximum API retry attempts | `3` |

## Usage

### Test Connection
```bash
./venv/bin/python main.py --test-connection
```

### List Watchlists Information
```bash
./venv/bin/python main.py --list-watchlists
```

### Get Watchlist Details
```bash
./venv/bin/python main.py --watchlist-info "Your Watchlist Name"
```

### Scan a Watchlist (Coming in Phase 3)
```bash
./venv/bin/python main.py --watchlist "My Watchlist"
```

### Custom IVR Threshold
```bash
./venv/bin/python main.py --watchlist "High IV Plays" --threshold 30
```

### Debug Mode
```bash
./venv/bin/python main.py --debug --watchlist "Test List"
```

## Project Status

This project is currently in **Phase 2** development:

- ✅ **Phase 1**: Setup and Authentication (Complete)
  - Project structure created
  - Configuration management implemented
  - tastytrade API authentication working
  - Session management with remember tokens
  - Connection testing functionality

- ✅ **Phase 2**: Watchlist Integration (Complete)
  - Watchlist retrieval by name (private and public)
  - Symbol extraction and filtering
  - Equity-only filtering capability
  - Comprehensive error handling
  - Multiple watchlist support
  - Watchlist information and validation

- ⏳ **Phase 3**: Market Data & IVR Calculation (Next)
  - Fetch market data and option chains
  - Implement IVR calculation algorithm
  - Apply threshold filtering

- 📋 **Phase 4**: Scanning Logic & Output (Planned)
  - Complete end-to-end workflow
  - Formatted output and reporting

- 📋 **Phase 5**: Enhancement & Optimization (Future)
  - Additional features and optimizations

## Development

### Project Structure
```
tastytrade-ivr-scanner/
├── src/
│   ├── __init__.py
│   ├── auth.py           # Authentication and session management
│   ├── config.py         # Configuration management
│   ├── watchlist.py      # Watchlist operations (coming soon)
│   ├── market_data.py    # Market data and IVR calculations (coming soon)
│   └── scanner.py        # Main scanning logic (coming soon)
├── tests/                # Unit tests (coming soon)
├── .env.example          # Environment variables template
├── .agents               # Agent automation configuration
├── PROJECT_PLAN.md       # Detailed project plan
├── requirements.txt      # Python dependencies
├── main.py              # Application entry point
└── README.md
```

### Running Tests
```bash
python -m pytest tests/  # Coming in Phase 2
```

### Contributing

This project uses agent-based development. See `.agents` file for agent roles and responsibilities.

## Security

- 🔒 Credentials are stored in environment variables
- 🔑 Remember tokens used for session persistence
- 📝 Sensitive data excluded from logs
- ⚠️ Never commit `.env` file to version control

## Troubleshooting

### Authentication Issues
1. Verify your credentials in the `.env` file
2. Check if you're using the correct environment (test vs production)
3. Ensure you have valid tastytrade credentials for the selected environment
4. For test environment (`TASTYTRADE_IS_TEST=true`), you need certification/sandbox credentials
5. For production environment (`TASTYTRADE_IS_TEST=false`), use your live trading credentials
6. Run `./venv/bin/python main.py --test-connection` to diagnose issues

### Common Errors
- **"Required environment variable not set"**: Check your `.env` file
- **"Authentication failed"**: Verify username/password
- **"Connection test failed"**: Check network connectivity and API status

## API Rate Limits

The application implements intelligent rate limiting:
- Automatic retry with exponential backoff
- Configurable maximum retry attempts
- Data caching to reduce API calls

## License

This project is for educational and personal use. Please comply with tastytrade's Terms of Service and API usage guidelines.

## Support

For issues and questions:
1. Check the troubleshooting section
2. Review the logs in `tastytrade_scanner.log`
3. Ensure you're using the latest version of dependencies# tasty-coach
