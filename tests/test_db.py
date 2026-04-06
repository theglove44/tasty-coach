"""Tests for the SQLite database layer."""

import unittest
import sqlite3
from pathlib import Path
from utils.db import TradeDB


class TestTradeDB(unittest.TestCase):
    def setUp(self):
        """Create an in-memory database for each test."""
        self.db = TradeDB(db_path=Path(":memory:"))

    def tearDown(self):
        self.db.close()

    def test_migration_creates_tables(self):
        tables = self.db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [t["name"] for t in tables]
        self.assertIn("transactions", table_names)
        self.assertIn("orders", table_names)
        self.assertIn("trade_groups", table_names)
        self.assertIn("trade_group_transactions", table_names)
        self.assertIn("sync_state", table_names)

    def test_migration_is_idempotent(self):
        # Run migrate again — should not raise
        self.db._migrate()

    def test_upsert_transactions(self):
        txns = [
            {
                "id": 1,
                "account_number": "ABC",
                "transaction_type": "Trade",
                "transaction_sub_type": "Sell to Open",
                "description": "Sold option",
                "executed_at": "2024-01-15T10:00:00",
                "transaction_date": "2024-01-15",
                "value": 150.0,
                "net_value": 148.5,
                "is_estimated_fee": False,
                "symbol": "SPY 240315P490",
                "instrument_type": "Equity Option",
                "underlying_symbol": "SPY",
                "action": "Sell to Open",
                "quantity": 1.0,
                "price": 1.50,
                "regulatory_fees": 0.05,
                "clearing_fees": 0.10,
                "commission": 1.00,
                "order_id": 100,
            }
        ]
        count = self.db.upsert_transactions(txns)
        self.assertEqual(count, 1)

        # Duplicate insert should be ignored
        count2 = self.db.upsert_transactions(txns)
        # Total rows should still be 1
        row_count = self.db.conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        self.assertEqual(row_count, 1)

    def test_upsert_orders(self):
        orders = [
            {
                "id": 200,
                "account_number": "ABC",
                "time_in_force": "Day",
                "order_type": "Limit",
                "underlying_symbol": "SPY",
                "underlying_instrument_type": "Equity",
                "status": "Filled",
                "size": 1.0,
                "price": 1.50,
                "value": 150.0,
                "received_at": "2024-01-15T10:00:00",
                "terminal_at": "2024-01-15T10:00:01",
                "cancelled_at": None,
                "replacing_order_id": None,
                "replaces_order_id": None,
                "legs": [],
            }
        ]
        count = self.db.upsert_orders(orders)
        self.assertEqual(count, 1)

    def test_sync_state(self):
        state = self.db.get_sync_state("ABC")
        self.assertIsNone(state["last_transaction_id"])

        self.db.update_sync_state("ABC", last_transaction_id=500, last_order_id=200)
        state = self.db.get_sync_state("ABC")
        self.assertEqual(state["last_transaction_id"], 500)
        self.assertEqual(state["last_order_id"], 200)

        # Update only transaction id
        self.db.update_sync_state("ABC", last_transaction_id=600)
        state = self.db.get_sync_state("ABC")
        self.assertEqual(state["last_transaction_id"], 600)
        self.assertEqual(state["last_order_id"], 200)  # unchanged

    def test_create_and_query_trade_groups(self):
        gid = self.db.create_trade_group(
            account_number="ABC",
            underlying_symbol="SPY",
            strategy_type="Vertical",
            opened_at="2024-01-15T10:00:00",
        )
        self.assertIsNotNone(gid)

        groups = self.db.get_trade_groups("ABC")
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["underlying_symbol"], "SPY")
        self.assertEqual(groups[0]["status"], "open")

    def test_link_transaction_to_group(self):
        # Insert a transaction first
        self.db.upsert_transactions([{
            "id": 1, "account_number": "ABC", "transaction_type": "Trade",
            "transaction_sub_type": "Sell to Open", "description": "",
            "executed_at": "2024-01-15T10:00:00", "transaction_date": "2024-01-15",
            "value": 100.0, "net_value": 99.0, "is_estimated_fee": False,
            "underlying_symbol": "SPY", "action": "Sell to Open", "quantity": 1.0,
            "order_id": 100,
        }])

        gid = self.db.create_trade_group("ABC", "SPY", opened_at="2024-01-15T10:00:00")
        self.db.link_transaction(gid, 1, "open")

        txns = self.db.get_group_transactions(gid)
        self.assertEqual(len(txns), 1)
        self.assertEqual(txns[0]["role"], "open")

    def test_get_open_group_for_underlying(self):
        self.db.create_trade_group("ABC", "SPY", opened_at="2024-01-15T10:00:00")
        self.db.create_trade_group("ABC", "AAPL", opened_at="2024-01-15T10:00:00")

        group = self.db.get_open_group_for_underlying("ABC", "SPY")
        self.assertIsNotNone(group)
        self.assertEqual(group["underlying_symbol"], "SPY")

        group = self.db.get_open_group_for_underlying("ABC", "TSLA")
        self.assertIsNone(group)

    def test_roll_chain(self):
        g1 = self.db.create_trade_group("ABC", "SPY", opened_at="2024-01-01")
        self.db.update_trade_group(g1, status="closed", closed_at="2024-01-15")

        g2 = self.db.create_trade_group("ABC", "SPY", opened_at="2024-01-15", parent_group_id=g1)
        self.db.update_trade_group(g2, status="closed", closed_at="2024-02-01")

        g3 = self.db.create_trade_group("ABC", "SPY", opened_at="2024-02-01", parent_group_id=g2)

        chain = self.db.get_roll_chain(g3)
        self.assertEqual(len(chain), 3)
        self.assertEqual(chain[0]["id"], g1)
        self.assertEqual(chain[2]["id"], g3)

    def test_get_group_net_quantity(self):
        self.db.upsert_transactions([
            {
                "id": 1, "account_number": "ABC", "transaction_type": "Trade",
                "transaction_sub_type": "Sell to Open", "description": "",
                "executed_at": "2024-01-15T10:00:00", "transaction_date": "2024-01-15",
                "value": 100.0, "net_value": 99.0, "is_estimated_fee": False,
                "action": "Sell to Open", "quantity": 2.0, "order_id": 100,
                "underlying_symbol": "SPY",
            },
            {
                "id": 2, "account_number": "ABC", "transaction_type": "Trade",
                "transaction_sub_type": "Buy to Close", "description": "",
                "executed_at": "2024-01-20T10:00:00", "transaction_date": "2024-01-20",
                "value": -50.0, "net_value": -51.0, "is_estimated_fee": False,
                "action": "Buy to Close", "quantity": 1.0, "order_id": 101,
                "underlying_symbol": "SPY",
            },
        ])

        gid = self.db.create_trade_group("ABC", "SPY", opened_at="2024-01-15")
        self.db.link_transaction(gid, 1, "open")
        self.db.link_transaction(gid, 2, "close")

        net = self.db.get_group_net_quantity(gid)
        self.assertAlmostEqual(net, 1.0)  # 2 opened - 1 closed = 1 remaining


if __name__ == "__main__":
    unittest.main()
