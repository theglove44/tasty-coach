"""
Roll scenario calculation utilities.

This module provides pure calculation logic for analyzing options position roll scenarios,
separated from API concerns. Supports vertical spreads, single legs, and other common strategies.
"""

import copy
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)

# Roll scenario filters and thresholds
MIN_CREDIT_THRESHOLD = 0.10  # Minimum $0.10 credit for viable roll
MAX_DEBIT_THRESHOLD = 3.00   # Maximum $3.00 debit for roll (increased for ITM positions)
STRIKE_RANGE_PCT = 0.20      # ±20% around current strikes
MAX_EXPIRATIONS = 3          # Next 3 monthly expirations


@dataclass
class SpreadMetrics:
    """Calculated metrics for an options spread."""
    width: float
    max_profit: float
    max_loss: float
    breakeven: Optional[float]
    risk_reward_ratio: float


@dataclass
class RollScenario:
    """Complete roll scenario with all calculations."""
    scenario_type: str  # "roll_down", "roll_out", "roll_down_and_out"
    current_legs: List[Dict[str, Any]]
    new_legs: List[Dict[str, Any]]
    credit_debit: float  # Positive = credit, negative = debit
    new_breakeven: Optional[float]
    max_profit_change: float
    max_loss_change: float
    days_added: int
    new_dte: int
    new_expiration: date
    current_metrics: SpreadMetrics
    new_metrics: SpreadMetrics
    viability_score: float  # 0-100 rating based on credit, risk, etc.


