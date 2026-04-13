"""
Position review agent for analyzing roll scenarios.

Fetches current positions, enriches with market data, and generates
roll scenario recommendations (roll-down, roll-out, roll-down-and-out).
"""

import logging
import asyncio
from typing import List, Dict, Optional, Any
from datetime import datetime, date
from dataclasses import dataclass, asdict
import json

from tastytrade import Session, Account
from tastytrade.instruments import NestedOptionChain, get_option_chain, OptionType
from tastytrade.market_data import get_market_data_by_type
from tastytrade.streamer import DXLinkStreamer
from tastytrade.dxfeed import Greeks

from rich.console import Console
from rich.table import Table
from rich import box

from agents.portfolio import PortfolioAgent
from utils import redact
from utils.roll_calculator import (
    RollScenario,
    calculate_roll_down_scenario,
    calculate_roll_out_scenario,
    calculate_roll_down_and_out_scenario,
    STRIKE_RANGE_PCT,
    MAX_EXPIRATIONS
)


@dataclass
class PositionContext:
    """Enriched position data for roll analysis."""
    underlying: str
    current_price: float
    legs: List[Dict[str, Any]]
    strategy_type: str  # "Put Vertical", "Call Vertical", "Iron Condor", etc.
    dte: int
    expiration: date
    total_quantity: int
    entry_cost: float
    current_value: float
    unrealized_pl: float
    greeks: Optional[Dict[str, Any]] = None


@dataclass
class ReviewResult:
    """Complete review output for a position."""
    position: PositionContext
    roll_scenarios: List[RollScenario]
    available_expirations: List[date]
    available_strikes: Dict[str, List[float]]  # 'calls' and 'puts'
    metadata: Dict[str, Any]


