"""Hardcoded sector classification for the watchlist universe.

V1 keeps this static. Sector overlap drives the account-fit filter so the AI
coach (and `--best-trades`) won't surface a candidate whose underlying shares
a sector with an open position. Unknown symbols return ``None`` and bypass
the gate (fail-open: better to surface a possibly-overlapping pick than
silently drop a legitimate one).
"""

from __future__ import annotations

from typing import Optional

_SECTORS: dict[str, str] = {
    # --- Mega-cap tech ---
    "AAPL": "tech_hardware",
    "MSFT": "tech_software",
    "GOOGL": "tech_internet",
    "GOOG": "tech_internet",
    "META": "tech_internet",
    "AMZN": "consumer_internet",
    "NVDA": "tech_semiconductors",
    "AMD": "tech_semiconductors",
    "INTC": "tech_semiconductors",
    "AVGO": "tech_semiconductors",
    "TSM": "tech_semiconductors",
    "MU": "tech_semiconductors",
    "QCOM": "tech_semiconductors",
    "MRVL": "tech_semiconductors",
    "ARM": "tech_semiconductors",
    "ON": "tech_semiconductors",
    "NXPI": "tech_semiconductors",
    "LRCX": "tech_semiconductors",
    "AMAT": "tech_semiconductors",
    "ASML": "tech_semiconductors",
    "KLAC": "tech_semiconductors",
    "WDC": "tech_semiconductors",
    "STX": "tech_semiconductors",
    "TXN": "tech_semiconductors",
    "ADI": "tech_semiconductors",
    "SMCI": "tech_hardware",
    "TSLA": "auto",
    "NFLX": "tech_internet",
    "ORCL": "tech_software",
    "CRM": "tech_software",
    "ADBE": "tech_software",
    "NOW": "tech_software",
    "PLTR": "tech_software",
    "SNOW": "tech_software",
    "SHOP": "tech_software",
    # --- Financials / banks ---
    "JPM": "financial_bank",
    "BAC": "financial_bank",
    "WFC": "financial_bank",
    "C": "financial_bank",
    "GS": "financial_bank",
    "MS": "financial_bank",
    "SCHW": "financial_broker",
    "BLK": "financial_asset_mgr",
    "BRK/B": "financial_diversified",
    "V": "financial_payments",
    "MA": "financial_payments",
    "PYPL": "financial_payments",
    "AXP": "financial_payments",
    "SQ": "financial_payments",
    # --- Healthcare ---
    "JNJ": "health_pharma",
    "PFE": "health_pharma",
    "MRK": "health_pharma",
    "LLY": "health_pharma",
    "ABBV": "health_pharma",
    "BMY": "health_pharma",
    "UNH": "health_insurer",
    "CVS": "health_insurer",
    "TMO": "health_devices",
    "ABT": "health_devices",
    # --- Energy ---
    "XOM": "energy_oil",
    "CVX": "energy_oil",
    "COP": "energy_oil",
    "OXY": "energy_oil",
    "SLB": "energy_services",
    "MPC": "energy_refiner",
    # --- Industrial / aerospace ---
    "BA": "industrial_aerospace",
    "CAT": "industrial_machinery",
    "DE": "industrial_machinery",
    "GE": "industrial_diversified",
    "HON": "industrial_diversified",
    "RTX": "industrial_aerospace",
    "LMT": "industrial_defense",
    # --- Consumer ---
    "WMT": "consumer_staples",
    "COST": "consumer_staples",
    "TGT": "consumer_staples",
    "HD": "consumer_retail",
    "LOW": "consumer_retail",
    "NKE": "consumer_apparel",
    "MCD": "consumer_restaurants",
    "SBUX": "consumer_restaurants",
    "DIS": "media",
    # --- Comm services ---
    "T": "telecom",
    "VZ": "telecom",
    "TMUS": "telecom",
    # --- Crypto / fintech ---
    "COIN": "crypto",
    "MSTR": "crypto",
    "MARA": "crypto",
    "RIOT": "crypto",
    # --- Index ETFs (treat as own sector for concentration purposes) ---
    "SPY": "etf_broad",
    "QQQ": "etf_broad",
    "IWM": "etf_broad",
    "DIA": "etf_broad",
    # --- Sector ETFs ---
    "XLF": "etf_financials",
    "XLE": "etf_energy",
    "XLK": "etf_tech",
    "XLV": "etf_health",
    "XLY": "etf_consumer_disc",
    "XLP": "etf_consumer_staples",
    "GLD": "etf_metals",
    "SLV": "etf_metals",
    "TLT": "etf_treasury",
    "USO": "etf_energy",
    # --- Misc high-volume ---
    "BABA": "tech_internet",
    "NBIS": "tech_internet",
    "UBER": "consumer_internet",
    "LYFT": "consumer_internet",
    "ABNB": "consumer_internet",
    "RBLX": "tech_software",
    "DKNG": "consumer_gaming",
    "F": "auto",
    "GM": "auto",
    "RIVN": "auto",
    "LCID": "auto",
}


def get_sector(symbol: str) -> Optional[str]:
    """Return the sector tag for a ticker, or None if unknown."""
    if not symbol:
        return None
    return _SECTORS.get(symbol.strip().upper())