def extract_decimal(value: Any) -> float:
    """
    Safely convert various types to float.
    Reuses pattern from manager.py for consistency.
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0
    return 0.0


def calculate_spread_metrics(legs: List[Dict[str, Any]]) -> SpreadMetrics:
    """
    Calculate key metrics for an options spread.

    Args:
        legs: List of leg dicts with keys: strike, option_type, quantity, action

    Returns:
        SpreadMetrics with width, max profit/loss, breakeven, risk/reward
    """
    if not legs:
        return SpreadMetrics(0, 0, 0, None, 0)

    # Extract strikes and types
    strikes = [extract_decimal(leg.get('strike', 0)) for leg in legs]
    types = [leg.get('option_type', '').upper() for leg in legs]
    quantities = [leg.get('quantity', 0) for leg in legs]

    # Calculate width (difference between strikes)
    if len(strikes) >= 2:
        width = abs(max(strikes) - min(strikes))
    else:
        width = 0

    # For vertical spreads (2 legs, same type)
    if len(legs) == 2 and types[0] == types[1]:
        option_type = types[0]

        # Identify short and long legs
        short_strike = None
        long_strike = None

        for i, leg in enumerate(legs):
            action = leg.get('action', '').upper()
            if 'SELL' in action or action == 'STO':
                short_strike = strikes[i]
            elif 'BUY' in action or action == 'BTO':
                long_strike = strikes[i]

        # Calculate max profit/loss and breakeven
        if short_strike and long_strike:
            # For put spreads
            if option_type == 'PUT' or option_type == 'P':
                # Max profit = credit received (calculated elsewhere)
                # Max loss = width - credit
                # Breakeven = short strike - credit
                max_loss = width
                breakeven_offset = 0  # Will be adjusted with actual credit

            # For call spreads
            elif option_type == 'CALL' or option_type == 'C':
                # Max profit = credit received
                # Max loss = width - credit
                # Breakeven = short strike + credit
                max_loss = width
                breakeven_offset = 0
            else:
                max_loss = 0
                breakeven_offset = 0
        else:
            max_loss = 0
            breakeven_offset = 0
    else:
        # Single leg or complex strategy
        max_loss = 0
        breakeven_offset = 0

    # Max profit and breakeven need actual credit value (calculated in roll scenario)
    max_profit = 0  # Placeholder
    breakeven = None  # Placeholder
    risk_reward = 0

    return SpreadMetrics(
        width=width,
        max_profit=max_profit,
        max_loss=max_loss,
        breakeven=breakeven,
        risk_reward_ratio=risk_reward
    )


def calculate_breakeven(
    legs: List[Dict[str, Any]],
    credit_received: float,
    underlying_price: Optional[float] = None
) -> Optional[float]:
    """
    Calculate breakeven price for a spread given the credit received.

    Args:
        legs: List of leg dicts with strikes and option types
        credit_received: Net credit received for the position
        underlying_price: Optional current price of underlying

    Returns:
        Breakeven price, or None if cannot calculate
    """
    if not legs or len(legs) < 1:
        return None

    # For vertical spreads
    if len(legs) == 2:
        strikes = [extract_decimal(leg.get('strike', 0)) for leg in legs]
        types = [leg.get('option_type', '').upper() for leg in legs]

        # Same type = vertical spread
        if types[0] == types[1]:
            option_type = types[0]

            # Find short strike (the one we sold)
            short_strike = None
            for i, leg in enumerate(legs):
                action = leg.get('action', '').upper()
                if 'SELL' in action or action == 'STO':
                    short_strike = strikes[i]
                    break

            if short_strike:
                if option_type in ['PUT', 'P']:
                    # Put spread: breakeven = short strike - credit
                    return short_strike - credit_received
                elif option_type in ['CALL', 'C']:
                    # Call spread: breakeven = short strike + credit
                    return short_strike + credit_received

    # Single leg
    elif len(legs) == 1:
        strike = extract_decimal(legs[0].get('strike', 0))
        option_type = legs[0].get('option_type', '').upper()
        action = legs[0].get('action', '').upper()

        if 'SELL' in action or action == 'STO':
            # Short single leg
            if option_type in ['PUT', 'P']:
                return strike - credit_received
            elif option_type in ['CALL', 'C']:
                return strike + credit_received

    return None


def calculate_net_credit_debit(
    close_current_legs: List[Dict[str, Any]],
    open_new_legs: List[Dict[str, Any]]
) -> float:
    """
    Calculate net credit/debit for rolling a position.

    Positive = credit received
    Negative = debit paid

    Args:
        close_current_legs: Legs to close with current market prices
        open_new_legs: Legs to open with target market prices

    Returns:
        Net credit (positive) or debit (negative)
    """
    # Close current position
    # Selling = receive bid, Buying back = pay ask
    close_proceeds = 0.0

    for leg in close_current_legs:
        action = leg.get('action', '').upper()
        quantity = abs(leg.get('quantity', 0))

        # If we originally sold, we buy back at ask
        if 'SELL' in action or action == 'STO':
            price = extract_decimal(leg.get('ask', leg.get('mark', 0)))
            close_proceeds -= price * quantity  # Debit to close short
        # If we originally bought, we sell at bid
        elif 'BUY' in action or action == 'BTO':
            price = extract_decimal(leg.get('bid', leg.get('mark', 0)))
            close_proceeds += price * quantity  # Credit to close long

    # Open new position
    # Selling = receive bid, Buying = pay ask
    open_proceeds = 0.0

    for leg in open_new_legs:
        action = leg.get('action', '').upper()
        quantity = abs(leg.get('quantity', 0))

        if 'SELL' in action or action == 'STO':
            price = extract_decimal(leg.get('bid', leg.get('mark', 0)))
            open_proceeds += price * quantity  # Credit from selling
        elif 'BUY' in action or action == 'BTO':
            price = extract_decimal(leg.get('ask', leg.get('mark', 0)))
            open_proceeds -= price * quantity  # Debit from buying

    # Net credit/debit
    net = close_proceeds + open_proceeds

    return round(net, 2)


def calculate_viability_score(scenario: RollScenario) -> float:
    """
    Calculate a 0-100 viability score for a roll scenario.

    Factors:
    - Credit received (higher = better)
    - Risk/reward ratio (higher = better)
    - Days added (more time = better for theta strategies)
    - Avoids excessive debits

    Returns:
        Score from 0-100
    """
    score = 50.0  # Base score

    # Credit bonus (up to +30 points)
    if scenario.credit_debit > 0:
        # $0.50+ credit = full bonus
        credit_bonus = min(scenario.credit_debit * 60, 30)
        score += credit_bonus
    else:
        # Debit penalty
        debit_penalty = abs(scenario.credit_debit) * 40
        score -= debit_penalty

    # Days added bonus (up to +15 points)
    if scenario.days_added > 0:
        # 30+ days = full bonus
        days_bonus = min(scenario.days_added / 2, 15)
        score += days_bonus

    # Risk/reward improvement (up to +15 points)
    if scenario.new_metrics.width > 0:
        rr_current = scenario.current_metrics.max_profit / max(scenario.current_metrics.width, 0.01)
        rr_new = scenario.new_metrics.max_profit / max(scenario.new_metrics.width, 0.01)

        if rr_new > rr_current:
            rr_bonus = min((rr_new - rr_current) * 100, 15)
            score += rr_bonus

    # Clamp to 0-100
    return max(0, min(100, round(score, 1)))


def calculate_roll_down_scenario(
    current_position: Dict[str, Any],
    target_strikes: List[float],
    new_chain_data: Dict[str, Any],
    current_chain_data: Dict[str, Any]
) -> List[RollScenario]:
    """
    Calculate roll-down scenarios (same expiration, lower strikes for puts / higher for calls).

    Args:
        current_position: Dict with current legs, expiration, dte
        target_strikes: List of candidate short strikes to roll to
        new_chain_data: Market data for new strikes (same expiration)
        current_chain_data: Market data for current strikes (to close)

    Returns:
        List of viable RollScenario objects
    """
    scenarios = []

    current_legs_orig = current_position.get('legs', [])
    current_expiration = current_position.get('expiration')
    current_dte = current_position.get('dte', 0)

    if len(current_legs_orig) < 1:
        return scenarios

    # Extract current strikes and option type
    current_strikes = [extract_decimal(leg.get('strike', 0)) for leg in current_legs_orig]
    option_type = current_legs_orig[0].get('option_type', '').upper()

    # Strike-shift rolls are only defined for single options and same-type
    # verticals. Complex spreads such as iron condors need side-specific logic,
    # otherwise a single target strike can collapse four legs into nonsense.
    if len(current_legs_orig) > 2:
        return scenarios
    if len(current_legs_orig) == 2:
        leg_types = {leg.get('option_type', '').upper() for leg in current_legs_orig}
        if len(leg_types) != 1:
            return scenarios

    # Determine direction based on option type
    # For puts: roll down = lower strikes
    # For calls: roll down = higher strikes (but usually called "roll up")
    is_put = option_type in ['PUT', 'P']

    # Calculate current metrics
    current_metrics = calculate_spread_metrics(current_legs_orig)

    for target_short_strike in target_strikes:
        # Skip if not a valid roll down
        if is_put and target_short_strike >= min(current_strikes):
            continue
        if not is_put and target_short_strike <= max(current_strikes):
            continue

        # Deep copy to avoid mutating shared data across iterations
        current_legs = copy.deepcopy(current_legs_orig)

        # Build new legs with target strikes
        new_legs = []

        for leg in current_legs:
            old_strike = extract_decimal(leg.get('strike', 0))
            action = leg.get('action', '')
            quantity = leg.get('quantity', 0)

            # Calculate strike offset
            if len(current_legs) == 2:
                # Vertical spread - maintain width
                width = abs(current_strikes[1] - current_strikes[0])

                if 'SELL' in action.upper() or action == 'STO':
                    # Short leg - use target strike
                    new_strike = target_short_strike
                else:
                    # Long leg - offset by width
                    if is_put:
                        new_strike = target_short_strike - width
                    else:
                        new_strike = target_short_strike + width
            else:
                # Single leg
                new_strike = target_short_strike

            # Find market data for new strike
            new_option_data = None
            for opt in new_chain_data.get('options', []):
                if (extract_decimal(opt.get('strike')) == new_strike and
                    opt.get('option_type', '').upper() == option_type):
                    new_option_data = opt
                    break

            if not new_option_data:
                break

            # Find current market data for closing
            current_option_data = None
            for opt in current_chain_data.get('options', []):
                if (extract_decimal(opt.get('strike')) == old_strike and
                    opt.get('option_type', '').upper() == option_type):
                    current_option_data = opt
                    break

            # Build leg dict with market prices
            new_leg = {
                'symbol': new_option_data.get('symbol', ''),
                'strike': new_strike,
                'option_type': option_type,
                'action': action,
                'quantity': quantity,
                'bid': extract_decimal(new_option_data.get('bid', 0)),
                'ask': extract_decimal(new_option_data.get('ask', 0)),
                'mark': extract_decimal(new_option_data.get('mark', 0))
            }
            new_legs.append(new_leg)

            # Update current leg with market data for closing calculation
            if current_option_data:
                leg['bid'] = extract_decimal(current_option_data.get('bid', 0))
                leg['ask'] = extract_decimal(current_option_data.get('ask', 0))
                leg['mark'] = extract_decimal(current_option_data.get('mark', 0))

        # Skip if couldn't build complete new position
        if len(new_legs) != len(current_legs):
            continue

        # Calculate net credit/debit
        credit_debit = calculate_net_credit_debit(current_legs, new_legs)

        # Filter out excessive debits
        if credit_debit < -MAX_DEBIT_THRESHOLD:
            continue

        # Calculate new metrics
        new_metrics = calculate_spread_metrics(new_legs)
        new_metrics.max_profit = credit_debit * 100  # Per contract
        new_metrics.max_loss = (new_metrics.width - credit_debit) * 100

        # Calculate breakeven
        new_breakeven = calculate_breakeven(new_legs, credit_debit)

        # Build scenario
        scenario = RollScenario(
            scenario_type="roll_down",
            current_legs=current_legs,
            new_legs=new_legs,
            credit_debit=credit_debit,
            new_breakeven=new_breakeven,
            max_profit_change=new_metrics.max_profit - current_metrics.max_profit,
            max_loss_change=new_metrics.max_loss - current_metrics.max_loss,
            days_added=0,  # Same expiration
            new_dte=current_dte,
            new_expiration=current_expiration,
            current_metrics=current_metrics,
            new_metrics=new_metrics,
            viability_score=0  # Calculated next
        )

        # Calculate viability score
        scenario.viability_score = calculate_viability_score(scenario)

        scenarios.append(scenario)

    # Sort by viability score
    scenarios.sort(key=lambda s: s.viability_score, reverse=True)

    return scenarios


def calculate_roll_out_scenario(
    current_position: Dict[str, Any],
    target_expirations: List[date],
    new_chain_data: Dict[date, Dict[str, Any]],
    current_chain_data: Dict[str, Any]
) -> List[RollScenario]:
    """
    Calculate roll-out scenarios (same strikes, later expiration).

    Args:
        current_position: Dict with current legs, expiration, dte
        target_expirations: List of candidate expirations to roll to
        new_chain_data: Market data for new expirations (keyed by date)
        current_chain_data: Market data for current expiration (to close)

    Returns:
        List of viable RollScenario objects
    """
    scenarios = []

    current_legs_orig = current_position.get('legs', [])
    current_expiration = current_position.get('expiration')
    current_dte = current_position.get('dte', 0)

    if len(current_legs_orig) < 1:
        return scenarios

    # Calculate current metrics
    current_metrics = calculate_spread_metrics(current_legs_orig)

    for target_exp_date in target_expirations:
        if target_exp_date <= current_expiration:
            continue

        # Calculate days added
        days_added = (target_exp_date - current_expiration).days
        new_dte = current_dte + days_added

        # Get chain data for target expiration
        target_chain = new_chain_data.get(target_exp_date, {})
        if not target_chain:
            continue

        # Deep copy to avoid mutating shared data across iterations
        current_legs = copy.deepcopy(current_legs_orig)

        # Build new legs with same strikes, new expiration
        new_legs = []

        for leg in current_legs:
            strike = extract_decimal(leg.get('strike', 0))
            option_type = leg.get('option_type', '').upper()
            action = leg.get('action', '')
            quantity = leg.get('quantity', 0)

            # Find market data for same strike, new expiration
            new_option_data = None
            for opt in target_chain.get('options', []):
                if (extract_decimal(opt.get('strike')) == strike and
                    opt.get('option_type', '').upper() == option_type):
                    new_option_data = opt
                    break

            if not new_option_data:
                logger.debug(f"No market data for {option_type} {strike} at {target_exp_date}")
                break

            # Find current market data for closing
            current_option_data = None
            for opt in current_chain_data.get('options', []):
                if (extract_decimal(opt.get('strike')) == strike and
                    opt.get('option_type', '').upper() == option_type):
                    current_option_data = opt
                    break

            # Build leg dict
            new_leg = {
                'symbol': new_option_data.get('symbol', ''),
                'strike': strike,
                'option_type': option_type,
                'action': action,
                'quantity': quantity,
                'bid': extract_decimal(new_option_data.get('bid', 0)),
                'ask': extract_decimal(new_option_data.get('ask', 0)),
                'mark': extract_decimal(new_option_data.get('mark', 0))
            }
            new_legs.append(new_leg)

            # Update current leg with market data
            if current_option_data:
                leg['bid'] = extract_decimal(current_option_data.get('bid', 0))
                leg['ask'] = extract_decimal(current_option_data.get('ask', 0))
                leg['mark'] = extract_decimal(current_option_data.get('mark', 0))

        # Skip if couldn't build complete position
        if len(new_legs) != len(current_legs):
            continue

        # Calculate net credit/debit
        credit_debit = calculate_net_credit_debit(current_legs, new_legs)

        # Filter excessive debits
        if credit_debit < -MAX_DEBIT_THRESHOLD:
            continue

        # Calculate new metrics
        new_metrics = calculate_spread_metrics(new_legs)
        new_metrics.max_profit = credit_debit * 100
        new_metrics.max_loss = (new_metrics.width - credit_debit) * 100

        # Breakeven same as current (same strikes)
        current_breakeven = calculate_breakeven(current_legs, credit_debit)

        # Build scenario
        scenario = RollScenario(
            scenario_type="roll_out",
            current_legs=current_legs,
            new_legs=new_legs,
            credit_debit=credit_debit,
            new_breakeven=current_breakeven,
            max_profit_change=new_metrics.max_profit - current_metrics.max_profit,
            max_loss_change=new_metrics.max_loss - current_metrics.max_loss,
            days_added=days_added,
            new_dte=new_dte,
            new_expiration=target_exp_date,
            current_metrics=current_metrics,
            new_metrics=new_metrics,
            viability_score=0
        )

        scenario.viability_score = calculate_viability_score(scenario)
        scenarios.append(scenario)

    # Sort by viability score
    scenarios.sort(key=lambda s: s.viability_score, reverse=True)

    return scenarios


def calculate_roll_down_and_out_scenario(
    current_position: Dict[str, Any],
    target_strikes: List[float],
    target_expirations: List[date],
    new_chain_data: Dict[date, Dict[str, Any]],
    current_chain_data: Dict[str, Any]
) -> List[RollScenario]:
    """
    Calculate roll-down-and-out scenarios (lower strikes + later expiration).

    Combines both roll-down and roll-out for maximum credit collection.

    Args:
        current_position: Dict with current legs, expiration, dte
        target_strikes: List of candidate strikes to roll to
        target_expirations: List of candidate expirations to roll to
        new_chain_data: Market data for new expirations (keyed by date)
        current_chain_data: Market data for current expiration

    Returns:
        List of viable RollScenario objects
    """
    scenarios = []

    current_legs_orig = current_position.get('legs', [])
    current_expiration = current_position.get('expiration')
    current_dte = current_position.get('dte', 0)

    if len(current_legs_orig) < 1:
        return scenarios

    # Extract current info
    current_strikes = [extract_decimal(leg.get('strike', 0)) for leg in current_legs_orig]
    option_type = current_legs_orig[0].get('option_type', '').upper()
    is_put = option_type in ['PUT', 'P']

    # Strike-shift rolls are only defined for single options and same-type
    # verticals. Complex spreads such as iron condors need side-specific logic,
    # otherwise a single target strike can collapse four legs into nonsense.
    if len(current_legs_orig) > 2:
        return scenarios
    if len(current_legs_orig) == 2:
        leg_types = {leg.get('option_type', '').upper() for leg in current_legs_orig}
        if len(leg_types) != 1:
            return scenarios

    # Calculate current metrics
    current_metrics = calculate_spread_metrics(current_legs_orig)

    # Limit combinations to avoid explosion
    max_scenarios = 10
    scenario_count = 0

    for target_exp_date in target_expirations:
        if target_exp_date <= current_expiration:
            continue

        # Calculate days added
        days_added = (target_exp_date - current_expiration).days
        new_dte = current_dte + days_added

        # Get chain data for target expiration
        target_chain = new_chain_data.get(target_exp_date, {})
        if not target_chain:
            continue

        for target_short_strike in target_strikes:
            # Skip invalid roll downs
            if is_put and target_short_strike >= min(current_strikes):
                continue
            if not is_put and target_short_strike <= max(current_strikes):
                continue

            # Deep copy to avoid mutating shared data across iterations
            current_legs = copy.deepcopy(current_legs_orig)

            # Build new legs
            new_legs = []

            for leg in current_legs:
                old_strike = extract_decimal(leg.get('strike', 0))
                action = leg.get('action', '')
                quantity = leg.get('quantity', 0)

                # Calculate new strike
                if len(current_legs) == 2:
                    width = abs(current_strikes[1] - current_strikes[0])

                    if 'SELL' in action.upper() or action == 'STO':
                        new_strike = target_short_strike
                    else:
                        if is_put:
                            new_strike = target_short_strike - width
                        else:
                            new_strike = target_short_strike + width
                else:
                    new_strike = target_short_strike

                # Find market data
                new_option_data = None
                for opt in target_chain.get('options', []):
                    if (extract_decimal(opt.get('strike')) == new_strike and
                        opt.get('option_type', '').upper() == option_type):
                        new_option_data = opt
                        break

                if not new_option_data:
                    break

                # Find current market data
                current_option_data = None
                for opt in current_chain_data.get('options', []):
                    if (extract_decimal(opt.get('strike')) == old_strike and
                        opt.get('option_type', '').upper() == option_type):
                        current_option_data = opt
                        break

                # Build leg
                new_leg = {
                    'symbol': new_option_data.get('symbol', ''),
                    'strike': new_strike,
                    'option_type': option_type,
                    'action': action,
                    'quantity': quantity,
                    'bid': extract_decimal(new_option_data.get('bid', 0)),
                    'ask': extract_decimal(new_option_data.get('ask', 0)),
                    'mark': extract_decimal(new_option_data.get('mark', 0))
                }
                new_legs.append(new_leg)

                if current_option_data:
                    leg['bid'] = extract_decimal(current_option_data.get('bid', 0))
                    leg['ask'] = extract_decimal(current_option_data.get('ask', 0))
                    leg['mark'] = extract_decimal(current_option_data.get('mark', 0))

            if len(new_legs) != len(current_legs):
                continue

            # Calculate credit/debit
            credit_debit = calculate_net_credit_debit(current_legs, new_legs)

            if credit_debit < -MAX_DEBIT_THRESHOLD:
                continue

            # Calculate metrics
            new_metrics = calculate_spread_metrics(new_legs)
            new_metrics.max_profit = credit_debit * 100
            new_metrics.max_loss = (new_metrics.width - credit_debit) * 100

            new_breakeven = calculate_breakeven(new_legs, credit_debit)

            scenario = RollScenario(
                scenario_type="roll_down_and_out",
                current_legs=current_legs,
                new_legs=new_legs,
                credit_debit=credit_debit,
                new_breakeven=new_breakeven,
                max_profit_change=new_metrics.max_profit - current_metrics.max_profit,
                max_loss_change=new_metrics.max_loss - current_metrics.max_loss,
                days_added=days_added,
                new_dte=new_dte,
                new_expiration=target_exp_date,
                current_metrics=current_metrics,
                new_metrics=new_metrics,
                viability_score=0
            )

            scenario.viability_score = calculate_viability_score(scenario)
            scenarios.append(scenario)

            scenario_count += 1
            if scenario_count >= max_scenarios:
                break

        if scenario_count >= max_scenarios:
            break

    # Sort by viability
    scenarios.sort(key=lambda s: s.viability_score, reverse=True)

    return scenarios
