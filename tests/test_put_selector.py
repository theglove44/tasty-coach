"""Tests for the cash-secured-put screener: emission, scoring, skew, CLI."""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from agents.options_researcher import (
    OptionsResearcherAgent,
    StrikeRow,
    _compute_put_call_skew,
    CSP_DELTA_MIN,
    CSP_DELTA_MAX,
    CSP_MIN_OTM_PCT,
    CSP_MAX_PER_SYMBOL,
)
from agents.trade_ranker import (
    AccountState,
    Candidate,
    SymbolContext,
    _candidate_to_dict,
    _csp_annualized_return,
    _csp_short_strike,
    _score_csp_candidate,
    _score_csp_distance,
    _score_csp_income,
    _score_csp_pop,
    _score_csp_time_efficiency,
    _score_csp_vol_env,
    score_candidate,
)


def _put_row(strike: float, delta: float, *, mid: float = 1.50, iv: float = 0.30,
             oi: int = 1000, bid: float = 1.45, ask: float = 1.55) -> StrikeRow:
    return StrikeRow(
        streamer_symbol=f".AAPL{strike:.0f}P",
        occ_symbol=f"AAPL  260619P{int(strike * 1000):08d}",
        expiration=date(2026, 6, 19),
        option_type="PUT",
        strike=strike,
        bid=bid,
        ask=ask,
        mid=mid,
        volume=500,
        open_interest=oi,
        delta=delta,
        gamma=0.01,
        theta=-0.05,
        vega=0.10,
        iv=iv,
    )


def _call_row(strike: float, delta: float, iv: float = 0.25) -> StrikeRow:
    return StrikeRow(
        streamer_symbol=f".AAPL{strike:.0f}C",
        occ_symbol=f"AAPL  260619C{int(strike * 1000):08d}",
        expiration=date(2026, 6, 19),
        option_type="CALL",
        strike=strike,
        bid=1.0, ask=1.1, mid=1.05,
        volume=400, open_interest=800,
        delta=delta, gamma=0.01, theta=-0.05, vega=0.10, iv=iv,
    )


class TestBuildCashSecuredPuts(unittest.TestCase):
    """OptionsResearcherAgent._build_cash_secured_puts emission."""

    def setUp(self):
        self.agent = OptionsResearcherAgent(MagicMock())

    def test_emits_one_idea_per_qualifying_put_strike(self):
        rows = [
            _put_row(145.0, -0.20, mid=1.50),
            _put_row(140.0, -0.15, mid=0.80),
            _put_row(135.0, -0.10, mid=0.40),  # delta below CSP_DELTA_MIN — drop
            _put_row(155.0, -0.50, mid=4.50),  # delta above CSP_DELTA_MAX — drop
        ]
        ideas = self.agent._build_cash_secured_puts(
            rows, "AAPL", date(2026, 6, 19), 49, underlying_price=150.0,
        )
        self.assertEqual(len(ideas), 2)
        for i in ideas:
            self.assertEqual(i.strategy, "CASH_SECURED_PUT")
            self.assertGreater(i.credit, 0)
            self.assertEqual(i.width, i.short_strike)  # width=strike for CSPs
            self.assertEqual(len(i.legs), 1)
            self.assertEqual(i.legs[0]["action"], "SELL")

    def test_filters_itm_puts(self):
        rows = [
            _put_row(155.0, -0.55, mid=6.0),  # ITM — strike >= spot
            _put_row(145.0, -0.20, mid=1.5),
        ]
        ideas = self.agent._build_cash_secured_puts(
            rows, "AAPL", date(2026, 6, 19), 49, underlying_price=150.0,
        )
        # Only the OTM 145 strike qualifies (155 ITM dropped, also delta out of range)
        self.assertEqual(len(ideas), 1)
        self.assertEqual(ideas[0].short_strike, 145.0)

    def test_filters_strikes_inside_otm_floor(self):
        # 149 is only 0.67% OTM — below default 3% floor.
        rows = [_put_row(149.0, -0.45, mid=2.0), _put_row(140.0, -0.20, mid=1.0)]
        ideas = self.agent._build_cash_secured_puts(
            rows, "AAPL", date(2026, 6, 19), 49, underlying_price=150.0,
        )
        self.assertEqual(len(ideas), 1)
        self.assertEqual(ideas[0].short_strike, 140.0)

    def test_skips_when_underlying_price_unavailable_or_zero(self):
        rows = [_put_row(145.0, -0.20, mid=1.50)]
        self.assertEqual(self.agent._build_cash_secured_puts(rows, "AAPL", date(2026, 6, 19), 49, 0.0), [])
        self.assertEqual(self.agent._build_cash_secured_puts(rows, "AAPL", date(2026, 6, 19), 49, -1.0), [])

    def test_skips_rows_missing_delta_or_mid(self):
        rows = [
            _put_row(145.0, -0.20, mid=1.50),
            StrikeRow(streamer_symbol="x", occ_symbol="x", expiration=date(2026, 6, 19),
                      option_type="PUT", strike=144.0, mid=None, delta=-0.22),
            StrikeRow(streamer_symbol="x", occ_symbol="x", expiration=date(2026, 6, 19),
                      option_type="PUT", strike=143.0, mid=1.0, delta=None),
        ]
        ideas = self.agent._build_cash_secured_puts(rows, "AAPL", date(2026, 6, 19), 49, 150.0)
        self.assertEqual(len(ideas), 1)

    def test_caps_at_max_per_symbol_by_premium_desc(self):
        rows = [_put_row(150.0 - i, -0.20, mid=2.0 - 0.1 * i) for i in range(1, 10)]
        ideas = self.agent._build_cash_secured_puts(
            rows, "AAPL", date(2026, 6, 19), 49, 150.0,
            max_per_symbol=3,
        )
        self.assertEqual(len(ideas), 3)
        # Sorted by premium descending
        credits = [i.credit for i in ideas]
        self.assertEqual(credits, sorted(credits, reverse=True))

    def test_max_loss_is_strike_minus_credit(self):
        rows = [_put_row(145.0, -0.20, mid=1.50)]
        ideas = self.agent._build_cash_secured_puts(rows, "AAPL", date(2026, 6, 19), 49, 150.0)
        self.assertAlmostEqual(ideas[0].max_loss, 145.0 - 1.50, places=4)

    def test_credit_pct_of_width_normalized_against_strike(self):
        rows = [_put_row(145.0, -0.20, mid=1.45)]
        ideas = self.agent._build_cash_secured_puts(rows, "AAPL", date(2026, 6, 19), 49, 150.0)
        self.assertAlmostEqual(ideas[0].credit_pct_of_width, 1.45 / 145.0, places=4)


