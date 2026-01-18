import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from decimal import Decimal
from agents.manager import RiskManager
from tastytrade.dxfeed import Greeks

class TestRiskManager(unittest.IsolatedAsyncioTestCase):
    async def test_calculate_risk_metrics(self):
        # Mock Session
        mock_session = MagicMock()
        
        # Mock Account
        mock_account = MagicMock()
        
        # Mock Balances
        mock_balances = MagicMock()
        mock_balances.net_liquidating_value = Decimal(100000)
        mock_balances.equity_buying_power = Decimal(60000) # 40% used (40k used)
        mock_account.get_balances.return_value = mock_balances
        
        # Mock Positions
        # 1. Stock Position (High Value)
        pos1 = MagicMock()
        pos1.symbol = "AAPL"
        pos1.instrument_type = "Equity"
        pos1.mark = Decimal(150)
        pos1.quantity = Decimal(40) # 6000 value (6% of NLV) -> Should trigger warning
        pos1.multiplier = Decimal(1)
        
        # 2. Option Position (Need Greeks)
        pos2 = MagicMock()
        pos2.symbol = "SPY 250117C500"
        pos2.instrument_type = "Equity Option"
        pos2.mark = Decimal(2.0)
        pos2.quantity = Decimal(1)
        pos2.multiplier = Decimal(100)
        
        mock_account.get_positions.return_value = [pos1, pos2]
        
        # Patch Account.get
        with patch('tastytrade.Account.get', return_value=[mock_account]):
            risk = RiskManager(mock_session)
            
            # Mock _fetch_greeks internal method to avoid complex Streamer mocking
            # We can test _fetch_greeks separately or just assume it works for this high level test
            mock_greeks = MagicMock()
            mock_greeks.delta = Decimal("0.5")
            mock_greeks.theta = Decimal("-0.1") # -0.1 * 100 = -10 theta
            
            with patch.object(risk, '_fetch_greeks', new_callable=AsyncMock) as mock_fetch:
                mock_fetch.return_value = {"SPY 250117C500": mock_greeks}
                
                report = await risk.calculate_portfolio_risk()
                
                # Verify NLV
                self.assertEqual(report['nlv'], Decimal(100000))
                
                # Verify BP Usage
                # Used = 100k - 60k = 40k. 40%.
                self.assertEqual(report['bp_usage_pct'], 40.0)
                self.assertEqual(report['bp_usage_status'], "OK")
                
                # Verify Trade Size Warning
                self.assertTrue(len(report['trade_size_warnings']) > 0)
                self.assertIn("AAPL", report['trade_size_warnings'][0])
                
                # Verify Greeks
                # Delta: 0.5 * 100 * 1 = 50
                # Theta: -0.1 * 100 * 1 = -10
                self.assertEqual(report['portfolio_delta'], Decimal(50))
                self.assertEqual(report['portfolio_theta'], Decimal(-10))
                
                # Target Theta: 0.1% of 100k = 100. -10 is far below 100.
                # So should be LOW status? Wait, theta is usually negative.
                # "Target a daily Theta of between %0.1 and %0.5"
                # Usually implies positive theta decay collection (selling premium).
                # So ideally Theta should be +100 to +500.
                # If we have -10 (buying options), it's definitely "LOW" (or wrong direction).
                # My logic checks `total_theta < theta_low_target`. 
                # -10 < 100 is True. So LOW.
                self.assertIn("LOW", report['theta_status'])

if __name__ == '__main__':
    unittest.main()
