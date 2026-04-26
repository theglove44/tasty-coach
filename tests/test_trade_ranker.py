"""Tests for agents.trade_ranker watchlist scanning and symbol context building."""

import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from agents.trade_ranker import (
    Candidate,
    Rejection,
    SymbolContext,
    _build_context,
    generate_candidates,
    scan_watchlists,
)


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


def _make_idea(strategy="BULL_PUT_SPREAD", *, expiration="2026-06-19", dte=45,
               width=5.0, credit=1.5, max_loss=350.0, credit_pct=0.30,
               short_delta=0.30, pop=0.65, score=72.0,
               score_breakdown=None, breakevens=None, net_greeks=None, legs=None):
    return {
        "rank": 1,
        "strategy": strategy,
        "expiration": expiration,
        "dte": dte,
        "width": width,
        "credit": credit,
        "max_loss": max_loss,
        "credit_pct_of_width": credit_pct,
        "short_delta": short_delta,
        "pop_estimate": pop,
        "breakevens": breakevens if breakevens is not None else [148.5],
        "net_greeks": net_greeks if net_greeks is not None else {"delta": 0.05, "gamma": 0.001, "theta": 0.20, "vega": -0.15},
        "legs": legs if legs is not None else [{"action": "SELL"}, {"action": "BUY"}],
        "score": score,
        "score_breakdown": score_breakdown if score_breakdown is not None else {"raw": {}},
    }


def _make_ok_report(symbol="AAPL", *, ideas=None, warnings=None):
    return {
        "status": "OK",
        "symbol": symbol,
        "warnings": warnings if warnings is not None else [],
        "trade_ideas": ideas if ideas is not None else [_make_idea()],
    }


def _make_failure_report(symbol="AAPL", status="NO_CHAIN", warnings=None):
    return {
        "status": status,
        "symbol": symbol,
        "warnings": warnings if warnings is not None else [],
        "trade_ideas": [],
    }


