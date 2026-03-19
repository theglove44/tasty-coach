"""Risk Management Agent."""

import logging
import asyncio
from decimal import Decimal
from typing import List, Dict, Any, Optional

from tastytrade import Session, Account
from tastytrade.dxfeed import Greeks
from tastytrade.streamer import DXLinkStreamer
from tastytrade.market_data import get_market_data_by_type
from tastytrade.instruments import get_option_chain

from utils.market_schedule import MarketSchedule


class RiskManager:
    """Monitors portfolio health and risk metrics for a specific account."""

    def __init__(self, session: Session, account_number: Optional[str] = None):
        self.session = session
        self.logger = logging.getLogger(__name__)
        self.account_number = account_number
        self.account: Optional[Account] = None
        self.market_schedule = MarketSchedule(session)

    async def _get_account(self) -> Account:
        if self.account:
            return self.account

        accounts = Account.get(self.session)
        if not accounts:
            raise ValueError("No accounts found.")

        if self.account_number:
            for acct in accounts:
                if getattr(acct, "account_number", None) == self.account_number:
                    self.account = acct
                    return acct
            available = ", ".join([getattr(a, "account_number", "?") for a in accounts])
            raise ValueError(f"Account {self.account_number} not found. Available: {available}")

        self.account = accounts[0]
        return self.account

    def _is_option(self, pos) -> bool:
        """Check if a position is an equity option using the enum value."""
        inst_type = getattr(pos, "instrument_type", None)
        if inst_type is None:
            return False
        # Compare via .value for enum-safe check (API: "Equity Option")
        type_str = getattr(inst_type, "value", str(inst_type))
        return "Equity Option" == type_str

    async def _fetch_marks(self, positions: List[Any]) -> Dict[str, float]:
        """Fetch live marks for positions via market data API.

        Per API docs, Position objects don't have a mark field.
        We must fetch marks from GET /market-data/by-type with typed params.
        """
        marks: Dict[str, float] = {}

        # Split by instrument type for correct API params
        equity_syms = []
        option_syms = []
        for pos in positions:
            type_str = getattr(getattr(pos, "instrument_type", None), "value", "")
            if type_str == "Equity":
                equity_syms.append(pos.symbol)
            elif type_str == "Equity Option":
                option_syms.append(pos.symbol)

        batch_size = 50
        try:
            if equity_syms:
                quotes = get_market_data_by_type(self.session, equities=equity_syms)
                for q in quotes:
                    marks[q.symbol] = float(q.mark) if q.mark else 0.0
            for i in range(0, len(option_syms), batch_size):
                batch = option_syms[i:i + batch_size]
                quotes = get_market_data_by_type(self.session, options=batch)
                for q in quotes:
                    marks[q.symbol] = float(q.mark) if q.mark else 0.0
        except Exception as e:
            self.logger.warning(f"Failed to fetch position marks: {e}")

        return marks

    async def calculate_portfolio_risk(self) -> Dict[str, Any]:
        account = await self._get_account()
        balances = account.get_balances(self.session)
        positions = account.get_positions(self.session)

        nlv = extract_decimal(getattr(balances, "net_liquidating_value", None))
        bp = extract_decimal(getattr(balances, "equity_buying_power", None))

        bp_used = nlv - bp
        bp_usage_pct = (bp_used / nlv) * 100 if nlv > 0 else Decimal(0)

        # Check market session timing
        session_warnings: List[str] = []
        if not self.market_schedule.is_market_open():
             session_warnings.append("Market is CLOSED. Liquidity and spreads may be unreliable.")

        trade_size_warnings: List[str] = []
        max_trade_pct = Decimal(5.0)

        # Fix A: Fetch live marks from market data API (positions don't have mark field)
        marks_map = await self._fetch_marks(positions)

        # Collect option positions and build OCC→streamer symbol map
        option_positions: List[Any] = []
        occ_to_streamer: Dict[str, str] = {}

        for pos in positions:
            mark = Decimal(str(marks_map.get(pos.symbol, 0.0)))
            qty = extract_decimal(getattr(pos, "quantity", None))
            mult = extract_decimal(getattr(pos, "multiplier", None) or 1)

            market_value = abs(mark * qty * mult)
            trade_pct = (market_value / nlv) * 100 if nlv > 0 else Decimal(0)

            if trade_pct > max_trade_pct:
                trade_size_warnings.append(
                    f"{pos.symbol}: {trade_pct:.2f}% of NLV (Limit: {max_trade_pct}%)"
                )

            # Fix B: Compare via enum value string, not raw string
            if self._is_option(pos):
                option_positions.append(pos)

        # Fix C: Resolve OCC symbols to streamer symbols for DXLink subscription
        # The streamer uses a different symbol format than positions
        if option_positions:
            occ_to_streamer = await self._resolve_streamer_symbols(option_positions)

        total_delta = Decimal(0)
        total_theta = Decimal(0)

        if occ_to_streamer:
            streamer_symbols = list(occ_to_streamer.values())
            greeks_data = await self._fetch_greeks(streamer_symbols)

            # Build reverse map: streamer_symbol → occ_symbol
            streamer_to_occ = {v: k for k, v in occ_to_streamer.items()}

            for pos in option_positions:
                streamer_sym = occ_to_streamer.get(pos.symbol)
                if not streamer_sym or streamer_sym not in greeks_data:
                    continue

                data = greeks_data[streamer_sym]
                if data and data.delta is not None and data.theta is not None:
                    contract_delta = extract_decimal(data.delta)
                    contract_theta = extract_decimal(data.theta)

                    qty = extract_decimal(getattr(pos, "quantity", None))
                    mult = extract_decimal(getattr(pos, "multiplier", None) or 1)

                    # Fix D: Per API docs, quantity is always positive.
                    # Apply direction sign for correct portfolio Greeks.
                    direction = getattr(pos, "quantity_direction", "Long")
                    sign = Decimal(-1) if direction == "Short" else Decimal(1)

                    total_delta += contract_delta * mult * qty * sign
                    total_theta += contract_theta * mult * qty * sign

        day_trade_excess = extract_decimal(getattr(balances, "day_trade_excess", None))
        day_trade_bp = extract_decimal(getattr(balances, "day_trading_buying_power", None))
        cash_balance = extract_decimal(getattr(balances, "cash_balance", None))

        theta_low_target = nlv * Decimal("0.001")
        theta_high_target = nlv * Decimal("0.005")

        theta_status = "OK"
        if total_theta < theta_low_target:
            theta_status = f"LOW (Current: {total_theta:.2f}, Target > {theta_low_target:.2f})"
        elif total_theta > theta_high_target:
            theta_status = f"HIGH (Current: {total_theta:.2f}, Target < {theta_high_target:.2f})"

        if day_trade_excess < 0:
            session_warnings.append(f"Day Trade Excess is NEGATIVE: ${day_trade_excess:.2f}")

        return {
            "nlv": nlv,
            "bp_usage_pct": bp_usage_pct,
            "bp_usage_status": "WARNING (>50%)" if bp_usage_pct > 50 else "OK",
            "day_trade_excess": day_trade_excess,
            "day_trading_buying_power": day_trade_bp,
            "cash_balance": cash_balance,
            "trade_size_warnings": trade_size_warnings,
            "session_warnings": session_warnings,
            "portfolio_delta": total_delta,
            "portfolio_theta": total_theta,
            "theta_status": theta_status,
        }

    async def _resolve_streamer_symbols(self, positions: List[Any]) -> Dict[str, str]:
        """Map OCC symbols to streamer symbols via option chain lookup.

        Per API docs, DXLink uses streamer-symbol (e.g. .SPY250321P500)
        while positions use OCC symbols (e.g. SPY   250321P00500000).
        The instruments endpoint returns both, so we look up the mapping.
        """
        occ_to_streamer: Dict[str, str] = {}

        # Group by underlying to minimize API calls
        by_underlying: Dict[str, List[str]] = {}
        for pos in positions:
            underlying = getattr(pos, "underlying_symbol", None)
            if underlying:
                by_underlying.setdefault(underlying, []).append(pos.symbol)

        for underlying, occ_symbols in by_underlying.items():
            try:
                chain = get_option_chain(self.session, underlying)
                # chain is dict[date, list[Option]]
                for exp_date, options in chain.items():
                    for opt in options:
                        if opt.symbol in occ_symbols:
                            occ_to_streamer[opt.symbol] = opt.streamer_symbol
                # Early exit if all resolved
                if len(occ_to_streamer) >= sum(len(v) for v in by_underlying.values()):
                    break
            except Exception as e:
                self.logger.warning(f"Failed to resolve streamer symbols for {underlying}: {e}")

        return occ_to_streamer

    async def _fetch_greeks(self, symbols: List[str]) -> Dict[str, Greeks]:
        """Fetch a snapshot of greeks, with a hard timeout even if no events arrive.

        Args:
            symbols: List of streamer symbols (not OCC symbols)
        """
        if not symbols:
            return {}

        results: Dict[str, Greeks] = {}

        try:
            async with DXLinkStreamer(self.session) as streamer:
                await streamer.subscribe(Greeks, symbols)

                start_time = asyncio.get_running_loop().time()
                timeout_s = 5.0

                agen = streamer.listen(Greeks)

                while len(results) < len(symbols):
                    remaining = timeout_s - (asyncio.get_running_loop().time() - start_time)
                    if remaining <= 0:
                        break

                    try:
                        greeks = await asyncio.wait_for(agen.__anext__(), timeout=min(0.5, remaining))
                    except asyncio.TimeoutError:
                        continue
                    except StopAsyncIteration:
                        break

                    if greeks.event_symbol in symbols:
                        results[greeks.event_symbol] = greeks

        except Exception as e:
            self.logger.error(f"Error fetching greeks: {e}")

        if len(results) < len(symbols):
            self.logger.warning(f"Timeout waiting for greeks. Got {len(results)}/{len(symbols)}")

        return results


def extract_decimal(value):
    """Helper to ensure we have a Decimal or 0."""

    if value is None:
        return Decimal(0)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
