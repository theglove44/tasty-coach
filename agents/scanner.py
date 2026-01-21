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
from tastytrade.instruments import get_option_chain, get_future_option_chain


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

@dataclass
class SnapshotData:
    """Data class for Market Snapshot."""
    symbol: str
    last: float = 0.0
    net_change: float = 0.0
    percent_change: float = 0.0
    description: str = ""


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

    def get_market_snapshot(self, symbols: List[str]) -> List[SnapshotData]:
        """Fetch market snapshot (price, change) for symbols."""
        futures = [s for s in symbols if s.startswith('/')]
        # Treat everything else as equity/index for now
        equities = [s for s in symbols if not s.startswith('/')]
        
        snapshot_data = []

        try:
            # Fetch Futures
            if futures:
                # Resolve root symbols (e.g. /ES) to active contracts (e.g. /ESH6)
                resolved_futures = []
                for f in futures:
                    # Try to resolve via Future Option Chain active underlying
                    # Input could be '/ES' or 'ES' or '/ESH6'
                    # We try to treat it as a product code first (strip /)
                    product_code = f.lstrip('/')
                    
                    found = False
                    try:
                        # Try future option chain first (most reliable for roots)
                        chain = get_future_option_chain(self.session, product_code)
                        if chain:
                            # Use first exp, first strike to find underlying
                            first_exp = list(chain.keys())[0]
                            strike = chain[first_exp][0]
                            if hasattr(strike, 'underlying_symbol'):
                                resolved_futures.append(strike.underlying_symbol)
                                found = True
                    except Exception:
                        pass
                    
                    if not found:
                        # If failed, it might be already a valid symbol or equity option chain?
                        # Or maybe get_option_chain works (like for /ES sometimes?)
                        try:
                            chain = get_option_chain(self.session, f)
                            if chain:
                                first_exp = list(chain.keys())[0]
                                strike = chain[first_exp][0]
                                if hasattr(strike, 'underlying_symbol'):
                                    resolved_futures.append(strike.underlying_symbol)
                                    found = True
                        except Exception:
                            pass
                            
                    if not found:
                         # Fallback to original
                         resolved_futures.append(f)

                data = get_market_data_by_type(self.session, futures=resolved_futures)
                
                for d in data:
                    last = float(d.last) if d.last else 0.0
                    prev = float(d.prev_close) if d.prev_close else 0.0
                    change = last - prev
                    pct = (change / prev) * 100 if prev != 0 else 0.0
                    
                    snapshot_data.append(SnapshotData(
                        symbol=d.symbol,
                        last=last,
                        net_change=change,
                        percent_change=pct,
                        description=getattr(d, 'description', "")
                    ))

            
            # Fetch Equities/Indices
            if equities:
                data = get_market_data_by_type(self.session, equities=equities)
                for d in data:
                    last = float(d.last) if d.last else 0.0
                    prev = float(d.prev_close) if d.prev_close else 0.0
                    change = last - prev
                    pct = (change / prev) * 100 if prev != 0 else 0.0
                    
                    snapshot_data.append(SnapshotData(
                        symbol=d.symbol,
                        last=last,
                        net_change=change,
                        percent_change=pct,
                        description=getattr(d, 'description', "")
                    ))

        except Exception as e:
            self.logger.error(f"Error fetching snapshot: {e}")

        return snapshot_data


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
        report.append("-" * 70)
        return "\n".join(report)

    def print_snapshot(self, data: List[SnapshotData]) -> None:
        """Print a market snapshot table."""
        if not data:
            print("No snapshot data available.")
            return

        # Sort by Change % (Descending)
        data.sort(key=lambda x: x.percent_change, reverse=True)

        print("")
        print(f"{'Symbol':<10} {'Last':>10} {'Chg':>10} {'Chg%':>10}")
        print("-" * 44)

        for item in data:
            # Color coding (ANSI escape codes)
            # Red: \033[91m, Green: \033[92m, Reset: \033[0m
            color = "\033[92m" if item.net_change >= 0 else "\033[91m"
            reset = "\033[0m"
            
            # Format numbers
            last_str = f"{item.last:,.2f}"
            chg_str = f"{item.net_change:+.2f}"
            pct_str = f"{item.percent_change:+.2f}%"

            # Apply color to the whole line or just values? 
            # User image shows values colored.
            # Symbol white/bold, values colored.
            
            symbol_fmt = f"\033[1m{item.symbol:<10}\033[0m" # Bold symbol
            
            # For coloring, we apply to each value col
            print(f"{symbol_fmt} {color}{last_str:>10} {chg_str:>10} {pct_str:>10}{reset}")
        print("")

