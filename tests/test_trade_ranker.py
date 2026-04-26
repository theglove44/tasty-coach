"""Tests for agents.trade_ranker watchlist scanning and symbol context building."""

import asyncio
import unittest
from datetime import date
from decimal import Decimal
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

from agents.trade_ranker import (
    AccountState,
    Candidate,
    Rejection,
    SymbolContext,
    _build_context,
    _check_broken_pricing,
    _check_dte_bounds,
    _check_earnings_blackout,
    _check_open_interest,
    _check_spread,
    _score_account_fit,
    _score_concentration_penalty,
    apply_account_filters,
    apply_quality_gates,
    filter_by_ivr,
    generate_candidates,
    scan_watchlists,
    score_candidate,
    score_candidates,
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
    async def test_per_watchlist_fetch_failure_warns_does_not_crash(self, mock_prices, mock_metrics):
        mock_metrics.return_value = []
        mock_prices.return_value = []
        scanner = MagicMock()
        scanner.get_symbols_from_watchlist = AsyncMock(side_effect=[
            RuntimeError("auth expired"),
            ["AAPL"],
        ])
        mock_metrics.return_value = [_make_metric("AAPL")]
        mock_prices.return_value = [_make_price("AAPL")]
        session = MagicMock()
        contexts, warnings = await scan_watchlists(
            session, watchlists=["Bad", "Good"], scanner=scanner
        )
        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0].symbol, "AAPL")
        self.assertEqual(len(warnings), 1)
        self.assertTrue(warnings[0].startswith("watchlist 'Bad' fetch failed: "))
        self.assertIn("auth expired", warnings[0])

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


def _make_candidate(
    *,
    symbol: str = "AAPL",
    structure: str = "BULL_PUT_SPREAD",
    expiration: date = date(2026, 6, 19),
    dte: int = 45,
    width: float = 5.0,
    credit: float = 1.5,
    max_loss: float = 350.0,
    credit_pct_of_width: float = 0.30,
    short_delta: float = 0.30,
    pop_estimate: float = 0.65,
    breakevens: Optional[list] = None,
    net_greeks: Optional[dict] = None,
    legs: Optional[list] = None,
    researcher_score: float = 72.0,
    researcher_score_breakdown: Optional[dict] = None,
    next_earnings_date: Optional[date] = None,
    iv_rank: Optional[float] = None,
) -> Candidate:
    ctx = SymbolContext(symbol=symbol, next_earnings_date=next_earnings_date, iv_rank=iv_rank)
    default_legs = [
        {"action": "SELL", "bid": 1.50, "ask": 1.55, "mid": 1.525, "open_interest": 500},
        {"action": "BUY", "bid": 0.40, "ask": 0.42, "mid": 0.41, "open_interest": 500},
    ]
    return Candidate(
        symbol=symbol,
        structure=structure,
        expiration=expiration,
        dte=dte,
        width=width,
        credit=credit,
        max_loss=max_loss,
        credit_pct_of_width=credit_pct_of_width,
        short_delta=short_delta,
        pop_estimate=pop_estimate,
        breakevens=breakevens if breakevens is not None else [148.5],
        net_greeks=net_greeks if net_greeks is not None else {"delta": 0.05, "gamma": 0.001, "theta": 0.20, "vega": -0.15},
        legs=legs if legs is not None else default_legs,
        researcher_score=researcher_score,
        researcher_score_breakdown=researcher_score_breakdown if researcher_score_breakdown is not None else {"raw": {}},
        context=ctx,
    )


class TestGenerateCandidates(unittest.IsolatedAsyncioTestCase):
    """Tests for generate_candidates orchestration."""

    async def test_single_context_produces_candidate(self):
        researcher = MagicMock()
        researcher.research = AsyncMock(return_value=_make_ok_report())
        ctx = SymbolContext(symbol="AAPL", iv_rank=99.0)
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
        ctx = SymbolContext(symbol="AAPL", iv_rank=99.0)
        candidates, _ = await generate_candidates(MagicMock(), [ctx], researcher=researcher)
        self.assertEqual(candidates[0].expiration, date(2026, 6, 19))
        self.assertIsInstance(candidates[0].expiration, date)

    async def test_context_carried_through_to_candidate(self):
        researcher = MagicMock()
        researcher.research = AsyncMock(return_value=_make_ok_report())
        ctx = SymbolContext(symbol="AAPL", iv_rank=99.0)
        candidates, _ = await generate_candidates(MagicMock(), [ctx], researcher=researcher)
        self.assertIs(candidates[0].context, ctx)

    async def test_status_not_ok_emits_rejection(self):
        researcher = MagicMock()
        researcher.research = AsyncMock(return_value=_make_failure_report(status="NO_VIABLE_IDEAS", warnings=[]))
        ctx = SymbolContext(symbol="AAPL", iv_rank=99.0)
        candidates, rejections = await generate_candidates(MagicMock(), [ctx], researcher=researcher)
        self.assertEqual(candidates, [])
        self.assertEqual(len(rejections), 1)
        self.assertEqual(rejections[0].reason, "NO_VIABLE_IDEAS")
        self.assertIsNone(rejections[0].detail)
        self.assertEqual(rejections[0].symbol, "AAPL")

    async def test_rejection_includes_first_warning(self):
        researcher = MagicMock()
        researcher.research = AsyncMock(return_value=_make_failure_report(status="NO_CHAIN", warnings=["chain unavailable", "x"]))
        ctx = SymbolContext(symbol="AAPL", iv_rank=99.0)
        _, rejections = await generate_candidates(MagicMock(), [ctx], researcher=researcher)
        self.assertEqual(rejections[0].detail, "chain unavailable")
        self.assertEqual(rejections[0].reason, "NO_CHAIN")

    async def test_researcher_exception_emits_rejection(self):
        researcher = MagicMock()
        researcher.research = AsyncMock(side_effect=RuntimeError("boom"))
        ctx = SymbolContext(symbol="AAPL", iv_rank=99.0)
        candidates, rejections = await generate_candidates(MagicMock(), [ctx], researcher=researcher)
        self.assertEqual(candidates, [])
        self.assertEqual(len(rejections), 1)
        self.assertEqual(rejections[0].reason, "researcher_exception")
        self.assertIn("boom", rejections[0].detail)

    async def test_max_per_symbol_caps_candidates(self):
        ideas = [_make_idea(score=float(i)) for i in range(5)]
        researcher = MagicMock()
        researcher.research = AsyncMock(return_value=_make_ok_report(ideas=ideas))
        ctx = SymbolContext(symbol="AAPL", iv_rank=99.0)
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
        ctx = SymbolContext(symbol="AAPL", iv_rank=99.0)
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
        contexts = [SymbolContext(symbol="AAPL", iv_rank=99.0), SymbolContext(symbol="MSFT")]
        candidates, _ = await generate_candidates(MagicMock(), contexts, researcher=researcher)
        self.assertEqual([c.symbol for c in candidates], ["AAPL", "MSFT"])

    async def test_research_timeout_emits_rejection(self):
        async def hang(symbol):
            await asyncio.sleep(10)
            return _make_ok_report(symbol=symbol)
        researcher = MagicMock()
        researcher.research = AsyncMock(side_effect=hang)
        ctx = SymbolContext(symbol="AAPL")
        candidates, rejections = await generate_candidates(
            MagicMock(), [ctx], researcher=researcher, timeout_seconds=0.05
        )
        self.assertEqual(candidates, [])
        self.assertEqual(len(rejections), 1)
        self.assertEqual(rejections[0].reason, "research_timeout")
        self.assertIn("0.05", rejections[0].detail)

    async def test_concurrency_runs_calls_in_parallel(self):
        active = 0
        peak = 0
        lock = asyncio.Lock()

        async def slow(symbol):
            nonlocal active, peak
            async with lock:
                active += 1
                if active > peak:
                    peak = active
            await asyncio.sleep(0.05)
            async with lock:
                active -= 1
            return _make_ok_report(symbol=symbol)

        researcher = MagicMock()
        researcher.research = AsyncMock(side_effect=slow)
        contexts = [SymbolContext(symbol=s) for s in ("A", "B", "C", "D", "E")]
        await generate_candidates(MagicMock(), contexts, researcher=researcher, concurrency=3)
        self.assertGreaterEqual(peak, 2)
        self.assertLessEqual(peak, 3)

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
        ctx = SymbolContext(symbol="AAPL", iv_rank=99.0)
        candidates, _ = await generate_candidates(MagicMock(), [ctx], researcher=researcher)
        c = candidates[0]
        self.assertEqual(c.breakevens, [])
        self.assertEqual(c.net_greeks, {})
        self.assertEqual(c.legs, [])
        self.assertEqual(c.researcher_score_breakdown, {})


