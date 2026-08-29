"""Tests for the structure query param threading through scan endpoints."""

from __future__ import annotations

import unittest

import server.app as server_app


class TestCacheKeyIncludes(unittest.TestCase):
    """_bt_key produces distinct keys for distinct watchlist tuples."""

    def test_same_account_different_watchlists_different_key(self):
        k1 = server_app._bt_key("ACCT", ["A", "B"])
        k2 = server_app._bt_key("ACCT", ["A"])
        self.assertNotEqual(k1, k2)

    def test_watchlist_order_irrelevant(self):
        k1 = server_app._bt_key("ACCT", ["A", "B"])
        k2 = server_app._bt_key("ACCT", ["B", "A"])
        self.assertEqual(k1, k2)

    def test_key_to_list_sorted(self):
        k = server_app._bt_key("ACCT", ["B", "A"])
        self.assertEqual(server_app._key_to_list(k), ["A", "B"])


class TestSettingsGroupsIncludeNewKeys(unittest.TestCase):
    """The dashboard settings editor must surface bt_per_trade_risk_dollars."""

    def test_per_trade_risk_dollars_in_sizing_group(self):
        sizing = next(g for g in server_app.SETTINGS_GROUPS if g["id"] == "sizing")
        self.assertIn("bt_per_trade_risk_dollars", sizing["keys"])

    def test_no_csp_group(self):
        groups_by_id = {g["id"]: g for g in server_app.SETTINGS_GROUPS}
        self.assertNotIn("csp", groups_by_id)


if __name__ == "__main__":
    unittest.main()
