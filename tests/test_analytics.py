"""Tests for the analytics agent."""

import unittest
from pathlib import Path
from utils.db import TradeDB


class TestAnalyticsQueries(unittest.TestCase):
    """Test analytics SQL queries directly against seeded data."""

    def setUp(self):
        self.db = TradeDB(db_path=Path(":memory:"))
        self._seed_data()

    def tearDown(self):
        self.db.close()

    def _seed_data(self):
        """Seed trade groups for analytics testing."""
        # Winner: SPY vertical, +$100
        g1 = self.db.create_trade_group(
            "ABC", "SPY", strategy_type="Vertical", opened_at="2024-01-15T10:00:00"
        )
        self.db.update_trade_group(
            g1, status="closed", closed_at="2024-01-25T10:00:00",
            total_premium_collected=200.0, total_premium_paid=100.0,
            total_fees=2.0, realized_pl=100.0, holding_days=10,
        )

        # Loser: AAPL vertical, -$50
        g2 = self.db.create_trade_group(
            "ABC", "AAPL", strategy_type="Vertical", opened_at="2024-02-01T10:00:00"
        )
        self.db.update_trade_group(
            g2, status="closed", closed_at="2024-02-15T10:00:00",
            total_premium_collected=80.0, total_premium_paid=130.0,
            total_fees=2.0, realized_pl=-50.0, holding_days=14,
        )

        # Winner: TSLA iron condor, +$200
        g3 = self.db.create_trade_group(
            "ABC", "TSLA", strategy_type="Iron Condor", opened_at="2024-02-10T10:00:00"
        )
        self.db.update_trade_group(
            g3, status="expired", closed_at="2024-03-15T16:00:00",
            total_premium_collected=200.0, total_premium_paid=0.0,
            total_fees=4.0, realized_pl=200.0, holding_days=34,
        )

        # Open position (should be excluded from closed analytics)
        g4 = self.db.create_trade_group(
            "ABC", "QQQ", strategy_type="Vertical", opened_at="2024-03-01T10:00:00"
        )

    def test_performance_summary(self):
        row = self.db.conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN realized_pl > 0 THEN 1 ELSE 0 END) as winners,
                SUM(CASE WHEN realized_pl <= 0 THEN 1 ELSE 0 END) as losers,
                SUM(realized_pl) as total_pl
            FROM trade_groups
            WHERE account_number = 'ABC' AND status IN ('closed', 'expired', 'assigned')
        """).fetchone()

        self.assertEqual(row["total"], 3)
        self.assertEqual(row["winners"], 2)
        self.assertEqual(row["losers"], 1)
        self.assertAlmostEqual(row["total_pl"], 250.0)

    def test_strategy_breakdown(self):
        rows = self.db.conn.execute("""
            SELECT
                strategy_type,
                COUNT(*) as trades,
                SUM(realized_pl) as total_pl
            FROM trade_groups
            WHERE account_number = 'ABC' AND status IN ('closed', 'expired', 'assigned')
            GROUP BY strategy_type
            ORDER BY total_pl DESC
        """).fetchall()

        strategies = {r["strategy_type"]: r for r in rows}
        self.assertIn("Vertical", strategies)
        self.assertIn("Iron Condor", strategies)
        self.assertEqual(strategies["Vertical"]["trades"], 2)
        self.assertEqual(strategies["Iron Condor"]["trades"], 1)
        self.assertAlmostEqual(strategies["Iron Condor"]["total_pl"], 200.0)

    def test_monthly_pl(self):
        rows = self.db.conn.execute("""
            SELECT
                strftime('%Y-%m', closed_at) as period,
                COUNT(*) as trades,
                SUM(realized_pl) as pl
            FROM trade_groups
            WHERE account_number = 'ABC' AND status IN ('closed', 'expired', 'assigned')
              AND closed_at IS NOT NULL
            GROUP BY period
            ORDER BY period
        """).fetchall()

        self.assertEqual(len(rows), 3)
        periods = {r["period"]: r for r in rows}
        self.assertAlmostEqual(periods["2024-01"]["pl"], 100.0)
        self.assertAlmostEqual(periods["2024-02"]["pl"], -50.0)
        self.assertAlmostEqual(periods["2024-03"]["pl"], 200.0)

    def test_excludes_open_positions(self):
        row = self.db.conn.execute("""
            SELECT COUNT(*) as cnt FROM trade_groups
            WHERE account_number = 'ABC' AND status IN ('closed', 'expired', 'assigned')
        """).fetchone()
        self.assertEqual(row["cnt"], 3)  # QQQ open position excluded

    def test_date_filtering(self):
        row = self.db.conn.execute("""
            SELECT COUNT(*) as cnt FROM trade_groups
            WHERE account_number = 'ABC' AND status IN ('closed', 'expired', 'assigned')
              AND opened_at >= '2024-02-01'
        """).fetchone()
        self.assertEqual(row["cnt"], 2)  # AAPL + TSLA

    def test_roll_chain_pl(self):
        # Create a roll chain: g5 -> g6 -> g7
        g5 = self.db.create_trade_group(
            "ABC", "IWM", strategy_type="Vertical", opened_at="2024-01-01"
        )
        self.db.update_trade_group(
            g5, status="closed", closed_at="2024-01-15",
            realized_pl=50.0, total_fees=1.0,
        )

        g6 = self.db.create_trade_group(
            "ABC", "IWM", strategy_type="Vertical",
            opened_at="2024-01-15", parent_group_id=g5,
        )
        self.db.update_trade_group(
            g6, status="closed", closed_at="2024-02-01",
            realized_pl=-20.0, total_fees=1.0,
        )

        g7 = self.db.create_trade_group(
            "ABC", "IWM", strategy_type="Vertical",
            opened_at="2024-02-01", parent_group_id=g6,
        )
        self.db.update_trade_group(
            g7, status="closed", closed_at="2024-02-15",
            realized_pl=80.0, total_fees=1.0,
        )

        chain = self.db.get_roll_chain(g7)
        self.assertEqual(len(chain), 3)

        total_pl = sum(g["realized_pl"] or 0 for g in chain)
        self.assertAlmostEqual(total_pl, 110.0)  # 50 - 20 + 80


if __name__ == "__main__":
    unittest.main()