class TestComputePutCallSkew(unittest.TestCase):
    """_compute_put_call_skew picks legs closest to ~25Δ and returns put_iv / call_iv."""

    def test_returns_ratio_at_reference_delta(self):
        rows = [
            _put_row(145.0, -0.25, iv=0.35),  # closest to -25Δ
            _put_row(140.0, -0.15, iv=0.40),
            _call_row(155.0, 0.25, iv=0.28),  # closest to +25Δ
            _call_row(160.0, 0.10, iv=0.22),
        ]
        skew = _compute_put_call_skew(rows)
        self.assertIsNotNone(skew)
        self.assertAlmostEqual(skew, 0.35 / 0.28, places=4)

    def test_returns_none_when_no_puts_or_calls(self):
        self.assertIsNone(_compute_put_call_skew([]))
        self.assertIsNone(_compute_put_call_skew([_put_row(145.0, -0.25)]))
        self.assertIsNone(_compute_put_call_skew([_call_row(155.0, 0.25)]))

    def test_skips_rows_without_iv(self):
        rows = [
            StrikeRow(streamer_symbol="p", occ_symbol="p", expiration=date(2026, 6, 19),
                      option_type="PUT", strike=145, delta=-0.25, iv=None),
            _call_row(155.0, 0.25, iv=0.28),
        ]
        self.assertIsNone(_compute_put_call_skew(rows))


def _make_csp_candidate(
    *,
    symbol: str = "AAPL",
    strike: float = 145.0,
    credit: float = 1.50,
    delta: float = -0.22,
    dte: int = 45,
    spot: float = 150.0,
    iv_rank: float = 50.0,
    earnings: date | None = None,
    skew: float | None = None,
) -> Candidate:
    ctx = SymbolContext(
        symbol=symbol,
        current_price=Decimal(str(spot)),
        iv_rank=iv_rank,
        next_earnings_date=earnings,
        put_call_skew=skew,
    )
    return Candidate(
        symbol=symbol,
        structure="CASH_SECURED_PUT",
        expiration=date(2026, 6, 19),
        dte=dte,
        width=strike,
        credit=credit,
        max_loss=strike - credit,
        credit_pct_of_width=credit / strike,
        short_delta=delta,
        pop_estimate=1.0 - abs(delta),
        breakevens=[strike - credit],
        net_greeks={},
        legs=[{"action": "SELL", "option_type": "PUT", "strike": strike,
               "bid": credit - 0.05, "ask": credit + 0.05, "mid": credit,
               "open_interest": 1000, "delta": delta, "iv": 0.30}],
        researcher_score=0.0,
        researcher_score_breakdown={},
        context=ctx,
    )


