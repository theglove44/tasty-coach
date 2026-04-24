"""Static correlation bucket mapping for Phase C concentration analysis."""

from typing import Dict, Iterable, List, Tuple

BUCKETS: Dict[str, str] = {
    "SPY": "US_EQUITY_INDEX", "SPX": "US_EQUITY_INDEX",
    "QQQ": "US_EQUITY_INDEX", "NDX": "US_EQUITY_INDEX",
    "IWM": "US_EQUITY_INDEX", "RUT": "US_EQUITY_INDEX",
    "DIA": "US_EQUITY_INDEX",
    "AAPL": "MEGA_TECH", "MSFT": "MEGA_TECH", "GOOGL": "MEGA_TECH",
    "GOOG": "MEGA_TECH", "META": "MEGA_TECH", "AMZN": "MEGA_TECH",
    "NVDA": "MEGA_TECH", "TSLA": "MEGA_TECH",
    "AMD": "SEMIS", "INTC": "SEMIS", "SMH": "SEMIS", "TSM": "SEMIS",
    "XLE": "ENERGY", "USO": "ENERGY", "XOM": "ENERGY", "CVX": "ENERGY",
    "XLF": "FINANCIALS", "JPM": "FINANCIALS", "BAC": "FINANCIALS",
    "GS": "FINANCIALS", "WFC": "FINANCIALS",
    "GLD": "GOLD", "GDX": "GOLD", "SLV": "GOLD",
    "VXX": "VOLATILITY", "UVXY": "VOLATILITY", "VIX": "VOLATILITY",
    "TLT": "BONDS", "IEF": "BONDS", "HYG": "BONDS",
}


def bucket_for(symbol: str) -> str:
    """Return the correlation bucket label for `symbol`.

    Unknown symbols map to their uppercased self so they form a singleton bucket.
    """
    key = symbol.upper()
    return BUCKETS.get(key, key)


def group_by_bucket(
    symbol_values: Iterable[Tuple[str, float]],
) -> Dict[str, List[Tuple[str, float]]]:
    """Group (symbol, value) pairs by correlation bucket, preserving insertion order."""
    grouped: Dict[str, List[Tuple[str, float]]] = {}
    for sym, val in symbol_values:
        b = bucket_for(sym)
        grouped.setdefault(b, []).append((sym, val))
    return grouped