class TestQualityGates(unittest.TestCase):
    """Tests for apply_quality_gates and individual _check_* helpers."""

    DEFAULT_KW = dict(
        blackout_days=7,
        min_dte=21,
        max_dte=60,
        min_open_interest=200,
        max_spread_pct=0.10,
        today=date(2026, 4, 26),
    )

    def test_passing_candidate_survives_all_gates(self):
        c = _make_candidate()
        passing, rejections = apply_quality_gates([c], **self.DEFAULT_KW)
        self.assertEqual(passing, [c])
        self.assertEqual(rejections, [])

    def test_earnings_within_blackout_rejected(self):
        c = _make_candidate(next_earnings_date=date(2026, 5, 1))
        passing, rejections = apply_quality_gates([c], **self.DEFAULT_KW)
        self.assertEqual(passing, [])
        self.assertEqual(len(rejections), 1)
        self.assertEqual(rejections[0].reason, "earnings_blackout")
        self.assertEqual(rejections[0].detail, "earnings 2026-05-01 within 7d window")

    def test_earnings_outside_blackout_passes(self):
        c = _make_candidate(next_earnings_date=date(2026, 5, 15))
        passing, rejections = apply_quality_gates([c], **self.DEFAULT_KW)
        self.assertEqual(passing, [c])
        self.assertEqual(rejections, [])

    def test_no_earnings_data_skips_gate(self):
        c = _make_candidate(next_earnings_date=None)
        self.assertIsNone(_check_earnings_blackout(c, 7, date(2026, 4, 26)))

    def test_earnings_today_still_rejected(self):
        today = date(2026, 4, 26)
        c = _make_candidate(next_earnings_date=today)
        rejection = _check_earnings_blackout(c, 7, today)
        self.assertIsNotNone(rejection)
        self.assertEqual(rejection.reason, "earnings_blackout")

    def test_earnings_yesterday_does_not_reject(self):
        today = date(2026, 4, 26)
        c = _make_candidate(next_earnings_date=date(2026, 4, 25))
        self.assertIsNone(_check_earnings_blackout(c, 7, today))

    def test_earnings_far_past_does_not_reject(self):
        today = date(2026, 4, 26)
        c = _make_candidate(next_earnings_date=date(2026, 3, 27))
        self.assertIsNone(_check_earnings_blackout(c, 7, today))

    def test_dte_below_min_rejected(self):
        c = _make_candidate(dte=12)
        passing, rejections = apply_quality_gates([c], **self.DEFAULT_KW)
        self.assertEqual(passing, [])
        self.assertEqual(rejections[0].reason, "dte_out_of_range")
        self.assertEqual(rejections[0].detail, "dte=12 below min=21")

    def test_dte_above_max_rejected(self):
        c = _make_candidate(dte=70)
        passing, rejections = apply_quality_gates([c], **self.DEFAULT_KW)
        self.assertEqual(passing, [])
        self.assertEqual(rejections[0].reason, "dte_out_of_range")
        self.assertEqual(rejections[0].detail, "dte=70 above max=60")

    def test_dte_in_range_passes(self):
        c = _make_candidate(dte=45)
        passing, _ = apply_quality_gates([c], **self.DEFAULT_KW)
        self.assertEqual(passing, [c])

    def test_zero_credit_rejected(self):
        c = _make_candidate(credit=0.0)
        passing, rejections = apply_quality_gates([c], **self.DEFAULT_KW)
        self.assertEqual(passing, [])
        self.assertEqual(rejections[0].reason, "broken_pricing")
        self.assertEqual(rejections[0].detail, "credit=0.0")

    def test_sell_leg_zero_bid_rejected(self):
        legs = [
            {"action": "SELL", "bid": 0.0, "ask": 0.05, "mid": 0.025, "open_interest": 500},
            {"action": "BUY", "bid": 0.40, "ask": 0.42, "mid": 0.41, "open_interest": 500},
        ]
        c = _make_candidate(legs=legs)
        passing, rejections = apply_quality_gates([c], **self.DEFAULT_KW)
        self.assertEqual(passing, [])
        self.assertEqual(rejections[0].reason, "broken_pricing")
        self.assertEqual(rejections[0].detail, "sell-leg bid=0.0")

    def test_buy_leg_zero_bid_does_not_reject(self):
        legs = [
            {"action": "SELL", "bid": 1.50, "ask": 1.55, "mid": 1.525, "open_interest": 500},
            {"action": "BUY", "bid": 0.0, "ask": 0.05, "mid": 0.025, "open_interest": 500},
        ]
        c = _make_candidate(legs=legs)
        self.assertIsNone(_check_broken_pricing(c))

    def test_low_open_interest_rejected(self):
        legs = [
            {"action": "SELL", "bid": 1.50, "ask": 1.55, "mid": 1.525, "open_interest": 150},
            {"action": "BUY", "bid": 0.40, "ask": 0.42, "mid": 0.41, "open_interest": 500},
        ]
        c = _make_candidate(legs=legs)
        passing, rejections = apply_quality_gates([c], **self.DEFAULT_KW)
        self.assertEqual(passing, [])
        self.assertEqual(rejections[0].reason, "low_open_interest")
        self.assertEqual(rejections[0].detail, "min OI 150 below floor 200")

    def test_all_oi_none_does_not_reject(self):
        legs = [
            {"action": "SELL", "bid": 1.50, "ask": 1.55, "mid": 1.525, "open_interest": None},
            {"action": "BUY", "bid": 0.40, "ask": 0.45, "mid": 0.425, "open_interest": None},
        ]
        c = _make_candidate(legs=legs)
        self.assertIsNone(_check_open_interest(c, 200))

    def test_wide_spread_rejected(self):
        legs = [
            {"action": "SELL", "bid": 1.40, "ask": 1.70, "mid": 1.55, "open_interest": 500},
            {"action": "BUY", "bid": 0.40, "ask": 0.42, "mid": 0.41, "open_interest": 500},
        ]
        c = _make_candidate(legs=legs)
        passing, rejections = apply_quality_gates([c], **self.DEFAULT_KW)
        self.assertEqual(passing, [])
        self.assertEqual(rejections[0].reason, "wide_spread")
        self.assertEqual(rejections[0].detail, "max spread 0.194 above cap 0.100")

    def test_missing_pricing_skips_spread_gate(self):
        legs = [
            {"action": "SELL", "bid": None, "ask": None, "mid": None, "open_interest": 500},
            {"action": "BUY", "bid": None, "ask": None, "mid": None, "open_interest": 500},
        ]
        c = _make_candidate(legs=legs)
        self.assertIsNone(_check_spread(c, 0.10))

    def test_first_failure_wins_earnings_before_dte(self):
        c = _make_candidate(next_earnings_date=date(2026, 5, 1), dte=12)
        passing, rejections = apply_quality_gates([c], **self.DEFAULT_KW)
        self.assertEqual(passing, [])
        self.assertEqual(len(rejections), 1)
        self.assertEqual(rejections[0].reason, "earnings_blackout")

    def test_empty_candidates_returns_empty(self):
        passing, rejections = apply_quality_gates([], **self.DEFAULT_KW)
        self.assertEqual(passing, [])
        self.assertEqual(rejections, [])

    def test_passing_and_failing_partition_correctly(self):
        good = _make_candidate(symbol="AAPL")
        bad = _make_candidate(symbol="MSFT", dte=12)
        passing, rejections = apply_quality_gates([good, bad], **self.DEFAULT_KW)
        self.assertEqual(passing, [good])
        self.assertEqual(len(rejections), 1)
        self.assertEqual(rejections[0].symbol, "MSFT")
        self.assertEqual(rejections[0].reason, "dte_out_of_range")


