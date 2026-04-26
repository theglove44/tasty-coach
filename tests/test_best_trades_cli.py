"""Tests for TCBT-2 best-trades CLI entry point and launcher integration."""

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, MagicMock, patch


class TestBestTradesArgparse(unittest.TestCase):
    """Test argparse integration for best-trades flags."""

    def setUp(self):
        from main import setup_argument_parser
        self.parser = setup_argument_parser()

    def test_help_lists_best_trades_flag(self):
        help_text = self.parser.format_help()
        self.assertIn("--best-trades", help_text)

    def test_help_lists_top_flag(self):
        help_text = self.parser.format_help()
        self.assertIn("--top", help_text)

    def test_help_lists_bt_watchlist_flag(self):
        help_text = self.parser.format_help()
        self.assertIn("--bt-watchlist", help_text)

    def test_best_trades_defaults(self):
        args = self.parser.parse_args(["--best-trades"])
        self.assertTrue(args.best_trades)
        self.assertEqual(args.top, 3)
        self.assertIsNone(args.bt_watchlist)
        self.assertEqual(args.format, "text")

    def test_bt_watchlist_appends(self):
        args = self.parser.parse_args(["--best-trades", "--bt-watchlist", "A", "--bt-watchlist", "B"])
        self.assertEqual(args.bt_watchlist, ["A", "B"])

    def test_top_parses_int(self):
        args = self.parser.parse_args(["--best-trades", "--top", "7"])
        self.assertEqual(args.top, 7)

    def test_format_choice_reused(self):
        args = self.parser.parse_args(["--best-trades", "--format", "json"])
        self.assertEqual(args.format, "json")

    def test_existing_watchlist_flag_unaffected(self):
        args = self.parser.parse_args(["-w", "Foo"])
        self.assertEqual(args.watchlist, "Foo")
        self.assertIsNone(args.bt_watchlist)


class TestRunBestTradesStub(unittest.IsolatedAsyncioTestCase):
    """Test the run_best_trades stub function."""

    async def test_default_watchlists_used_when_none(self):
        from agents.trade_ranker import run_best_trades, DEFAULT_WATCHLISTS
        result = await run_best_trades(MagicMock())
        self.assertEqual(result["watchlists"], list(DEFAULT_WATCHLISTS))

    async def test_explicit_watchlists_honoured(self):
        from agents.trade_ranker import run_best_trades
        result = await run_best_trades(MagicMock(), watchlists=["X", "Y"])
        self.assertEqual(result["watchlists"], ["X", "Y"])

    async def test_explicit_empty_watchlists_honoured(self):
        from agents.trade_ranker import run_best_trades
        result = await run_best_trades(MagicMock(), watchlists=[])
        self.assertEqual(result["watchlists"], [])

    async def test_canonical_shape(self):
        from agents.trade_ranker import run_best_trades
        result = await run_best_trades(MagicMock())
        self.assertEqual(set(result.keys()), {"top", "rejected", "warnings", "watchlists"})
        self.assertEqual(result["top"], [])
        self.assertEqual(result["rejected"], [])
        self.assertEqual(result["warnings"], [])

    async def test_session_not_called(self):
        from agents.trade_ranker import run_best_trades
        session = MagicMock()
        await run_best_trades(session)
        self.assertEqual(session.method_calls, [])
        self.assertEqual(session.mock_calls, [])

    async def test_top_arg_accepted(self):
        from agents.trade_ranker import run_best_trades
        result = await run_best_trades(MagicMock(), top=10)
        self.assertEqual(set(result.keys()), {"top", "rejected", "warnings", "watchlists"})

    async def test_output_format_arg_accepted(self):
        from agents.trade_ranker import run_best_trades
        result = await run_best_trades(MagicMock(), output_format="json")
        self.assertEqual(set(result.keys()), {"top", "rejected", "warnings", "watchlists"})


