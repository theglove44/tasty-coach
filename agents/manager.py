"""Risk Management Agent."""

import logging
import asyncio
from decimal import Decimal
from typing import List, Dict, Any, Optional

from tastytrade import Session, Account
from tastytrade.dxfeed import Greeks
from tastytrade.streamer import DXLinkStreamer

from utils.market_schedule import MarketSchedule


class RiskManager:
    """Monitors portfolio health and risk metrics for a specific account."""

    def __init__(self, session: Session, account_number: Optional[str] = None):
        self.session = session
        self.logger = logging.getLogger(__name__)
        self.account_number = account_number
        self.account: Optional[Account] = None
        self.market_schedule = MarketSchedule(session)

    def _get_account(self) -> Account:
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

    async def calculate_portfolio_risk(self) -> Dict[str, Any]:
        account = self._get_account()
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

        option_symbols: List[str] = []

        for pos in positions:
            mark = extract_decimal(getattr(pos, "mark", None))
            qty = extract_decimal(getattr(pos, "quantity", None))
            mult = extract_decimal(getattr(pos, "multiplier", None) or 1)

            market_value = abs(mark * qty * mult)
            trade_pct = (market_value / nlv) * 100 if nlv > 0 else Decimal(0)

            if trade_pct > max_trade_pct:
                trade_size_warnings.append(
                    f"{pos.symbol}: {trade_pct:.2f}% of NLV (Limit: {max_trade_pct}%)"
                )

            if getattr(pos, "instrument_type", None) == "Equity Option":
                option_symbols.append(pos.symbol)

        total_delta = Decimal(0)
        total_theta = Decimal(0)

        if option_symbols:
            greeks_data = await self._fetch_greeks(option_symbols)

            for pos in positions:
                if pos.symbol in greeks_data:
                    data = greeks_data[pos.symbol]
                    if data and data.delta is not None and data.theta is not None:
                        contract_delta = extract_decimal(data.delta)
                        contract_theta = extract_decimal(data.theta)

                        qty = extract_decimal(getattr(pos, "quantity", None))
                        mult = extract_decimal(getattr(pos, "multiplier", None) or 1)

                        total_delta += contract_delta * mult * qty
                        total_theta += contract_theta * mult * qty

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

    async def _fetch_greeks(self, symbols: List[str]) -> Dict[str, Greeks]:
        """Fetch a snapshot of greeks, with a hard timeout even if no events arrive."""

        if not symbols:
            return {}

        results: Dict[str, Greeks] = {}

        try:
            async with DXLinkStreamer(self.session) as streamer:
                await streamer.subscribe(Greeks, symbols)

                start_time = asyncio.get_event_loop().time()
                timeout_s = 5.0

                agen = streamer.listen(Greeks)

                while len(results) < len(symbols):
                    remaining = timeout_s - (asyncio.get_event_loop().time() - start_time)
                    if remaining <= 0:
                        break

                    try:
                        greeks = await asyncio.wait_for(agen.__anext__(), timeout=min(0.5, remaining))
                    except asyncio.TimeoutError:
                        continue
                    except StopAsyncIteration:
                        break

                    if greeks.eventSymbol in symbols:
                        results[greeks.eventSymbol] = greeks

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
