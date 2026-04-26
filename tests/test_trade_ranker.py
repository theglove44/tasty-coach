"""Tests for agents.trade_ranker watchlist scanning and symbol context building."""

import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from agents.trade_ranker import SymbolContext, _build_context, scan_watchlists


def _make_metric(
    symbol,
    *,
    ivr=Decimal("0.45"),
    ivp=Decimal("0.30"),
    iv=Decimal("0.25"),
    beta=Decimal("1.1"),
    liq=Decimal("3"),
    earnings_date=None,
):
    m = MagicMock()
    m.symbol = symbol
    m.implied_volatility_index_rank = ivr
    m.implied_volatility_percentile = ivp
    m.implied_volatility_index = iv
    m.beta = beta
    m.liquidity_rank = liq
    if earnings_date is not None:
        m.earnings = MagicMock()
        m.earnings.expected_report_date = earnings_date
    else:
        m.earnings = None
    return m


def _make_price(symbol, *, mark=Decimal("100.00"), last=Decimal("99.50"), volume=Decimal("1000000")):
    d = MagicMock()
    d.symbol = symbol
    d.mark = mark
    d.last = last
    d.volume = volume
    return d


class TestBuildContext(unittest.TestCase):
    """Tests for _build_context helper."""

    def test_single_symbol_produces_context(self):
        metric = _make_metric("AAPL", ivr=Decimal("0.45"))
        data = _make_price("AAPL", mark=Decimal("150.00"), volume=Decimal("5000000"))
        ctx = _build_context("AAPL", metric, data)
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.symbol, "AAPL")
        self.assertEqual(ctx.current_price, Decimal("150.00"))
        self.assertEqual(ctx.volume, Decimal("5000000"))
        self.assertEqual(ctx.iv_rank, 45.0)
        self.assertEqual(ctx.iv_percentile, 30.0)
        self.assertEqual(ctx.current_iv, 0.25)
        self.assertEqual(ctx.beta, 1.1)
        self.assertEqual(ctx.liquidity_rank, 3.0)
        self.assertIsNone(ctx.next_earnings_date)

    def test_broken_symbol_emits_warning_no_crash(self):
        ctx = _build_context("AAPL", None, None)
        self.assertIsNone(ctx)

    def test_earnings_date_preserved_as_date_object(self):
        earnings_date = date(2026, 5, 1)
        metric = _make_metric("AAPL", earnings_date=earnings_date)
        data = _make_price("AAPL")
        ctx = _build_context("AAPL", metric, data)
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.next_earnings_date, date(2026, 5, 1))
        self.assertIsInstance(ctx.next_earnings_date, date)

    def test_partial_data_metric_only(self):
        metric = _make_metric("AAPL")
        ctx = _build_context("AAPL", metric, None)
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.symbol, "AAPL")
        self.assertIsNone(ctx.current_price)
        self.assertIsNone(ctx.volume)
        self.assertEqual(ctx.iv_rank, 45.0)

    def test_partial_data_price_only(self):
        data = _make_price("AAPL", mark=Decimal("150.00"))
        ctx = _build_context("AAPL", None, data)
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.symbol, "AAPL")
        self.assertEqual(ctx.current_price, Decimal("150.00"))
        self.assertEqual(ctx.volume, Decimal("1000000"))
        self.assertIsNone(ctx.iv_rank)

    def test_mark_none_falls_back_to_last(self):
        data = _make_price("AAPL", mark=None, last=Decimal("12.34"))
        ctx = _build_context("AAPL", None, data)
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.current_price, Decimal("12.34"))

    def test_zero_valued_metrics_preserved_not_coerced_to_none(self):
        """Legitimate zero values (e.g. IVR=0 for a quiet stock) must survive as 0.0, not None."""
        metric = _make_metric(
            "AAPL",
            ivr=Decimal("0"),
            ivp=Decimal("0"),
            iv=Decimal("0"),
            beta=Decimal("0"),
            liq=Decimal("0"),
        )
        ctx = _build_context("AAPL", metric, _make_price("AAPL"))
        self.assertEqual(ctx.iv_rank, 0.0)
        self.assertEqual(ctx.iv_percentile, 0.0)
        self.assertEqual(ctx.current_iv, 0.0)
        self.assertEqual(ctx.beta, 0.0)
        self.assertEqual(ctx.liquidity_rank, 0.0)

    def test_none_valued_metrics_remain_none(self):
        """When the SDK returns None for a metric field, the context field stays None."""
        metric = _make_metric(
            "AAPL",
            ivr=None,
            ivp=None,
            iv=None,
            beta=None,
            liq=None,
        )
        ctx = _build_context("AAPL", metric, _make_price("AAPL"))
        self.assertIsNone(ctx.iv_rank)
        self.assertIsNone(ctx.iv_percentile)
        self.assertIsNone(ctx.current_iv)
        self.assertIsNone(ctx.beta)
        self.assertIsNone(ctx.liquidity_rank)


