"""Tests for server.snapshot.assemble_dashboard_data and helpers."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from server.snapshot import _serialize_position, assemble_dashboard_data


def _mock_pos(*, symbol, instrument_type, underlying_symbol=None,
              quantity=1, direction="Short", avg_open=1.50):
    p = MagicMock()
    p.symbol = symbol
    p.instrument_type = MagicMock()
    p.instrument_type.value = instrument_type
    p.underlying_symbol = underlying_symbol
    p.quantity = quantity
    p.quantity_direction = MagicMock()
    p.quantity_direction.value = direction
    p.average_open_price = avg_open
    return p


class TestSerializePosition(unittest.TestCase):
    """Underlying fallback should never leak the full OCC string."""

    def test_option_with_underlying_symbol_set(self):
        p = _mock_pos(symbol="AAPL  260619P00150000", instrument_type="Equity Option",
                      underlying_symbol="AAPL")
        out = _serialize_position(p)
        self.assertEqual(out["underlying"], "AAPL")
        self.assertEqual(out["strike"], 150.0)
        self.assertEqual(out["option_type"], "PUT")
        self.assertEqual(out["expiration"], "2026-06-19")
        self.assertEqual(out["sector"], "tech_hardware")

    def test_option_without_underlying_symbol_falls_back_to_parsed_root(self):
        # Regression: prior behaviour would set underlying = full OCC string,
        # which over-counts unique underlyings and breaks sector lookups.
        p = _mock_pos(symbol="AAPL  260619P00150000", instrument_type="Equity Option",
                      underlying_symbol=None)
        out = _serialize_position(p)
        self.assertEqual(out["underlying"], "AAPL")
        self.assertEqual(out["sector"], "tech_hardware")

    def test_equity_position_underlying_is_symbol(self):
        p = _mock_pos(symbol="AAPL", instrument_type="Equity",
                      underlying_symbol=None, quantity=100, avg_open=180.5)
        out = _serialize_position(p)
        self.assertEqual(out["underlying"], "AAPL")
        self.assertIsNone(out["strike"])
        self.assertIsNone(out["expiration"])
        self.assertEqual(out["sector"], "tech_hardware")

    def test_unparseable_symbol_falls_back_to_symbol(self):
        p = _mock_pos(symbol="WEIRD SYMBOL", instrument_type="Other",
                      underlying_symbol=None)
        out = _serialize_position(p)
        # No OCC parse, no underlying_symbol → fall back to the symbol itself
        self.assertEqual(out["underlying"], "WEIRD SYMBOL")
        self.assertIsNone(out["sector"])


class TestAssembleDashboardData(unittest.TestCase):
    """Shape of the dashboard payload + over_leveraged signal."""

    def _run(self, report, positions):
        ctx = MagicMock()
        ctx.session = MagicMock()
        ctx.account_number = "ACCT"

        with patch("server.snapshot.RiskManager") as mock_rm, \
             patch("server.snapshot.PortfolioAgent") as mock_pa:
            mock_rm.return_value.calculate_portfolio_risk = AsyncMock(return_value=report)
            pa_inst = MagicMock()
            pa_inst.get_positions = AsyncMock(return_value=positions)
            mock_pa.return_value.init = AsyncMock(return_value=pa_inst)
            return asyncio.run(assemble_dashboard_data(ctx))

    def test_payload_has_expected_top_level_keys(self):
        out = self._run({"nlv": 20000.0, "bp_usage_pct": 25.0}, [])
        for key in ("account_number", "kpis", "positions", "alerts", "warnings", "generated_at"):
            self.assertIn(key, out)

    def test_over_leveraged_flag_set_when_bp_negative(self):
        # PM accounts with EBP > NLV yield negative bp_usage_pct;
        # the payload must surface this rather than abs() over it.
        out = self._run({"nlv": 20000.0, "bp_usage_pct": -20.0}, [])
        self.assertTrue(out["kpis"]["over_leveraged"])
        self.assertEqual(out["kpis"]["bp_usage_pct"], -20.0)

    def test_over_leveraged_flag_unset_when_bp_positive(self):
        out = self._run({"nlv": 20000.0, "bp_usage_pct": 30.0}, [])
        self.assertFalse(out["kpis"]["over_leveraged"])
        self.assertEqual(out["kpis"]["bp_usage_pct"], 30.0)

    def test_underlying_count_dedups_options_under_root_symbol(self):
        # Two AAPL option positions plus one MSFT option = 2 underlyings,
        # not 3. Regression for the OCC-string fallback bug.
        positions = [
            _mock_pos(symbol="AAPL  260619P00150000", instrument_type="Equity Option",
                      underlying_symbol=None),
            _mock_pos(symbol="AAPL  260619P00145000", instrument_type="Equity Option",
                      underlying_symbol=None),
            _mock_pos(symbol="MSFT  260619P00400000", instrument_type="Equity Option",
                      underlying_symbol=None),
        ]
        out = self._run({"nlv": 20000.0, "bp_usage_pct": 10.0}, positions)
        self.assertEqual(out["kpis"]["position_count"], 3)
        self.assertEqual(out["kpis"]["underlying_count"], 2)


if __name__ == "__main__":
    unittest.main()
