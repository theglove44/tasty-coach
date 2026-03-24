"""Tests for trade grouping algorithm — the most critical test file."""

import unittest
from pathlib import Path
from utils.db import TradeDB
from utils.trade_grouper import TradeGrouper


def make_txn(
    id, account="ABC", txn_type="Trade", sub_type="Sell to Open",
    executed_at="2024-01-15T10:00:00", txn_date="2024-01-15",
    value=100.0, net_value=99.0, underlying="SPY", action="Sell to Open",
    quantity=1.0, price=1.0, order_id=100, symbol=None, instrument_type="Equity Option",
):
    """Helper to create a transaction dict."""
    return {
        "id": id,
        "account_number": account,
        "transaction_type": txn_type,
        "transaction_sub_type": sub_type,
        "description": f"Test txn {id}",
        "executed_at": executed_at,
        "transaction_date": txn_date,
        "value": value,
        "net_value": net_value,
        "is_estimated_fee": False,
        "symbol": symbol or f"{underlying} Option",
        "instrument_type": instrument_type,
        "underlying_symbol": underlying,
        "action": action,
        "quantity": quantity,
        "price": price,
        "regulatory_fees": 0.02,
        "clearing_fees": 0.05,
        "commission": 0.50,
        "order_id": order_id,
    }


