"""Tests for the position action advisor."""

import unittest
from dataclasses import FrozenInstanceError
from datetime import date, timedelta

from agents.advisor import ActionSuggestion, suggest_action
from agents.reviewer import PositionContext
from utils.roll_calculator import RollScenario, SpreadMetrics


def _make_ctx(strategy_type="Put Vertical", dte=30, entry_cost=-100.0,
              unrealized_pl=0.0, short_strikes=None, long_strikes=None,
              spot=100.0):
    legs = []
    for k in (short_strikes or []):
        legs.append({
            "symbol": "X", "strike": k, "option_type": "PUT",
            "action": "STO", "quantity": 1, "avg_open_price": 1.0,
            "mark": 1.0, "bid": 0.9, "ask": 1.1,
            "current_value": 100.0, "unrealized_pl": 0.0,
        })
    for k in (long_strikes or []):
        legs.append({
            "symbol": "X", "strike": k, "option_type": "PUT",
            "action": "BTO", "quantity": 1, "avg_open_price": 0.5,
            "mark": 0.5, "bid": 0.4, "ask": 0.6,
            "current_value": 50.0, "unrealized_pl": 0.0,
        })
    return PositionContext(
        underlying="X", current_price=spot, legs=legs,
        strategy_type=strategy_type, dte=dte,
        expiration=date.today() + timedelta(days=dte),
        total_quantity=1, entry_cost=entry_cost,
        current_value=50.0, unrealized_pl=unrealized_pl,
    )


def _make_scenario(viability=80.0):
    sm = SpreadMetrics(
        width=10.0, max_profit=100.0, max_loss=-50.0,
        breakeven=95.0, risk_reward_ratio=2.0,
    )
    return RollScenario(
        scenario_type="roll_down",
        current_legs=[], new_legs=[],
        credit_debit=25.0, new_breakeven=95.0,
        max_profit_change=0.0, max_loss_change=0.0,
        days_added=30, new_dte=60,
        new_expiration=date.today() + timedelta(days=60),
        current_metrics=sm, new_metrics=sm,
        viability_score=viability,
    )


