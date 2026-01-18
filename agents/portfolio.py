import logging
from typing import List, Dict, Any, Optional

from tastytrade import Session, Account


class PortfolioAgent:
    """Handles account status + positions for a specific account."""

    def __init__(self, session: Session, account_number: Optional[str] = None):
        self.session = session
        self.logger = logging.getLogger(__name__)
        self.account_number = account_number
        self.account: Optional[Account] = self._get_account()

    def _get_account(self) -> Optional[Account]:
        try:
            accounts = Account.get(self.session)
            if not accounts:
                return None

            if self.account_number:
                for acct in accounts:
                    if getattr(acct, "account_number", None) == self.account_number:
                        return acct
                available = ", ".join([getattr(a, "account_number", "?") for a in accounts])
                raise ValueError(
                    f"Account {self.account_number} not found. Available: {available}"
                )

            return accounts[0]
        except Exception as e:
            self.logger.error(f"Error fetching accounts: {e}")
            return None

    def get_account_status(self) -> Dict[str, Any]:
        """Fetch basic account balance info."""
        if not self.account:
            return {}
        try:
            balances = self.account.get_balances(self.session)
            return {
                "net_liquidating_value": float(balances.net_liquidating_value),
                "equity_buying_power": float(balances.equity_buying_power),
                "maintenance_margin": float(balances.maintenance_margin),
                "day_trading_buying_power": float(balances.day_trading_buying_power),
                "day_trade_excess": float(balances.day_trade_excess),
                "cash_balance": float(balances.cash_balance),
                "pending_cash": float(balances.pending_cash),
                # Only include futures margin if relevant (non-zero) or just always return it
                "futures_margin_requirement": float(balances.futures_margin_requirement),
            }
        except Exception as e:
            self.logger.error(f"Error fetching account status: {e}")
            return {}

    def get_positions(self) -> List[Any]:
        """Fetch all current open positions."""
        if not self.account:
            return []
        try:
            return self.account.get_positions(self.session)
        except Exception as e:
            self.logger.error(f"Error fetching positions: {e}")
            return []
