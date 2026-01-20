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
                "maintenance_margin": float(balances.maintenance_requirement),
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

    def print_positions_report(self):
        """Prints a CLI-friendly report of account balances and open positions."""
        # 1. Account Summary
        status = self.get_account_status()
        if not status:
            print("❌ Could not fetch account status.")
            return

        print("\n" + "=" * 50)
        print(f"💰 ACCOUNT SUMMARY ({self.account_number})")
        print("=" * 50)
        print(f"Net Liq:       ${status.get('net_liquidating_value', 0):,.2f}")
        print(f"Equity BP:     ${status.get('equity_buying_power', 0):,.2f}")
        print(f"Cash Balance:  ${status.get('cash_balance', 0):,.2f}")
        print(f"Day Trade BP:  ${status.get('day_trading_buying_power', 0):,.2f}")
        
        # 2. Positions Table
        positions = self.get_positions()
        print("\n" + "=" * 90)
        print(f"📊 OPEN POSITIONS ({len(positions)})")
        print("=" * 90)
        
        if not positions:
            print("No open positions found.")
            return

        # Header
        # Sym | Qty | Avg Price | Mark | Value | P/L Open
        header = f"{'Symbol':<10} | {'Qty':>5} | {'Avg Price':>10} | {'Mark':>10} | {'Value':>10}"
        print(header)
        print("-" * 90)

        for pos in positions:
            sym = getattr(pos, 'symbol', 'Unknown')
            qty = getattr(pos, 'quantity', 0)
            avg_price = float(getattr(pos, 'average_open_price', 0) or 0)
            
            # Since we don't have separate fetching of Mark Price here easily without streaming or quotes,
            # we rely on what the position object has. 
            # Note: CurrentPosition object *might* not have current market price populated unless updated recently or streaming.
            # However, 'market_value' is usually provided by the API snapshot.
            market_value = float(getattr(pos, 'market_value', 0) or 0)
            
            # Approximate Mark Price if not explicitly available
            # Options/Stocks will differ in multiplier, so this is rough simple math for display if needed
            # But let's just stick to what we know: Market Value.
            
            # Formatting
            print(f"{sym:<10} | {qty:>5} | ${avg_price:>9.2f} | {'-':>10} | ${market_value:>9.2f}")

        print("-" * 90)