class TestBestTradesCliOutput(unittest.IsolatedAsyncioTestCase):
    """Test text and JSON output formats and CLI dispatch."""

    def test_text_output_contains_stub_marker(self):
        from agents.trade_ranker import _print_best_trades_text, STUB_MARKER
        result = {"top": [], "rejected": [], "warnings": [], "watchlists": ["A"]}
        f = io.StringIO()
        with redirect_stdout(f):
            _print_best_trades_text(result, 3)
        self.assertIn(STUB_MARKER, f.getvalue())

    def test_text_output_lists_watchlists(self):
        from agents.trade_ranker import _print_best_trades_text
        result = {"top": [], "rejected": [], "warnings": [], "watchlists": ["A"]}
        f = io.StringIO()
        with redirect_stdout(f):
            _print_best_trades_text(result, 3)
        self.assertIn("A", f.getvalue())

    def _build_client_mock(self):
        client_inst = MagicMock()
        client_inst.authenticate.return_value = True
        client_inst.get_session.return_value = MagicMock()
        client_inst.config.log_level = "INFO"
        client_inst.config.account_number = None
        client_inst.config.ivr_threshold = 25.0
        return client_inst

    async def test_json_dispatch_emits_valid_json(self):
        result_dict = {"top": [], "rejected": [], "warnings": [], "watchlists": ["X"]}
        with patch("main._warn_if_not_in_venv"), \
             patch("agents.trade_ranker.run_best_trades", new_callable=AsyncMock) as mock_run, \
             patch("main.TastyClient") as mock_client:
            mock_run.return_value = result_dict
            mock_client.return_value = self._build_client_mock()
            f = io.StringIO()
            with redirect_stdout(f), patch.object(sys, "argv", ["main.py", "--best-trades", "--format", "json"]):
                from main import async_main
                rc = await async_main()
            parsed = json.loads(f.getvalue().strip())
            self.assertEqual(parsed, result_dict)
            self.assertEqual(rc, 0)

    async def test_text_dispatch_calls_printer(self):
        result_dict = {"top": [], "rejected": [], "warnings": [], "watchlists": ["A"]}
        with patch("main._warn_if_not_in_venv"), \
             patch("agents.trade_ranker.run_best_trades", new_callable=AsyncMock) as mock_run, \
             patch("agents.trade_ranker._print_best_trades_text") as mock_printer, \
             patch("main.TastyClient") as mock_client:
            mock_run.return_value = result_dict
            mock_client.return_value = self._build_client_mock()
            with patch.object(sys, "argv", ["main.py", "--best-trades", "--format", "text"]):
                from main import async_main
                await async_main()
            mock_printer.assert_called_once_with(result_dict, 3)

    async def test_dispatch_passes_bt_watchlist(self):
        with patch("main._warn_if_not_in_venv"), \
             patch("agents.trade_ranker.run_best_trades", new_callable=AsyncMock) as mock_run, \
             patch("main.TastyClient") as mock_client:
            mock_run.return_value = {"top": [], "rejected": [], "warnings": [], "watchlists": ["FOO", "BAR"]}
            mock_client.return_value = self._build_client_mock()
            with patch.object(sys, "argv", ["main.py", "--best-trades", "--bt-watchlist", "FOO", "--bt-watchlist", "BAR"]):
                from main import async_main
                await async_main()
            self.assertEqual(mock_run.call_args[1]["watchlists"], ["FOO", "BAR"])

    async def test_dispatch_passes_top(self):
        with patch("main._warn_if_not_in_venv"), \
             patch("agents.trade_ranker.run_best_trades", new_callable=AsyncMock) as mock_run, \
             patch("main.TastyClient") as mock_client:
            mock_run.return_value = {"top": [], "rejected": [], "warnings": [], "watchlists": []}
            mock_client.return_value = self._build_client_mock()
            with patch.object(sys, "argv", ["main.py", "--best-trades", "--top", "5"]):
                from main import async_main
                await async_main()
            self.assertEqual(mock_run.call_args[1]["top"], 5)

    async def test_dispatch_runs_without_account(self):
        with patch("main._warn_if_not_in_venv"), \
             patch("agents.trade_ranker.run_best_trades", new_callable=AsyncMock) as mock_run, \
             patch("main.TastyClient") as mock_client:
            mock_run.return_value = {"top": [], "rejected": [], "warnings": [], "watchlists": []}
            client_inst = self._build_client_mock()
            client_inst.get_accounts = AsyncMock(side_effect=AssertionError("get_accounts must not be called for --best-trades"))
            mock_client.return_value = client_inst
            with patch.object(sys, "argv", ["main.py", "--best-trades"]):
                from main import async_main
                rc = await async_main()
            self.assertEqual(rc, 0)


class TestBestTradesLauncher(unittest.IsolatedAsyncioTestCase):
    """Test launcher integration."""

    def _build_ui(self):
        from utils.launcher_ui import LauncherUI
        ui = LauncherUI(MagicMock(), MagicMock())
        ui.context = MagicMock()
        return ui

    def test_action_present(self):
        ui = self._build_ui()
        b_actions = [a for a in ui._actions() if a.key == "b"]
        self.assertEqual(len(b_actions), 1)
        self.assertEqual(b_actions[0].title, "Best trades today")

    def test_action_handler_is_method(self):
        ui = self._build_ui()
        b_action = next(a for a in ui._actions() if a.key == "b")
        self.assertEqual(b_action.handler, ui._run_best_trades)

    def test_action_does_not_exit(self):
        ui = self._build_ui()
        b_action = next(a for a in ui._actions() if a.key == "b")
        self.assertFalse(b_action.exit_on_run)

    async def test_handler_calls_run_best_trades(self):
        with patch("agents.trade_ranker.run_best_trades", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = {"top": [], "rejected": [], "warnings": [], "watchlists": []}
            ui = self._build_ui()
            ui.session = MagicMock()
            await ui._run_best_trades()
            mock_run.assert_called_once()
            self.assertEqual(mock_run.call_args[0][0], ui.session)

    async def test_handler_prints_via_text_printer(self):
        with patch("agents.trade_ranker.run_best_trades", new_callable=AsyncMock) as mock_run, \
             patch("agents.trade_ranker._print_best_trades_text") as mock_printer:
            mock_run.return_value = {"top": [], "rejected": [], "warnings": [], "watchlists": []}
            ui = self._build_ui()
            ui.session = MagicMock()
            await ui._run_best_trades()
            mock_printer.assert_called_once()


if __name__ == "__main__":
    unittest.main()
