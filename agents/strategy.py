import logging
import asyncio
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime, date, timedelta
from dataclasses import dataclass
from decimal import Decimal

from tastytrade import Session
from tastytrade.instruments import NestedOptionChain, OptionType
from tastytrade.metrics import get_market_metrics
from tastytrade.market_data import get_market_data_by_type
from tastytrade.streamer import DXLinkStreamer
from tastytrade.dxfeed import Greeks

from rich.console import Console
from rich.table import Table
from rich import box

from agents.gex import GEXResult

@dataclass
class StrategyTarget:
    """Potential trade target with legs and expected metrics."""
    symbol: str
    strategy_type: str  # 'Vertical' or 'Iron Condor'
    expiration: date
    dte: int
    width: float
    expected_credit: float
    legs: List[Dict]
    ivr: float
    delta_target: float = 0.30
    gex_regime: Optional[str] = None  # "positive" | "negative"
    gex_signal: Optional[str] = None  # "MEAN_REVERSION" | "ACCELERATION" | "MAGNET_PIN"
    gamma_call_wall: Optional[float] = None
    gamma_put_wall: Optional[float] = None
    gex_warning: Optional[str] = None  # e.g., "Short strike beyond put wall"

    @property
    def max_loss(self) -> float:
        """Calculate max loss per share."""
        return self.width - self.expected_credit

    @property
    def bp_effect(self) -> float:
        """Calculate buying power effect (Max Loss * 100 for standard option)."""
        return self.max_loss * 100.0

    @property
    def credit_pct(self) -> float:
        """Calculate credit as percentage of width."""
        return (self.expected_credit / self.width) * 100.0 if self.width > 0 else 0.0