class TestCspScoringComponents(unittest.TestCase):
    """Each scoring helper clamps as expected at boundaries."""

    def test_short_strike_pulled_from_sell_leg(self):
        c = _make_csp_candidate(strike=140.0)
        self.assertEqual(_csp_short_strike(c), 140.0)

    def test_annualized_return_formula(self):
        # 1.50 credit, 45 DTE, strike 145 → (1.50*365/45)/145 = 0.0839...
        c = _make_csp_candidate(strike=145.0, credit=1.50, dte=45)
        self.assertAlmostEqual(_csp_annualized_return(c), (1.50 * 365 / 45) / 145.0, places=4)

    def test_income_zero_below_floor(self):
        c = _make_csp_candidate(strike=200.0, credit=0.40, dte=45)  # tiny annualized
        self.assertEqual(_score_csp_income(c, min_annualized_return=0.10), 0.0)

    def test_income_caps_at_max(self):
        c = _make_csp_candidate(strike=50.0, credit=5.0, dte=30)  # huge annualized
        score = _score_csp_income(c, min_annualized_return=0.10)
        self.assertAlmostEqual(score, 20.0, places=2)

    def test_distance_zero_inside_floor(self):
        c = _make_csp_candidate(strike=149.0, spot=150.0)  # 0.67% buffer
        self.assertEqual(_score_csp_distance(c, min_otm_pct=0.03), 0.0)

    def test_distance_caps_at_max(self):
        c = _make_csp_candidate(strike=120.0, spot=150.0)  # 20% buffer
        self.assertAlmostEqual(_score_csp_distance(c, min_otm_pct=0.03), 25.0, places=2)

    def test_pop_clamps_below_threshold(self):
        c = _make_csp_candidate(delta=-0.40)  # POP 0.60 < 0.65 → 0
        self.assertEqual(_score_csp_pop(c), 0.0)

    def test_pop_caps_at_max(self):
        c = _make_csp_candidate(delta=-0.10)  # POP 0.90 > 0.85 → cap 20
        self.assertAlmostEqual(_score_csp_pop(c), 20.0, places=2)

    def test_vol_env_placeholder_when_ivr_none(self):
        c = _make_csp_candidate(iv_rank=50.0)
        c.context.iv_rank = None
        self.assertAlmostEqual(_score_csp_vol_env(c), 7.5, places=2)

    def test_vol_env_ramps_30_to_70(self):
        c = _make_csp_candidate(iv_rank=30.0)
        self.assertAlmostEqual(_score_csp_vol_env(c), 0.0, places=2)
        c2 = _make_csp_candidate(iv_rank=70.0)
        self.assertAlmostEqual(_score_csp_vol_env(c2), 15.0, places=2)
        c3 = _make_csp_candidate(iv_rank=50.0)
        self.assertAlmostEqual(_score_csp_vol_env(c3), 7.5, places=2)

    def test_time_efficiency_peaks_30_to_45(self):
        for d in (30, 35, 45):
            c = _make_csp_candidate(dte=d)
            self.assertAlmostEqual(_score_csp_time_efficiency(c), 10.0, places=2)

    def test_time_efficiency_ramps_below_30(self):
        c = _make_csp_candidate(dte=21)
        self.assertAlmostEqual(_score_csp_time_efficiency(c), 0.0, places=2)
        c2 = _make_csp_candidate(dte=25)
        self.assertGreater(_score_csp_time_efficiency(c2), 0.0)
        self.assertLess(_score_csp_time_efficiency(c2), 10.0)

    def test_time_efficiency_short_dte_penalised_harder_than_long(self):
        # Sub-21 DTE = gamma risk → floor 0.10; >60 DTE = slow theta → floor 0.40.
        # Asymmetry matches the article's "short-DTE more dangerous" framing.
        c_short = _make_csp_candidate(dte=10)
        c_long = _make_csp_candidate(dte=90)
        s_short = _score_csp_time_efficiency(c_short)
        s_long = _score_csp_time_efficiency(c_long)
        self.assertAlmostEqual(s_short, 1.0, places=2)
        self.assertAlmostEqual(s_long, 4.0, places=2)
        self.assertLess(s_short, s_long)