class TestGenerateCandidates(unittest.IsolatedAsyncioTestCase):
    """Tests for generate_candidates orchestration."""

    async def test_single_context_produces_candidate(self):
        researcher = MagicMock()
        researcher.research = AsyncMock(return_value=_make_ok_report())
        ctx = SymbolContext(symbol="AAPL")
        candidates, rejections = await generate_candidates(MagicMock(), [ctx], researcher=researcher)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(len(rejections), 0)
        c = candidates[0]
        self.assertEqual(c.symbol, "AAPL")
        self.assertEqual(c.structure, "BULL_PUT_SPREAD")
        self.assertEqual(c.dte, 45)
        self.assertEqual(c.credit, 1.5)
        self.assertEqual(c.max_loss, 350.0)
        self.assertEqual(c.short_delta, 0.30)
        self.assertEqual(c.legs, [{"action": "SELL"}, {"action": "BUY"}])
        self.assertEqual(c.researcher_score, 72.0)
        self.assertEqual(c.researcher_score_breakdown, {"raw": {}})

    async def test_expiration_parsed_to_date_object(self):
        researcher = MagicMock()
        researcher.research = AsyncMock(return_value=_make_ok_report(ideas=[_make_idea(expiration="2026-06-19")]))
        ctx = SymbolContext(symbol="AAPL")
        candidates, _ = await generate_candidates(MagicMock(), [ctx], researcher=researcher)
        self.assertEqual(candidates[0].expiration, date(2026, 6, 19))
        self.assertIsInstance(candidates[0].expiration, date)

    async def test_context_carried_through_to_candidate(self):
        researcher = MagicMock()
        researcher.research = AsyncMock(return_value=_make_ok_report())
        ctx = SymbolContext(symbol="AAPL")
        candidates, _ = await generate_candidates(MagicMock(), [ctx], researcher=researcher)
        self.assertIs(candidates[0].context, ctx)

    async def test_status_not_ok_emits_rejection(self):
        researcher = MagicMock()
        researcher.research = AsyncMock(return_value=_make_failure_report(status="NO_VIABLE_IDEAS", warnings=[]))
        ctx = SymbolContext(symbol="AAPL")
        candidates, rejections = await generate_candidates(MagicMock(), [ctx], researcher=researcher)
        self.assertEqual(candidates, [])
        self.assertEqual(len(rejections), 1)
        self.assertEqual(rejections[0].reason, "NO_VIABLE_IDEAS")
        self.assertIsNone(rejections[0].detail)
        self.assertEqual(rejections[0].symbol, "AAPL")

    async def test_rejection_includes_first_warning(self):
        researcher = MagicMock()
        researcher.research = AsyncMock(return_value=_make_failure_report(status="NO_CHAIN", warnings=["chain unavailable", "x"]))
        ctx = SymbolContext(symbol="AAPL")
        _, rejections = await generate_candidates(MagicMock(), [ctx], researcher=researcher)
        self.assertEqual(rejections[0].detail, "chain unavailable")
        self.assertEqual(rejections[0].reason, "NO_CHAIN")

    async def test_researcher_exception_emits_rejection(self):
        researcher = MagicMock()
        researcher.research = AsyncMock(side_effect=RuntimeError("boom"))
        ctx = SymbolContext(symbol="AAPL")
        candidates, rejections = await generate_candidates(MagicMock(), [ctx], researcher=researcher)
        self.assertEqual(candidates, [])
        self.assertEqual(len(rejections), 1)
        self.assertEqual(rejections[0].reason, "researcher_exception")
        self.assertIn("boom", rejections[0].detail)

    async def test_max_per_symbol_caps_candidates(self):
        ideas = [_make_idea(score=float(i)) for i in range(5)]
        researcher = MagicMock()
        researcher.research = AsyncMock(return_value=_make_ok_report(ideas=ideas))
        ctx = SymbolContext(symbol="AAPL")
        candidates, _ = await generate_candidates(MagicMock(), [ctx], researcher=researcher, max_per_symbol=2)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0].researcher_score, 0.0)
        self.assertEqual(candidates[1].researcher_score, 1.0)

    async def test_empty_contexts_returns_empty(self):
        researcher = MagicMock()
        researcher.research = AsyncMock()
        candidates, rejections = await generate_candidates(MagicMock(), [], researcher=researcher)
        self.assertEqual(candidates, [])
        self.assertEqual(rejections, [])
        researcher.research.assert_not_called()

    @patch("agents.trade_ranker.OptionsResearcherAgent")
    async def test_default_researcher_constructed_when_not_passed(self, mock_class):
        instance = MagicMock()
        instance.research = AsyncMock(return_value=_make_ok_report())
        mock_class.return_value = instance
        session = MagicMock()
        ctx = SymbolContext(symbol="AAPL")
        await generate_candidates(session, [ctx])
        mock_class.assert_called_once_with(session)

    async def test_each_strategy_type_handled(self):
        researcher = MagicMock()
        researcher.research = AsyncMock(side_effect=[
            _make_ok_report(symbol="AAPL", ideas=[_make_idea(strategy="BULL_PUT_SPREAD")]),
            _make_ok_report(symbol="MSFT", ideas=[_make_idea(strategy="BEAR_CALL_SPREAD")]),
            _make_ok_report(symbol="SPY", ideas=[_make_idea(strategy="IRON_CONDOR")]),
        ])
        contexts = [SymbolContext(symbol=s) for s in ("AAPL", "MSFT", "SPY")]
        candidates, _ = await generate_candidates(MagicMock(), contexts, researcher=researcher)
        self.assertEqual([c.structure for c in candidates], ["BULL_PUT_SPREAD", "BEAR_CALL_SPREAD", "IRON_CONDOR"])

    async def test_multiple_contexts_preserve_order(self):
        researcher = MagicMock()
        researcher.research = AsyncMock(side_effect=[
            _make_ok_report(symbol="AAPL"),
            _make_ok_report(symbol="MSFT"),
        ])
        contexts = [SymbolContext(symbol="AAPL"), SymbolContext(symbol="MSFT")]
        candidates, _ = await generate_candidates(MagicMock(), contexts, researcher=researcher)
        self.assertEqual([c.symbol for c in candidates], ["AAPL", "MSFT"])

    async def test_optional_fields_default_to_empty(self):
        idea = {
            "rank": 1, "strategy": "BULL_PUT_SPREAD", "expiration": "2026-06-19",
            "dte": 45, "width": 5.0, "credit": 1.5, "max_loss": 350.0,
            "credit_pct_of_width": 0.30, "short_delta": 0.30, "pop_estimate": 0.65,
            "breakevens": None, "net_greeks": None, "legs": None,
            "score": 72.0, "score_breakdown": None,
        }
        report = {"status": "OK", "symbol": "AAPL", "warnings": [], "trade_ideas": [idea]}
        researcher = MagicMock()
        researcher.research = AsyncMock(return_value=report)
        ctx = SymbolContext(symbol="AAPL")
        candidates, _ = await generate_candidates(MagicMock(), [ctx], researcher=researcher)
        c = candidates[0]
        self.assertEqual(c.breakevens, [])
        self.assertEqual(c.net_greeks, {})
        self.assertEqual(c.legs, [])
        self.assertEqual(c.researcher_score_breakdown, {})


if __name__ == "__main__":
    unittest.main()