class TestScanWatchlists(unittest.IsolatedAsyncioTestCase):
    """Tests for scan_watchlists orchestration."""

    @patch("agents.trade_ranker.get_market_metrics")
    @patch("agents.trade_ranker.get_market_data_by_type")
    async def test_single_symbol_produces_context(self, mock_prices, mock_metrics):
        mock_metrics.return_value = [_make_metric("AAPL", ivr=Decimal("0.45"))]
        mock_prices.return_value = [_make_price("AAPL")]
        scanner = MagicMock()
        scanner.get_symbols_from_watchlist = AsyncMock(return_value=["AAPL"])
        session = MagicMock()
        contexts, warnings = await scan_watchlists(session, watchlists=["Test"], scanner=scanner)
        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0].symbol, "AAPL")
        self.assertEqual(contexts[0].iv_rank, 45.0)
        self.assertEqual(len(warnings), 0)

    @patch("agents.trade_ranker.get_market_metrics")
    @patch("agents.trade_ranker.get_market_data_by_type")
    async def test_broken_symbol_emits_warning_no_crash(self, mock_prices, mock_metrics):
        mock_metrics.return_value = []
        mock_prices.return_value = []
        scanner = MagicMock()
        scanner.get_symbols_from_watchlist = AsyncMock(return_value=["AAPL"])
        session = MagicMock()
        contexts, warnings = await scan_watchlists(session, watchlists=["Test"], scanner=scanner)
        self.assertEqual(len(contexts), 0)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0], "AAPL: no market metrics or price data returned")

    @patch("agents.trade_ranker.get_market_metrics")
    @patch("agents.trade_ranker.get_market_data_by_type")
    async def test_merge_two_watchlists_dedupes_preserving_order(self, mock_prices, mock_metrics):
        mock_metrics.return_value = [_make_metric("AAPL"), _make_metric("MSFT"), _make_metric("GOOG")]
        mock_prices.return_value = [_make_price("AAPL"), _make_price("MSFT"), _make_price("GOOG")]
        scanner = MagicMock()
        scanner.get_symbols_from_watchlist = AsyncMock(side_effect=[["AAPL", "MSFT"], ["MSFT", "GOOG"]])
        session = MagicMock()
        contexts, warnings = await scan_watchlists(session, watchlists=["A", "B"], scanner=scanner)
        symbols = [c.symbol for c in contexts]
        self.assertEqual(symbols, ["AAPL", "MSFT", "GOOG"])
        self.assertEqual(len(warnings), 0)

    @patch("agents.trade_ranker.get_market_metrics")
    @patch("agents.trade_ranker.get_market_data_by_type")
    async def test_missing_watchlist_emits_warning(self, mock_prices, mock_metrics):
        mock_metrics.return_value = [_make_metric("AAPL")]
        mock_prices.return_value = [_make_price("AAPL")]
        scanner = MagicMock()
        scanner.get_symbols_from_watchlist = AsyncMock(side_effect=[[], ["AAPL"]])
        session = MagicMock()
        contexts, warnings = await scan_watchlists(session, watchlists=["Foo", "Bar"], scanner=scanner)
        self.assertEqual(len(contexts), 1)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0], "watchlist 'Foo' not found or empty")

    @patch("agents.trade_ranker.ScannerAgent")
    @patch("agents.trade_ranker.get_market_metrics")
    @patch("agents.trade_ranker.get_market_data_by_type")
    async def test_default_watchlists_used_when_none(self, mock_prices, mock_metrics, mock_scanner_class):
        mock_metrics.return_value = []
        mock_prices.return_value = []
        scanner = MagicMock()
        scanner.get_symbols_from_watchlist = AsyncMock(return_value=[])
        mock_scanner_class.return_value = scanner
        session = MagicMock()
        contexts, warnings = await scan_watchlists(session, watchlists=None)
        expected_calls = [
            unittest.mock.call("Chris Historical Trades", equity_only=True),
            unittest.mock.call("High Options Volume", equity_only=True),
        ]
        scanner.get_symbols_from_watchlist.assert_has_calls(expected_calls)

    @patch("agents.trade_ranker.get_market_metrics")
    @patch("agents.trade_ranker.get_market_data_by_type")
    async def test_explicit_empty_watchlists_returns_empty(self, mock_prices, mock_metrics):
        session = MagicMock()
        contexts, warnings = await scan_watchlists(session, watchlists=[])
        self.assertEqual(contexts, [])
        self.assertEqual(warnings, [])
        mock_metrics.assert_not_called()
        mock_prices.assert_not_called()

    @patch("agents.trade_ranker.get_market_metrics")
    @patch("agents.trade_ranker.get_market_data_by_type")
    async def test_earnings_date_preserved_as_date_object(self, mock_prices, mock_metrics):
        earnings_date = date(2026, 5, 1)
        mock_metrics.return_value = [_make_metric("AAPL", earnings_date=earnings_date)]
        mock_prices.return_value = [_make_price("AAPL")]
        scanner = MagicMock()
        scanner.get_symbols_from_watchlist = AsyncMock(return_value=["AAPL"])
        session = MagicMock()
        contexts, warnings = await scan_watchlists(session, watchlists=["Test"], scanner=scanner)
        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0].next_earnings_date, date(2026, 5, 1))
        self.assertIsInstance(contexts[0].next_earnings_date, date)

    @patch("agents.trade_ranker.get_market_metrics")
    @patch("agents.trade_ranker.get_market_data_by_type")
    async def test_partial_data_does_not_emit_warning(self, mock_prices, mock_metrics):
        mock_metrics.return_value = [_make_metric("AAPL")]
        mock_prices.return_value = []
        scanner = MagicMock()
        scanner.get_symbols_from_watchlist = AsyncMock(return_value=["AAPL"])
        session = MagicMock()
        contexts, warnings = await scan_watchlists(session, watchlists=["Test"], scanner=scanner)
        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0].symbol, "AAPL")
        self.assertEqual(len(warnings), 0)

    @patch("agents.trade_ranker.get_market_metrics")
    @patch("agents.trade_ranker.get_market_data_by_type")
    async def test_batch_failure_warns_does_not_crash(self, mock_prices, mock_metrics):
        mock_metrics.side_effect = RuntimeError("boom")
        scanner = MagicMock()
        scanner.get_symbols_from_watchlist = AsyncMock(return_value=["AAPL"])
        session = MagicMock()
        contexts, warnings = await scan_watchlists(session, watchlists=["Test"], scanner=scanner)
        self.assertEqual(len(contexts), 0)
        self.assertEqual(len(warnings), 1)
        self.assertTrue(warnings[0].startswith("batch fetch failed: "))
        self.assertIn("boom", warnings[0])


if __name__ == "__main__":
    unittest.main()
