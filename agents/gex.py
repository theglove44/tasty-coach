"""
Gamma Exposure (GEX) Agent.

Calculates GEX profiles for symbols using Tastytrade API and dxFeed streaming.
Identifies gamma walls, zero-gamma levels, and trading regimes.
"""

import logging
import asyncio
from datetime import date
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from decimal import Decimal

import pandas as pd
from tastytrade import Session, DXLinkStreamer
from tastytrade.dxfeed import Greeks, Quote, Summary, Trade
from tastytrade.instruments import Option, get_option_chain
from tastytrade.market_data import a_get_market_data_by_type

# Constants
GEX_REVERSION_THRESHOLD = 1_000_000_000  # $1B Net GEX threshold


@dataclass
class GEXResult:
    """Container for GEX calculation results."""
    symbol: str
    spot_price: float
    total_gex: float
    zero_gamma_level: Optional[float]
    max_dte: int
    strike_range: tuple
    df: pd.DataFrame  # Full option-level data
    strike_gex: pd.DataFrame  # Aggregated by strike
    major_levels: pd.DataFrame  # Filtered major walls
    call_wall: Optional[float]  # Highest positive GEX strike
    put_wall: Optional[float]  # Lowest negative GEX strike
    strategy: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class GEXAgent:
    """
    Gamma Exposure Analysis Agent.
    
    Calculates GEX profiles to identify:
    - Call/Put walls (major gamma levels)
    - Zero Gamma level (dealer hedging flip point)
    - Positive/Negative gamma regimes
    - Trading signals based on GEX analysis
    """

    def __init__(self, session: Session):
        self.session = session
        self.logger = logging.getLogger(__name__)

    async def _get_spot_price(self, streamer: DXLinkStreamer, symbol: str) -> Optional[float]:
        """Fetch current spot price for a symbol via streaming."""
        await streamer.subscribe(Quote, [symbol])
        await streamer.subscribe(Trade, [symbol])
        
        try:
            t_quote = asyncio.create_task(streamer.get_event(Quote))
            t_trade = asyncio.create_task(streamer.get_event(Trade))
            
            done, pending = await asyncio.wait(
                [t_quote, t_trade], 
                return_when=asyncio.FIRST_COMPLETED, 
                timeout=5.0
            )
            
            for p in pending:
                p.cancel()
                
            if not done:
                return None
                
            event = done.pop().result()
            
            if hasattr(event, 'price') and event.price:
                return float(event.price)
            if hasattr(event, 'last_price') and event.last_price:
                return float(event.last_price)
            if (hasattr(event, 'ask_price') and hasattr(event, 'bid_price')
                and event.ask_price and event.bid_price):
                return (float(event.ask_price) + float(event.bid_price)) / 2.0
                
        except Exception as e:
            self.logger.warning(f"Error getting spot price: {e}")
            
        return None

    def _calculate_zero_gamma(self, strike_gex: pd.DataFrame, spot: float) -> Optional[float]:
        """
        Calculate the zero gamma level (where cumulative GEX crosses zero).
        This is where dealer hedging flips from supportive to resistive.
        """
        if strike_gex.empty:
            return None

        sorted_df = strike_gex.sort_values('Strike')
        gex_values = sorted_df['Net GEX ($M)'].values
        strikes = sorted_df['Strike'].values

        for i in range(len(gex_values) - 1):
            if gex_values[i] * gex_values[i + 1] < 0:  # Sign change
                x1, x2 = strikes[i], strikes[i + 1]
                y1, y2 = gex_values[i], gex_values[i + 1]
                zero_cross = x1 - y1 * (x2 - x1) / (y2 - y1)
                return round(zero_cross, 2)

        return None

    def _analyze_strategy(
        self,
        total_gex: float,
        spot_price: float,
        call_wall: Optional[float],
        put_wall: Optional[float],
        zero_gamma: Optional[float]
    ) -> Optional[Dict[str, Any]]:
        """
        Analyze GEX data to generate trading signals/strategies.
        """
        if spot_price is None or call_wall is None or put_wall is None:
            return None

        import datetime
        current_hour = datetime.datetime.now().hour
        
        # Mean Reversion Play (Positive GEX Regime)
        if total_gex > GEX_REVERSION_THRESHOLD:
            if put_wall < spot_price < call_wall:
                return {
                    "signal": "MEAN_REVERSION",
                    "bias": "NEUTRAL",
                    "message": "Positive Gamma ($1B+). Volatility dampened. Fade moves to walls.",
                    "validity": "High",
                }

        # Acceleration Play (Negative GEX Regime)
        is_neg_gamma = total_gex < 0
        price_below_flip = (zero_gamma is not None) and (spot_price < zero_gamma)
        
        if is_neg_gamma or price_below_flip:
            return {
                "signal": "ACCELERATION",
                "bias": "BEARISH_VOL",
                "message": "Negative Gamma. Dealers chasing price. Expect range expansion.",
                "validity": "High",
            }

        # Magnet Pinning (Late Day)
        if current_hour >= 14:
            valid_walls = [w for w in [call_wall, put_wall] if w is not None]
            if valid_walls:
                nearest_wall = min(valid_walls, key=lambda x: abs(x - spot_price))
                dist_pct = abs(spot_price - nearest_wall) / spot_price
                
                if dist_pct < 0.005:
                    return {
                        "signal": "MAGNET_PIN",
                        "bias": "NEUTRAL",
                        "message": f"Price pinning to {nearest_wall} wall into close.",
                        "validity": "Medium",
                    }
                    
        return None

    async def calculate_gex(
        self,
        symbol: str = 'SPY',
        max_dte: int = 30,
        strike_range_pct: float = 0.20,
        major_level_threshold: float = 50.0,
        data_wait_seconds: float = 5.0,
    ) -> GEXResult:
        """
        Calculate GEX profile for a given symbol.

        Args:
            symbol: Ticker symbol (e.g., 'SPY', 'QQQ', 'SPX')
            max_dte: Maximum days to expiration
            strike_range_pct: Strike range as percentage of spot (0.20 = 80%-120%)
            major_level_threshold: Minimum absolute GEX ($M) for major levels
            data_wait_seconds: Time to wait for streaming data

        Returns:
            GEXResult with all calculated data
        """
        self.logger.info(f"Calculating GEX for {symbol}...")

        async with DXLinkStreamer(self.session) as streamer:
            # Get spot price
            spot = await self._get_spot_price(streamer, symbol)
            if spot is None:
                return GEXResult(
                    symbol=symbol, spot_price=0, total_gex=0, zero_gamma_level=None,
                    max_dte=max_dte, strike_range=(0, 0), df=pd.DataFrame(),
                    strike_gex=pd.DataFrame(), major_levels=pd.DataFrame(),
                    call_wall=None, put_wall=None,
                    error="Could not fetch spot price"
                )

            # Get option chain
            self.logger.info(f"Fetching option chain for {symbol}...")
            try:
                chain = get_option_chain(self.session, symbol)
            except Exception as e:
                return GEXResult(
                    symbol=symbol, spot_price=spot, total_gex=0, zero_gamma_level=None,
                    max_dte=max_dte, strike_range=(0, 0), df=pd.DataFrame(),
                    strike_gex=pd.DataFrame(), major_levels=pd.DataFrame(),
                    call_wall=None, put_wall=None,
                    error=f"Failed to fetch option chain: {e}"
                )

            # Flatten chain to list
            all_options_raw = []
            if isinstance(chain, dict):
                for opts in chain.values():
                    if isinstance(opts, list):
                        all_options_raw.extend(opts)

            # Filter options
            today = date.today()
            lower_bound = spot * (1 - strike_range_pct)
            upper_bound = spot * (1 + strike_range_pct)

            all_options = []
            for opt in all_options_raw:
                if not hasattr(opt, 'expiration_date') or opt.expiration_date is None:
                    continue
                if not hasattr(opt, 'strike_price') or opt.strike_price is None:
                    continue

                days_to_exp = (opt.expiration_date - today).days
                if not (0 <= days_to_exp <= max_dte):
                    continue
                if not (lower_bound <= float(opt.strike_price) <= upper_bound):
                    continue
                all_options.append(opt)

            if not all_options:
                return GEXResult(
                    symbol=symbol, spot_price=spot, total_gex=0, zero_gamma_level=None,
                    max_dte=max_dte, strike_range=(lower_bound, upper_bound),
                    df=pd.DataFrame(), strike_gex=pd.DataFrame(), major_levels=pd.DataFrame(),
                    call_wall=None, put_wall=None,
                    error="No options found after filtering"
                )

            self.logger.info(f"Found {len(all_options)} options to analyze...")

            # Fetch market data (OI)
            market_data_map = {}
            all_symbols = [opt.symbol for opt in all_options]

            for i in range(0, len(all_symbols), 100):
                chunk = all_symbols[i:i + 100]
                try:
                    market_data = await a_get_market_data_by_type(self.session, options=chunk)
                    for md in market_data:
                        entry = {}
                        if md.open_interest is not None:
                            entry['oi'] = int(md.open_interest)
                        if hasattr(md, 'volume') and md.volume is not None:
                            entry['volume'] = int(md.volume)
                        if entry:
                            market_data_map[md.symbol] = entry
                except Exception:
                    pass

            # Stream Greeks
            greeks_events = []

            async def listen_greeks():
                async for event in streamer.listen(Greeks):
                    greeks_events.append(event)

            t_greeks = asyncio.create_task(listen_greeks())

            symbols_to_sub = [opt.streamer_symbol for opt in all_options]
            try:
                await streamer.subscribe(Greeks, symbols_to_sub)
            except Exception:
                pass

            self.logger.info(f"Collecting streaming data ({data_wait_seconds}s)...")
            await asyncio.sleep(data_wait_seconds)

            t_greeks.cancel()
            try:
                await t_greeks
            except asyncio.CancelledError:
                pass

            greek_map = {g.event_symbol: g for g in greeks_events}

            # Calculate GEX
            self.logger.info("Calculating GEX values...")
            data = []
            for opt in all_options:
                s_sym = opt.streamer_symbol
                matching_greek = greek_map.get(s_sym)

                gamma = float(matching_greek.gamma) if matching_greek and matching_greek.gamma else 0.0

                md_entry = market_data_map.get(opt.symbol, {})
                oi = md_entry.get('oi', 0)
                volume = md_entry.get('volume', 0)

                strike = float(opt.strike_price)
                raw_gex_m = (oi * gamma * 100 * (spot ** 2) * 0.01) / 1_000_000

                is_call = opt.option_type == 'C'
                net_gex = raw_gex_m if is_call else -raw_gex_m

                data.append({
                    'Expiration': opt.expiration_date,
                    'Strike': strike,
                    'Type': 'Call' if is_call else 'Put',
                    'OI': oi,
                    'Volume': volume,
                    'Gamma': gamma,
                    'Net GEX ($M)': round(net_gex, 4),
                    'Call GEX ($M)': round(raw_gex_m if is_call else 0.0, 4),
                    'Put GEX ($M)': round(-raw_gex_m if not is_call else 0.0, 4)
                })

            if not data:
                return GEXResult(
                    symbol=symbol, spot_price=spot, total_gex=0, zero_gamma_level=None,
                    max_dte=max_dte, strike_range=(lower_bound, upper_bound),
                    df=pd.DataFrame(), strike_gex=pd.DataFrame(), major_levels=pd.DataFrame(),
                    call_wall=None, put_wall=None,
                    error="No GEX data calculated"
                )

            df = pd.DataFrame(data)
            total_gex = df['Net GEX ($M)'].sum()

            # Aggregate by strike
            strike_gex = df.groupby('Strike')[['Net GEX ($M)', 'Call GEX ($M)', 'Put GEX ($M)', 'OI', 'Volume']].sum().reset_index()
            strike_gex.rename(columns={'OI': 'Total OI', 'Volume': 'Total Volume'}, inplace=True)
            strike_gex = strike_gex.sort_values(by='Strike')

            # Major levels
            major_levels = strike_gex[strike_gex['Net GEX ($M)'].abs() > major_level_threshold].copy()
            major_levels['Net GEX ($M)'] = major_levels['Net GEX ($M)'].round(1)
            major_levels['Type'] = major_levels['Net GEX ($M)'].apply(lambda x: 'Call' if x > 0 else 'Put')

            # Find walls
            positive_gex = strike_gex[strike_gex['Net GEX ($M)'] > 0]
            negative_gex = strike_gex[strike_gex['Net GEX ($M)'] < 0]

            call_wall = None
            put_wall = None

            if not positive_gex.empty:
                call_wall = positive_gex.loc[positive_gex['Net GEX ($M)'].idxmax(), 'Strike']
            if not negative_gex.empty:
                put_wall = negative_gex.loc[negative_gex['Net GEX ($M)'].idxmin(), 'Strike']

            # Zero gamma
            zero_gamma = self._calculate_zero_gamma(strike_gex, spot)

            self.logger.info("GEX calculation complete.")

            return GEXResult(
                symbol=symbol,
                spot_price=spot,
                total_gex=round(total_gex, 2),
                zero_gamma_level=zero_gamma,
                max_dte=max_dte,
                strike_range=(lower_bound, upper_bound),
                df=df,
                strike_gex=strike_gex,
                major_levels=major_levels,
                call_wall=call_wall,
                put_wall=put_wall,
                strategy=self._analyze_strategy(total_gex, spot, call_wall, put_wall, zero_gamma),
                error=None
            )

    def get_gamma_walls(self, result: GEXResult) -> Dict[str, Any]:
        """
        Extract key gamma levels from a GEX result.
        
        Returns:
            Dict with call_wall, put_wall, zero_gamma, and spot_price
        """
        return {
            'call_wall': result.call_wall,
            'put_wall': result.put_wall,
            'zero_gamma': result.zero_gamma_level,
            'spot_price': result.spot_price,
            'total_gex': result.total_gex,
        }

    def analyze_regime(self, result: GEXResult) -> str:
        """
        Analyze the current gamma regime.
        
        Returns:
            Human-readable description of the gamma regime and implications.
        """
        if result.error:
            return f"Error: {result.error}"

        total_gex = result.total_gex
        spot = result.spot_price
        call_wall = result.call_wall
        put_wall = result.put_wall
        zero_gamma = result.zero_gamma_level

        lines = []
        
        # Regime classification
        if total_gex > 0:
            gex_b = total_gex / 1000  # Convert to billions for display
            lines.append(f"POSITIVE GAMMA REGIME (+${gex_b:.2f}B)")
            lines.append("  → Dealers are long gamma (will sell rallies, buy dips)")
            lines.append("  → Expect volatility compression and mean reversion")
            lines.append("  → Good environment for selling premium")
        else:
            gex_b = abs(total_gex) / 1000
            lines.append(f"NEGATIVE GAMMA REGIME (-${gex_b:.2f}B)")
            lines.append("  → Dealers are short gamma (will chase price)")
            lines.append("  → Expect volatility expansion and trend continuation")
            lines.append("  → Careful with short premium positions")

        # Key levels
        lines.append("")
        lines.append("KEY LEVELS:")
        if call_wall:
            dist = ((call_wall - spot) / spot) * 100
            lines.append(f"  Call Wall: {call_wall:.2f} ({dist:+.1f}% from spot)")
        if put_wall:
            dist = ((put_wall - spot) / spot) * 100
            lines.append(f"  Put Wall:  {put_wall:.2f} ({dist:+.1f}% from spot)")
        if zero_gamma:
            dist = ((zero_gamma - spot) / spot) * 100
            lines.append(f"  Zero Gamma: {zero_gamma:.2f} ({dist:+.1f}% from spot)")

        # Trading signal
        if result.strategy:
            lines.append("")
            lines.append(f"SIGNAL: {result.strategy['signal']}")
            lines.append(f"  {result.strategy['message']}")

        return "\n".join(lines)

    def generate_report(self, result: GEXResult) -> str:
        """
        Generate a formatted console report for GEX analysis.
        Similar to ScannerAgent.generate_report() style.
        """
        if result.error:
            return f"GEX Error: {result.error}"

        lines = [
            "=" * 70,
            f"       G A M M A   E X P O S U R E   A N A L Y S I S".center(70),
            "=" * 70,
            f" Symbol: {result.symbol} | Spot: ${result.spot_price:.2f} | Net GEX: ${result.total_gex:.1f}M",
            "-" * 70,
        ]

        # Regime
        if result.total_gex > 0:
            regime = "POSITIVE (Dealers Long Gamma - Volatility Dampened)"
        else:
            regime = "NEGATIVE (Dealers Short Gamma - Volatility Amplified)"
        lines.append(f" Regime: {regime}")

        # Key Levels
        lines.append("-" * 70)
        lines.append(" KEY GAMMA LEVELS:")
        
        if result.call_wall:
            dist = ((result.call_wall - result.spot_price) / result.spot_price) * 100
            lines.append(f"   Call Wall (Resistance): ${result.call_wall:.2f} ({dist:+.1f}%)")
        if result.put_wall:
            dist = ((result.put_wall - result.spot_price) / result.spot_price) * 100
            lines.append(f"   Put Wall (Support):     ${result.put_wall:.2f} ({dist:+.1f}%)")
        if result.zero_gamma_level:
            dist = ((result.zero_gamma_level - result.spot_price) / result.spot_price) * 100
            lines.append(f"   Zero Gamma (Flip):      ${result.zero_gamma_level:.2f} ({dist:+.1f}%)")

        # Major Levels Table
        if not result.major_levels.empty:
            lines.append("-" * 70)
            lines.append(" MAJOR GEX LEVELS (|GEX| > $50M):")
            lines.append(f" {'Strike':>10} | {'Net GEX':>10} | {'Type':>6} | {'Total OI':>10}")
            lines.append(" " + "-" * 45)
            
            for _, row in result.major_levels.head(10).iterrows():
                lines.append(
                    f" {row['Strike']:>10.2f} | "
                    f"${row['Net GEX ($M)']:>8.1f}M | "
                    f"{row['Type']:>6} | "
                    f"{int(row['Total OI']):>10,}"
                )

        # Strategy Signal
        if result.strategy:
            lines.append("-" * 70)
            lines.append(f" SIGNAL: {result.strategy['signal']} ({result.strategy['validity']} validity)")
            lines.append(f"   {result.strategy['message']}")

        lines.append("=" * 70)
        
        return "\n".join(lines)


def run_gex_sync(session: Session, symbol: str = 'SPY', **kwargs) -> GEXResult:
    """Synchronous wrapper for GEXAgent.calculate_gex()."""
    agent = GEXAgent(session)
    return asyncio.run(agent.calculate_gex(symbol, **kwargs))
