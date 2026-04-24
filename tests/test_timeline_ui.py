"""Tests for utils/timeline_ui.py — renderer + orchestrator."""

import io
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from rich.console import Console
from rich.panel import Panel

from agents.timeline import TimelineEvent
from utils.timeline_ui import MAX_ROWS, render_timeline, run_timeline


def _evt(event_type="open", amount=None, quantity=None, is_roll_leg=False,
         occurred_at=None, symbol="SPY", underlying="SPY", description="desc",
         transaction_id=1, order_id=None):
    if occurred_at is None:
        occurred_at = datetime(2026, 4, 24, 10, tzinfo=timezone.utc)
    return TimelineEvent(
        event_type=event_type,
        occurred_at=occurred_at,
        symbol=symbol,
        underlying_symbol=underlying,
        description=description,
        quantity=quantity,
        amount=amount,
        transaction_id=transaction_id,
        order_id=order_id,
        raw_type="Trade",
        raw_sub_type="",
        is_roll_leg=is_roll_leg,
    )


def _render_to_str(renderable) -> str:
    c = Console(record=True, width=200, force_terminal=False)
    c.print(renderable)
    return c.export_text()


class TestRenderTimeline(unittest.TestCase):
    def test_render_empty_shows_no_events_message(self):
        out = _render_to_str(render_timeline([], days=30, account_number="ACCT"))
        self.assertIn("No events in the last 30 days", out)

    def test_render_includes_account_and_days_in_title(self):
        out = _render_to_str(render_timeline([], days=30, account_number="ACCT123"))
        self.assertIn("ACCT123", out)
        self.assertIn("30d", out)

    def test_render_single_assignment_row(self):
        e = _evt(event_type="assignment", symbol="SPY", description="Assigned 100 SPY")
        out = _render_to_str(render_timeline([e], days=30, account_number="A"))
        self.assertIn("assignment", out)
        self.assertIn("SPY", out)
        self.assertIn("Assigned 100 SPY", out)

    def test_render_signed_amount_positive_prefix(self):
        e = _evt(amount=Decimal("1.50"))
        out = _render_to_str(render_timeline([e], days=30, account_number="A"))
        self.assertIn("+$1.50", out)

    def test_render_signed_amount_negative_prefix(self):
        e = _evt(amount=Decimal("-2.00"))
        out = _render_to_str(render_timeline([e], days=30, account_number="A"))
        self.assertIn("-$2.00", out)

    def test_render_roll_leg_labelled_roll(self):
        e = _evt(event_type="close", is_roll_leg=True)
        out = _render_to_str(render_timeline([e], days=30, account_number="A"))
        self.assertIn("roll", out)

    def test_render_truncates_beyond_max_rows(self):
        events = [_evt(transaction_id=i) for i in range(MAX_ROWS + 50)]
        out = _render_to_str(render_timeline(events, days=30, account_number="A"))
        self.assertIn(f"showing newest {MAX_ROWS} of {MAX_ROWS + 50}", out)

    def test_render_handles_none_amount_and_quantity(self):
        e = _evt(amount=None, quantity=None)
        panel = render_timeline([e], days=30, account_number="A")
        self.assertIsInstance(panel, Panel)

    def test_render_handles_datetime_min(self):
        e = _evt(occurred_at=datetime.min.replace(tzinfo=timezone.utc))
        out = _render_to_str(render_timeline([e], days=30, account_number="A"))
        self.assertIn("—", out)

    def test_render_returns_panel_instance(self):
        self.assertIsInstance(render_timeline([], days=30, account_number="A"), Panel)


class TestRunTimeline(unittest.IsolatedAsyncioTestCase):
    async def test_run_timeline_success_returns_zero(self):
        events = [_evt(event_type="open", description="opened")]
        fake_agent = MagicMock()
        fake_agent.account = object()
        fake_agent.get_recent_events = AsyncMock(return_value=events)
        async def fake_init():
            return fake_agent

        buf = io.StringIO()
        console = Console(file=buf, width=200, force_terminal=False)

        with patch("agents.history.HistoryAgent") as MockAgent:
            instance = MockAgent.return_value
            instance.init = fake_init
            rc = await run_timeline(
                session=MagicMock(), account_number="ACCT",
                days=30, console=console,
            )

        self.assertEqual(rc, 0)
        self.assertIn("Event Timeline", buf.getvalue())

    async def test_run_timeline_catches_fetch_error_returns_one(self):
        async def boom():
            raise RuntimeError("fetch failed")

        # Capture stderr
        stderr = io.StringIO()
        with patch("sys.stderr", stderr), patch("agents.history.HistoryAgent") as MockAgent:
            instance = MockAgent.return_value
            instance.init = AsyncMock(side_effect=RuntimeError("fetch failed"))
            rc = await run_timeline(
                session=MagicMock(), account_number="ACCT",
                days=30, console=Console(file=io.StringIO(), force_terminal=False),
            )

        self.assertEqual(rc, 1)
        self.assertIn("Error fetching timeline", stderr.getvalue())

    async def test_run_timeline_empty_still_returns_zero(self):
        fake_agent = MagicMock()
        fake_agent.account = object()  # non-None — account resolved
        fake_agent.get_recent_events = AsyncMock(return_value=[])
        async def fake_init():
            return fake_agent

        with patch("agents.history.HistoryAgent") as MockAgent:
            instance = MockAgent.return_value
            instance.init = fake_init
            rc = await run_timeline(
                session=MagicMock(), account_number="ACCT",
                days=30, console=Console(file=io.StringIO(), force_terminal=False),
            )

        self.assertEqual(rc, 0)

    async def test_run_timeline_unresolved_account_returns_one(self):
        fake_agent = MagicMock()
        fake_agent.account = None  # init succeeded but account not resolved
        fake_agent.get_recent_events = AsyncMock(return_value=[])
        async def fake_init():
            return fake_agent

        stderr = io.StringIO()
        with patch("sys.stderr", stderr), patch("agents.history.HistoryAgent") as MockAgent:
            instance = MockAgent.return_value
            instance.init = fake_init
            rc = await run_timeline(
                session=MagicMock(), account_number="NOPE",
                days=30, console=Console(file=io.StringIO(), force_terminal=False),
            )

        self.assertEqual(rc, 1)
        self.assertIn("could not be resolved", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
