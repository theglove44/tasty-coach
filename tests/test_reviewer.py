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


if __name__ == "__main__":
    unittest.main()