class TestScoring(unittest.TestCase):
    """Tests for score_candidate and score_candidates."""

    _TODAY = date(2026, 4, 26)

    @staticmethod
    def _liquid_legs():
        return [
            {"action": "SELL", "bid": 1.00, "ask": 1.02, "mid": 1.01, "open_interest": 5000},
            {"action": "BUY",  "bid": 0.50, "ask": 0.52, "mid": 0.51, "open_interest": 5000},
        ]

    def test_score_in_zero_to_hundred_range(self):
        c = _make_candidate(iv_rank=70.0, credit_pct_of_width=0.35, legs=self._liquid_legs())
        scored = score_candidate(c, today=self._TODAY)
        self.assertGreaterEqual(scored.score, 0.0)
        self.assertLessEqual(scored.score, 100.0)

    def test_breakdown_keys_exactly_seven(self):
        c = _make_candidate()
        scored = score_candidate(c, today=self._TODAY)
        self.assertEqual(
            set(scored.score_breakdown.keys()),
            {"regime_fit", "liquidity", "volatility_edge", "event_risk", "structure_quality", "account_fit", "concentration_penalty"},
        )

    def test_breakdown_sums_within_tolerance_of_score(self):
        c = _make_candidate(iv_rank=50.0, credit_pct_of_width=0.30, legs=self._liquid_legs())
        scored = score_candidate(c, today=self._TODAY)
        b = scored.score_breakdown
        total = b["regime_fit"] + b["liquidity"] + b["volatility_edge"] + b["event_risk"] + b["structure_quality"] + b["account_fit"] - b["concentration_penalty"]
        self.assertAlmostEqual(total, scored.score, places=9)

    def test_high_ivr_scores_higher_than_low_ivr(self):
        high = _make_candidate(iv_rank=80.0, legs=self._liquid_legs())
        low = _make_candidate(iv_rank=20.0, legs=self._liquid_legs())
        self.assertGreater(score_candidate(high, today=self._TODAY).score, score_candidate(low, today=self._TODAY).score)

    def test_higher_credit_ratio_scores_higher(self):
        good = _make_candidate(credit_pct_of_width=0.45, legs=self._liquid_legs())
        bad = _make_candidate(credit_pct_of_width=0.22, legs=self._liquid_legs())
        self.assertGreater(score_candidate(good, today=self._TODAY).score, score_candidate(bad, today=self._TODAY).score)

    def test_tighter_spread_scores_higher(self):
        tight_legs = [
            {"action": "SELL", "bid": 1.00, "ask": 1.01, "mid": 1.005, "open_interest": 5000},
            {"action": "BUY",  "bid": 0.50, "ask": 0.51, "mid": 0.505, "open_interest": 5000},
        ]
        wide_legs = [
            {"action": "SELL", "bid": 1.00, "ask": 1.09, "mid": 1.045, "open_interest": 5000},
            {"action": "BUY",  "bid": 0.50, "ask": 0.55, "mid": 0.525, "open_interest": 5000},
        ]
        tight_score = score_candidate(_make_candidate(legs=tight_legs), today=self._TODAY).score_breakdown["liquidity"]
        wide_score = score_candidate(_make_candidate(legs=wide_legs), today=self._TODAY).score_breakdown["liquidity"]
        self.assertGreater(tight_score, wide_score)

    def test_higher_oi_scores_higher(self):
        deep = self._liquid_legs()
        thin = [
            {"action": "SELL", "bid": 1.00, "ask": 1.02, "mid": 1.01, "open_interest": 50},
            {"action": "BUY",  "bid": 0.50, "ask": 0.52, "mid": 0.51, "open_interest": 50},
        ]
        deep_lq = score_candidate(_make_candidate(legs=deep), today=self._TODAY).score_breakdown["liquidity"]
        thin_lq = score_candidate(_make_candidate(legs=thin), today=self._TODAY).score_breakdown["liquidity"]
        self.assertGreater(deep_lq, thin_lq)

    def test_no_earnings_full_event_risk_score(self):
        c = _make_candidate(next_earnings_date=None)
        self.assertEqual(score_candidate(c, today=self._TODAY).score_breakdown["event_risk"], 10.0)

    def test_close_earnings_8d_lowers_event_score(self):
        c = _make_candidate(next_earnings_date=date(2026, 5, 4))
        ev = score_candidate(c, today=self._TODAY).score_breakdown["event_risk"]
        self.assertGreater(ev, 0.0)
        self.assertLess(ev, 10.0)
        self.assertAlmostEqual(ev, (1 / 14.0) * 10.0, places=9)

    def test_close_earnings_14d_partial_event_score(self):
        c = _make_candidate(next_earnings_date=date(2026, 5, 10))
        self.assertAlmostEqual(score_candidate(c, today=self._TODAY).score_breakdown["event_risk"], 5.0, places=9)

    def test_far_earnings_full_event_score(self):
        c = _make_candidate(next_earnings_date=date(2026, 5, 26))
        self.assertEqual(score_candidate(c, today=self._TODAY).score_breakdown["event_risk"], 10.0)

    def test_past_earnings_full_event_score(self):
        c = _make_candidate(next_earnings_date=date(2026, 4, 21))
        self.assertEqual(score_candidate(c, today=self._TODAY).score_breakdown["event_risk"], 10.0)

    def test_short_delta_at_quarter_scores_high(self):
        c = _make_candidate(short_delta=0.25, credit_pct_of_width=0.40, legs=self._liquid_legs())
        sq = score_candidate(c, today=self._TODAY).score_breakdown["structure_quality"]
        self.assertGreaterEqual(sq, 10.0)

    def test_short_delta_at_45_scores_lower(self):
        good = _make_candidate(short_delta=0.25, credit_pct_of_width=0.40, legs=self._liquid_legs())
        bad = _make_candidate(short_delta=0.45, credit_pct_of_width=0.40, legs=self._liquid_legs())
        self.assertGreater(
            score_candidate(good, today=self._TODAY).score_breakdown["structure_quality"],
            score_candidate(bad, today=self._TODAY).score_breakdown["structure_quality"],
        )

    def test_account_fit_placeholder_returns_ten(self):
        c = _make_candidate()
        self.assertEqual(score_candidate(c, today=self._TODAY).score_breakdown["account_fit"], 10.0)

    def test_concentration_penalty_placeholder_returns_zero(self):
        c = _make_candidate()
        self.assertEqual(score_candidate(c, today=self._TODAY).score_breakdown["concentration_penalty"], 0.0)

    def test_summary_reason_is_single_line(self):
        c = _make_candidate(iv_rank=70.0, credit_pct_of_width=0.40, legs=self._liquid_legs())
        self.assertNotIn("\n", score_candidate(c, today=self._TODAY).summary_reason)

    def test_summary_reason_mentions_strong_factors(self):
        c = _make_candidate(iv_rank=70.0, credit_pct_of_width=0.40, legs=self._liquid_legs())
        self.assertIn("IVR", score_candidate(c, today=self._TODAY).summary_reason)

    def test_summary_reason_fallback_when_all_weak(self):
        c = _make_candidate(
            iv_rank=0.0,
            credit_pct_of_width=0.18,
            legs=[],
            short_delta=0.05,
            next_earnings_date=date(2026, 5, 1),
        )
        self.assertEqual(score_candidate(c, today=self._TODAY).summary_reason, "weak across all factors")

    def test_score_candidates_preserves_order(self):
        candidates = [
            _make_candidate(symbol="AAPL"),
            _make_candidate(symbol="MSFT"),
            _make_candidate(symbol="SPY"),
        ]
        scored = score_candidates(candidates, today=self._TODAY)
        self.assertEqual([c.symbol for c in scored], ["AAPL", "MSFT", "SPY"])

    def test_score_candidates_empty_returns_empty(self):
        self.assertEqual(score_candidates([], today=self._TODAY), [])

    def test_score_candidate_returns_new_instance_not_mutated(self):
        c = _make_candidate(iv_rank=50.0, legs=self._liquid_legs())
        scored = score_candidate(c, today=self._TODAY)
        self.assertEqual(c.score, 0.0)
        self.assertGreater(scored.score, 0.0)
        self.assertIsNot(scored, c)

    def test_legs_empty_zero_liquidity(self):
        c = _make_candidate(legs=[])
        self.assertEqual(score_candidate(c, today=self._TODAY).score_breakdown["liquidity"], 0.0)

    def test_iv_rank_none_neutral_regime_fit(self):
        c = _make_candidate(iv_rank=None)
        self.assertEqual(score_candidate(c, today=self._TODAY).score_breakdown["regime_fit"], 7.5)

    def test_negative_short_delta_scores_same_as_positive(self):
        """PUT spreads carry signed (negative) short_delta from researcher; structure_quality must use magnitude."""
        legs = self._liquid_legs()
        put = _make_candidate(short_delta=-0.25, credit_pct_of_width=0.40, legs=legs)
        call = _make_candidate(short_delta=0.25, credit_pct_of_width=0.40, legs=legs)
        put_sq = score_candidate(put, today=self._TODAY).score_breakdown["structure_quality"]
        call_sq = score_candidate(call, today=self._TODAY).score_breakdown["structure_quality"]
        self.assertAlmostEqual(put_sq, call_sq, places=9)

    def test_crossed_market_does_not_inflate_liquidity(self):
        """Crossed quote (ask < bid) → negative spread → liquidity must stay at weight cap, not exceed it."""
        crossed_legs = [
            {"action": "SELL", "bid": 1.05, "ask": 1.00, "mid": 1.025, "open_interest": 5000},
            {"action": "BUY",  "bid": 0.55, "ask": 0.50, "mid": 0.525, "open_interest": 5000},
        ]
        c = _make_candidate(legs=crossed_legs)
        liquidity = score_candidate(c, today=self._TODAY).score_breakdown["liquidity"]
        self.assertLessEqual(liquidity, 20.0)

    def test_score_clamped_to_hundred(self):
        max_legs = [
            {"action": "SELL", "bid": 1.00, "ask": 1.00, "mid": 1.00, "open_interest": 10000},
            {"action": "BUY",  "bid": 0.50, "ask": 0.50, "mid": 0.50, "open_interest": 10000},
        ]
        c = _make_candidate(
            iv_rank=100.0,
            credit_pct_of_width=0.50,
            short_delta=0.25,
            legs=max_legs,
            next_earnings_date=date(2026, 6, 25),
        )
        scored = score_candidate(c, today=self._TODAY)
        self.assertLessEqual(scored.score, 100.0)
        self.assertAlmostEqual(scored.score, 100.0, places=2)


