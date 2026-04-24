"""Tests for concentration analysis in RiskManager (Phase C Slice 1)."""

import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from agents.manager import RiskManager


class TestConcentration(unittest.IsolatedAsyncioTestCase):
    def _mk_pos(self, symbol, underlying, market_value, instrument_type="Equity"):
        p = MagicMock()
        p.symbol = symbol
        p.underlying_symbol = underlying
        p.instrument_type = MagicMock(value=instrument_type)
        p.quantity = Decimal(1)
        p.multiplier = Decimal(1)
        p._mark = float(market_value)
        p.quantity_direction = "Long"
        return p

    async def _run(self, positions, nlv, threshold=None, toggles=None):
        mock_session = MagicMock()
        mock_account = MagicMock()
        mock_balances = MagicMock()
        mock_balances.net_liquidating_value = Decimal(nlv)
        mock_balances.equity_buying_power = Decimal(nlv // 2) if nlv > 0 else Decimal(0)
        mock_balances.day_trade_excess = Decimal(0)
        mock_balances.day_trading_buying_power = Decimal(0)
        mock_balances.cash_balance = Decimal(0)
        mock_account.get_balances.return_value = mock_balances
        mock_account.get_positions.return_value = positions

        with patch("tastytrade.Account.get", return_value=[mock_account]):
            risk = RiskManager(mock_session)

            async def _fake_marks(ps):
                return {p.symbol: float(getattr(p, "_mark", 0.0)) for p in ps}

            async def _no_streamer(ps):
                return {}

            async def _no_greeks(syms):
                return {}

            risk._fetch_marks = _fake_marks
            risk._resolve_streamer_symbols = _no_streamer
            risk._fetch_greeks = _no_greeks

            import agents.manager as mgr

            def _mock_get(key, default=None):
                if key == "concentration_pct_nlv_warn":
                    return threshold if threshold is not None else 0.15
                if key == "alert_toggles":
                    return toggles if toggles is not None else {
                        "position_size": True, "bp": True, "theta": True,
                        "market": True, "concentration": True, "assignment": True,
                    }
                if key == "position_pct_nlv_warn":
                    return 0.99
                if key == "bp_usage_warn":
                    return 0.99
                if key == "theta_target":
                    return None
                return default

            with patch.object(mgr.settings, "get", side_effect=_mock_get):
                return await risk.calculate_portfolio_risk()

    async def test_concentration_empty_portfolio_returns_empty_lists(self):
        report = await self._run([], nlv=100000)
        self.assertEqual(report["concentration"], [])
        self.assertEqual(report["correlation_concentration"], [])

    async def test_concentration_single_underweight_underlying_not_flagged(self):
        pos = self._mk_pos("AAPL", "AAPL", 10000.0)
        report = await self._run([pos], nlv=100000, threshold=0.15)
        self.assertEqual(len(report["concentration"]), 1)
        row = report["concentration"][0]
        self.assertEqual(row["underlying"], "AAPL")
        self.assertAlmostEqual(row["pct_nlv"], 0.1)
        self.assertFalse(row["flagged"])
        conc = [a for a in report["alerts"] if a.category == "concentration"]
        self.assertEqual(conc, [])

    async def test_concentration_flags_single_overweight_underlying(self):
        pos = self._mk_pos("SPY", "SPY", 20000.0)
        report = await self._run([pos], nlv=100000, threshold=0.15)
        row = report["concentration"][0]
        self.assertEqual(row["underlying"], "SPY")
        self.assertTrue(row["flagged"])
        conc = [a for a in report["alerts"] if a.category == "concentration"]
        self.assertEqual(len(conc), 1)
        self.assertIn("SPY", conc[0].message)
        self.assertIn("20.0%", conc[0].message)

    async def test_concentration_aggregates_duplicate_underlying(self):
        pos1 = self._mk_pos("AAPL  250321C00150000", "AAPL", 5000.0, instrument_type="Equity Option")
        pos2 = self._mk_pos("AAPL  250421C00155000", "AAPL", 8000.0, instrument_type="Equity Option")
        report = await self._run([pos1, pos2], nlv=100000, threshold=0.15)
        self.assertEqual(len(report["concentration"]), 1)
        row = report["concentration"][0]
        self.assertEqual(row["underlying"], "AAPL")
        self.assertAlmostEqual(row["value"], 13000.0)
        self.assertAlmostEqual(row["pct_nlv"], 0.13)
        self.assertFalse(row["flagged"])

    async def test_concentration_correlation_bucket_aggregation_flagged(self):
        pos1 = self._mk_pos("SPY", "SPY", 10000.0)
        pos2 = self._mk_pos("QQQ", "QQQ", 10000.0)
        report = await self._run([pos1, pos2], nlv=100000, threshold=0.15)
        for row in report["concentration"]:
            self.assertFalse(row["flagged"])
        self.assertEqual(len(report["correlation_concentration"]), 1)
        bucket = report["correlation_concentration"][0]
        self.assertEqual(bucket["bucket"], "US_EQUITY_INDEX")
        self.assertIn("SPY", bucket["symbols"])
        self.assertIn("QQQ", bucket["symbols"])
        self.assertAlmostEqual(bucket["pct_nlv"], 0.2)
        self.assertTrue(bucket["flagged"])
        conc = [a for a in report["alerts"] if a.category == "concentration"]
        self.assertEqual(len(conc), 1)
        self.assertIn("US_EQUITY_INDEX", conc[0].message)

    async def test_concentration_singleton_bucket_not_included_in_by_bucket(self):
        pos = self._mk_pos("ZZZZ", "ZZZZ", 50000.0)
        report = await self._run([pos], nlv=100000, threshold=0.15)
        self.assertEqual(report["correlation_concentration"], [])
        self.assertEqual(len(report["concentration"]), 1)

    async def test_concentration_handles_zero_nlv(self):
        pos = self._mk_pos("SPY", "SPY", 1000.0)
        report = await self._run([pos], nlv=0, threshold=0.15)
        self.assertEqual(len(report["concentration"]), 1)
        self.assertEqual(report["concentration"][0]["pct_nlv"], 0.0)
        self.assertFalse(report["concentration"][0]["flagged"])
        conc = [a for a in report["alerts"] if a.category == "concentration"]
        self.assertEqual(conc, [])

    async def test_concentration_sort_order_desc_by_pct(self):
        pos1 = self._mk_pos("SPY", "SPY", 5000.0)
        pos2 = self._mk_pos("AAPL", "AAPL", 20000.0)
        pos3 = self._mk_pos("AMD", "AMD", 10000.0)
        report = await self._run([pos1, pos2, pos3], nlv=100000, threshold=0.15)
        order = [row["underlying"] for row in report["concentration"]]
        self.assertEqual(order, ["AAPL", "AMD", "SPY"])

    async def test_concentration_respects_alert_toggle_off(self):
        pos = self._mk_pos("SPY", "SPY", 20000.0)
        toggles = {
            "concentration": False, "position_size": True, "bp": True,
            "theta": True, "market": True, "assignment": True,
        }
        report = await self._run([pos], nlv=100000, threshold=0.15, toggles=toggles)
        self.assertTrue(report["concentration"][0]["flagged"])
        conc = [a for a in report["alerts"] if a.category == "concentration"]
        self.assertEqual(conc, [])

    async def test_concentration_values_are_json_safe_floats(self):
        pos1 = self._mk_pos("SPY", "SPY", 10000.0)
        pos2 = self._mk_pos("QQQ", "QQQ", 10000.0)
        report = await self._run([pos1, pos2], nlv=100000, threshold=0.15)

        def _check(obj, path=""):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    _check(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    _check(item, f"{path}[{i}]")
            else:
                self.assertIsInstance(
                    obj, (str, int, float, bool, type(None)),
                    f"Non-JSON-safe type at {path}: {type(obj).__name__}",
                )

        _check(report["concentration"])
        _check(report["correlation_concentration"])

    async def test_existing_risk_keys_unchanged(self):
        pos = self._mk_pos("SPY", "SPY", 10000.0)
        report = await self._run([pos], nlv=100000)
        original_keys = {
            "nlv", "bp_usage_pct", "bp_usage_status",
            "day_trade_excess", "day_trading_buying_power", "cash_balance",
            "trade_size_warnings", "session_warnings",
            "portfolio_delta", "portfolio_theta", "theta_status", "alerts",
        }
        for key in original_keys:
            self.assertIn(key, report, f"Missing original key: {key}")
        self.assertIsInstance(report["alerts"], list)
        self.assertIsInstance(report["trade_size_warnings"], list)
        self.assertIsInstance(report["session_warnings"], list)


if __name__ == "__main__":
    unittest.main()