class TestTradeGrouper(unittest.TestCase):
    def setUp(self):
        self.db = TradeDB(db_path=Path(":memory:"))
        self.grouper = TradeGrouper(self.db)

    def tearDown(self):
        self.db.close()

    def test_simple_open_and_close(self):
        """Open 1 contract, close it later — should create 1 group, mark it closed."""
        self.db.upsert_transactions([
            make_txn(1, action="Sell to Open", sub_type="Sell to Open",
                     value=150.0, net_value=148.5, order_id=100,
                     executed_at="2024-01-15T10:00:00"),
            make_txn(2, action="Buy to Close", sub_type="Buy to Close",
                     value=-50.0, net_value=-51.0, order_id=101,
                     executed_at="2024-01-25T10:00:00"),
        ])

        count = self.grouper.build_groups("ABC")
        self.assertEqual(count, 1)

        groups = self.db.get_trade_groups("ABC")
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["status"], "closed")
        self.assertEqual(groups[0]["underlying_symbol"], "SPY")
        self.assertIsNotNone(groups[0]["realized_pl"])
        self.assertEqual(groups[0]["holding_days"], 10)

    def test_multi_leg_open(self):
        """Open a 2-leg vertical (same order_id) — should be 1 group."""
        self.db.upsert_transactions([
            make_txn(1, action="Sell to Open", sub_type="Sell to Open",
                     value=200.0, net_value=199.0, order_id=100,
                     executed_at="2024-01-15T10:00:00", symbol="SPY 240315P490"),
            make_txn(2, action="Buy to Open", sub_type="Buy to Open",
                     value=-100.0, net_value=-101.0, order_id=100,
                     executed_at="2024-01-15T10:00:00", symbol="SPY 240315P485"),
        ])

        count = self.grouper.build_groups("ABC")
        self.assertEqual(count, 1)

        groups = self.db.get_trade_groups("ABC")
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["strategy_type"], "Vertical")
        self.assertEqual(groups[0]["status"], "open")

    def test_iron_condor(self):
        """Open a 4-leg iron condor — should be 1 group with strategy 'Iron Condor'."""
        self.db.upsert_transactions([
            make_txn(1, action="Sell to Open", order_id=100,
                     executed_at="2024-01-15T10:00:00"),
            make_txn(2, action="Buy to Open", order_id=100,
                     executed_at="2024-01-15T10:00:00"),
            make_txn(3, action="Sell to Open", order_id=100,
                     executed_at="2024-01-15T10:00:00"),
            make_txn(4, action="Buy to Open", order_id=100,
                     executed_at="2024-01-15T10:00:00"),
        ])

        self.grouper.build_groups("ABC")
        groups = self.db.get_trade_groups("ABC")
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["strategy_type"], "Iron Condor")

    def test_partial_close_stays_open(self):
        """Open 2 contracts, close 1 — group should stay open."""
        self.db.upsert_transactions([
            make_txn(1, action="Sell to Open", sub_type="Sell to Open",
                     quantity=2.0, order_id=100,
                     executed_at="2024-01-15T10:00:00"),
            make_txn(2, action="Buy to Close", sub_type="Buy to Close",
                     quantity=1.0, order_id=101,
                     executed_at="2024-01-20T10:00:00"),
        ])

        self.grouper.build_groups("ABC")
        groups = self.db.get_trade_groups("ABC")
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["status"], "open")

    def test_partial_then_full_close(self):
        """Open 2, close 1, close 1 — should end up closed."""
        self.db.upsert_transactions([
            make_txn(1, action="Sell to Open", quantity=2.0, order_id=100,
                     executed_at="2024-01-15T10:00:00"),
            make_txn(2, action="Buy to Close", quantity=1.0, order_id=101,
                     executed_at="2024-01-20T10:00:00"),
            make_txn(3, action="Buy to Close", quantity=1.0, order_id=102,
                     executed_at="2024-01-25T10:00:00"),
        ])

        self.grouper.build_groups("ABC")
        groups = self.db.get_trade_groups("ABC")
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["status"], "closed")

    def test_roll_creates_linked_groups(self):
        """Roll = close + open in same order. Should create 2 groups linked by parent_group_id."""
        # First, open a position
        self.db.upsert_transactions([
            make_txn(1, action="Sell to Open", sub_type="Sell to Open",
                     order_id=100, executed_at="2024-01-15T10:00:00"),
        ])
        self.grouper.build_groups("ABC")

        # Now roll: close old + open new in same order
        self.db.upsert_transactions([
            make_txn(2, action="Buy to Close", sub_type="Buy to Close",
                     value=-50.0, net_value=-51.0, order_id=200,
                     executed_at="2024-01-25T10:00:00"),
            make_txn(3, action="Sell to Open", sub_type="Sell to Open",
                     value=120.0, net_value=119.0, order_id=200,
                     executed_at="2024-01-25T10:00:00"),
        ])
        self.grouper.build_groups("ABC")

        groups = self.db.get_trade_groups("ABC")
        self.assertEqual(len(groups), 2)

        # Find the new group (has parent_group_id)
        old_group = [g for g in groups if g["parent_group_id"] is None][0]
        new_group = [g for g in groups if g["parent_group_id"] is not None][0]

        self.assertEqual(old_group["status"], "closed")
        self.assertEqual(new_group["status"], "open")
        self.assertEqual(new_group["parent_group_id"], old_group["id"])

        # Verify chain
        chain = self.db.get_roll_chain(new_group["id"])
        self.assertEqual(len(chain), 2)

    def test_expiration(self):
        """Position expires worthless — group should be marked 'expired'."""
        self.db.upsert_transactions([
            make_txn(1, action="Sell to Open", order_id=100,
                     executed_at="2024-01-15T10:00:00"),
            make_txn(2, txn_type="Receive Deliver", sub_type="Expiration",
                     action=None, value=0, net_value=0, order_id=None, quantity=1.0,
                     executed_at="2024-03-15T16:00:00"),
        ])

        self.grouper.build_groups("ABC")
        groups = self.db.get_trade_groups("ABC")
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["status"], "expired")

    def test_assignment(self):
        """Short put gets assigned — group should be marked 'assigned'."""
        self.db.upsert_transactions([
            make_txn(1, action="Sell to Open", order_id=100,
                     executed_at="2024-01-15T10:00:00"),
            make_txn(2, txn_type="Receive Deliver", sub_type="Assignment",
                     action=None, value=0, net_value=0, order_id=None, quantity=1.0,
                     executed_at="2024-02-15T16:00:00"),
        ])

        self.grouper.build_groups("ABC")
        groups = self.db.get_trade_groups("ABC")
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["status"], "assigned")

    def test_multiple_underlyings(self):
        """Trades on different underlyings should create separate groups."""
        self.db.upsert_transactions([
            make_txn(1, underlying="SPY", action="Sell to Open", order_id=100,
                     executed_at="2024-01-15T10:00:00"),
            make_txn(2, underlying="AAPL", action="Sell to Open", order_id=101,
                     executed_at="2024-01-15T10:00:00"),
        ])

        count = self.grouper.build_groups("ABC")
        self.assertEqual(count, 2)

        groups = self.db.get_trade_groups("ABC")
        underlyings = {g["underlying_symbol"] for g in groups}
        self.assertEqual(underlyings, {"SPY", "AAPL"})

    def test_idempotent_grouping(self):
        """Running build_groups twice should not create duplicate groups."""
        self.db.upsert_transactions([
            make_txn(1, action="Sell to Open", order_id=100,
                     executed_at="2024-01-15T10:00:00"),
        ])

        count1 = self.grouper.build_groups("ABC")
        self.assertEqual(count1, 1)

        count2 = self.grouper.build_groups("ABC")
        self.assertEqual(count2, 0)

        groups = self.db.get_trade_groups("ABC")
        self.assertEqual(len(groups), 1)

    def test_group_totals_computed(self):
        """Verify premium collected/paid and fees are computed correctly."""
        self.db.upsert_transactions([
            make_txn(1, action="Sell to Open", value=200.0, net_value=198.0,
                     order_id=100, executed_at="2024-01-15T10:00:00"),
            make_txn(2, action="Buy to Close", value=-80.0, net_value=-81.0,
                     order_id=101, executed_at="2024-01-25T10:00:00"),
        ])

        self.grouper.build_groups("ABC")
        groups = self.db.get_trade_groups("ABC")
        g = groups[0]

        self.assertGreater(g["total_premium_collected"], 0)
        self.assertGreater(g["total_premium_paid"], 0)
        self.assertGreater(g["total_fees"], 0)
        self.assertIsNotNone(g["realized_pl"])


if __name__ == "__main__":
    unittest.main()
