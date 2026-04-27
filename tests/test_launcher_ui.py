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


class TestSettingsEditorCoverage(unittest.IsolatedAsyncioTestCase):
    """Settings editor must expose every editable key from the settings module."""

    async def test_editor_iterates_numeric_integer_and_optional_keys(self):
        """The settings editor's editable_keys must be a superset of NUMERIC + INTEGER + OPTIONAL_NUMERIC."""
        from utils.settings import INTEGER_KEYS, NUMERIC_KEYS, OPTIONAL_NUMERIC_KEYS, settings as settings_obj
        ui = LauncherUI(MagicMock(), MagicMock(), account_number="A123")
        ui.console = MagicMock()
        prompted_keys: list[str] = []

        def fake_ask(prompt, default=None, console=None):
            prompted_keys.append(prompt.strip())
            return default if default is not None else ""

        with patch("rich.prompt.Prompt.ask", side_effect=fake_ask), \
             patch("rich.prompt.Confirm.ask", return_value=False):
            await ui._run_settings_editor()

        expected_keys = NUMERIC_KEYS | INTEGER_KEYS | OPTIONAL_NUMERIC_KEYS
        for key in expected_keys:
            self.assertTrue(
                any(key in p for p in prompted_keys),
                f"settings editor did not prompt for {key}",
            )

    async def test_descriptions_cover_every_editable_key(self):
        from utils.settings import INTEGER_KEYS, NUMERIC_KEYS, OPTIONAL_NUMERIC_KEYS, SETTINGS_DESCRIPTIONS
        editable = NUMERIC_KEYS | INTEGER_KEYS | OPTIONAL_NUMERIC_KEYS
        missing = editable - set(SETTINGS_DESCRIPTIONS.keys())
        self.assertEqual(missing, set(), f"missing descriptions: {missing}")


if __name__ == "__main__":
    unittest.main()
