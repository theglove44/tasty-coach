import unittest
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agents.history import AccountHistoryAgent


class TestAccountHistoryAgent(unittest.IsolatedAsyncioTestCase):
    async def test_build_performance_report_uses_utc_history_bounds(self) -> None:
        """History windows should convert New York midnights to UTC before querying."""
        mock_session = MagicMock()
        mock_account = MagicMock()
        mock_account.account_number = "5WT00000"

        first_point = SimpleNamespace(
            time="2026-01-08T05:00:00Z",
            open="100.0",
            high="105.0",
            low="95.0",
            close="101.0",
        )
        second_point = SimpleNamespace(
            time="2026-01-16T04:30:00Z",
            open="101.0",
            high="111.0",
            low="99.0",
            close="110.0",
        )

        mock_account.get_net_liquidating_value_history.return_value = [first_point, second_point]
        mock_account.get_history.return_value = []

        with patch("agents.history.today_in_new_york", return_value=date(2026, 1, 15)), patch(
            "tastytrade.Account.get", return_value=[mock_account]
        ):
            agent = await AccountHistoryAgent(mock_session).init()
            report = await agent.build_performance_report(range_name="week")

        expected_start_time = datetime(2026, 1, 8, 5, 0, 0)
        mock_account.get_net_liquidating_value_history.assert_called_once_with(
            mock_session,
            start_time=expected_start_time,
        )

        self.assertEqual(report["starting_value"], Decimal("100.0"))
        self.assertEqual(report["ending_value"], Decimal("110.0"))
        self.assertEqual(report["high_value"], Decimal("111.0"))
        self.assertEqual(report["low_value"], Decimal("95.0"))
        self.assertEqual(len(report["history_points"]), 2)


if __name__ == "__main__":
    unittest.main()