class StrategyAgent:
    """Handles strategy selection and entry logic."""
    
    def __init__(self, session: Session):
        self.session = session
        self.logger = logging.getLogger(__name__)

    async def _fetch_greeks(self, streamer_symbols: List[str], timeout: int = 5) -> Dict[str, Greeks]:
        """Fetch Greeks using DXLinkStreamer for a list of streamer symbols."""
        greeks_map = {}
        if not streamer_symbols:
            return greeks_map

        try:
            async with DXLinkStreamer(self.session) as streamer:
                await streamer.subscribe(Greeks, streamer_symbols)
                start_time = asyncio.get_event_loop().time()
                while len(greeks_map) < len(streamer_symbols):
                    if asyncio.get_event_loop().time() - start_time > timeout:
                        self.logger.warning(f"Timeout reached while fetching greeks. Got {len(greeks_map)}/{len(streamer_symbols)}")
                        break
                    
                    async for event in streamer.listen(Greeks):
                        if isinstance(event, Greeks):
                            greeks_map[event.event_symbol] = event
                        
                        if len(greeks_map) >= len(streamer_symbols):
                            break
                        
                        if asyncio.get_event_loop().time() - start_time > timeout:
                            break
        except Exception as e:
            self.logger.error(f"Error in streamer: {e}")
            
        return greeks_map

    def _get_target_expiration(self, chain: NestedOptionChain) -> Optional[Any]:
        """Find the nearest Monthly expiration to 45 DTE, excluding weeklies."""
        today = date.today()
        candidates = []
        for exp in chain.expirations:
            expiry_date = exp.expiration_date
            is_friday = expiry_date.weekday() == 4
            is_third_week = 15 <= expiry_date.day <= 21
            
            if is_friday and is_third_week:
                dte = (expiry_date - today).days
                candidates.append((abs(dte - 45), dte, exp))
        
        if not candidates:
            return None
            
        candidates.sort(key=lambda x: x[0])
        return candidates[0][2]

    async def screen_strategies(self, symbol: str, current_ivr: float) -> List[StrategyTarget]:
        """Screen for Vertical Spreads and Iron Condors based on specs."""
        if current_ivr < 25.0:
            return []

        self.logger.info(f"Screening strategies for {symbol} (IVR: {current_ivr}%)...")
        try:
            chains = NestedOptionChain.get(self.session, symbol)
            if not chains: return []
            chain = chains[0]
            target_exp = self._get_target_expiration(chain)
            if not target_exp: 
                self.logger.warning(f"No 45 DTE monthly expiration found for {symbol}")
                return []
            
            from tastytrade.instruments import get_option_chain
            full_chain = get_option_chain(self.session, symbol)
            expiry_str = target_exp.expiration_date.strftime('%Y-%m-%d')
            options = full_chain.get(target_exp.expiration_date)
            if not options:
                self.logger.warning(f"Could not find options for {expiry_str}")
                return []
                
            streamer_to_option = {opt.streamer_symbol: opt for opt in options}
            greeks = await self._fetch_greeks(list(streamer_to_option.keys()))
            
            targets = []
            
            # Filter for 30 delta
            for opt_type in [OptionType.PUT, OptionType.CALL]:
                best_short = None
                min_diff = float('inf')
                
                type_options = [opt for opt in options if opt.option_type == opt_type]
                for opt in type_options:
                    greek = greeks.get(opt.streamer_symbol)
                    if not greek or greek.delta is None: continue
                    
                    delta = abs(float(greek.delta))
                    diff = abs(delta - 0.30)
                    if diff < min_diff:
                        min_diff = diff
                        best_short = opt
                
                if not best_short: continue
                
                sorted_strikes = sorted(list(set(opt.strike_price for opt in type_options)))
                
                increment = 1.0
                if len(sorted_strikes) > 1:
                    increment = float(abs(sorted_strikes[1] - sorted_strikes[0]))
                
                target_width = 3.0 if increment <= 1.5 else 5.0
                readable_type = "Call Vertical" if opt_type == OptionType.CALL else "Put Vertical"
                self.logger.info(f"{symbol} Checking {readable_type}: Short Strike {best_short.strike_price}, Width {target_width}")
                
                # Find long strike
                best_long = None
                target_long_price = float(best_short.strike_price) + (target_width if opt_type == OptionType.CALL else -target_width)
                
                # Use Decimal for comparison
                target_long_dec = Decimal(str(target_long_price))
                best_long = next((opt for opt in type_options if opt.strike_price == target_long_dec), None)

                if not best_long:
                    self.logger.debug(f"No {target_width} width strike for {symbol} {readable_type}")
                    continue
                    
                prices = get_market_data_by_type(self.session, [best_short.symbol, best_long.symbol])
                if len(prices) < 2: continue
                
                short_mark = float(next(p for p in prices if p.symbol == best_short.symbol).mark)
                long_mark = float(next(p for p in prices if p.symbol == best_long.symbol).mark)
                credit = short_mark - long_mark
                
                min_credit = target_width * 0.25
                if credit < min_credit:
                    self.logger.info(f"Rejected {symbol} {readable_type}: Credit ${credit:.2f} < ${min_credit:.2f} (25% width)")
                    continue
                    
                targets.append(StrategyTarget(
                    symbol=symbol,
                    strategy_type=readable_type,
                    expiration=target_exp.expiration_date,
                    dte=(target_exp.expiration_date - date.today()).days,
                    width=target_width,
                    expected_credit=credit,
                    legs=[
                        {
                            'symbol': best_short.symbol,
                            'action': 'Sell',
                            'side': 'short',
                            'option_type': "CALL" if opt_type == OptionType.CALL else "PUT",
                            'strike': float(best_short.strike_price)
                        },
                        {
                            'symbol': best_long.symbol,
                            'action': 'Buy',
                            'side': 'long',
                            'option_type': "CALL" if opt_type == OptionType.CALL else "PUT",
                            'strike': float(best_long.strike_price)
                        }
                    ],
                    ivr=current_ivr
                ))

            # IC Check
            put_v = next((t for t in targets if "Put" in t.strategy_type), None)
            call_v = next((t for t in targets if "Call" in t.strategy_type), None)
            if put_v and call_v:
                targets.append(StrategyTarget(
                    symbol=symbol,
                    strategy_type="Iron Condor",
                    expiration=target_exp.expiration_date,
                    dte=put_v.dte,
                    width=put_v.width,
                    expected_credit=put_v.expected_credit + call_v.expected_credit,
                    legs=put_v.legs + call_v.legs,
                    ivr=current_ivr
                ))
            
            return targets
        except Exception as e:
            self.logger.error(f"Error screening {symbol}: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return []

    async def screen_strategies_with_gex(
        self,
        symbol: str,
        current_ivr: float,
        gex_result: Optional[GEXResult] = None
    ) -> List[StrategyTarget]:
        """Screen strategies with GEX context applied."""
        strategies = await self.screen_strategies(symbol, current_ivr)

        if not gex_result or gex_result.error:
            return strategies

        gex_signal = gex_result.strategy.get('signal') if gex_result.strategy else None
        gex_regime = "positive" if gex_result.total_gex > 0 else "negative"

        for strat in strategies:
            strat.gex_regime = gex_regime
            strat.gex_signal = gex_signal
            strat.gamma_call_wall = gex_result.call_wall
            strat.gamma_put_wall = gex_result.put_wall

            warnings = []
            if symbol in ["SPY", "SPX"]:
                for leg in strat.legs:
                    action = leg.get('side') or leg.get('action')
                    if not isinstance(action, str) or action.lower() not in ('short', 'sell', 'sold'):
                        continue
                    strike = leg.get('strike')
                    if strike is None:
                        continue
                    leg_type = leg.get('option_type')
                    if gex_result.put_wall is not None and strike < gex_result.put_wall:
                        label = "put" if leg_type == "PUT" else "strike"
                        warnings.append(
                            f"Short {label} {strike:.2f} below put wall {gex_result.put_wall:.2f}"
                        )
                    if gex_result.call_wall is not None and strike > gex_result.call_wall:
                        label = "call" if leg_type == "CALL" else "strike"
                        warnings.append(
                            f"Short {label} {strike:.2f} above call wall {gex_result.call_wall:.2f}"
                        )

            if warnings:
                strat.gex_warning = "; ".join(warnings)

        return strategies

    def manage_positions(self, positions: List[Any]) -> List[Dict]:
        """Check for 50% profit target or 21 DTE time stop."""
        to_close = []
        today = date.today()
        for pos in positions:
            if not pos.instrument_type or 'Option' not in pos.instrument_type.value:
                continue
            if getattr(pos, "expires_at", None):
                dte = (pos.expires_at.date() - today).days
                if dte <= 21:
                    to_close.append({'position': pos, 'reason': f'Time Stop ({dte} DTE)'})
                    continue
            is_short = pos.quantity < 0
            open_price = float(pos.average_open_price or 0)
            current_mark = float(pos.mark or 0) if hasattr(pos, 'mark') else 0.0
            if is_short and open_price > 0:
                profit_pct = (open_price - current_mark) / open_price
                if profit_pct >= 0.50:
                    to_close.append({'position': pos, 'reason': f'Profit Target ({profit_pct:.1%})'})
        return to_close

    def print_strategy_report(self, targets: List[StrategyTarget]) -> None:
        """Print a formatted report using Rich."""
        if not targets:
            self.logger.info("No valid strategies found.")
            return

        console = Console(width=180)
        
        # Check for GEX context
        gex_context = next(
            (t for t in targets if t.gex_regime or t.gex_signal or t.gamma_call_wall or t.gamma_put_wall),
            None
        )
        
        if gex_context:
            gex_table = Table(box=box.SIMPLE, show_header=False, title="Market Gamma Context")
            gex_table.add_column("Key", style="cyan")
            gex_table.add_column("Value", style="bold")
            
            if gex_context.gex_regime:
                color = "green" if gex_context.gex_regime == "positive" else "red"
                gex_table.add_row("Regime", f"[{color}]{gex_context.gex_regime.upper()} GAMMA[/{color}]")
            
            if gex_context.gex_signal:
                gex_table.add_row("Signal", gex_context.gex_signal)
                
            cw = f"{gex_context.gamma_call_wall:.2f}" if gex_context.gamma_call_wall else "N/A"
            pw = f"{gex_context.gamma_put_wall:.2f}" if gex_context.gamma_put_wall else "N/A"
            gex_table.add_row("Walls", f"Call: {cw} | Put: {pw}")
            
            console.print(gex_table)
            console.print("")

        # Main Strategy Table
        table = Table(title=f"Potential Strategies ({len(targets)})", box=box.ROUNDED)
        
        table.add_column("Symbol", style="cyan", no_wrap=True)
        table.add_column("Strategy", style="magenta")
        table.add_column("Exp / DTE", justify="right")
        table.add_column("Width", justify="right")
        table.add_column("Credit", justify="right", style="green")
        table.add_column("% Width", justify="right")
        table.add_column("Max Loss", justify="right", style="red")
        table.add_column("BP Eff", justify="right")
        table.add_column("Legs", style="dim")
        table.add_column("Warnings", style="red")

        for t in targets:
            # Format columns
            exp_str = f"{t.expiration.strftime('%m-%d')} ({t.dte}d)"
            credit_str = f"${t.expected_credit:.2f}"
            width_str = f"${t.width:.1f}"
            pct_width = f"{t.credit_pct:.1f}%"
            max_loss = f"${t.max_loss:.2f}"
            bp_eff = f"${t.bp_effect:.0f}"
            
            legs_desc = ", ".join([f"{l['action']} {l['strike']}" for l in t.legs])
            
            warning = t.gex_warning if t.gex_warning else ""
            
            table.add_row(
                t.symbol,
                t.strategy_type,
                exp_str,
                width_str,
                credit_str,
                pct_width,
                max_loss,
                bp_eff,
                legs_desc,
                warning
            )

        console.print(table)
