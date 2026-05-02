"""Tests for the structure query param threading through scan endpoints."""

from __future__ import annotations

import unittest

import server.app as server_app


class TestNormalizeStructure(unittest.TestCase):
    def test_csp_alias_maps_to_canonical(self):
        self.assertEqual(server_app._normalize_structure("csp"), "CASH_SECURED_PUT")
        self.assertEqual(server_app._normalize_structure("CSP"), "CASH_SECURED_PUT")
        self.assertEqual(server_app._normalize_structure(" csp "), "CASH_SECURED_PUT")

    def test_canonical_passes_through(self):
        self.assertEqual(
            server_app._normalize_structure("CASH_SECURED_PUT"),
            "CASH_SECURED_PUT",
        )
        self.assertEqual(
            server_app._normalize_structure("cash_secured_put"),
            "CASH_SECURED_PUT",
        )

    def test_none_and_empty_pass_through_as_none(self):
        self.assertIsNone(server_app._normalize_structure(None))
        self.assertIsNone(server_app._normalize_structure(""))
        self.assertIsNone(server_app._normalize_structure("   "))

    def test_unknown_alias_passes_through_unchanged(self):
        # Unknown structure names go through verbatim — run_best_trades will
        # reject them downstream rather than the alias mapping silently
        # converting to None.
        self.assertEqual(server_app._normalize_structure("unknown"), "unknown")


class TestCacheKeyIncludesStructure(unittest.TestCase):
    """_bt_key produces distinct keys for distinct (watchlists, structure) tuples."""

    def test_same_watchlists_different_structure_different_key(self):
        k_all = server_app._bt_key("ACCT", ["A", "B"], None)
        k_csp = server_app._bt_key("ACCT", ["A", "B"], "csp")
        self.assertNotEqual(k_all, k_csp)
        self.assertEqual(k_all[2], None)
        self.assertEqual(k_csp[2], "CASH_SECURED_PUT")

    def test_watchlist_order_irrelevant(self):
        k1 = server_app._bt_key("ACCT", ["A", "B"], "csp")
        k2 = server_app._bt_key("ACCT", ["B", "A"], "csp")
        self.assertEqual(k1, k2)

    def test_structure_alias_normalized_in_key(self):
        # "csp" and "CASH_SECURED_PUT" must produce the same key so the cache
        # is hit regardless of caller spelling.
        k1 = server_app._bt_key("ACCT", ["A"], "csp")
        k2 = server_app._bt_key("ACCT", ["A"], "CASH_SECURED_PUT")
        self.assertEqual(k1, k2)

    def test_key_structure_helper_returns_third_element(self):
        k = server_app._bt_key("ACCT", ["A"], "csp")
        self.assertEqual(server_app._key_structure(k), "CASH_SECURED_PUT")
        k_none = server_app._bt_key("ACCT", ["A"], None)
        self.assertIsNone(server_app._key_structure(k_none))

    def test_key_to_list_unaffected_by_structure(self):
        k = server_app._bt_key("ACCT", ["B", "A"], "csp")
        self.assertEqual(server_app._key_to_list(k), ["A", "B"])


class TestSettingsGroupsIncludeNewKeys(unittest.TestCase):
    """The dashboard settings editor must surface bt_per_trade_risk_dollars + bt_csp_*."""

    def test_per_trade_risk_dollars_in_sizing_group(self):
        sizing = next(g for g in server_app.SETTINGS_GROUPS if g["id"] == "sizing")
        self.assertIn("bt_per_trade_risk_dollars", sizing["keys"])

    def test_csp_group_present_with_all_keys(self):
        groups_by_id = {g["id"]: g for g in server_app.SETTINGS_GROUPS}
        self.assertIn("csp", groups_by_id)
        csp_keys = set(groups_by_id["csp"]["keys"])
        expected = {
            "bt_csp_delta_min",
            "bt_csp_delta_max",
            "bt_csp_min_otm_pct",
            "bt_csp_min_annualized_return",
            "bt_csp_skew_warn_threshold",
            "bt_csp_max_per_symbol",
            "bt_csp_max_pct_nlv_per_trade",
        }
        self.assertEqual(csp_keys & expected, expected)


if __name__ == "__main__":
    unittest.main()
