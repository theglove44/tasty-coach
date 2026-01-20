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
        from tastytrade.market_data import get_market_data_by_type

        # 1. Account Summary
        status = self.get_account_status()
        if not status:
            print("❌ Could not fetch account status.")
            return

        print("\n" + "=" * 90)
        print(f"💰 ACCOUNT SUMMARY ({self.account_number})")
        print("=" * 90)
        print(f"Net Liq:       ${status.get('net_liquidating_value', 0):,.2f}")
        print(f"Equity BP:     ${status.get('equity_buying_power', 0):,.2f}")
        print(f"Cash Balance:  ${status.get('cash_balance', 0):,.2f}")
        
        # 2. Positions Table
        positions = self.get_positions()
        
        if not positions:
            print("\nNo open positions found.")
            return

        # Fetch market data for all positions for accurate P/L
        symbols = [p.symbol for p in positions]
        quotes_map = {}
        try:
            quotes = get_market_data_by_type(self.session, symbols)
            quotes_map = {q.symbol: q for q in quotes}
        except Exception as e:
            self.logger.warning(f"Failed to fetch market data: {e}. P/L may be inaccurate.")

        print("\n" + "=" * 130)
        print(f"📊 OPEN POSITIONS ({len(positions)} legs)")
        print("=" * 130)
        
        grouped_data = self._group_positions(positions)
        
        # Header
        # Qty | Symbol/Strike | Exp | DTE | Trade Prc | Mark | Value | P/L Open | P/L %
        header = f"{'Qty':>5} | {'Symbol/Strike':<22} | {'Exp':<8} | {'DTE':>4} | {'Trd Prc':>9} | {'Mark':>9} | {'Value':>10} | {'P/L Opn':>10} | {'P/L %':>7}"
        print(header)
        print("-" * 130)

        for underlying, strategies in grouped_data.items():
            print(f" ► {underlying}")
            for strat in strategies:
                # Pre-calculate Strategy Totals
                strat_pl_open = 0.0
                strat_entry_cost = 0.0
                
                for pos in strat['legs']:
                    qty = int(getattr(pos, 'quantity', 0))
                    # Handle Short qty
                    if getattr(pos, 'quantity_direction', 'Long') == 'Short':
                        qty = -abs(qty)
                    
                    multiplier = int(getattr(pos, 'multiplier', 100) or 100)
                    avg_open_price = float(getattr(pos, 'average_open_price', 0) or 0)
                    
                    # Mark
                    mark = 0.0
                    if pos.symbol in quotes_map:
                        mark = float(quotes_map[pos.symbol].mark)
                    else:
                         mv = float(getattr(pos, 'market_value', 0))
                         if qty != 0:
                             mark = abs(mv / (qty * multiplier))
                    
                    # Entry Cost (Net)
                    # For Long: positive cost. For Short: negative cost (credit).
                    strat_entry_cost += (qty * avg_open_price * multiplier)
                    
                    # P/L
                    strat_pl_open += (mark - avg_open_price) * qty * multiplier

                # Strategy P/L %
                # If cost is 0 (unlikely), avoid div 0
                strat_pl_pct = 0.0
                if abs(strat_entry_cost) > 0.01:
                    # For Credit trades (negative cost), P/L is positive when Mark < Open. 
                    # We want % of max profit (credit)? Or % of captured value?
                    # Standard ROI: P/L / Capital.
                    # But for short premium, 'Capital' is margin, which we don't have easily here.
                    # Usually traders want "% of Max Profit" for credit spreads.
                    # Max Profit = Credit. 
                    # return P/L / Abs(Credit).
                    strat_pl_pct = strat_pl_open / abs(strat_entry_cost)

                # Print Strategy Header with Totals
                # Align P/L to the columns: P/L Opn is ~ column 100-110, P/L % ~ 120
                # Header: ... | Value      | P/L Opn    | P/L %
                # We can construct a string that pads spaces until those columns.
                # Strategy Name len varies.
                # Use fixed spacing logic or simplified 
                
                # Let's align P/L Opn to be roughly under the "P/L Opn" header
                # The header layout is:
                # Qty (5) | Sym (22) | Exp (8) | DTE (4) | Trd Prc (9) | Mark (9) | Value (10) | P/L Opn (10) | P/L % (7)
                # Separators: " | " (3 chars)
                # Lengths: 5+3+22+3+8+3+4+3+9+3+9+3+10+3 = 88 chars to start of P/L Opn
                
                prefix = f"    └── {strat['name']}"
                padding = " " * (88 - len(prefix))
                
                # If prefix is too long, just space it out a bit
                if len(prefix) > 85:
                    padding = "   "
                
                print(f"{prefix}{padding}{strat_pl_open:>10.2f} | {strat_pl_pct:>6.1%}")

                for pos in strat['legs']:
                    qty = int(getattr(pos, 'quantity', 0))
                    # Handle Short qty
                    if getattr(pos, 'quantity_direction', 'Long') == 'Short':
                        qty = -abs(qty)
                    
                    details = getattr(pos, '_parsed_details', None)
                    multiplier = int(getattr(pos, 'multiplier', 100) or 100)
                    
                    dte_str = "-"
                    exp_str = "-"
                    display_name = getattr(pos, 'symbol', 'Unknown')

                    passed_expiration = False
                    if details:
                        # Option
                        display_name = f"{details['strike']:.1f} {details['type'][0]}"
                        exp_str = details['expiration'].strftime('%y-%m-%d')
                        days = (details['expiration'] - date.today()).days
                        dte_str = str(days)
                        if days < 0: passed_expiration = True
                    else:
                        # Stock or other
                        if hasattr(pos, 'expires_at') and pos.expires_at: # Future / Future Option
                            exp_date = pos.expires_at.date()
                            exp_str = exp_date.strftime('%y-%m-%d')
                            dte_str = str((exp_date - date.today()).days)

                    avg_open_price = float(getattr(pos, 'average_open_price', 0) or 0)
                    
                    # Determine Mark
                    mark = 0.0
                    if pos.symbol in quotes_map:
                        mark = float(quotes_map[pos.symbol].mark)
                    else:
                         mv = float(getattr(pos, 'market_value', 0))
                         if qty != 0:
                             mark = abs(mv / (qty * multiplier))

                    market_value = mark * qty * multiplier
                    
                    pl_open = (mark - avg_open_price) * qty * multiplier
                    
                    # P/L %
                    pl_pct = 0.0
                    if avg_open_price != 0:
                        if qty > 0:
                            pl_pct = (mark - avg_open_price) / avg_open_price
                        else: # Short
                            pl_pct = (avg_open_price - mark) / avg_open_price

                    print(f"{qty:>5} |   {display_name:<20} | {exp_str:<8} | {dte_str:>4} | ${avg_open_price:>8.2f} | ${mark:>8.2f} | ${market_value:>9.2f} | ${pl_open:>9.2f} | {pl_pct:>6.1%}")
            print("-" * 130)