class TestAccountFiltersAndScoring(unittest.TestCase):
    """Tests for apply_account_filters and account-aware scoring (TCBT-4)."""

    DEFAULT_FILTERS = dict(
        max_pct_nlv_per_trade=0.05,
        bp_cap_for_new=0.50,
        concentration_block_pct=0.25,
    )

    @staticmethod
    def _state(nlv=20000.0, bp_usage_pct=0.20, exposures=None):
        return AccountState(nlv=nlv, bp_usage_pct=bp_usage_pct, existing_exposures=exposures or {})

    def test_passing_candidate_survives_all_account_filters(self):
        c = _make_candidate(symbol="AAPL", max_loss=200.0)
        survivors, rejections = apply_account_filters([c], self._state(), **self.DEFAULT_FILTERS)
        self.assertEqual(survivors, [c])
        self.assertEqual(rejections, [])

    def test_oversized_vs_nlv_rejected(self):
        c = _make_candidate(symbol="AAPL", max_loss=2000.0)
        survivors, rejections = apply_account_filters([c], self._state(), **self.DEFAULT_FILTERS)
        self.assertEqual(survivors, [])
        self.assertEqual(rejections[0].reason, "oversized_vs_nlv")
        self.assertIn("10.0% NLV above cap 5.0%", rejections[0].detail)

    def test_bp_over_cap_rejected(self):
        c = _make_candidate(symbol="AAPL", max_loss=200.0)
        survivors, rejections = apply_account_filters([c], self._state(bp_usage_pct=0.495), **self.DEFAULT_FILTERS)
        self.assertEqual(survivors, [])
        self.assertEqual(rejections[0].reason, "bp_over_cap")
        self.assertIn("post-trade BP 50.5% above cap 50.0%", rejections[0].detail)

    def test_concentration_overlap_rejected(self):
        c = _make_candidate(symbol="AAPL", max_loss=1500.0)
        state = self._state(exposures={"AAPL": 4000.0})
        filters = dict(self.DEFAULT_FILTERS, max_pct_nlv_per_trade=0.10)
        survivors, rejections = apply_account_filters([c], state, **filters)
        self.assertEqual(survivors, [])
        self.assertEqual(rejections[0].reason, "concentration_overlap")
        self.assertIn("AAPL exposure $4000 + $1500 = 27.5% NLV above cap 25.0%", rejections[0].detail)

    def test_first_failure_wins_oversized_before_bp(self):
        c = _make_candidate(symbol="AAPL", max_loss=2000.0)
        state = self._state(bp_usage_pct=0.495)
        survivors, rejections = apply_account_filters([c], state, **self.DEFAULT_FILTERS)
        self.assertEqual(rejections[0].reason, "oversized_vs_nlv")

    def test_empty_candidates_returns_empty_account_filters(self):
        survivors, rejections = apply_account_filters([], self._state(), **self.DEFAULT_FILTERS)
        self.assertEqual(survivors, [])
        self.assertEqual(rejections, [])

    def test_threshold_boundary_oversized_just_under_passes(self):
        c = _make_candidate(symbol="AAPL", max_loss=1000.0)
        survivors, _ = apply_account_filters([c], self._state(), **self.DEFAULT_FILTERS)
        self.assertEqual(survivors, [c])

    def test_threshold_boundary_concentration_no_existing_exposure_passes(self):
        c = _make_candidate(symbol="AAPL", max_loss=1000.0)
        state = self._state(bp_usage_pct=0.10, exposures={"AAPL": 4000.0})
        survivors, _ = apply_account_filters([c], state, **self.DEFAULT_FILTERS)
        self.assertEqual(survivors, [c])

    def test_account_fit_full_when_max_loss_under_two_pct(self):
        c = _make_candidate(max_loss=200.0)
        self.assertEqual(_score_account_fit(c, self._state()), 10.0)

    def test_account_fit_zero_when_max_loss_at_or_above_five_pct(self):
        c5 = _make_candidate(max_loss=1000.0)
        c10 = _make_candidate(max_loss=2000.0)
        self.assertEqual(_score_account_fit(c5, self._state()), 0.0)
        self.assertEqual(_score_account_fit(c10, self._state()), 0.0)

    def test_account_fit_linear_ramp_at_three_pct(self):
        c = _make_candidate(max_loss=600.0)
        self.assertAlmostEqual(_score_account_fit(c, self._state()), 6.6667, places=4)

    def test_account_fit_no_state_returns_ten_placeholder(self):
        c = _make_candidate(max_loss=99999.0)
        self.assertEqual(_score_account_fit(c, None), 10.0)

    def test_concentration_penalty_zero_no_existing_exposure_small_trade(self):
        c = _make_candidate(symbol="AAPL", max_loss=400.0)
        self.assertEqual(_score_concentration_penalty(c, self._state()), 0.0)

    def test_concentration_penalty_ramps_with_exposure(self):
        c = _make_candidate(symbol="AAPL", max_loss=1000.0)
        state = self._state(exposures={"AAPL": 2000.0})
        self.assertAlmostEqual(_score_concentration_penalty(c, state), 5.0, places=4)

    def test_concentration_penalty_full_at_or_above_twentyfive_pct(self):
        c = _make_candidate(symbol="AAPL", max_loss=1000.0)
        state25 = self._state(exposures={"AAPL": 4000.0})
        state40 = self._state(exposures={"AAPL": 7000.0})
        self.assertEqual(_score_concentration_penalty(c, state25), 10.0)
        self.assertEqual(_score_concentration_penalty(c, state40), 10.0)

    def test_concentration_penalty_no_state_returns_zero_placeholder(self):
        c = _make_candidate(symbol="AAPL", max_loss=99999.0)
        self.assertEqual(_score_concentration_penalty(c, None), 0.0)

    def test_score_candidate_threads_account_state_to_components(self):
        c = _make_candidate(symbol="AAPL", max_loss=600.0, iv_rank=50.0)
        state = self._state(exposures={"AAPL": 2000.0})
        scored_with = score_candidate(c, today=date(2026, 4, 26), account_state=state)
        scored_without = score_candidate(c, today=date(2026, 4, 26))
        self.assertNotEqual(scored_with.score_breakdown["account_fit"], scored_without.score_breakdown["account_fit"])
        self.assertGreater(scored_without.score, scored_with.score)

    def test_score_candidate_without_state_matches_tcbt10_baseline(self):
        c = _make_candidate(iv_rank=60.0)
        a = score_candidate(c, today=date(2026, 4, 26))
        b = score_candidate(c, today=date(2026, 4, 26), account_state=None)
        self.assertEqual(a.score, b.score)
        self.assertEqual(a.score_breakdown, b.score_breakdown)

    def test_score_candidates_propagates_state_to_each(self):
        c1 = _make_candidate(symbol="AAPL", max_loss=200.0)
        c2 = _make_candidate(symbol="MSFT", max_loss=2000.0)
        state = self._state()
        scored = score_candidates([c1, c2], today=date(2026, 4, 26), account_state=state)
        self.assertEqual(scored[0].score_breakdown["account_fit"], 10.0)
        self.assertEqual(scored[1].score_breakdown["account_fit"], 0.0)

    def test_higher_existing_exposure_lowers_score(self):
        c = _make_candidate(symbol="AAPL", max_loss=1000.0, iv_rank=50.0)
        state_low = self._state(exposures={"AAPL": 0.0})
        state_high = self._state(exposures={"AAPL": 3000.0})
        s_low = score_candidate(c, today=date(2026, 4, 26), account_state=state_low).score
        s_high = score_candidate(c, today=date(2026, 4, 26), account_state=state_high).score
        self.assertGreater(s_low, s_high)

    # Non-positive NLV guards (Codex review on PR #15)

    def test_zero_nlv_rejects_all_candidates_with_reason(self):
        candidates = [
            _make_candidate(symbol="AAPL", max_loss=200.0),
            _make_candidate(symbol="MSFT", max_loss=300.0),
        ]
        state = AccountState(nlv=0.0, bp_usage_pct=0.0, existing_exposures={})
        survivors, rejections = apply_account_filters(candidates, state, **self.DEFAULT_FILTERS)
        self.assertEqual(survivors, [])
        self.assertEqual(len(rejections), 2)
        self.assertEqual({r.reason for r in rejections}, {"non_positive_nlv"})
        self.assertEqual([r.symbol for r in rejections], ["AAPL", "MSFT"])

    def test_negative_nlv_rejects_all_candidates_with_reason(self):
        c = _make_candidate(symbol="AAPL", max_loss=200.0)
        state = AccountState(nlv=-500.0, bp_usage_pct=0.0, existing_exposures={})
        survivors, rejections = apply_account_filters([c], state, **self.DEFAULT_FILTERS)
        self.assertEqual(survivors, [])
        self.assertEqual(len(rejections), 1)
        self.assertEqual(rejections[0].reason, "non_positive_nlv")
        self.assertIn("non-positive", rejections[0].detail)

    def test_zero_nlv_account_fit_returns_placeholder(self):
        c = _make_candidate(max_loss=99999.0)
        state = AccountState(nlv=0.0, bp_usage_pct=0.0)
        self.assertEqual(_score_account_fit(c, state), 10.0)

    def test_zero_nlv_concentration_penalty_returns_zero(self):
        c = _make_candidate(symbol="AAPL", max_loss=99999.0)
        state = AccountState(nlv=0.0, bp_usage_pct=0.0, existing_exposures={"AAPL": 50000.0})
        self.assertEqual(_score_concentration_penalty(c, state), 0.0)

    def test_zero_nlv_score_candidate_does_not_raise(self):
        c = _make_candidate(iv_rank=50.0, max_loss=1000.0)
        state = AccountState(nlv=0.0, bp_usage_pct=0.0)
        scored = score_candidate(c, today=date(2026, 4, 26), account_state=state)
        self.assertEqual(scored.score_breakdown["account_fit"], 10.0)
        self.assertEqual(scored.score_breakdown["concentration_penalty"], 0.0)


