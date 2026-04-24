"""Tests for the unified account dashboard."""

import types
import unittest
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from rich.console import Console

from utils.dashboard_ui import (
    DashboardData,
    EM_DASH,
    fmt_money,
    fmt_pct,
    fmt_num,
    fmt_signed_money,
    _is_nan,
    _dte_from_occ,
    render_kpi_panel,
    render_performance_panel,
    render_positions_panel,
    render_alerts_panel,
    render_events_panel,
    render_dashboard,
)


def _render_to_str(renderable) -> str:
    """Helper to render a Rich object to string for testing."""
    c = Console(record=True, width=120, force_terminal=False)
    c.print(renderable)
    return c.export_text()


class TestFormatters(unittest.TestCase):
    """Test formatting helper functions."""

    def test_fmt_money_positive(self):
        result = fmt_money(1234.56)
        self.assertEqual(result, "$1,234.56")

    def test_fmt_money_negative(self):
        result = fmt_money(-50.00)
        self.assertEqual(result, "-$50.00")

    def test_fmt_money_none_returns_em_dash(self):
        result = fmt_money(None)
        self.assertEqual(result, EM_DASH)

    def test_fmt_money_nan_returns_em_dash(self):
        result = fmt_money(float("nan"))
        self.assertEqual(result, EM_DASH)

    def test_fmt_money_sign_prefix_positive(self):
        result = fmt_money(100.00, sign=True)
        self.assertEqual(result, "+$100.00")

    def test_fmt_pct_basic(self):
        result = fmt_pct(12.3)
        self.assertEqual(result, "12.3%")

    def test_fmt_pct_none(self):
        result = fmt_pct(None)
        self.assertEqual(result, EM_DASH)

    def test_fmt_num_none(self):
        result = fmt_num(None)
        self.assertEqual(result, EM_DASH)

    def test_fmt_signed_money_positive_has_plus(self):
        result = fmt_signed_money(50.00)
        self.assertTrue(result.startswith("+"))


class TestDTEParser(unittest.TestCase):
    """Test OCC symbol parsing and DTE calculation."""

    def test_dte_from_occ_valid_option(self):
        # Set a fixed today so test is deterministic
        # Expiration 10 days from 2026-04-24 is 2026-05-04
        fixed_today = date(2026, 4, 24)
        symbol = "TEST  260504C00100000"
        dte = _dte_from_occ(symbol, today=fixed_today)
        self.assertEqual(dte, 10)

    def test_dte_from_occ_equity_symbol_returns_none(self):
        result = _dte_from_occ("AAPL")
        self.assertIsNone(result)

    def test_dte_from_occ_malformed_returns_none(self):
        result = _dte_from_occ("BADFORMAT")
        self.assertIsNone(result)

    def test_dte_from_occ_slash_root_symbol(self):
        fixed_today = date(2026, 4, 24)
        # BRK/B option expiring 2026-05-04 (10 days out)
        dte = _dte_from_occ("BRK/B 260504C00100000", today=fixed_today)
        self.assertEqual(dte, 10)

    def test_render_performance_panel_shows_fees(self):
        data = DashboardData(performance={"total_fees": 42.5})
        rendered = _render_to_str(render_performance_panel(data))
        self.assertIn("$42.50", rendered)

    def test_render_positions_panel_shows_con_badge_for_correlation_bucket(self):
        pos = types.SimpleNamespace(
            symbol="SPY", quantity=1, quantity_direction="Long",
            average_open_price=400, close_price=405, market_value=405,
            underlying_symbol="SPY", instrument_type="Equity",
        )
        data = DashboardData(
            positions=[pos],
            nlv=Decimal("100000"),
            risk={
                "concentration": [],
                "correlation_concentration": [
                    {"bucket": "US_EQUITY_INDEX", "symbols": ["SPY", "QQQ"],
                     "value": 20000.0, "pct_nlv": 0.2, "flagged": True},
                ],
            },
        )
        rendered = _render_to_str(render_positions_panel(data))
        self.assertIn("CON", rendered)

    def test_render_positions_panel_detects_enum_instrument_type(self):
        from enum import Enum

        class _FakeInstr(Enum):
            EQUITY_OPTION = "Equity Option"

        fixed_today = date(2026, 4, 24)
        exp_date = fixed_today + timedelta(days=5)
        yymmdd = f"{exp_date.year % 100:02d}{exp_date.month:02d}{exp_date.day:02d}"
        symbol = f"SPY  {yymmdd}C00500000"
        pos = types.SimpleNamespace(
            symbol=symbol, quantity=1, quantity_direction="Short",
            average_open_price=1.50, close_price=1.25, market_value=-125,
            underlying_symbol="SPY", instrument_type=_FakeInstr.EQUITY_OPTION,
        )
        data = DashboardData(positions=[pos], nlv=Decimal("100000"))
        rendered = _render_to_str(render_positions_panel(data))
        self.assertIn("⚠", rendered)