class TestCspScoreCandidateDispatch(unittest.TestCase):
    """score_candidate dispatches to CSP path when structure is CASH_SECURED_PUT."""

    def test_csp_breakdown_keys_differ_from_spread(self):
        c = _make_csp_candidate()
        scored = score_candidate(c, today=date(2026, 5, 1))
        self.assertIn("csp_income", scored.score_breakdown)
        self.assertIn("csp_distance", scored.score_breakdown)
        self.assertIn("csp_pop", scored.score_breakdown)
        self.assertIn("csp_vol_env", scored.score_breakdown)
        self.assertIn("csp_time_efficiency", scored.score_breakdown)
        self.assertNotIn("regime_fit", scored.score_breakdown)

    def test_csp_score_clamped_to_0_100(self):
        c = _make_csp_candidate()
        scored = score_candidate(c, today=date(2026, 5, 1))
        self.assertGreaterEqual(scored.score, 0.0)
        self.assertLessEqual(scored.score, 100.0)

    def test_earnings_within_7d_zeroes_time_efficiency(self):
        c = _make_csp_candidate(earnings=date(2026, 5, 5))
        scored = _score_csp_candidate(c, today=date(2026, 5, 1))
        self.assertEqual(scored.score_breakdown["csp_time_efficiency"], 0.0)

    def test_summary_reason_mentions_skew_when_elevated(self):
        c = _make_csp_candidate(skew=1.30)
        scored = score_candidate(c, today=date(2026, 5, 1))
        self.assertIn("skew", scored.summary_reason.lower())


class TestCspCandidateToDict(unittest.TestCase):
    """_candidate_to_dict emits CSP-specific fields when structure is CASH_SECURED_PUT."""

    def test_emits_cash_required_and_annualized_return(self):
        c = _make_csp_candidate(strike=145.0, credit=1.50, dte=45)
        d = _candidate_to_dict(c)
        self.assertEqual(d["cash_required"], 14500.0)
        self.assertAlmostEqual(d["annualized_return"], (1.50 * 365 / 45) / 145.0, places=4)
        self.assertAlmostEqual(d["premium_per_day"], 1.50 / 45, places=4)
        self.assertAlmostEqual(d["pct_otm"], (150.0 - 145.0) / 150.0, places=4)
        self.assertEqual(d["spot_price"], 150.0)

    def test_emits_skew_when_present(self):
        c = _make_csp_candidate(skew=1.26)
        d = _candidate_to_dict(c)
        self.assertEqual(d["put_call_skew"], 1.26)

    def test_omits_csp_fields_for_spread_structure(self):
        c = _make_csp_candidate()
        c2 = Candidate(
            symbol="AAPL", structure="BULL_PUT_SPREAD", expiration=c.expiration,
            dte=c.dte, width=5.0, credit=c.credit, max_loss=3.50, credit_pct_of_width=0.30,
            short_delta=c.short_delta, pop_estimate=c.pop_estimate, breakevens=[],
            net_greeks={}, legs=[], researcher_score=0.0, researcher_score_breakdown={},
            context=c.context,
        )
        d = _candidate_to_dict(c2)
        self.assertNotIn("cash_required", d)
        self.assertNotIn("annualized_return", d)
        self.assertNotIn("pct_otm", d)


