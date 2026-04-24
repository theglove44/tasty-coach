"""Tests for utils.correlation_buckets."""

import unittest

from utils.correlation_buckets import bucket_for, group_by_bucket


class TestCorrelationBuckets(unittest.TestCase):
    def test_bucket_for_known_symbol_returns_bucket(self):
        self.assertEqual(bucket_for("SPY"), "US_EQUITY_INDEX")
        self.assertEqual(bucket_for("AAPL"), "MEGA_TECH")
        self.assertEqual(bucket_for("AMD"), "SEMIS")

    def test_bucket_for_unknown_symbol_returns_self(self):
        self.assertEqual(bucket_for("ZZZZ"), "ZZZZ")
        self.assertEqual(bucket_for("RANDOM123"), "RANDOM123")

    def test_bucket_for_is_case_insensitive(self):
        self.assertEqual(bucket_for("spy"), "US_EQUITY_INDEX")
        self.assertEqual(bucket_for("Aapl"), "MEGA_TECH")

    def test_group_by_bucket_aggregates_correlated_symbols(self):
        data = [("SPY", 10000.0), ("QQQ", 15000.0), ("AAPL", 5000.0)]
        grouped = group_by_bucket(data)
        self.assertIn("US_EQUITY_INDEX", grouped)
        self.assertIn("MEGA_TECH", grouped)
        self.assertEqual(len(grouped["US_EQUITY_INDEX"]), 2)
        self.assertEqual(grouped["US_EQUITY_INDEX"][0], ("SPY", 10000.0))
        self.assertEqual(grouped["US_EQUITY_INDEX"][1], ("QQQ", 15000.0))

    def test_group_by_bucket_preserves_insertion_order(self):
        data = [("QQQ", 10000.0), ("SPY", 5000.0), ("IWM", 8000.0)]
        grouped = group_by_bucket(data)
        bucket_items = grouped["US_EQUITY_INDEX"]
        self.assertEqual([s for s, _ in bucket_items], ["QQQ", "SPY", "IWM"])

    def test_group_by_bucket_empty_input(self):
        self.assertEqual(group_by_bucket([]), {})


if __name__ == "__main__":
    unittest.main()