def _mk_top_candidate(symbol: str, score: float, structure: str = "BULL_PUT_SPREAD") -> Candidate:
    """Build a minimal Candidate for top-selection tests."""
    return Candidate(
        symbol=symbol,
        structure=structure,
        expiration=date(2026, 6, 19),
        dte=45,
        width=5.0,
        credit=1.50,
        max_loss=350.0,
        credit_pct_of_width=0.30,
        short_delta=0.20,
        pop_estimate=0.75,
        breakevens=[148.50],
        net_greeks={},
        legs=[],
        researcher_score=80.0,
        researcher_score_breakdown={},
        context=SymbolContext(symbol=symbol),
        score=score,
        score_breakdown={"liquidity": score * 0.4},
        summary_reason=f"{symbol} test",
    )


class TestSelectTopPerSymbol(unittest.TestCase):
    """Tests for _select_top_per_symbol helper."""

    def test_select_top_empty_returns_empty(self):
        from agents.trade_ranker import _select_top_per_symbol
        self.assertEqual(_select_top_per_symbol([], 3), [])

    def test_select_top_one_per_symbol(self):
        from agents.trade_ranker import _select_top_per_symbol
        candidates = [_mk_top_candidate("A", 90), _mk_top_candidate("B", 80), _mk_top_candidate("C", 70)]
        result = _select_top_per_symbol(candidates, 3)
        self.assertEqual([c.symbol for c in result], ["A", "B", "C"])

    def test_select_top_picks_max_score_within_symbol(self):
        from agents.trade_ranker import _select_top_per_symbol
        candidates = [
            _mk_top_candidate("A", 60),
            _mk_top_candidate("A", 90),
            _mk_top_candidate("B", 70),
        ]
        result = _select_top_per_symbol(candidates, 3)
        self.assertEqual(len(result), 2)
        symbols_to_scores = {c.symbol: c.score for c in result}
        self.assertEqual(symbols_to_scores["A"], 90)
        self.assertEqual(symbols_to_scores["B"], 70)

    def test_select_top_caps_at_n(self):
        from agents.trade_ranker import _select_top_per_symbol
        candidates = [_mk_top_candidate(s, 90 - i * 10) for i, s in enumerate(["A", "B", "C", "D", "E"])]
        result = _select_top_per_symbol(candidates, 3)
        self.assertEqual(len(result), 3)
        self.assertEqual([c.symbol for c in result], ["A", "B", "C"])

    def test_select_top_sorts_by_score_desc_with_symbol_tiebreak(self):
        from agents.trade_ranker import _select_top_per_symbol
        candidates = [_mk_top_candidate("C", 80), _mk_top_candidate("A", 80), _mk_top_candidate("B", 80)]
        result = _select_top_per_symbol(candidates, 3)
        self.assertEqual([c.symbol for c in result], ["A", "B", "C"])

    def test_select_top_zero_returns_empty(self):
        from agents.trade_ranker import _select_top_per_symbol
        candidates = [_mk_top_candidate("A", 90)]
        self.assertEqual(_select_top_per_symbol(candidates, 0), [])

    def test_select_top_negative_returns_empty(self):
        from agents.trade_ranker import _select_top_per_symbol
        candidates = [_mk_top_candidate("A", 90)]
        self.assertEqual(_select_top_per_symbol(candidates, -1), [])


