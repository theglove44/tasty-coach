import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agents.reviewer import ReviewerAgent


class TestReviewerAgent(unittest.IsolatedAsyncioTestCase):
    async def test_enrich_chain_treats_missing_quote_volume_as_zero(self):
        """Regression: market data can return None volume/OI fields."""
        option = SimpleNamespace(
            symbol="NVDA  260619P00100000",
            strike_price=Decimal("100"),
            option_type="PUT",
            expiration_date=None,
        )
        quote = SimpleNamespace(
            symbol=option.symbol,
            bid=Decimal("1.20"),
            ask=Decimal("1.30"),
            mark=Decimal("1.25"),
            volume=None,
            open_interest=None,
        )

        reviewer = ReviewerAgent(MagicMock())
        with patch("agents.reviewer.get_market_data_by_type", return_value=[quote]):
            result = await reviewer._enrich_chain_with_market_data([option])

        self.assertEqual(len(result["options"]), 1)
        enriched = result["options"][0]
        self.assertEqual(enriched["volume"], 0)
        self.assertEqual(enriched["open_interest"], 0)
        self.assertEqual(enriched["bid"], 1.2)
        self.assertEqual(enriched["ask"], 1.3)
        self.assertEqual(enriched["mark"], 1.25)

    async def test_format_leg_summary_shows_each_iron_condor_leg(self):
        """Roll tables should not collapse iron condors to min/max strikes."""
        legs = [
            {"action": "STO", "option_type": "CALL", "strike": 45.0, "quantity": 1},
            {"action": "BTO", "option_type": "PUT", "strike": 25.0, "quantity": 1},
            {"action": "BTO", "option_type": "CALL", "strike": 50.0, "quantity": 1},
            {"action": "STO", "option_type": "PUT", "strike": 30.0, "quantity": 1},
        ]

        summary = ReviewerAgent._format_leg_summary(legs)

        self.assertEqual(summary, "BTO 25P / STO 30P / STO 45C / BTO 50C")


class TestReviewerAdvisorIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_review_positions_populates_action_suggestion(self):
        from datetime import date, timedelta
        from agents.advisor import ActionSuggestion
        from agents.reviewer import PositionContext

        sentinel = ActionSuggestion(
            action="hold", confidence="low", reason="test sentinel",
        )

        reviewer = ReviewerAgent(MagicMock())
        reviewer.portfolio = MagicMock()

        position_ctx = PositionContext(
            underlying="X", current_price=100.0, legs=[],
            strategy_type="Put Vertical", dte=30,
            expiration=date.today() + timedelta(days=30),
            total_quantity=1, entry_cost=-100.0,
            current_value=50.0, unrealized_pl=10.0,
        )

        async def _fake_get_positions():
            return [MagicMock()]
        reviewer.portfolio.get_positions = _fake_get_positions
        reviewer.portfolio._group_positions = MagicMock(return_value={
            "X": [{"name": "Put Vertical", "legs": [MagicMock()]}]
        })

        async def _fake_fetch_ctx(legs, underlying):
            return position_ctx
        async def _fake_chain(underlying, exp):
            return {"expirations": {}, "call_strikes": [], "put_strikes": []}
        async def _fake_scenarios(ctx, chain):
            return []

        reviewer._fetch_position_context = _fake_fetch_ctx
        reviewer._fetch_roll_chain_data = _fake_chain
        reviewer._generate_roll_scenarios = _fake_scenarios

        with patch("agents.reviewer.suggest_action", return_value=sentinel) as m:
            results = await reviewer.review_positions()

        self.assertEqual(len(results), 1)
        self.assertIs(results[0].action_suggestion, sentinel)
        m.assert_called_once()

    def test_print_review_report_renders_suggestion_line(self):
        from datetime import date, timedelta
        from io import StringIO
        from rich.console import Console
        from agents.advisor import ActionSuggestion
        from agents.reviewer import PositionContext, ReviewResult

        position_ctx = PositionContext(
            underlying="X", current_price=100.0, legs=[],
            strategy_type="Put Vertical", dte=30,
            expiration=date.today() + timedelta(days=30),
            total_quantity=1, entry_cost=-100.0,
            current_value=50.0, unrealized_pl=10.0,
        )
        result = ReviewResult(
            position=position_ctx, roll_scenarios=[],
            available_expirations=[], available_strikes={"calls": [], "puts": []},
            metadata={},
            action_suggestion=ActionSuggestion(
                action="hold", confidence="low", reason="unit test reason",
            ),
        )

        buf = StringIO()
        with patch("agents.reviewer.Console", return_value=Console(file=buf, width=200, force_terminal=False)):
            reviewer = ReviewerAgent(MagicMock())
            reviewer.print_review_report([result])

        output = buf.getvalue()
        self.assertIn("Suggestion:", output)
        self.assertIn("hold", output)
        self.assertIn("unit test reason", output)


if __name__ == "__main__":
    unittest.main()
