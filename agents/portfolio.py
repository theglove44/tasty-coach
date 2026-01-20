import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, date

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

    def _parse_occ_symbol(self, symbol: str) -> Dict[str, Any]:
        """Parse OCC option symbol to extract details.
        Format: R...RYYMMDDTSSSSSSSS
        """
        import re
        # Regex for OCC symbol
        match = re.match(r'^([A-Z]+)\s+(\d{6})([CP])(\d{8})$', symbol)
        if not match:
            return {}
        
        root, date_str, type_char, strike_str = match.groups()
        strike = float(strike_str) / 1000.0
        # Parse date YYMMDD
        exp_date = datetime.strptime(date_str, '%y%m%d').date()
        
        return {
            'root': root,
            'expiration': exp_date,
            'type': 'CALL' if type_char == 'C' else 'PUT',
            'strike': strike
        }

    def _group_positions(self, positions: List[Any]) -> Dict[str, Any]:
        """Group positions by Underlying -> Expiration -> Strategy."""
        grouped = {}
        
        for pos in positions:
            sym = getattr(pos, 'symbol', '')
            details = self._parse_occ_symbol(sym)
            
            underlying = getattr(pos, 'underlying_symbol', sym)
            
            # If not an option (failed parse), treat as Stock/Other
            if not details:
                if underlying not in grouped:
                    grouped[underlying] = {'strategies': [], 'misc': []}
                grouped[underlying]['misc'].append(pos)
                continue
                
            exp_date = details['expiration']
            
            if underlying not in grouped:
                grouped[underlying] = {'strategies': [], 'misc': [], 'by_date': {}}
            
            if exp_date not in grouped[underlying]['by_date']:
                grouped[underlying]['by_date'][exp_date] = []
            
            # Enrich position with parsed data for easier logic
            pos._parsed_details = details
            grouped[underlying]['by_date'][exp_date].append(pos)

        # Process groups into strategies
        results = {}
        for underlying, data in grouped.items():
            strategies = []
            
            # 1. Process Option Chains by Expiration
            for exp_date, legs in data['by_date'].items():
                # Simple Heuristics
                # Sort by strike
                legs.sort(key=lambda x: x._parsed_details['strike'])
                
                qty_call = sum(1 for p in legs if p._parsed_details['type'] == 'CALL')
                qty_put = sum(1 for p in legs if p._parsed_details['type'] == 'PUT')
                
                # Check for net quantity to verify if it's a spread or directional
                
                strat_name = "Custom / Mixed"
                if len(legs) == 4 and qty_call == 2 and qty_put == 2:
                    strat_name = "Iron Condor"
                elif len(legs) == 2:
                    if qty_call == 2:
                        strat_name = "Vertical Call"
                    elif qty_put == 2:
                        strat_name = "Vertical Put"
                    elif qty_call == 1 and qty_put == 1:
                        strat_name = "Strangle/Straddle"
                elif len(legs) == 1:
                    l = legs[0]
                    kind = l._parsed_details['type'].capitalize()
                    strat_name = f"Single {kind}"
                
                strategies.append({
                    'name': f"{strat_name} ({exp_date.strftime('%b %d')})",
                    'legs': legs
                })
            
            # 2. Add Misc (Stock)
            if data['misc']:
                strategies.append({
                    'name': 'Stock / Equity',
                    'legs': data['misc']
                })
            
            results[underlying] = strategies
            
        return results

    def print_positions_report(self):
        """Prints a CLI-friendly report of account balances and open positions."""
        # 1. Account Summary
        status = self.get_account_status()
        if not status:
            print("❌ Could not fetch account status.")
            return

        print("\n" + "=" * 60)
        print(f"💰 ACCOUNT SUMMARY ({self.account_number})")
        print("=" * 60)
        print(f"Net Liq:       ${status.get('net_liquidating_value', 0):,.2f}")
        print(f"Equity BP:     ${status.get('equity_buying_power', 0):,.2f}")
        print(f"Cash Balance:  ${status.get('cash_balance', 0):,.2f}")
        
        # 2. Positions Table
        positions = self.get_positions()
        print("\n" + "=" * 100)
        print(f"📊 OPEN POSITIONS ({len(positions)} legs)")
        print("=" * 100)
        
        if not positions:
            print("No open positions found.")
            return

        grouped_data = self._group_positions(positions)
        
        # Header
        print(f"{'Qty':>5} | {'Symbol/Strike':<25} | {'Exp':<10} | {'Avg Price':>10} | {'Mark':>10} | {'Value':>10}")
        print("-" * 100)

        for underlying, strategies in grouped_data.items():
            print(f" ► {underlying}")
            for strat in strategies:
                print(f"    └── {strat['name']}")
                for pos in strat['legs']:
                    qty = int(getattr(pos, 'quantity', 0))
                    # Handle Short qty
                    if getattr(pos, 'quantity_direction', 'Long') == 'Short':
                        qty = -abs(qty)
                    
                    details = getattr(pos, '_parsed_details', None)
                    
                    if details:
                        # Option
                        display_name = f"{details['strike']:.1f} {details['type'][0]}"
                        exp_str = details['expiration'].strftime('%y-%m-%d')
                    else:
                        # Stock
                        display_name = getattr(pos, 'symbol', 'Unknown')
                        exp_str = "-"

                    avg_price = float(getattr(pos, 'average_open_price', 0) or 0)
                    market_value = float(getattr(pos, 'market_value', 0) or 0)
                    
                    print(f"{qty:>5} |   {display_name:<23} | {exp_str:<10} | ${avg_price:>9.2f} | {'-':>10} | ${market_value:>9.2f}")
            print("-" * 100)