class TestFilterByIvr(unittest.TestCase):
    """Tests for filter_by_ivr helper."""

    def test_keeps_at_or_above_threshold(self):
        contexts = [SymbolContext(symbol="A", iv_rank=30.0), SymbolContext(symbol="B", iv_rank=80.0)]
        passing, warnings = filter_by_ivr(contexts, 30.0)
        self.assertEqual([c.symbol for c in passing], ["A", "B"])
        self.assertEqual(warnings, [])

    def test_drops_below_threshold(self):
        contexts = [SymbolContext(symbol="A", iv_rank=15.0), SymbolContext(symbol="B", iv_rank=50.0)]
        passing, warnings = filter_by_ivr(contexts, 30.0)
        self.assertEqual([c.symbol for c in passing], ["B"])
        self.assertEqual(warnings, ["skipped 1 symbols below IVR 30"])

    def test_drops_none_iv_rank(self):
        contexts = [SymbolContext(symbol="A", iv_rank=None), SymbolContext(symbol="B", iv_rank=50.0)]
        passing, warnings = filter_by_ivr(contexts, 30.0)
        self.assertEqual([c.symbol for c in passing], ["B"])
        self.assertEqual(warnings, ["skipped 1 symbols with no IVR data"])

    def test_aggregates_multiple_skips(self):
        contexts = [
            SymbolContext(symbol="A", iv_rank=10.0),
            SymbolContext(symbol="B", iv_rank=None),
            SymbolContext(symbol="C", iv_rank=20.0),
            SymbolContext(symbol="D", iv_rank=None),
            SymbolContext(symbol="E", iv_rank=60.0),
        ]
        passing, warnings = filter_by_ivr(contexts, 30.0)
        self.assertEqual([c.symbol for c in passing], ["E"])
        self.assertIn("skipped 2 symbols below IVR 30", warnings)
        self.assertIn("skipped 2 symbols with no IVR data", warnings)

    def test_empty_input_returns_empty(self):
        passing, warnings = filter_by_ivr([], 30.0)
        self.assertEqual(passing, [])
        self.assertEqual(warnings, [])

    def test_threshold_zero_keeps_all_with_data(self):
        contexts = [SymbolContext(symbol="A", iv_rank=0.0), SymbolContext(symbol="B", iv_rank=None)]
        passing, _ = filter_by_ivr(contexts, 0.0)
        self.assertEqual([c.symbol for c in passing], ["A"])


class TestLoadThresholds(unittest.TestCase):
    """Tests for _load_thresholds helper."""

    @patch("agents.trade_ranker.settings")
    def test_load_thresholds_returns_all_keys(self, mock_settings):
        from agents.trade_ranker import _load_thresholds
        mock_settings.get.side_effect = lambda key: f"value_for_{key}"
        result = _load_thresholds()
        self.assertEqual(
            set(result.keys()),
            {
                "blackout_days",
                "min_dte",
                "max_dte",
                "min_open_interest",
                "max_spread_pct",
                "max_per_symbol",
                "max_pct_nlv_per_trade",
                "bp_cap_for_new",
                "concentration_block_pct",
                "min_ivr",
                "research_concurrency",
                "research_timeout_seconds",
            },
        )
        expected_calls = [
            "bt_earnings_blackout_days",
            "bt_min_dte",
            "bt_max_dte",
            "bt_min_open_interest",
            "bt_max_spread_pct",
            "bt_max_per_symbol",
            "bt_max_pct_nlv_per_trade",
            "bt_bp_cap_for_new",
            "bt_concentration_overlap_block_pct",
            "bt_min_ivr",
            "bt_research_concurrency",
            "bt_research_timeout_seconds",
        ]
        actual_calls = [call.args[0] for call in mock_settings.get.call_args_list]
        self.assertEqual(set(actual_calls), set(expected_calls))