class TestCspAccountFilterUsesSeparateCap(unittest.TestCase):
    """CSPs route through bt_csp_max_pct_nlv_per_trade; spreads use bt_max_pct_nlv_per_trade."""

    def _state(self, nlv=20000.0):
        return AccountState(nlv=nlv, bp_usage_pct=0.10, existing_exposures={})

    def test_csp_admitted_above_spread_cap_below_csp_cap(self):
        # 50 strike CSP, 1.00 credit on $20k NLV: max_loss=$4,900 = 24.5% NLV.
        # Spread cap (5%) would reject; CSP cap at 50% admits it.
        from agents.trade_ranker import apply_account_filters
        c = _make_csp_candidate(strike=50.0, credit=1.00, spot=55.0)
        survivors, rejections = apply_account_filters(
            [c], self._state(),
            max_pct_nlv_per_trade=0.05,
            bp_cap_for_new=0.99,  # don't trip BP cap; we're isolating size cap behavior
            concentration_block_pct=0.50,
            csp_max_pct_nlv_per_trade=0.50,
        )
        self.assertEqual(len(survivors), 1)
        self.assertEqual(rejections, [])

    def test_csp_rejected_above_csp_cap(self):
        from agents.trade_ranker import apply_account_filters
        c = _make_csp_candidate(strike=145.0, credit=1.50)  # 71.7% NLV
        survivors, rejections = apply_account_filters(
            [c], self._state(),
            max_pct_nlv_per_trade=0.05,
            bp_cap_for_new=0.50,
            concentration_block_pct=0.25,
            csp_max_pct_nlv_per_trade=0.50,
        )
        self.assertEqual(survivors, [])
        self.assertEqual(rejections[0].reason, "oversized_vs_nlv")

    def test_spread_unaffected_by_csp_cap(self):
        # Spread max_loss=3.50 points = $350 = 1.75% NLV — passes both caps.
        from agents.trade_ranker import apply_account_filters
        c = _make_csp_candidate()
        c.structure = "BULL_PUT_SPREAD"
        c.max_loss = 3.50
        survivors, _ = apply_account_filters(
            [c], self._state(),
            max_pct_nlv_per_trade=0.05,
            bp_cap_for_new=0.50,
            concentration_block_pct=0.25,
            csp_max_pct_nlv_per_trade=0.50,
        )
        self.assertEqual(len(survivors), 1)

    def test_csp_account_fit_ramp_uses_wider_band(self):
        # 145-strike CSP on $20k NLV = 71.7% — way above 25% saturation → 0.
        # 145-strike CSP on $200k NLV = 7.2% → between 10..0 ramp at (25-7.2)/15 ≈ 11.9 → cap 10.
        from agents.trade_ranker import _score_account_fit
        c = _make_csp_candidate(strike=145.0, credit=1.50)
        big_nlv = AccountState(nlv=200_000.0, bp_usage_pct=0.10)
        small_nlv = AccountState(nlv=20_000.0, bp_usage_pct=0.10)
        self.assertGreater(_score_account_fit(c, big_nlv), 0.0)
        self.assertEqual(_score_account_fit(c, small_nlv), 0.0)


class TestStructureFilterNoSpotRejection(unittest.IsolatedAsyncioTestCase):
    """Symbols missing current_price under --put-selector emit no_spot_for_csp rejections."""

    async def test_no_spot_emits_rejection(self):
        from agents.trade_ranker import generate_candidates, SymbolContext
        ctx = SymbolContext(symbol="ZZZZ", current_price=None, iv_rank=99.0)
        researcher = MagicMock()
        researcher.research = MagicMock()  # should NOT be called
        candidates, rejections = await generate_candidates(
            MagicMock(), [ctx], researcher=researcher,
            structure_filter="CASH_SECURED_PUT",
        )
        self.assertEqual(candidates, [])
        self.assertEqual(len(rejections), 1)
        self.assertEqual(rejections[0].reason, "no_spot_for_csp")
        researcher.research.assert_not_called()


class TestCspScoringEdgeCases(unittest.TestCase):
    """User-tuned thresholds shouldn't crash the scorer."""

    def test_income_floor_above_cap_saturates(self):
        c = _make_csp_candidate(strike=50.0, credit=5.0, dte=30)  # huge ann return
        # User sets floor = 0.50 (above the 0.30 cap) — should saturate at full weight, not div-by-zero.
        score = _score_csp_income(c, min_annualized_return=0.50)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 20.0)

    def test_distance_floor_above_cap_saturates(self):
        c = _make_csp_candidate(strike=120.0, spot=150.0)  # 20% buffer
        score = _score_csp_distance(c, min_otm_pct=0.20)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 25.0)


class TestSkewDistanceGate(unittest.TestCase):
    def test_returns_none_when_no_leg_near_reference(self):
        # Only deep-ITM put and deep-OTM call available — too far from 25Δ.
        rows = [
            _put_row(180.0, -0.80, iv=0.50),  # 80Δ — 55 from 25Δ
            _call_row(200.0, 0.05, iv=0.20),  # 5Δ — 20 from 25Δ
        ]
        self.assertIsNone(_compute_put_call_skew(rows))


if __name__ == "__main__":
    unittest.main()
