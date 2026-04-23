import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from utils.launcher_ui import LauncherUI


class TestLauncherUI(unittest.IsolatedAsyncioTestCase):
    async def test_review_position_accepts_typed_symbol_directly(self):
        """Option 7 should not force a watchlist when a symbol is typed."""
        ui = LauncherUI(MagicMock(), MagicMock(), account_number="A123")
        ui.context = SimpleNamespace(account_number="A123")
        ui._prompt_text = AsyncMock(side_effect=["NVDA", "n", ""])
        ui._get_account_symbols = AsyncMock(side_effect=AssertionError("position picker should not be opened"))

        reviewer = MagicMock()
        reviewer.review_positions = AsyncMock(return_value=[SimpleNamespace()])
        reviewer.print_review_report = MagicMock()

        reviewer_factory = MagicMock()
        reviewer_factory.return_value.init = AsyncMock(return_value=reviewer)

        with patch("utils.launcher_ui.ReviewerAgent", reviewer_factory):
            await ui._run_review_position()

        reviewer.review_positions.assert_awaited_once_with(underlying_filter="NVDA")
        reviewer.print_review_report.assert_called_once()
        ui._get_account_symbols.assert_not_called()

    async def test_review_position_blank_symbol_uses_open_position_picker(self):
        """Blank review input should fall back to account positions, not watchlists."""
        ui = LauncherUI(MagicMock(), MagicMock(), account_number="A123")
        ui.context = SimpleNamespace(account_number="A123")
        ui._prompt_text = AsyncMock(side_effect=["", "n", ""])
        ui._get_account_symbols = AsyncMock(return_value=["AAPL", "NVDA"])
        ui._pick_symbol = AsyncMock(return_value="NVDA")

        reviewer = MagicMock()
        reviewer.review_positions = AsyncMock(return_value=[SimpleNamespace()])
        reviewer.print_review_report = MagicMock()

        reviewer_factory = MagicMock()
        reviewer_factory.return_value.init = AsyncMock(return_value=reviewer)

        with patch("utils.launcher_ui.ReviewerAgent", reviewer_factory):
            await ui._run_review_position()

        ui._get_account_symbols.assert_awaited_once()
        ui._pick_symbol.assert_awaited_once()
        reviewer.review_positions.assert_awaited_once_with(underlying_filter="NVDA")


if __name__ == "__main__":
    unittest.main()