class TestRunBestTradesIntegration(unittest.IsolatedAsyncioTestCase):
    """End-to-end pipeline tests for run_best_trades."""

    def setUp(self):
        from utils.settings import DEFAULTS
        self._settings_patcher = patch("agents.trade_ranker.settings")
        mock_settings = self._settings_patcher.start()
        mock_settings.get.side_effect = lambda key: DEFAULTS.get(key)

    def tearDown(self):
        self._settings_patcher.stop()

    @staticmethod
    def _passing_candidate(symbol: str = "AAPL", score: float = 0.0) -> Candidate:
        return _mk_top_candidate(symbol, score)

    @patch("agents.trade_ranker.scan_watchlists", new_callable=AsyncMock)
    async def test_empty_scan_returns_no_trades(self, mock_scan):
        from agents.trade_ranker import run_best_trades
        mock_scan.return_value = ([], ["no symbols"])
        result = await run_best_trades(MagicMock(), watchlists=["X"])
        self.assertEqual(result["top"], [])
        self.assertEqual(result["rejected"], [])
        self.assertEqual(result["warnings"], ["no symbols"])
        self.assertIsNone(result["account"])

    @patch("agents.trade_ranker.generate_candidates", new_callable=AsyncMock)
    @patch("agents.trade_ranker.scan_watchlists", new_callable=AsyncMock)
    async def test_no_candidates_returns_no_trades(self, mock_scan, mock_gen):
        from agents.trade_ranker import run_best_trades
        mock_scan.return_value = ([SymbolContext(symbol="AAPL", iv_rank=99.0)], [])
        mock_gen.return_value = ([], [Rejection(symbol="AAPL", reason="no_chains", detail="none")])
        result = await run_best_trades(MagicMock(), watchlists=["X"])
        self.assertEqual(result["top"], [])
        self.assertEqual(len(result["rejected"]), 1)
        self.assertEqual(result["rejected"][0]["reason"], "no_chains")

    @patch("agents.trade_ranker.apply_quality_gates")
    @patch("agents.trade_ranker.generate_candidates", new_callable=AsyncMock)
    @patch("agents.trade_ranker.scan_watchlists", new_callable=AsyncMock)
    async def test_all_rejected_by_gates_returns_no_trades(self, mock_scan, mock_gen, mock_gates):
        from agents.trade_ranker import run_best_trades
        mock_scan.return_value = ([SymbolContext(symbol="AAPL", iv_rank=99.0)], [])
        candidate = self._passing_candidate()
        mock_gen.return_value = ([candidate], [])
        mock_gates.return_value = ([], [Rejection(symbol="AAPL", reason="earnings_blackout", detail="2 days")])
        result = await run_best_trades(MagicMock(), watchlists=["X"])
        self.assertEqual(result["top"], [])
        self.assertEqual(result["rejected"][0]["reason"], "earnings_blackout")

    @patch("agents.trade_ranker.apply_quality_gates")
    @patch("agents.trade_ranker.generate_candidates", new_callable=AsyncMock)
    @patch("agents.trade_ranker.scan_watchlists", new_callable=AsyncMock)
    async def test_basic_pipeline_returns_scored_top(self, mock_scan, mock_gen, mock_gates):
        from agents.trade_ranker import run_best_trades
        mock_scan.return_value = ([SymbolContext(symbol="AAPL", iv_rank=99.0)], [])
        candidate = self._passing_candidate("AAPL", 75.0)
        mock_gen.return_value = ([candidate], [])
        mock_gates.return_value = ([candidate], [])
        result = await run_best_trades(MagicMock(), watchlists=["X"])
        self.assertEqual(len(result["top"]), 1)
        self.assertEqual(result["top"][0]["symbol"], "AAPL")
        self.assertIsNone(result["account"])
        self.assertIsInstance(result["top"][0]["score"], float)

    @patch("agents.trade_ranker.apply_quality_gates")
    @patch("agents.trade_ranker.generate_candidates", new_callable=AsyncMock)
    @patch("agents.trade_ranker.scan_watchlists", new_callable=AsyncMock)
    async def test_top_selection_dedupes_by_symbol(self, mock_scan, mock_gen, mock_gates):
        from agents.trade_ranker import run_best_trades
        mock_scan.return_value = ([SymbolContext(symbol="AAPL", iv_rank=99.0)], [])
        c1 = self._passing_candidate("AAPL", 60.0)
        c2 = self._passing_candidate("AAPL", 90.0)
        c3 = self._passing_candidate("AAPL", 70.0)
        mock_gen.return_value = ([c1, c2, c3], [])
        mock_gates.return_value = ([c1, c2, c3], [])
        result = await run_best_trades(MagicMock(), watchlists=["X"])
        self.assertEqual(len(result["top"]), 1)
        self.assertEqual(result["top"][0]["symbol"], "AAPL")

    @patch("agents.trade_ranker.apply_quality_gates")
    @patch("agents.trade_ranker.generate_candidates", new_callable=AsyncMock)
    @patch("agents.trade_ranker.scan_watchlists", new_callable=AsyncMock)
    async def test_top_selection_caps_at_n(self, mock_scan, mock_gen, mock_gates):
        from agents.trade_ranker import run_best_trades
        mock_scan.return_value = ([SymbolContext(symbol="AAPL", iv_rank=99.0)], [])
        candidates = [self._passing_candidate(s, 100 - i * 10) for i, s in enumerate(["A", "B", "C", "D", "E"])]
        mock_gen.return_value = (candidates, [])
        mock_gates.return_value = (candidates, [])
        result = await run_best_trades(MagicMock(), watchlists=["X"], top=3)
        self.assertEqual(len(result["top"]), 3)

    @patch("agents.trade_ranker.score_candidates")
    @patch("agents.trade_ranker.apply_quality_gates")
    @patch("agents.trade_ranker.generate_candidates", new_callable=AsyncMock)
    @patch("agents.trade_ranker.scan_watchlists", new_callable=AsyncMock)
    async def test_top_selection_sorts_by_score_descending(self, mock_scan, mock_gen, mock_gates, mock_score):
        from agents.trade_ranker import run_best_trades
        mock_scan.return_value = ([SymbolContext(symbol="AAPL", iv_rank=99.0)], [])
        candidates = [self._passing_candidate(s, 50) for s in ["X", "Y", "Z"]]
        mock_gen.return_value = (candidates, [])
        mock_gates.return_value = (candidates, [])
        mock_score.return_value = [
            self._passing_candidate("X", 10),
            self._passing_candidate("Y", 90),
            self._passing_candidate("Z", 50),
        ]
        result = await run_best_trades(MagicMock(), watchlists=["W"])
        self.assertEqual([t["symbol"] for t in result["top"]], ["Y", "Z", "X"])

    @patch("agents.trade_ranker.score_candidates")
    @patch("agents.trade_ranker.apply_quality_gates")
    @patch("agents.trade_ranker.generate_candidates", new_callable=AsyncMock)
    @patch("agents.trade_ranker.scan_watchlists", new_callable=AsyncMock)
    async def test_top_selection_tie_breaks_by_symbol_ascending(self, mock_scan, mock_gen, mock_gates, mock_score):
        from agents.trade_ranker import run_best_trades
        mock_scan.return_value = ([SymbolContext(symbol="AAPL", iv_rank=99.0)], [])
        candidates = [self._passing_candidate(s, 75) for s in ["B", "A", "C"]]
        mock_gen.return_value = (candidates, [])
        mock_gates.return_value = (candidates, [])
        mock_score.return_value = [
            self._passing_candidate("B", 75),
            self._passing_candidate("A", 75),
            self._passing_candidate("C", 75),
        ]
        result = await run_best_trades(MagicMock(), watchlists=["W"])
        self.assertEqual([t["symbol"] for t in result["top"]], ["A", "B", "C"])

    @patch("agents.trade_ranker._build_account_state", new_callable=AsyncMock)
    @patch("agents.trade_ranker.apply_account_filters")
    @patch("agents.trade_ranker.apply_quality_gates")
    @patch("agents.trade_ranker.generate_candidates", new_callable=AsyncMock)
    @patch("agents.trade_ranker.scan_watchlists", new_callable=AsyncMock)
    async def test_account_state_provided_runs_account_filters(
        self, mock_scan, mock_gen, mock_gates, mock_account_filters, mock_build_state
    ):
        from agents.trade_ranker import run_best_trades
        mock_scan.return_value = ([SymbolContext(symbol="AAPL", iv_rank=99.0)], [])
        candidate = self._passing_candidate("AAPL", 75.0)
        mock_gen.return_value = ([candidate], [])
        mock_gates.return_value = ([candidate], [])
        mock_state = AccountState(nlv=50000.0, bp_usage_pct=0.30, existing_exposures={})
        mock_build_state.return_value = mock_state
        mock_account_filters.return_value = ([candidate], [])
        result = await run_best_trades(MagicMock(), watchlists=["X"], account_number="ABC123")
        mock_account_filters.assert_called_once()
        args, kwargs = mock_account_filters.call_args
        self.assertEqual(args[1], mock_state)
        self.assertEqual(result["account"], {"nlv": 50000.0, "bp_usage_pct": 0.30})

    @patch("agents.trade_ranker.apply_account_filters")
    @patch("agents.trade_ranker.apply_quality_gates")
    @patch("agents.trade_ranker.generate_candidates", new_callable=AsyncMock)
    @patch("agents.trade_ranker.scan_watchlists", new_callable=AsyncMock)
    async def test_account_state_skipped_when_no_account_number(
        self, mock_scan, mock_gen, mock_gates, mock_account_filters
    ):
        from agents.trade_ranker import run_best_trades
        mock_scan.return_value = ([SymbolContext(symbol="AAPL", iv_rank=99.0)], [])
        candidate = self._passing_candidate("AAPL", 75.0)
        mock_gen.return_value = ([candidate], [])
        mock_gates.return_value = ([candidate], [])
        result = await run_best_trades(MagicMock(), watchlists=["X"], account_number=None)
        mock_account_filters.assert_not_called()
        self.assertIsNone(result["account"])

    @patch("agents.trade_ranker._build_account_state", new_callable=AsyncMock)
    @patch("agents.trade_ranker.apply_account_filters")
    @patch("agents.trade_ranker.apply_quality_gates")
    @patch("agents.trade_ranker.generate_candidates", new_callable=AsyncMock)
    @patch("agents.trade_ranker.scan_watchlists", new_callable=AsyncMock)
    async def test_build_account_state_failure_degrades_gracefully(
        self, mock_scan, mock_gen, mock_gates, mock_account_filters, mock_build_state
    ):
        from agents.trade_ranker import run_best_trades
        mock_scan.return_value = ([SymbolContext(symbol="AAPL", iv_rank=99.0)], [])
        candidate = self._passing_candidate("AAPL", 75.0)
        mock_gen.return_value = ([candidate], [])
        mock_gates.return_value = ([candidate], [])
        mock_build_state.side_effect = RuntimeError("api down")
        result = await run_best_trades(MagicMock(), watchlists=["X"], account_number="ABC123")
        mock_account_filters.assert_not_called()
        self.assertIsNone(result["account"])
        self.assertTrue(any("account state unavailable" in w and "api down" in w for w in result["warnings"]))
        self.assertEqual(len(result["top"]), 1)

    @patch("agents.trade_ranker.apply_quality_gates")
    @patch("agents.trade_ranker.generate_candidates", new_callable=AsyncMock)
    @patch("agents.trade_ranker.scan_watchlists", new_callable=AsyncMock)
    async def test_result_shape_has_canonical_keys(self, mock_scan, mock_gen, mock_gates):
        from agents.trade_ranker import run_best_trades
        mock_scan.return_value = ([SymbolContext(symbol="AAPL", iv_rank=99.0)], [])
        candidate = self._passing_candidate("AAPL", 75.0)
        mock_gen.return_value = ([candidate], [])
        mock_gates.return_value = ([candidate], [])
        result = await run_best_trades(MagicMock(), watchlists=["X"])
        self.assertGreaterEqual(set(result.keys()), {"top", "rejected", "warnings", "watchlists", "account"})

    @patch("agents.trade_ranker.generate_candidates", new_callable=AsyncMock)
    @patch("agents.trade_ranker.scan_watchlists", new_callable=AsyncMock)
    async def test_rejected_items_have_symbol_reason_detail_only(self, mock_scan, mock_gen):
        from agents.trade_ranker import run_best_trades
        mock_scan.return_value = ([SymbolContext(symbol="AAPL", iv_rank=99.0)], [])
        mock_gen.return_value = ([], [Rejection(symbol="AAPL", reason="no_chains", detail="none")])
        result = await run_best_trades(MagicMock(), watchlists=["X"])
        for item in result["rejected"]:
            self.assertEqual(set(item.keys()), {"symbol", "reason", "detail"})

    @patch("agents.trade_ranker.scan_watchlists", new_callable=AsyncMock)
    async def test_warnings_aggregated_from_scan(self, mock_scan):
        from agents.trade_ranker import run_best_trades
        mock_scan.return_value = ([], ["w1", "w2"])
        result = await run_best_trades(MagicMock(), watchlists=["X"])
        self.assertEqual(result["warnings"], ["w1", "w2"])

    @patch("agents.trade_ranker.score_candidates")
    @patch("agents.trade_ranker.apply_quality_gates")
    @patch("agents.trade_ranker.generate_candidates", new_callable=AsyncMock)
    @patch("agents.trade_ranker.scan_watchlists", new_callable=AsyncMock)
    async def test_today_parameter_threaded_to_gates_and_scoring(
        self, mock_scan, mock_gen, mock_gates, mock_score
    ):
        from agents.trade_ranker import run_best_trades
        mock_scan.return_value = ([SymbolContext(symbol="AAPL", iv_rank=99.0)], [])
        candidate = self._passing_candidate("AAPL", 75.0)
        mock_gen.return_value = ([candidate], [])
        mock_gates.return_value = ([candidate], [])
        mock_score.return_value = [candidate]
        target_date = date(2026, 5, 1)
        await run_best_trades(MagicMock(), watchlists=["X"], today=target_date)
        gates_kwargs = mock_gates.call_args.kwargs
        self.assertEqual(gates_kwargs["today"], target_date)
        score_kwargs = mock_score.call_args.kwargs
        self.assertEqual(score_kwargs["today"], target_date)

    @patch("agents.trade_ranker.apply_quality_gates")
    @patch("agents.trade_ranker.generate_candidates", new_callable=AsyncMock)
    @patch("agents.trade_ranker.scan_watchlists", new_callable=AsyncMock)
    async def test_top_zero_returns_empty_top(self, mock_scan, mock_gen, mock_gates):
        from agents.trade_ranker import run_best_trades
        mock_scan.return_value = ([SymbolContext(symbol="AAPL", iv_rank=99.0)], [])
        candidate = self._passing_candidate("AAPL", 75.0)
        mock_gen.return_value = ([candidate], [])
        mock_gates.return_value = ([candidate], [])
        result = await run_best_trades(MagicMock(), watchlists=["X"], top=0)
        self.assertEqual(result["top"], [])

    @patch("agents.trade_ranker.scan_watchlists", new_callable=AsyncMock)
    async def test_default_watchlists_used_when_none(self, mock_scan):
        from agents.trade_ranker import run_best_trades, DEFAULT_WATCHLISTS
        mock_scan.return_value = ([], [])
        await run_best_trades(MagicMock(), watchlists=None)
        called_args = mock_scan.await_args
        self.assertEqual(called_args.args[1], list(DEFAULT_WATCHLISTS))

    @patch("agents.trade_ranker.generate_candidates", new_callable=AsyncMock)
    @patch("agents.trade_ranker.scan_watchlists", new_callable=AsyncMock)
    async def test_ivr_prefilter_drops_low_ivr_before_research(self, mock_scan, mock_gen):
        from agents.trade_ranker import run_best_trades
        mock_scan.return_value = (
            [
                SymbolContext(symbol="AAPL", iv_rank=15.0),
                SymbolContext(symbol="MSFT", iv_rank=50.0),
                SymbolContext(symbol="UNKN", iv_rank=None),
            ],
            [],
        )
        mock_gen.return_value = ([], [])
        result = await run_best_trades(MagicMock(), watchlists=["X"])
        mock_gen.assert_awaited_once()
        passed_contexts = mock_gen.await_args.args[1]
        self.assertEqual([c.symbol for c in passed_contexts], ["MSFT"])
        self.assertTrue(any("below IVR 30" in w for w in result["warnings"]))
        self.assertTrue(any("no IVR data" in w for w in result["warnings"]))

    @patch("agents.trade_ranker.scan_watchlists", new_callable=AsyncMock)
    async def test_scan_failure_degrades_gracefully(self, mock_scan):
        from agents.trade_ranker import run_best_trades
        mock_scan.side_effect = RuntimeError("api down")
        result = await run_best_trades(MagicMock(), watchlists=["X"])
        self.assertEqual(result["top"], [])
        self.assertEqual(result["rejected"], [])
        self.assertIsNone(result["account"])
        self.assertTrue(any("watchlist scan failed" in w and "api down" in w for w in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
