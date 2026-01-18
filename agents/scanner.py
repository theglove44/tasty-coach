"""
Watchlist & IVR Filtering Agent.
"""

import logging
from typing import Dict, List, Tuple, Optional, Set
from datetime import datetime
from decimal import Decimal
from dataclasses import dataclass

from tastytrade import Session
from tastytrade.metrics import get_market_metrics, MarketMetricInfo
from tastytrade.market_data import get_market_data_by_type
from tastytrade.watchlists import PrivateWatchlist, PublicWatchlist
from tastytrade.order import InstrumentType

@dataclass
class IVRData:
    """Data class for IVR calculation results."""
    symbol: str
    current_iv: Optional[float] = None
    iv_rank: Optional[float] = None
    iv_percentile: Optional[float] = None
    beta: Optional[float] = None
    liquidity_rank: Optional[float] = None
    next_earnings_date: Optional[str] = None
    current_price: Optional[Decimal] = None
    volume: Optional[Decimal] = None
    has_options: bool = False
    error_message: Optional[str] = None

class ScannerAgent:
    """Watchlist & IVR Filtering Agent."""

    def __init__(self, session: Session, threshold: float = 25.0):
        self.session = session
        self.threshold = threshold
        self.logger = logging.getLogger(__name__)

    def get_symbols_from_watchlist(self, watchlist_name: str, equity_only: bool = True) -> List[str]:
        """Extract symbols from a private or public watchlist."""
        # Try private first
        watchlists = PrivateWatchlist.get(self.session)
        target = next((w for w in watchlists if w.name == watchlist_name), None)
        
        if not target:
            # Try public
            watchlists = PublicWatchlist.get(self.session)
            target = next((w for w in watchlists if w.name == watchlist_name), None)
            
        if not target:
            self.logger.error(f"Watchlist '{watchlist_name}' not found")
            return []

        symbols = []
        for entry in target.watchlist_entries:
            symbol = entry.symbol if hasattr(entry, 'symbol') else entry.get('symbol')
            inst_type = entry.instrument_type if hasattr(entry, 'instrument_type') else entry.get('instrument-type')
            
            if equity_only and inst_type != InstrumentType.EQUITY:
                continue
            symbols.append(symbol)
            
        return symbols

    def scan_ivr(self, symbols: List[str]) -> Dict[str, IVRData]:
        """Fetch IVR data for symbols in batches."""
        results = {}
        batch_size = 50
        
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            
            # Fetch Metrics
            try:
                metrics = {m.symbol: m for m in get_market_metrics(self.session, batch)}
                prices = {d.symbol: d for d in get_market_data_by_type(self.session, equities=batch)}
                
                for symbol in batch:
                    metric = metrics.get(symbol)
                    data = prices.get(symbol)
                    
                    ivr = IVRData(symbol=symbol)
                    if data:
                        ivr.current_price = data.mark or data.last
                        ivr.volume = data.volume
                        
                    if metric:
                        ivr.iv_rank = (float(metric.implied_volatility_index_rank) * 100) if metric.implied_volatility_index_rank else None
                        ivr.iv_percentile = (float(metric.implied_volatility_percentile) * 100) if metric.implied_volatility_percentile else None
                        ivr.current_iv = float(metric.implied_volatility_index) if metric.implied_volatility_index else None
                        ivr.beta = float(metric.beta) if metric.beta else None
                        ivr.liquidity_rank = float(metric.liquidity_rank) if metric.liquidity_rank else None
                        if metric.earnings and metric.earnings.expected_report_date:
                            ivr.next_earnings_date = metric.earnings.expected_report_date.strftime('%m/%d')
                        ivr.has_options = True
                        
                    results[symbol] = ivr
            except Exception as e:
                self.logger.error(f"Error scanning batch: {e}")
                
        return results

    def get_high_ivr_targets(self, results: Dict[str, IVRData]) -> List[IVRData]:
        """Filter results for those above threshold."""
        targets = [d for d in results.values() if d.iv_rank is not None and d.iv_rank >= self.threshold]
        targets.sort(key=lambda x: x.iv_rank, reverse=True)
        return targets

    def generate_report(self, targets: List[IVRData]) -> str:
        """Generate a console report for targets."""
        if not targets:
            return "No high IVR targets found."
            
        report = [
            "=" * 70,
            "           T A S T Y T R A D E   I V R   S C A N".center(70),
            "=" * 70,
            f" Threshold: > {self.threshold}% IVR | Targets: {len(targets)}",
            "-" * 70,
            f"{'Symbol':<8} | {'IVR':>5} | {'IVP':>5} | {'IV':>5} | {'Price':>9} | {'Liq':<5} | {'Earns':<5}",
            "-" * 70
        ]
        
        for t in targets:
            ivr = f"{t.iv_rank:>5.1f}%"
            ivp = f"{t.iv_percentile:>5.1f}%" if t.iv_percentile else "N/A  "
            iv = f"{t.current_iv * 100:4.0f}%" if t.current_iv else "N/A "
            price = f"${t.current_price:8.2f}" if t.current_price else "N/A     "
            stars = ("★" * min(5, max(1, int(t.liquidity_rank)))).ljust(5) if t.liquidity_rank else "N/A  "
            earns = t.next_earnings_date if t.next_earnings_date else "N/A  "
            
            report.append(f"{t.symbol:<8} | {ivr:>5} | {ivp:>5} | {iv:>5} | {price:>9} | {stars:<5} | {earns:<5}")
            
        report.append("-" * 70)
        return "\n".join(report)
