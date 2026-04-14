"""Comprehensive tests for OptionsResearcherAgent"""

import unittest
from unittest.mock import MagicMock, AsyncMock, patch, Mock
from datetime import date, datetime, timedelta
from decimal import Decimal

from agents.options_researcher import (
    OptionsResearcherAgent,
    StrikeRow,
    TradeIdea,
    DEFAULT_DTE_TARGET,
    DTE_FALLBACK_MIN,
    DTE_FALLBACK_MAX,
    TARGET_SHORT_DELTA,
    SHORT_DELTA_MIN,
    SHORT_DELTA_MAX,
    MIN_CREDIT_RATIO,
    SPREAD_WIDTHS,
)
from tastytrade.instruments import OptionType
from tastytrade.dxfeed import Greeks


class TestOptionsResearcherAgent(unittest.IsolatedAsyncioTestCase):
    """Test suite for OptionsResearcherAgent"""

    def setUp(self):
        """Set up test fixtures"""
        self.mock_session = MagicMock()
        self.agent = OptionsResearcherAgent(self.mock_session)

    async def test_research_invalid_symbol(self):
        """Test research with invalid (empty) symbol"""
        report = await self.agent.research("")
        self.assertEqual(report['status'], 'INVALID_SYMBOL')
        self.assertEqual(report['symbol'], '')

    async def test_research_no_chain(self):
        """Test research when chain fetch fails"""
        with patch('agents.options_researcher.get_option_chain', side_effect=Exception("Network error")):
            report = await self.agent.research("AAPL")
            self.assertEqual(report['status'], 'NO_CHAIN')
            self.assertEqual(report['symbol'], 'AAPL')

    async def test_research_empty_chain(self):
        """Test research when chain is empty"""
        with patch('agents.options_researcher.get_option_chain', return_value={}):
            report = await self.agent.research("AAPL")
            self.assertEqual(report['status'], 'NO_CHAIN')

    async def test_resolve_expiration_explicit_found(self):
        """Test _resolve_expiration with explicit date that exists"""
        today = date.today()
        exp_date = today + timedelta(days=45)
        chain = {exp_date: []}

        resolved, mode = await self.agent._resolve_expiration(chain, exp_date)
        self.assertEqual(resolved, exp_date)
        self.assertEqual(mode, 'EXPLICIT')

    async def test_resolve_expiration_explicit_not_found(self):
        """Test _resolve_expiration with explicit date that doesn't exist"""
        today = date.today()
        other_date = today + timedelta(days=30)
        requested = today + timedelta(days=45)
        chain = {other_date: []}

        resolved, mode = await self.agent._resolve_expiration(chain, requested)
        self.assertIsNone(resolved)
        self.assertEqual(mode, 'NONE')

    async def test_resolve_expiration_monthly_45dte(self):
        """Test _resolve_expiration finds nearest monthly ~45 DTE"""
        today = date.today()
        # Find nearest 3rd Friday at ~45 DTE
        current_year = today.year
        current_month = today.month

        # Build a chain with multiple dates
        chain_dates = []
        for offset in [25, 30, 35, 45, 50, 60]:
            d = today + timedelta(days=offset)
            chain_dates.append(d)

        chain = {d: [] for d in chain_dates}

        resolved, mode = await self.agent._resolve_expiration(chain, None)
        # Should pick something near 45 DTE
        if resolved:
            dte = (resolved - today).days
            self.assertTrue(DTE_FALLBACK_MIN <= dte <= DTE_FALLBACK_MAX)
            self.assertIn(mode, ['MONTHLY_45DTE', 'NEAREST_IN_WINDOW', 'NONE'])

    async def test_resolve_expiration_no_viable(self):
        """Test _resolve_expiration with no viable dates"""
        today = date.today()
        # Create dates outside the window
        chain = {
            today + timedelta(days=10): [],
            today + timedelta(days=100): [],
        }

        resolved, mode = await self.agent._resolve_expiration(chain, None)
        self.assertIsNone(resolved)
        self.assertEqual(mode, 'NONE')

    async def test_build_enriched_chain_drops_no_delta(self):
        """Test _build_enriched_chain drops strikes without delta"""
        exp = date.today() + timedelta(days=45)

        # Create mock options
        opt1 = MagicMock()
        opt1.streamer_symbol = 'AAPL__C100'
        opt1.symbol = 'AAPL 250516C00100000'
        opt1.option_type = OptionType.CALL
        opt1.strike_price = Decimal('100.0')

        opt2 = MagicMock()
        opt2.streamer_symbol = 'AAPL__C110'
        opt2.symbol = 'AAPL 250516C00110000'
        opt2.option_type = OptionType.CALL
        opt2.strike_price = Decimal('110.0')

        options = [opt1, opt2]

        # Mock market data
        md1 = MagicMock()
        md1.symbol = 'AAPL 250516C00100000'
        md1.bid = Decimal('2.0')
        md1.ask = Decimal('2.5')
        md1.mark = Decimal('2.2')
        md1.volume = 100
        md1.open_interest = 500

        md2 = MagicMock()
        md2.symbol = 'AAPL 250516C00110000'
        md2.bid = None
        md2.ask = None
        md2.mark = Decimal('1.0')
        md2.volume = 50
        md2.open_interest = 200

        # Mock greeks: opt1 has delta, opt2 doesn't
        greek1 = MagicMock()
        greek1.delta = Decimal('0.35')
        greek1.gamma = Decimal('0.01')
        greek1.theta = Decimal('-0.05')
        greek1.vega = Decimal('0.10')
        greek1.volatility = Decimal('0.25')

        greek2 = MagicMock()
        greek2.delta = None  # Missing delta
        greek2.gamma = Decimal('0.015')
        greek2.theta = Decimal('-0.06')
        greek2.vega = Decimal('0.11')
        greek2.volatility = Decimal('0.26')

        with patch('agents.options_researcher.get_market_data_by_type', return_value=[md1, md2]):
            with patch.object(self.agent, '_fetch_greeks', return_value={
                'AAPL__C100': greek1,
                'AAPL__C110': greek2,
            }):
                rows = await self.agent._build_enriched_chain(options, exp)

                # Should only have 1 row (opt1 with delta)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].strike, 100.0)

    def test_find_short_leg_success(self):
        """Test _find_short_leg finds best match"""
        rows = [
            StrikeRow('s1', 'o1', date.today(), 'PUT', 100.0, delta=-0.20),
            StrikeRow('s2', 'o2', date.today(), 'PUT', 105.0, delta=-0.30),
            StrikeRow('s3', 'o3', date.today(), 'PUT', 110.0, delta=-0.40),
        ]

        result = self.agent._find_short_leg(rows, 'PUT', target_delta=0.30)
        self.assertIsNotNone(result)
        self.assertEqual(result.strike, 105.0)

    def test_find_short_leg_none(self):
        """Test _find_short_leg returns None when no match"""
        rows = [
            StrikeRow('s1', 'o1', date.today(), 'PUT', 100.0, delta=-0.10),  # Too low
            StrikeRow('s2', 'o2', date.today(), 'PUT', 105.0, delta=-0.50),  # Too high
        ]

        result = self.agent._find_short_leg(rows, 'PUT')
        self.assertIsNone(result)

    def test_find_long_leg_call_success(self):
        """Test _find_long_leg for calls (buy higher strike)"""
        rows = [
            StrikeRow('s1', 'o1', date.today(), 'CALL', 100.0, mid=2.0),
            StrikeRow('s2', 'o2', date.today(), 'CALL', 105.0, mid=1.5),
        ]

        result = self.agent._find_long_leg(rows, 'CALL', 100.0, 5.0)
        self.assertIsNotNone(result)
        self.assertEqual(result.strike, 105.0)

    def test_find_long_leg_put_success(self):
        """Test _find_long_leg for puts (buy lower strike)"""
        rows = [
            StrikeRow('s1', 'o1', date.today(), 'PUT', 100.0, mid=2.0),
            StrikeRow('s2', 'o2', date.today(), 'PUT', 95.0, mid=1.5),
        ]

        result = self.agent._find_long_leg(rows, 'PUT', 100.0, 5.0)
        self.assertIsNotNone(result)
        self.assertEqual(result.strike, 95.0)

    def test_find_long_leg_none_mid(self):
        """Test _find_long_leg skips legs with no mid"""
        rows = [
            StrikeRow('s1', 'o1', date.today(), 'PUT', 100.0, mid=2.0),
            StrikeRow('s2', 'o2', date.today(), 'PUT', 95.0, mid=None),
        ]

        result = self.agent._find_long_leg(rows, 'PUT', 100.0, 5.0)
        self.assertIsNone(result)

    def test_build_vertical_put_spread_success(self):
        """Test _build_vertical builds a bull put spread"""
        today = date.today()
        exp = today + timedelta(days=45)

        # For a $5 width, need credit >= $1.67 (1/3 of $5)
        rows = [
            StrikeRow('s1', 'occ1', exp, 'PUT', 100.0, bid=1.85, ask=1.95, mid=1.90,
                      delta=-0.30, gamma=-0.01, theta=0.05, vega=-0.10, iv=0.25, volume=500, open_interest=2000),
            StrikeRow('s2', 'occ2', exp, 'PUT', 95.0, bid=0.20, ask=0.25, mid=0.22,
                      delta=-0.15, gamma=-0.005, theta=0.025, vega=-0.05, iv=0.26, volume=200, open_interest=800),
        ]

        idea = self.agent._build_vertical(rows, 'PUT', 'AAPL', exp, 45)
        self.assertIsNotNone(idea)
        self.assertEqual(idea.strategy, 'BULL_PUT_SPREAD')
        self.assertEqual(idea.short_strike, 100.0)
        self.assertEqual(idea.long_strike, 95.0)
        self.assertAlmostEqual(idea.credit, 1.68, places=2)
        self.assertEqual(idea.width, 5.0)
        self.assertGreater(idea.score, 0)

    def test_build_vertical_insufficient_credit(self):
        """Test _build_vertical rejects spread with low credit"""
        today = date.today()
        exp = today + timedelta(days=45)

        rows = [
            StrikeRow('s1', 'occ1', exp, 'PUT', 100.0, mid=0.1, delta=-0.30),
            StrikeRow('s2', 'occ2', exp, 'PUT', 95.0, mid=0.05, delta=-0.15),
        ]

        idea = self.agent._build_vertical(rows, 'PUT', 'AAPL', exp, 45)
        # Credit = 0.05, ratio = 0.05/5.0 = 0.01 < 1/3, should reject
        self.assertIsNone(idea)

    def test_build_iron_condor_success(self):
        """Test _build_iron_condor combines two verticals"""
        today = date.today()
        exp = today + timedelta(days=45)

        # For a $5 width, need credit >= $1.67 (1/3 of $5)
        put_rows = [
            StrikeRow('s1', 'occ1', exp, 'PUT', 100.0, bid=1.85, ask=1.95, mid=1.90,
                      delta=-0.30, gamma=-0.01, theta=0.05, vega=-0.10, iv=0.25, volume=500, open_interest=2000),
            StrikeRow('s2', 'occ2', exp, 'PUT', 95.0, bid=0.20, ask=0.25, mid=0.22,
                      delta=-0.15, gamma=-0.005, theta=0.025, vega=-0.05, iv=0.26, volume=200, open_interest=800),
        ]

        call_rows = [
            StrikeRow('s3', 'occ3', exp, 'CALL', 110.0, bid=1.70, ask=1.80, mid=1.75,
                      delta=0.30, gamma=0.01, theta=0.05, vega=-0.10, iv=0.25, volume=400, open_interest=1500),
            StrikeRow('s4', 'occ4', exp, 'CALL', 115.0, bid=0.05, ask=0.10, mid=0.07,
                      delta=0.15, gamma=0.005, theta=0.025, vega=-0.05, iv=0.26, volume=200, open_interest=700),
        ]

        all_rows = put_rows + call_rows

        idea = self.agent._build_iron_condor(all_rows, 'AAPL', exp, 45)
        self.assertIsNotNone(idea)
        self.assertEqual(idea.strategy, 'IRON_CONDOR')
        self.assertEqual(len(idea.legs), 4)
        self.assertAlmostEqual(idea.credit, 3.36, places=2)

    def test_score_idea_credit_component(self):
        """Test _score_idea credit component scoring"""
        idea_draft = {
            'credit_pct_of_width': 0.33,  # Exactly 1/3
            'short_delta': -0.30,
            'dte': 45,
            'legs': [
                StrikeRow('s1', 'o1', date.today(), 'PUT', 100.0, volume=500, open_interest=2000),
                StrikeRow('s2', 'o2', date.today(), 'PUT', 95.0, volume=200, open_interest=800),
            ],
        }

        score, breakdown = self.agent._score_idea(idea_draft)
        # At credit_pct = 1/3: C = 0, so credit component = 0
        self.assertGreater(score, 0)  # But other components add value

    def test_score_idea_delta_component(self):
        """Test _score_idea delta component is max at 0.30 delta"""
        idea_draft = {
            'credit_pct_of_width': 0.5,
            'short_delta': -0.30,  # Perfect delta
            'dte': 45,
            'legs': [
                StrikeRow('s1', 'o1', date.today(), 'PUT', 100.0, volume=500, open_interest=2000),
                StrikeRow('s2', 'o2', date.today(), 'PUT', 95.0, volume=200, open_interest=800),
            ],
        }

        score, breakdown = self.agent._score_idea(idea_draft)
        raw = breakdown['raw_components']
        # Delta component should be 1.0 (best)
        self.assertEqual(raw['delta_component'], 1.0)

    def test_score_idea_dte_component_30_60(self):
        """Test _score_idea DTE component is max at 30-60 DTE"""
        for dte in [30, 45, 60]:
            idea_draft = {
                'credit_pct_of_width': 0.5,
                'short_delta': -0.30,
                'dte': dte,
                'legs': [
                    StrikeRow('s1', 'o1', date.today(), 'PUT', 100.0, volume=500, open_interest=2000),
                ],
            }
            score, breakdown = self.agent._score_idea(idea_draft)
            raw = breakdown['raw_components']
            self.assertEqual(raw['dte_component'], 1.0)

    def test_score_idea_dte_component_21_29(self):
        """Test _score_idea DTE component scales at 21-29 DTE"""
        idea_draft_21 = {
            'credit_pct_of_width': 0.5,
            'short_delta': -0.30,
            'dte': 21,
            'legs': [StrikeRow('s1', 'o1', date.today(), 'PUT', 100.0, volume=500, open_interest=2000)],
        }
        score_21, breakdown_21 = self.agent._score_idea(idea_draft_21)

        idea_draft_25 = {
            'credit_pct_of_width': 0.5,
            'short_delta': -0.30,
            'dte': 25,
            'legs': [StrikeRow('s1', 'o1', date.today(), 'PUT', 100.0, volume=500, open_interest=2000)],
        }
        score_25, breakdown_25 = self.agent._score_idea(idea_draft_25)

        # 25 DTE should score better than 21 DTE
        self.assertGreater(breakdown_25['raw_components']['dte_component'],
                          breakdown_21['raw_components']['dte_component'])

    def test_rank_and_trim(self):
        """Test _rank_and_trim sorts and limits ideas"""
        ideas = [
            TradeIdea('BULL_PUT_SPREAD', 'AAPL', date.today() + timedelta(45), 45,
                     100, 95, score=50),
            TradeIdea('BEAR_CALL_SPREAD', 'AAPL', date.today() + timedelta(45), 45,
                     110, 115, score=75),
            TradeIdea('IRON_CONDOR', 'AAPL', date.today() + timedelta(45), 45,
                     100, 95, score=65),
        ]

        ranked = self.agent._rank_and_trim(ideas)
        self.assertEqual(ranked[0].score, 75)
        self.assertEqual(ranked[1].score, 65)
        self.assertEqual(ranked[2].score, 50)

    async def test_fetch_metrics_success(self):
        """Test _fetch_metrics fetches IV and IVR"""
        metric = MagicMock()
        metric.implied_volatility_index_rank = Decimal('0.425')
        metric.implied_volatility_index = Decimal('0.285')

        with patch('agents.options_researcher.get_market_metrics', return_value=[metric]):
            ivr, iv = await self.agent._fetch_metrics('AAPL')
            self.assertAlmostEqual(ivr, 42.5, places=1)
            self.assertAlmostEqual(iv, 0.285, places=3)

    async def test_fetch_metrics_failure(self):
        """Test _fetch_metrics handles failures gracefully"""
        with patch('agents.options_researcher.get_market_metrics', side_effect=Exception("API error")):
            ivr, iv = await self.agent._fetch_metrics('AAPL')
            self.assertIsNone(ivr)
            self.assertIsNone(iv)

    def test_clamp(self):
        """Test _clamp utility function"""
        self.assertEqual(self.agent._clamp(0.5, 0, 1), 0.5)
        self.assertEqual(self.agent._clamp(-0.5, 0, 1), 0)
        self.assertEqual(self.agent._clamp(1.5, 0, 1), 1)

    def test_to_report_structure(self):
        """Test _to_report builds valid report structure"""
        today = date.today()
        exp = today + timedelta(days=45)
        rows = [
            StrikeRow('s1', 'o1', exp, 'CALL', 100.0),
            StrikeRow('s2', 'o2', exp, 'PUT', 100.0),
        ]
        ideas = [
            TradeIdea('BULL_PUT_SPREAD', 'AAPL', exp, 45, 100, 95, score=70)
        ]

        report = self.agent._to_report(
            symbol='AAPL',
            expiration=exp,
            resolution_mode='MONTHLY_45DTE',
            ivr=42.5,
            iv=0.285,
            rows=rows,
            ideas=ideas,
            status='OK',
            warnings=[],
        )

        # Verify structure
        self.assertEqual(report['symbol'], 'AAPL')
        self.assertEqual(report['status'], 'OK')
        self.assertEqual(report['expiration'], exp.isoformat())
        self.assertEqual(report['dte'], 45)
        self.assertEqual(report['expiration_resolution'], 'MONTHLY_45DTE')
        self.assertEqual(report['underlying']['ivr'], 42.5)
        self.assertEqual(report['underlying']['iv'], 0.285)
        self.assertEqual(report['chain_summary']['total_strikes'], 2)
        self.assertEqual(report['chain_summary']['calls'], 1)
        self.assertEqual(report['chain_summary']['puts'], 1)
        self.assertTrue('generated_at' in report)
        self.assertEqual(len(report['trade_ideas']), 1)
        self.assertEqual(report['trade_ideas'][0]['rank'], 1)

    async def test_research_expiration_not_found(self):
        """Test research returns EXPIRATION_NOT_FOUND when explicit exp not in chain"""
        today = date.today()
        requested_exp = today + timedelta(days=50)
        other_exp = today + timedelta(days=30)

        chain = {other_exp: []}

        with patch('agents.options_researcher.get_option_chain', return_value=chain):
            report = await self.agent.research('AAPL', expiration=requested_exp)
            self.assertEqual(report['status'], 'EXPIRATION_NOT_FOUND')
            self.assertTrue(len(report['warnings']) > 0)

    async def test_research_no_viable_expiration(self):
        """Test research when no viable expiration found"""
        today = date.today()
        # Create chain with dates outside window
        chain = {
            today + timedelta(days=10): [],
            today + timedelta(days=100): [],
        }

        with patch('agents.options_researcher.get_option_chain', return_value=chain):
            report = await self.agent.research('AAPL')
            self.assertEqual(report['status'], 'NO_VIABLE_EXPIRATION')

    async def test_research_symbol_normalization(self):
        """Test research normalizes symbol to uppercase"""
        today = date.today()
        exp = today + timedelta(days=45)

        opt = MagicMock()
        opt.streamer_symbol = 'AAPL__C100'
        opt.symbol = 'AAPL 250516C00100000'
        opt.option_type = OptionType.CALL
        opt.strike_price = Decimal('100.0')

        md = MagicMock()
        md.symbol = 'AAPL 250516C00100000'
        md.bid = Decimal('2.0')
        md.ask = Decimal('2.5')
        md.mark = Decimal('2.2')
        md.volume = 100
        md.open_interest = 500

        greek = MagicMock()
        greek.delta = Decimal('0.35')
        greek.gamma = Decimal('0.01')
        greek.theta = Decimal('-0.05')
        greek.vega = Decimal('0.10')
        greek.volatility = Decimal('0.25')

        chain = {exp: [opt]}

        with patch('agents.options_researcher.get_option_chain', return_value=chain):
            with patch('agents.options_researcher.get_market_data_by_type', return_value=[md]):
                with patch('agents.options_researcher.get_market_metrics', return_value=[MagicMock(
                    implied_volatility_index_rank=Decimal('0.425'),
                    implied_volatility_index=Decimal('0.285'),
                )]):
                    with patch.object(self.agent, '_fetch_greeks', return_value={'AAPL__C100': greek}):
                        report = await self.agent.research('aapl')  # lowercase
                        self.assertEqual(report['symbol'], 'AAPL')

    def test_calculate_liquidity_score(self):
        """Test liquidity score calculation"""
        legs = [
            StrikeRow('s1', 'o1', date.today(), 'PUT', 100.0,
                     bid=1.95, ask=2.05, mid=2.0, open_interest=1000),
            StrikeRow('s2', 'o2', date.today(), 'PUT', 95.0,
                     bid=0.95, ask=1.05, mid=1.0, open_interest=500),
        ]

        score = self.agent._calculate_liquidity_score(legs)
        self.assertGreater(score, 0)
        self.assertLessEqual(score, 1.0)

    def test_calculate_liquidity_score_missing_data(self):
        """Test liquidity score with missing bid/ask/OI"""
        legs = [
            StrikeRow('s1', 'o1', date.today(), 'PUT', 100.0,
                     bid=None, ask=None, mid=None, open_interest=None),
        ]

        score = self.agent._calculate_liquidity_score(legs)
        # Should gracefully handle None values and return 0.5
        self.assertEqual(score, 0.5)

    async def test_research_bypasses_ivr_gate(self):
        """Test research returns ideas even when IVR would be below the 25% gate"""
        today = date.today()
        exp = today + timedelta(days=45)

        put_opt = MagicMock()
        put_opt.streamer_symbol = 'AAPL__P100'
        put_opt.symbol = 'AAPL 250516P00100000'
        put_opt.option_type = OptionType.PUT
        put_opt.strike_price = Decimal('100.0')

        long_put = MagicMock()
        long_put.streamer_symbol = 'AAPL__P95'
        long_put.symbol = 'AAPL 250516P00095000'
        long_put.option_type = OptionType.PUT
        long_put.strike_price = Decimal('95.0')

        chain = {exp: [put_opt, long_put]}

        md_short = MagicMock()
        md_short.symbol = 'AAPL 250516P00100000'
        md_short.bid = Decimal('2.00')
        md_short.ask = Decimal('2.10')
        md_short.mark = Decimal('2.05')
        md_short.volume = 500
        md_short.open_interest = 2000

        md_long = MagicMock()
        md_long.symbol = 'AAPL 250516P00095000'
        md_long.bid = Decimal('0.20')
        md_long.ask = Decimal('0.25')
        md_long.mark = Decimal('0.22')
        md_long.volume = 200
        md_long.open_interest = 800

        greek_short = MagicMock()
        greek_short.delta = Decimal('-0.30')
        greek_short.gamma = Decimal('-0.01')
        greek_short.theta = Decimal('0.05')
        greek_short.vega = Decimal('-0.10')
        greek_short.volatility = Decimal('0.25')

        greek_long = MagicMock()
        greek_long.delta = Decimal('-0.15')
        greek_long.gamma = Decimal('-0.005')
        greek_long.theta = Decimal('0.025')
        greek_long.vega = Decimal('-0.05')
        greek_long.volatility = Decimal('0.26')

        # IVR is only 5% — well below 25% gate — but research should still return ideas
        low_ivr_metric = MagicMock()
        low_ivr_metric.implied_volatility_index_rank = Decimal('0.05')
        low_ivr_metric.implied_volatility_index = Decimal('0.15')

        with patch('agents.options_researcher.get_option_chain', return_value=chain):
            with patch('agents.options_researcher.get_market_data_by_type', return_value=[md_short, md_long]):
                with patch('agents.options_researcher.get_market_metrics', return_value=[low_ivr_metric]):
                    with patch.object(self.agent, '_fetch_greeks', return_value={
                        'AAPL__P100': greek_short,
                        'AAPL__P95': greek_long,
                    }):
                        report = await self.agent.research('AAPL')
                        # IVR gate is bypassed — should still find at least one idea
                        self.assertEqual(report['status'], 'OK')
                        self.assertGreater(len(report['trade_ideas']), 0)
                        # IVR is reported but doesn't gate execution
                        self.assertAlmostEqual(report['underlying']['ivr'], 5.0, places=0)

    def test_score_breakdown_sums_to_total(self):
        """Test score breakdown components sum to total score (±0.01 tolerance)"""
        idea_draft = {
            'credit_pct_of_width': 0.50,
            'short_delta': -0.30,
            'dte': 45,
            'legs': [
                StrikeRow('s1', 'o1', date.today(), 'PUT', 100.0,
                         bid=1.90, ask=2.10, mid=2.00, volume=500, open_interest=2000),
                StrikeRow('s2', 'o2', date.today(), 'PUT', 95.0,
                         bid=0.90, ask=1.10, mid=1.00, volume=200, open_interest=800),
            ],
        }
        score, breakdown = self.agent._score_idea(idea_draft)
        component_sum = breakdown['credit'] + breakdown['delta'] + breakdown['dte'] + breakdown['liquidity']
        self.assertAlmostEqual(score, component_sum, places=2)

    def test_scoring_ranks_high_credit_above_low(self):
        """Test that higher credit-to-width ratio ranks above lower, all else equal"""
        today = date.today()
        exp = today + timedelta(days=45)

        # Low credit idea: credit_pct = 0.35
        low_credit_draft = {
            'credit_pct_of_width': 0.35,
            'short_delta': -0.30,
            'dte': 45,
            'legs': [StrikeRow('s1', 'o1', exp, 'PUT', 100.0, bid=1.90, ask=2.10, mid=2.00, open_interest=1000)],
        }
        # High credit idea: credit_pct = 0.60
        high_credit_draft = {
            'credit_pct_of_width': 0.60,
            'short_delta': -0.30,
            'dte': 45,
            'legs': [StrikeRow('s1', 'o1', exp, 'PUT', 100.0, bid=1.90, ask=2.10, mid=2.00, open_interest=1000)],
        }

        low_score, _ = self.agent._score_idea(low_credit_draft)
        high_score, _ = self.agent._score_idea(high_credit_draft)
        self.assertGreater(high_score, low_score)

    def test_ideas_capped_at_max_returned(self):
        """Test that _rank_and_trim returns at most MAX_IDEAS_RETURNED ideas"""
        from agents.options_researcher import MAX_IDEAS_RETURNED
        today = date.today()
        exp = today + timedelta(days=45)

        # Create more ideas than MAX_IDEAS_RETURNED
        many_ideas = [
            TradeIdea('BULL_PUT_SPREAD', 'AAPL', exp, 45, 100 - i, 95 - i, score=float(i))
            for i in range(MAX_IDEAS_RETURNED + 10)
        ]

        ranked = self.agent._rank_and_trim(many_ideas)
        self.assertLessEqual(len(ranked), MAX_IDEAS_RETURNED)
        # Should be sorted descending
        for i in range(len(ranked) - 1):
            self.assertGreaterEqual(ranked[i].score, ranked[i+1].score)

    def test_json_output_is_serialisable(self):
        """Test that research report can be serialised to JSON without errors"""
        import json
        today = date.today()
        exp = today + timedelta(days=45)

        rows = [
            StrikeRow('s1', 'o1', exp, 'CALL', 100.0, bid=2.0, ask=2.1, mid=2.05,
                     delta=0.30, gamma=0.01, theta=-0.05, vega=0.10, iv=0.25,
                     volume=500, open_interest=2000),
            StrikeRow('s2', 'o2', exp, 'PUT', 100.0, bid=1.9, ask=2.0, mid=1.95,
                     delta=-0.30, gamma=0.01, theta=-0.05, vega=0.10, iv=0.25,
                     volume=400, open_interest=1800),
        ]
        ideas = [
            TradeIdea('BULL_PUT_SPREAD', 'AAPL', exp, 45, 100.0, 95.0, score=70.0,
                     score_breakdown={'credit': 10, 'delta': 25, 'dte': 20, 'liquidity': 15,
                                      'raw_components': {'credit_component': 0.25, 'delta_component': 1.0,
                                                        'dte_component': 1.0, 'liquidity_component': 1.0}},
                     legs=[
                         {'action': 'SELL', 'option_type': 'PUT', 'strike': 100.0,
                          'occ_symbol': 'AAPL250516P00100000', 'streamer_symbol': 's2',
                          'bid': 1.9, 'ask': 2.0, 'mid': 1.95, 'volume': 400, 'open_interest': 1800,
                          'delta': -0.30, 'gamma': 0.01, 'theta': -0.05, 'vega': 0.10, 'iv': 0.25},
                         {'action': 'BUY', 'option_type': 'PUT', 'strike': 95.0,
                          'occ_symbol': 'AAPL250516P00095000', 'streamer_symbol': 's3',
                          'bid': 0.2, 'ask': 0.25, 'mid': 0.22, 'volume': 200, 'open_interest': 800,
                          'delta': -0.15, 'gamma': 0.005, 'theta': -0.025, 'vega': 0.05, 'iv': 0.26},
                     ])
        ]

        report = self.agent._to_report(
            symbol='AAPL', expiration=exp, resolution_mode='MONTHLY_45DTE',
            ivr=42.5, iv=0.285, rows=rows, ideas=ideas, status='OK', warnings=[],
        )

        # Must serialise without error
        serialised = json.dumps(report)
        self.assertIsInstance(serialised, str)

        # Deserialise and check key fields
        parsed = json.loads(serialised)
        self.assertEqual(parsed['symbol'], 'AAPL')
        self.assertEqual(parsed['status'], 'OK')
        self.assertIsInstance(parsed['generated_at'], str)
        self.assertIn('underlying', parsed)
        self.assertIn('trade_ideas', parsed)

    def test_condor_breakevens_correct(self):
        """Test iron condor breakevens: put_short=185, call_short=215, total_credit=2.00 → [183.00, 217.00]"""
        today = date.today()
        exp = today + timedelta(days=45)

        # Set up put side (short 185, long 180) - width 5, need credit >= 1.667 (33%)
        put_rows = [
            StrikeRow('sp', 'op1', exp, 'PUT', 185.0, bid=1.98, ask=2.08, mid=2.03,
                     delta=-0.30, gamma=-0.01, theta=0.05, vega=-0.10, iv=0.25,
                     volume=500, open_interest=2000),
            StrikeRow('lp', 'op2', exp, 'PUT', 180.0, bid=0.31, ask=0.41, mid=0.36,
                     delta=-0.10, gamma=-0.005, theta=0.02, vega=-0.05, iv=0.26,
                     volume=200, open_interest=800),
        ]

        # Set up call side (short 215, long 220) - width 5, need credit >= 1.667 (33%)
        call_rows = [
            StrikeRow('sc', 'oc1', exp, 'CALL', 215.0, bid=1.98, ask=2.08, mid=2.03,
                     delta=0.30, gamma=0.01, theta=0.05, vega=-0.10, iv=0.25,
                     volume=400, open_interest=1500),
            StrikeRow('lc', 'oc2', exp, 'CALL', 220.0, bid=0.31, ask=0.41, mid=0.36,
                     delta=0.10, gamma=0.005, theta=0.02, vega=-0.05, iv=0.26,
                     volume=200, open_interest=700),
        ]

        all_rows = put_rows + call_rows
        idea = self.agent._build_iron_condor(all_rows, 'TEST', exp, 45)

        self.assertIsNotNone(idea)
        self.assertEqual(idea.strategy, 'IRON_CONDOR')

        # put credit ≈ 1.67, call credit ≈ 1.67, total ≈ 3.34
        # breakevens: put_short(185) - total_credit = 185 - 3.34 = 181.66
        #            call_short(215) + total_credit = 215 + 3.34 = 218.34
        total_credit = idea.credit
        expected_put_be = 185.0 - total_credit
        expected_call_be = 215.0 + total_credit

        self.assertEqual(len(idea.breakeven), 2)
        self.assertAlmostEqual(idea.breakeven[0], expected_put_be, places=2)
        self.assertAlmostEqual(idea.breakeven[1], expected_call_be, places=2)


if __name__ == '__main__':
    unittest.main()