class TestRenderPanels(unittest.TestCase):
    """Test panel rendering functions."""

    def test_render_kpi_panel_returns_panel(self):
        data = DashboardData(
            risk={"nlv": 50000, "bp_usage_pct": 25.0, "bp_usage_status": "OK"}
        )
        panel = render_kpi_panel(data)
        self.assertIsNotNone(panel)
        self.assertEqual(panel.title, "Account")

    def test_render_kpi_panel_shows_nlv(self):
        data = DashboardData(risk={"nlv": 50000})
        rendered = _render_to_str(render_kpi_panel(data))
        self.assertIn("$50,000.00", rendered)

    def test_render_kpi_panel_empty_data_has_em_dash(self):
        data = DashboardData()
        rendered = _render_to_str(render_kpi_panel(data))
        self.assertIn(EM_DASH, rendered)

    def test_render_kpi_panel_risk_error_falls_back_to_account_status(self):
        data = DashboardData(
            account_status={"net_liquidating_value": 75000}
        )
        rendered = _render_to_str(render_kpi_panel(data))
        self.assertIn("$75,000.00", rendered)

    def test_render_performance_panel_returns_panel(self):
        data = DashboardData(
            performance={"total_trades": 10, "win_rate": 60.0}
        )
        panel = render_performance_panel(data)
        self.assertIsNotNone(panel)
        self.assertEqual(panel.title, "Performance")

    def test_render_performance_panel_shows_win_rate(self):
        data = DashboardData(
            performance={"total_trades": 10, "win_rate": 65.0}
        )
        rendered = _render_to_str(render_performance_panel(data))
        self.assertIn("65.0%", rendered)

    def test_render_performance_panel_empty_shows_em_dash(self):
        data = DashboardData(performance={})
        rendered = _render_to_str(render_performance_panel(data))
        self.assertIn(EM_DASH, rendered)

    def test_render_performance_panel_with_error_key_shows_em_dash(self):
        data = DashboardData(errors={"performance": "test error"})
        rendered = _render_to_str(render_performance_panel(data))
        self.assertIn(EM_DASH, rendered)

    def test_render_positions_panel_empty_list(self):
        data = DashboardData(positions=[])
        rendered = _render_to_str(render_positions_panel(data))
        self.assertIn(EM_DASH, rendered)

    def test_render_positions_panel_sorts_by_abs_market_value_desc(self):
        # Create synthetic positions
        pos1 = types.SimpleNamespace(
            symbol="SPY", quantity=1, quantity_direction="Long",
            average_open_price=400, close_price=405, market_value=405,
            underlying_symbol="SPY", instrument_type="Equity"
        )
        pos2 = types.SimpleNamespace(
            symbol="QQQ", quantity=2, quantity_direction="Long",
            average_open_price=300, close_price=305, market_value=610,
            underlying_symbol="QQQ", instrument_type="Equity"
        )
        pos3 = types.SimpleNamespace(
            symbol="IWM", quantity=3, quantity_direction="Short",
            average_open_price=200, close_price=198, market_value=-594,
            underlying_symbol="IWM", instrument_type="Equity"
        )

        data = DashboardData(positions=[pos1, pos2, pos3], nlv=Decimal("100000"))
        rendered = _render_to_str(render_positions_panel(data))
        # QQQ has largest abs market value (610), should appear first in table
        qidx = rendered.find("QQQ")
        siidx = rendered.find("SPY")
        iidx = rendered.find("IWM")
        self.assertGreater(siidx, qidx)  # QQQ before SPY
        self.assertGreater(iidx, qidx)   # QQQ before IWM

    def test_render_positions_panel_truncates_to_five(self):
        positions = []
        for i in range(7):
            positions.append(types.SimpleNamespace(
                symbol=f"SYM{i}", quantity=1, quantity_direction="Long",
                average_open_price=100, close_price=105, market_value=1000 + i * 100,
                underlying_symbol=f"SYM{i}", instrument_type="Equity"
            ))

        data = DashboardData(positions=positions)
        rendered = _render_to_str(render_positions_panel(data))
        # Should only show first 5 sorted by abs market value
        self.assertIn("SYM6", rendered)
        self.assertNotIn("SYM0", rendered)

    def test_render_positions_panel_nlv_flag_when_concentrated(self):
        pos = types.SimpleNamespace(
            symbol="BIG", quantity=1, quantity_direction="Long",
            average_open_price=50000, close_price=51000, market_value=51000,
            underlying_symbol="BIG", instrument_type="Equity"
        )
        data = DashboardData(
            positions=[pos],
            nlv=Decimal("100000"),
            position_pct_nlv_warn=0.15,  # 15% threshold
        )
        rendered = _render_to_str(render_positions_panel(data))
        # 51000 / 100000 = 51% > 15%, should have 🔴 flag
        self.assertIn("🔴", rendered)

    def test_render_positions_panel_dte_flag_on_short_option(self):
        fixed_today = date(2026, 4, 24)
        # Option expiring in 5 days (below 7-day threshold)
        exp_date = fixed_today + timedelta(days=5)
        yymmdd = f"{exp_date.year % 100:02d}{exp_date.month:02d}{exp_date.day:02d}"
        symbol = f"SPY  {yymmdd}C00500000"

        pos = types.SimpleNamespace(
            symbol=symbol, quantity=-1, quantity_direction="Short",
            average_open_price=1.50, close_price=1.25, market_value=-125,
            underlying_symbol="SPY", instrument_type="Option"
        )
        data = DashboardData(positions=[pos], nlv=Decimal("100000"))
        rendered = _render_to_str(render_positions_panel(data))
        # Should have ⚠ flag for short option within DTE threshold
        self.assertIn("⚠", rendered)

    def test_render_positions_panel_no_nlv_skips_concentration_flag(self):
        pos = types.SimpleNamespace(
            symbol="BIG", quantity=1, quantity_direction="Long",
            average_open_price=50000, close_price=51000, market_value=51000,
            underlying_symbol="BIG", instrument_type="Equity"
        )
        data = DashboardData(positions=[pos], nlv=None)
        rendered = _render_to_str(render_positions_panel(data))
        # No NLV means can't compute concentration, should not have 🔴
        self.assertNotIn("🔴", rendered)

    def test_render_alerts_panel_no_alerts_shows_message(self):
        data = DashboardData(risk={})
        rendered = _render_to_str(render_alerts_panel(data))
        self.assertIn("No active alerts", rendered)

    def test_render_alerts_panel_renders_alert_message(self):
        alert = {"severity": "warn", "category": "test", "message": "Something bad"}
        data = DashboardData(risk={"alerts": [alert]})
        rendered = _render_to_str(render_alerts_panel(data))
        self.assertIn("Something bad", rendered)

    def test_render_alerts_panel_sorts_critical_first(self):
        alerts = [
            {"severity": "info", "category": "cat1", "message": "Info msg"},
            {"severity": "critical", "category": "cat2", "message": "Critical msg"},
            {"severity": "warn", "category": "cat3", "message": "Warn msg"},
        ]
        data = DashboardData(risk={"alerts": alerts})
        rendered = _render_to_str(render_alerts_panel(data))
        c_idx = rendered.find("Critical msg")
        w_idx = rendered.find("Warn msg")
        i_idx = rendered.find("Info msg")
        self.assertLess(c_idx, w_idx)
        self.assertLess(w_idx, i_idx)

    def test_render_alerts_panel_includes_session_warnings(self):
        data = DashboardData(
            risk={"session_warnings": ["Market closed"]}
        )
        rendered = _render_to_str(render_alerts_panel(data))
        self.assertIn("Market closed", rendered)

    def test_render_alerts_panel_truncation_title(self):
        alerts = [{"severity": "info", "category": f"cat{i}", "message": f"msg{i}"}
                  for i in range(10)]
        data = DashboardData(risk={"alerts": alerts})
        rendered = _render_to_str(render_alerts_panel(data))
        self.assertIn("showing 8 of 10", rendered)

    def test_render_alerts_panel_error_shows_em_dash(self):
        data = DashboardData(
            risk={},
            errors={"risk": "Failed to fetch"}
        )
        rendered = _render_to_str(render_alerts_panel(data))
        self.assertIn(EM_DASH, rendered)

    def test_render_events_panel_empty(self):
        data = DashboardData(recent_events=[])
        rendered = _render_to_str(render_events_panel(data))
        self.assertIn(EM_DASH, rendered)

    def test_render_events_panel_renders_rows(self):
        events = [
            {"date": "2026-04-24", "type": "Trade", "symbol": "SPY", "amount": Decimal("100.00")},
            {"date": "2026-04-23", "type": "Dividend", "symbol": "AAPL", "amount": Decimal("50.00")},
        ]
        data = DashboardData(recent_events=events)
        rendered = _render_to_str(render_events_panel(data))
        self.assertIn("SPY", rendered)
        self.assertIn("AAPL", rendered)

    def test_render_events_panel_formats_amount_with_sign(self):
        events = [
            {"date": "2026-04-24", "type": "Trade", "symbol": "SPY", "amount": Decimal("100.50")},
        ]
        data = DashboardData(recent_events=events)
        rendered = _render_to_str(render_events_panel(data))
        self.assertIn("+$100.50", rendered)

    def test_render_dashboard_returns_layout(self):
        data = DashboardData()
        layout = render_dashboard(data)
        self.assertIsNotNone(layout)

    def test_render_dashboard_contains_all_panel_titles(self):
        data = DashboardData()
        layout = render_dashboard(data)
        rendered = _render_to_str(layout)
        self.assertIn("Account", rendered)
        self.assertIn("Performance", rendered)
        self.assertIn("Positions", rendered)
        self.assertIn("Alerts", rendered)
        self.assertIn("Recent events", rendered)

    def test_render_dashboard_with_all_errors_still_renders(self):
        data = DashboardData(
            errors={
                "risk": "error1",
                "portfolio": "error2",
                "performance": "error3",
                "history": "error4",
            }
        )
        layout = render_dashboard(data)
        rendered = _render_to_str(layout)
        # Should still render without crashing, containing EM_DASH
        self.assertIn(EM_DASH, rendered)


if __name__ == "__main__":
    unittest.main()