class TestAdvisor(unittest.TestCase):
    def test_profit_target_triggers_close_high_confidence(self):
        ctx = _make_ctx(dte=30, entry_cost=-100.0, unrealized_pl=60.0)
        s = suggest_action(ctx)
        self.assertEqual(s.action, "close")
        self.assertEqual(s.confidence, "high")
        self.assertIn("Profit target", s.reason)

    def test_profit_above_target_still_closes(self):
        ctx = _make_ctx(dte=30, entry_cost=-100.0, unrealized_pl=80.0)
        s = suggest_action(ctx)
        self.assertEqual(s.action, "close")

    def test_stop_loss_breach_with_viable_roll_triggers_roll(self):
        ctx = _make_ctx(dte=30, entry_cost=-100.0, unrealized_pl=-120.0)
        s = suggest_action(ctx, roll_scenarios=[_make_scenario(viability=80.0)])
        self.assertEqual(s.action, "roll")
        self.assertEqual(s.confidence, "high")
        self.assertTrue(len(s.roll_scenarios) > 0)

    def test_stop_loss_breach_without_viable_roll_triggers_close(self):
        ctx = _make_ctx(dte=30, entry_cost=-100.0, unrealized_pl=-120.0)
        s = suggest_action(ctx, roll_scenarios=None)
        self.assertEqual(s.action, "close")
        self.assertEqual(s.roll_scenarios, [])

    def test_stop_loss_breach_with_only_below_floor_scenarios_closes(self):
        ctx = _make_ctx(dte=30, entry_cost=-100.0, unrealized_pl=-120.0)
        s = suggest_action(ctx, roll_scenarios=[_make_scenario(viability=40.0)])
        self.assertEqual(s.action, "close")
        self.assertEqual(s.roll_scenarios, [])

    def test_near_expiration_in_profit_otm_lets_expire(self):
        # Short PUT at 90, spot 100 -> OTM by 10% -> let_expire
        ctx = _make_ctx(dte=1, entry_cost=-100.0, unrealized_pl=10.0,
                        short_strikes=[90.0], spot=100.0)
        s = suggest_action(ctx)
        self.assertEqual(s.action, "let_expire")
        self.assertEqual(s.confidence, "high")

    def test_near_expiration_short_call_itm_in_profit_closes_not_expires(self):
        # Short CALL at 90 with spot=100 is ITM even though P/L may be positive
        # from a large initial credit. Must NOT recommend let_expire.
        legs = [{
            "symbol": "X", "strike": 90.0, "option_type": "CALL",
            "action": "STO", "quantity": 1, "avg_open_price": 15.0,
            "mark": 11.0, "bid": 10.9, "ask": 11.1,
            "current_value": 1100.0, "unrealized_pl": 400.0,
        }]
        from agents.reviewer import PositionContext
        from datetime import date, timedelta
        ctx = PositionContext(
            underlying="X", current_price=100.0, legs=legs,
            strategy_type="Short Call", dte=1,
            expiration=date.today() + timedelta(days=1),
            total_quantity=1, entry_cost=-1500.0,
            current_value=-1100.0, unrealized_pl=400.0,
        )
        s = suggest_action(ctx)
        self.assertEqual(s.action, "close")
        self.assertEqual(s.confidence, "high")

    def test_near_expiration_short_put_itm_in_profit_closes(self):
        # Short PUT at 100 with spot=95 is ITM. Positive P/L must NOT trigger let_expire.
        legs = [{
            "symbol": "X", "strike": 100.0, "option_type": "PUT",
            "action": "STO", "quantity": 1, "avg_open_price": 8.0,
            "mark": 5.5, "bid": 5.4, "ask": 5.6,
            "current_value": 550.0, "unrealized_pl": 250.0,
        }]
        from agents.reviewer import PositionContext
        from datetime import date, timedelta
        ctx = PositionContext(
            underlying="X", current_price=95.0, legs=legs,
            strategy_type="Short Put", dte=1,
            expiration=date.today() + timedelta(days=1),
            total_quantity=1, entry_cost=-800.0,
            current_value=-550.0, unrealized_pl=250.0,
        )
        s = suggest_action(ctx)
        self.assertEqual(s.action, "close")

    def test_near_expiration_losing_closes(self):
        ctx = _make_ctx(dte=1, entry_cost=-100.0, unrealized_pl=-30.0, spot=100.0)
        s = suggest_action(ctx)
        self.assertEqual(s.action, "close")

    def test_near_expiration_near_short_strike_closes(self):
        ctx = _make_ctx(dte=1, entry_cost=-100.0, unrealized_pl=10.0,
                        short_strikes=[99.0], spot=100.0)
        s = suggest_action(ctx)
        self.assertEqual(s.action, "close")

    def test_rolling_window_with_viable_roll_triggers_roll(self):
        ctx = _make_ctx(dte=15, entry_cost=-100.0, unrealized_pl=10.0, spot=100.0)
        s = suggest_action(ctx, roll_scenarios=[_make_scenario(viability=80.0)])
        self.assertEqual(s.action, "roll")
        self.assertEqual(s.confidence, "medium")

    def test_rolling_window_no_roll_proximity_triggers_close(self):
        ctx = _make_ctx(dte=15, entry_cost=-100.0, unrealized_pl=10.0,
                        short_strikes=[99.0], spot=100.0)
        s = suggest_action(ctx)
        self.assertEqual(s.action, "close")
        self.assertEqual(s.confidence, "medium")

    def test_rolling_window_no_roll_no_pressure_triggers_hold(self):
        ctx = _make_ctx(dte=15, entry_cost=-100.0, unrealized_pl=10.0,
                        short_strikes=[85.0], spot=100.0)
        s = suggest_action(ctx)
        self.assertEqual(s.action, "hold")
        self.assertEqual(s.confidence, "low")

    def test_assignment_pressure_outside_window_triggers_reduce(self):
        ctx = _make_ctx(dte=30, entry_cost=-100.0, unrealized_pl=10.0,
                        short_strikes=[99.0], spot=100.0)
        s = suggest_action(ctx)
        self.assertEqual(s.action, "reduce")
        self.assertEqual(s.confidence, "medium")

    def test_default_holds_when_no_triggers(self):
        ctx = _make_ctx(dte=30, entry_cost=-100.0, unrealized_pl=10.0,
                        short_strikes=[85.0], spot=100.0)
        s = suggest_action(ctx)
        self.assertEqual(s.action, "hold")
        self.assertEqual(s.confidence, "low")

    def test_zero_entry_cost_does_not_divide_by_zero(self):
        ctx = _make_ctx(dte=30, entry_cost=0.0, unrealized_pl=100.0, spot=100.0)
        s = suggest_action(ctx)
        self.assertEqual(s.action, "close")

    def test_no_sto_legs_skips_proximity_rules(self):
        ctx = _make_ctx(dte=30, entry_cost=-100.0, unrealized_pl=10.0,
                        long_strikes=[85.0], short_strikes=[], spot=100.0)
        s = suggest_action(ctx)
        self.assertEqual(s.action, "hold")
        self.assertIsNone(s.metrics["short_strike"])
        self.assertIsNone(s.metrics["proximity_pct"])

    def test_iron_condor_picks_nearer_short_strike(self):
        ctx = _make_ctx(dte=30, entry_cost=-100.0, unrealized_pl=10.0,
                        short_strikes=[90.0, 110.0], spot=102.0)
        s = suggest_action(ctx)
        self.assertEqual(s.metrics["short_strike"], 110.0)

    def test_action_suggestion_is_frozen_dataclass(self):
        ctx = _make_ctx()
        s = suggest_action(ctx)
        with self.assertRaises(FrozenInstanceError):
            s.action = "roll"

    def test_roll_scenarios_empty_when_action_not_roll(self):
        ctx = _make_ctx(dte=30, entry_cost=-100.0, unrealized_pl=60.0, spot=100.0)
        s = suggest_action(ctx, roll_scenarios=[_make_scenario(viability=80.0)])
        self.assertEqual(s.action, "close")
        self.assertEqual(s.roll_scenarios, [])

    def test_debit_spread_profit_formula(self):
        ctx = _make_ctx(dte=30, entry_cost=100.0, unrealized_pl=60.0, spot=100.0)
        s = suggest_action(ctx)
        self.assertEqual(s.action, "close")
        self.assertAlmostEqual(s.metrics["return_pct"], 0.6)

    def test_near_expiration_long_only_closes_not_let_expire(self):
        ctx = _make_ctx(dte=1, entry_cost=100.0, unrealized_pl=20.0,
                        long_strikes=[90.0], short_strikes=[], spot=100.0)
        s = suggest_action(ctx)
        self.assertEqual(s.action, "close")

    def test_near_expiration_missing_spot_closes_not_let_expire(self):
        ctx = _make_ctx(dte=1, entry_cost=-100.0, unrealized_pl=10.0,
                        short_strikes=[90.0], spot=0.0)
        s = suggest_action(ctx)
        self.assertEqual(s.action, "close")

    def test_metrics_dict_populated(self):
        ctx = _make_ctx(dte=30, entry_cost=-100.0, unrealized_pl=10.0, spot=100.0)
        s = suggest_action(ctx)
        self.assertEqual(set(s.metrics.keys()),
                         {"return_pct", "dte", "short_strike", "proximity_pct"})


if __name__ == "__main__":
    unittest.main()