class ReviewerAgent:
    """Orchestrates position review and roll scenario analysis."""

    def __init__(self, session: Session, account_number: Optional[str] = None):
        self.session = session
        self.account_number = account_number
        self.portfolio: Optional[PortfolioAgent] = None
        self.logger = logging.getLogger(__name__)

    async def init(self) -> 'ReviewerAgent':
        """Async initialization - call after creating instance."""
        self.portfolio = await PortfolioAgent(self.session, self.account_number).init()
        return self

    async def review_positions(
        self,
        underlying_filter: Optional[str] = None
    ) -> List[ReviewResult]:
        """
        Main entry point - review all or specific underlying positions.

        Args:
            underlying_filter: If provided, only review positions for this underlying

        Returns:
            List of ReviewResult objects with position context and roll scenarios
        """
        if not self.portfolio:
            self.logger.error("Portfolio agent not initialized. Call init() first.")
            return []

        # Fetch all positions
        positions = await self.portfolio.get_positions()
        if not positions:
            self.logger.info("No positions found")
            return []

        # Group positions by underlying
        grouped = self.portfolio._group_positions(positions)

        # Filter if specific underlying requested
        if underlying_filter:
            underlying_filter = underlying_filter.upper()
            if underlying_filter not in grouped:
                self.logger.warning(f"No positions found for {underlying_filter}")
                return []
            grouped = {underlying_filter: grouped[underlying_filter]}

        # Process each underlying
        results = []
        for underlying, strategies in grouped.items():
            self.logger.info(f"Reviewing positions for {underlying}...")

            # Only process option strategies (skip stock positions)
            for strategy in strategies:
                if 'Stock' in strategy['name'] or 'Equity' in strategy['name']:
                    continue

                try:
                    # Build position context
                    position_ctx = await self._fetch_position_context(
                        strategy['legs'],
                        underlying
                    )

                    if not position_ctx:
                        continue

                    # Fetch options chain data for rolling
                    chain_data = await self._fetch_roll_chain_data(
                        underlying,
                        position_ctx.expiration
                    )

                    if not chain_data:
                        self.logger.warning(f"Could not fetch chain data for {underlying}")
                        continue

                    # Generate roll scenarios
                    roll_scenarios = await self._generate_roll_scenarios(
                        position_ctx,
                        chain_data
                    )

                    # Build result
                    result = ReviewResult(
                        position=position_ctx,
                        roll_scenarios=roll_scenarios,
                        available_expirations=list(chain_data.get('expirations', {}).keys()),
                        available_strikes={
                            'calls': chain_data.get('call_strikes', []),
                            'puts': chain_data.get('put_strikes', [])
                        },
                        metadata={
                            'reviewed_at': datetime.now().isoformat(),
                            'underlying_symbol': underlying
                        }
                    )

                    results.append(result)

                except Exception as e:
                    self.logger.error(f"Error reviewing {underlying}: {e}", exc_info=True)
                    continue

        return results

    async def _fetch_position_context(
        self,
        position_legs: List[Any],
        underlying: str
    ) -> Optional[PositionContext]:
        """
        Convert raw position legs to enriched PositionContext.

        Args:
            position_legs: List of Position objects from tastytrade API
            underlying: Underlying symbol

        Returns:
            PositionContext with enriched data, or None if error
        """
        if not position_legs:
            return None

        try:
            # Parse position details
            legs_data = []
            total_quantity = 0
            entry_cost = 0.0
            current_value = 0.0
            unrealized_pl = 0.0

            # Get first leg details for expiration/dte
            first_leg = position_legs[0]
            details = getattr(first_leg, '_parsed_details', None)

            if not details:
                self.logger.warning(f"Could not parse position details for {underlying}")
                return None

            expiration = details['expiration']
            dte = (expiration - date.today()).days

            # Determine strategy type
            strategy_type = "Unknown"
            if len(position_legs) == 1:
                strategy_type = f"Single {details['type']}"
            elif len(position_legs) == 2:
                types = [getattr(p, '_parsed_details', {}).get('type', '') for p in position_legs]
                if all(t == 'PUT' for t in types):
                    strategy_type = "Put Vertical"
                elif all(t == 'CALL' for t in types):
                    strategy_type = "Call Vertical"
            elif len(position_legs) == 4:
                strategy_type = "Iron Condor"

            # Fetch current market data — options need the options= keyword
            symbols = [p.symbol for p in position_legs]
            quotes_map = {}
            try:
                quotes = get_market_data_by_type(self.session, options=symbols)
                quotes_map = {q.symbol: q for q in quotes}
            except Exception as e:
                self.logger.warning(f"Failed to fetch market data: {e}")

            # Process each leg
            for pos in position_legs:
                qty = int(getattr(pos, 'quantity', 0))
                if getattr(pos, 'quantity_direction', 'Long') == 'Short':
                    qty = -abs(qty)

                multiplier = int(getattr(pos, 'multiplier', 100) or 100)
                avg_open_price = float(getattr(pos, 'average_open_price', 0) or 0)

                # Get current mark
                mark = 0.0
                if pos.symbol in quotes_map:
                    mark = float(quotes_map[pos.symbol].mark)
                    bid = float(quotes_map[pos.symbol].bid)
                    ask = float(quotes_map[pos.symbol].ask)
                else:
                    mv = float(getattr(pos, 'market_value', 0))
                    if qty != 0:
                        mark = abs(mv / (qty * multiplier))
                    bid = mark
                    ask = mark

                # Calculate P/L
                leg_entry_cost = qty * avg_open_price * multiplier
                leg_current_value = mark * qty * multiplier
                leg_pl = (mark - avg_open_price) * qty * multiplier

                entry_cost += leg_entry_cost
                current_value += leg_current_value
                unrealized_pl += leg_pl
                total_quantity += abs(qty)

                # Parse details
                leg_details = getattr(pos, '_parsed_details', {})

                # Determine action (STO/BTO)
                action = 'STO' if qty < 0 else 'BTO'

                # Build leg dict
                leg_data = {
                    'symbol': pos.symbol,
                    'strike': leg_details.get('strike', 0),
                    'option_type': leg_details.get('type', 'UNKNOWN'),
                    'action': action,
                    'quantity': abs(qty),
                    'avg_open_price': avg_open_price,
                    'mark': mark,
                    'bid': bid,
                    'ask': ask,
                    'current_value': leg_current_value,
                    'unrealized_pl': leg_pl
                }
                legs_data.append(leg_data)

            # Fetch underlying price
            underlying_price = 0.0
            try:
                underlying_quotes = get_market_data_by_type(
                    self.session,
                    equities=[underlying]
                )
                if underlying_quotes:
                    underlying_price = float(underlying_quotes[0].mark)
            except Exception as e:
                self.logger.warning(f"Failed to fetch underlying price for {underlying}: {e}")

            # Build position context
            position_ctx = PositionContext(
                underlying=underlying,
                current_price=underlying_price,
                legs=legs_data,
                strategy_type=strategy_type,
                dte=dte,
                expiration=expiration,
                total_quantity=total_quantity,
                entry_cost=entry_cost,
                current_value=current_value,
                unrealized_pl=unrealized_pl
            )

            return position_ctx

        except Exception as e:
            self.logger.error(f"Error fetching position context: {e}", exc_info=True)
            return None

    async def _fetch_roll_chain_data(
        self,
        underlying: str,
        current_expiration: date
    ) -> Dict[str, Any]:
        """
        Fetch options chains for current + next 3 monthly expirations.

        Args:
            underlying: Symbol to fetch chains for
            current_expiration: Current position expiration

        Returns:
            Dict with chain data organized by expiration
        """
        try:
            # Get nested chain for expiration list
            chains = NestedOptionChain.get(self.session, underlying)
            if not chains:
                return {}

            chain = chains[0] if len(chains) >= 1 else None
            if not chain:
                return {}

            # Filter to monthly expirations (3rd Friday pattern)
            monthly_exps = []
            for exp in chain.expirations:
                exp_date = exp.expiration_date

                # Include current expiration for roll-down scenarios
                if exp_date == current_expiration:
                    monthly_exps.insert(0, exp_date)  # Put at front
                    continue

                # Skip past expirations
                if exp_date <= current_expiration:
                    continue

                # Check if monthly expiration (Friday in 3rd week)
                is_friday = exp_date.weekday() == 4
                is_third_week = 15 <= exp_date.day <= 21

                if is_friday and is_third_week:
                    monthly_exps.append(exp_date)

                # Limit to next 3 monthlies (plus current)
                if len(monthly_exps) >= MAX_EXPIRATIONS + 1:
                    break

            if not monthly_exps:
                self.logger.warning(f"No monthly expirations found for {underlying}")
                return {}

            # Fetch full option chain
            full_chain = get_option_chain(self.session, underlying)

            # Organize chain data
            chain_data = {
                'expirations': {},
                'call_strikes': [],
                'put_strikes': []
            }

            for exp_date in monthly_exps:
                options = full_chain.get(exp_date, [])
                if not options:
                    continue

                # Separate by type
                calls = [opt for opt in options if opt.option_type == OptionType.CALL]
                puts = [opt for opt in options if opt.option_type == OptionType.PUT]

                # Extract strikes
                call_strikes = sorted(set(float(opt.strike_price) for opt in calls))
                put_strikes = sorted(set(float(opt.strike_price) for opt in puts))

                # Update overall strike lists
                if not chain_data['call_strikes']:
                    chain_data['call_strikes'] = call_strikes
                if not chain_data['put_strikes']:
                    chain_data['put_strikes'] = put_strikes

                # Store options with market data placeholders
                chain_data['expirations'][exp_date] = {
                    'calls': calls,
                    'puts': puts,
                    'call_strikes': call_strikes,
                    'put_strikes': put_strikes,
                    'options': options  # All options for this expiration
                }

            return chain_data

        except Exception as e:
            self.logger.error(f"Error fetching chain data: {e}", exc_info=True)
            return {}

    async def _generate_roll_scenarios(
        self,
        position: PositionContext,
        chain_data: Dict[str, Any]
    ) -> List[RollScenario]:
        """
        Generate all viable roll scenarios for a position.

        Args:
            position: Current position context
            chain_data: Options chain data

        Returns:
            List of RollScenario objects sorted by viability
        """
        scenarios = []

        try:
            # Extract current position info
            current_strikes = [leg['strike'] for leg in position.legs]
            option_type = position.legs[0]['option_type']
            is_put = option_type in ['PUT', 'P']

            # Filter relevant strikes (within ±20% of current)
            if is_put:
                base_strike = min(current_strikes)
                relevant_strikes = [
                    s for s in chain_data.get('put_strikes', [])
                    if s < base_strike  # Roll down for puts
                    and s >= base_strike * (1 - STRIKE_RANGE_PCT)
                ]
            else:
                base_strike = max(current_strikes)
                relevant_strikes = [
                    s for s in chain_data.get('call_strikes', [])
                    if s > base_strike  # Roll up for calls
                    and s <= base_strike * (1 + STRIKE_RANGE_PCT)
                ]

            # Get expirations (excluding current for roll-out)
            all_expirations = list(chain_data.get('expirations', {}).keys())
            future_expirations = [
                exp for exp in all_expirations
                if exp > position.expiration
            ]

            # Build position dict for roll calculator
            current_position = {
                'legs': position.legs,
                'expiration': position.expiration,
                'dte': position.dte
            }

            # Fetch market data for current expiration (for closing)
            current_chain_options = chain_data['expirations'].get(position.expiration, {}).get('options', [])
            current_chain_data = await self._enrich_chain_with_market_data(current_chain_options)

            # 1. Roll Down Scenarios (same expiration, different strikes)
            if relevant_strikes and position.expiration in chain_data['expirations']:
                new_chain_options = chain_data['expirations'][position.expiration]['options']
                new_chain_data = await self._enrich_chain_with_market_data(new_chain_options)

                roll_down_scenarios = calculate_roll_down_scenario(
                    current_position,
                    relevant_strikes,
                    new_chain_data,
                    current_chain_data
                )
                scenarios.extend(roll_down_scenarios[:3])  # Top 3

            # 2. Roll Out Scenarios (same strikes, later expiration)
            if future_expirations:
                new_chain_data_by_exp = {}
                for exp_date in future_expirations[:MAX_EXPIRATIONS]:
                    exp_options = chain_data['expirations'][exp_date]['options']
                    new_chain_data_by_exp[exp_date] = await self._enrich_chain_with_market_data(exp_options)

                roll_out_scenarios = calculate_roll_out_scenario(
                    current_position,
                    future_expirations[:MAX_EXPIRATIONS],
                    new_chain_data_by_exp,
                    current_chain_data
                )
                scenarios.extend(roll_out_scenarios[:3])  # Top 3

            # 3. Roll Down-and-Out Scenarios (different strikes + later expiration)
            if relevant_strikes and future_expirations:
                # Reuse enriched chain data from roll-out
                roll_down_out_scenarios = calculate_roll_down_and_out_scenario(
                    current_position,
                    relevant_strikes[:5],  # Limit strike combinations
                    future_expirations[:2],  # Limit to 2 expirations
                    new_chain_data_by_exp,
                    current_chain_data
                )
                scenarios.extend(roll_down_out_scenarios[:3])  # Top 3

        except Exception as e:
            self.logger.error(f"Error generating roll scenarios: {e}", exc_info=True)

        # Sort all scenarios by viability score
        scenarios.sort(key=lambda s: s.viability_score, reverse=True)

        return scenarios

    async def _enrich_chain_with_market_data(
        self,
        options: List[Any]
    ) -> Dict[str, Any]:
        """
        Enrich option chain with current market data (bid/ask/mark).

        Args:
            options: List of Option objects from chain

        Returns:
            Dict with 'options' key containing enriched option data
        """
        if not options:
            return {'options': []}

        try:
            # Fetch market data in batches to avoid 414 error
            symbols = [opt.symbol for opt in options]
            quotes_map = {}

            # Batch size of 50 to avoid URI too large error
            batch_size = 50
            for i in range(0, len(symbols), batch_size):
                batch = symbols[i:i + batch_size]
                try:
                    quotes = get_market_data_by_type(self.session, options=batch)
                    for q in quotes:
                        quotes_map[q.symbol] = q
                except Exception as e:
                    self.logger.warning(f"Failed to fetch batch {i//batch_size + 1}: {e}")
                    continue

            # Enrich options with market data
            enriched_options = []
            for opt in options:
                quote = quotes_map.get(opt.symbol)

                # Ensure option_type is 'PUT' or 'CALL' string
                if opt.option_type == OptionType.PUT:
                    option_type_str = 'PUT'
                elif opt.option_type == OptionType.CALL:
                    option_type_str = 'CALL'
                else:
                    option_type_str = str(opt.option_type)

                opt_dict = {
                    'symbol': opt.symbol,
                    'strike': float(opt.strike_price),
                    'option_type': option_type_str,
                    'expiration': opt.expiration_date if hasattr(opt, 'expiration_date') else None,
                    'bid': float(quote.bid) if quote and quote.bid else 0.0,
                    'ask': float(quote.ask) if quote and quote.ask else 0.0,
                    'mark': float(quote.mark) if quote and quote.mark else 0.0,
                    'volume': int(quote.volume) if quote and hasattr(quote, 'volume') else 0,
                    'open_interest': int(quote.open_interest) if quote and hasattr(quote, 'open_interest') else 0
                }
                enriched_options.append(opt_dict)

            return {'options': enriched_options}

        except Exception as e:
            self.logger.error(f"Error enriching chain data: {e}", exc_info=True)
            return {'options': []}

    def print_review_report(self, results: List[ReviewResult], discord: bool = False):
        """
        Print formatted review report using Rich.

        Args:
            results: List of ReviewResult objects
            discord: Whether to format for Discord
        """
        console = Console(width=180)

        open_block = "```" if discord else ""
        close_block = "```" if discord else ""

        for result in results:
            pos = result.position

            # Position Summary
            print(f"\n{open_block}═══════════════════════════════════════════════════════════════════════════════")
            print(f"  {pos.underlying} - {pos.strategy_type}")
            print(f"═══════════════════════════════════════════════════════════════════════════════")

            # Current Position Details
            summary_table = Table(title="Current Position", box=box.SIMPLE)
            summary_table.add_column("Metric", style="cyan")
            summary_table.add_column("Value", style="white")

            summary_table.add_row("Underlying Price", f"${pos.current_price:.2f}")
            summary_table.add_row("Expiration", pos.expiration.strftime('%Y-%m-%d'))
            summary_table.add_row("DTE", str(pos.dte))
            summary_table.add_row("Entry Cost", f"${redact.dollars(pos.entry_cost)}")
            summary_table.add_row("Current Value", f"${redact.dollars(pos.current_value)}")
            summary_table.add_row("Unrealized P/L", f"${redact.dollars(pos.unrealized_pl)}")

            if abs(pos.entry_cost) > 0:
                pl_pct = (pos.unrealized_pl / abs(pos.entry_cost)) * 100
                summary_table.add_row("P/L %", f"{pl_pct:.1f}%")

            console.print(summary_table)

            # Legs Detail
            legs_table = Table(title="Position Legs", box=box.SIMPLE)
            legs_table.add_column("Action", style="yellow")
            legs_table.add_column("Strike", style="white")
            legs_table.add_column("Type", style="cyan")
            legs_table.add_column("Qty", style="white")
            legs_table.add_column("Avg Price", style="green")
            legs_table.add_column("Mark", style="green")
            legs_table.add_column("P/L", style="magenta")

            for leg in pos.legs:
                action_str = leg['action']
                strike_str = f"${leg['strike']:.1f}"
                type_str = leg['option_type']
                qty_str = str(leg['quantity'])
                avg_str = f"${redact.dollars(leg['avg_open_price'])}"
                mark_str = f"${leg['mark']:.2f}"
                pl_str = f"${redact.dollars(leg['unrealized_pl'])}"

                legs_table.add_row(action_str, strike_str, type_str, qty_str, avg_str, mark_str, pl_str)

            console.print(legs_table)

            # Roll Scenarios
            if result.roll_scenarios:
                scenarios_table = Table(title="Roll Scenarios (Sorted by Viability)", box=box.ROUNDED)
                scenarios_table.add_column("Type", style="cyan")
                scenarios_table.add_column("New Strikes", style="white")
                scenarios_table.add_column("Expiration", style="yellow")
                scenarios_table.add_column("DTE", style="white")
                scenarios_table.add_column("Credit/Debit", style="green")
                scenarios_table.add_column("New BE", style="magenta")
                scenarios_table.add_column("Days Added", style="blue")
                scenarios_table.add_column("Score", style="bold green")

                for scenario in result.roll_scenarios[:10]:  # Top 10
                    type_str = scenario.scenario_type.replace('_', ' ').title()

                    # Extract new strikes
                    new_strikes = [leg['strike'] for leg in scenario.new_legs]
                    strikes_str = f"{min(new_strikes):.1f}/{max(new_strikes):.1f}"

                    exp_str = scenario.new_expiration.strftime('%y-%m-%d')
                    dte_str = str(scenario.new_dte)

                    # Credit/Debit with color
                    if scenario.credit_debit >= 0:
                        cd_str = f"${redact.dollars(scenario.credit_debit)} CR"
                        cd_style = "bold green"
                    else:
                        cd_str = f"${redact.dollars(abs(scenario.credit_debit))} DB"
                        cd_style = "bold red"

                    be_str = f"${redact.dollars(scenario.new_breakeven)}" if scenario.new_breakeven else "-"
                    days_str = f"+{scenario.days_added}" if scenario.days_added > 0 else "0"
                    score_str = f"{scenario.viability_score:.1f}"

                    scenarios_table.add_row(
                        type_str,
                        strikes_str,
                        exp_str,
                        dte_str,
                        cd_str,
                        be_str,
                        days_str,
                        score_str
                    )

                console.print(scenarios_table)
            else:
                print(f"\n⚠️  No viable roll scenarios found for {pos.underlying}")

            print(f"{close_block}\n")

    def export_json(self, results: List[ReviewResult], output_path: str):
        """
        Export results as JSON for AI consumption.

        Args:
            results: List of ReviewResult objects
            output_path: Path to write JSON file
        """
        try:
            output = {
                "positions": [],
                "underlying_prices": {},
                "roll_scenarios": {},
                "metadata": {
                    "generated_at": datetime.now().isoformat(),
                    "total_positions": len(results)
                }
            }

            for result in results:
                pos = result.position

                # Serialize position
                if redact.is_enabled():
                    pos_dict = {
                        "underlying": pos.underlying,
                        "current_price": pos.current_price,
                        "strategy_type": pos.strategy_type,
                        "expiration": pos.expiration.isoformat(),
                        "dte": pos.dte,
                        "entry_cost": redact.dollars(pos.entry_cost),
                        "current_value": redact.dollars(pos.current_value),
                        "unrealized_pl": redact.dollars(pos.unrealized_pl),
                        "legs": pos.legs
                    }
                else:
                    pos_dict = {
                        "underlying": pos.underlying,
                        "current_price": pos.current_price,
                        "strategy_type": pos.strategy_type,
                        "expiration": pos.expiration.isoformat(),
                        "dte": pos.dte,
                        "entry_cost": pos.entry_cost,
                        "current_value": pos.current_value,
                        "unrealized_pl": pos.unrealized_pl,
                        "legs": pos.legs
                    }
                output["positions"].append(pos_dict)

                # Underlying prices
                output["underlying_prices"][pos.underlying] = pos.current_price

                # Roll scenarios by type
                scenarios_by_type = {
                    "roll_down": [],
                    "roll_out": [],
                    "roll_down_and_out": []
                }

                for scenario in result.roll_scenarios:
                    if redact.is_enabled():
                        scenario_dict = {
                            "new_legs": scenario.new_legs,
                            "credit_debit": redact.dollars(scenario.credit_debit),
                            "new_breakeven": redact.dollars(scenario.new_breakeven) if scenario.new_breakeven else None,
                            "new_expiration": scenario.new_expiration.isoformat(),
                            "new_dte": scenario.new_dte,
                            "days_added": scenario.days_added,
                            "viability_score": scenario.viability_score,
                            "max_profit_change": scenario.max_profit_change,
                            "max_loss_change": scenario.max_loss_change
                        }
                    else:
                        scenario_dict = {
                            "new_legs": scenario.new_legs,
                            "credit_debit": scenario.credit_debit,
                            "new_breakeven": scenario.new_breakeven,
                            "new_expiration": scenario.new_expiration.isoformat(),
                            "new_dte": scenario.new_dte,
                            "days_added": scenario.days_added,
                            "viability_score": scenario.viability_score,
                            "max_profit_change": scenario.max_profit_change,
                            "max_loss_change": scenario.max_loss_change
                        }

                    scenarios_by_type[scenario.scenario_type].append(scenario_dict)

                output["roll_scenarios"][pos.underlying] = scenarios_by_type

            # Write to file
            with open(output_path, 'w') as f:
                json.dump(output, f, indent=2)

            self.logger.info(f"Exported review results to {output_path}")
            print(f"\n✅ Review results exported to: {output_path}")

        except Exception as e:
            self.logger.error(f"Error exporting JSON: {e}", exc_info=True)
            print(f"\n❌ Failed to export JSON: {e}")
