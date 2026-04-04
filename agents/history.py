"""Account history and performance reporting."""

import calendar
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from tastytrade import Account, Session
from tastytrade.utils import today_in_new_york

EXTERNAL_FLOW_SUBTYPES = {
    "ACAT",
    "Balance Adjustment",
    "Deposit",
    "Transfer",
    "Withdrawal",
}

NEW_YORK_TZ = ZoneInfo("America/New_York")


def _format_dollars(value: Decimal) -> str:
    """Format a decimal dollar amount for CLI output."""
    return f"{float(value):,.2f}"


def _format_account(account_number: Optional[str]) -> str:
    """Return the account number as-is when no redaction helper is available."""
    return account_number or "Unknown"


@dataclass
class PerformancePeriod:
    """Defines the start and end of a requested performance window."""

    label: str
    start_date: date
    end_date: date
    start_time: datetime
    end_time: datetime
    start_time_utc: datetime
    end_time_utc: datetime


class AccountHistoryAgent:
    """Builds account performance summaries from tastytrade history endpoints."""

    def __init__(self, session: Session, account_number: Optional[str] = None):
        self.session = session
        self.logger = logging.getLogger(__name__)
        self.account_number = account_number
        self.account: Optional[Account] = None

    async def init(self) -> "AccountHistoryAgent":
        """Async initialization that resolves the selected account."""
        self.account = await self._get_account()
        return self

    async def _get_account(self) -> Account:
        """Fetch the configured account."""
        accounts = Account.get(self.session)
        if not accounts:
            raise ValueError("No accounts found.")

        if self.account_number:
            for acct in accounts:
                if getattr(acct, "account_number", None) == self.account_number:
                    return acct
            available = ", ".join([getattr(a, "account_number", "?") for a in accounts])
            raise ValueError(f"Account {self.account_number} not found. Available: {available}")

        return accounts[0]

    def resolve_period(
        self,
        range_name: Optional[str] = None,
        month: Optional[str] = None,
        today: Optional[date] = None,
    ) -> PerformancePeriod:
        """Translate CLI period input into a concrete date range."""
        current_day = today or today_in_new_york()

        if month:
            try:
                month_start = datetime.strptime(month, "%Y-%m").date().replace(day=1)
            except ValueError as exc:
                raise ValueError("Month must use YYYY-MM format, for example 2026-03") from exc

            if month_start > current_day:
                raise ValueError("History month cannot be in the future")

            last_day = calendar.monthrange(month_start.year, month_start.month)[1]
            month_end = month_start.replace(day=last_day)
            end_date = min(month_end, current_day)
            return PerformancePeriod(
                label=month_start.strftime("%B %Y"),
                start_date=month_start,
                end_date=end_date,
                start_time=self._local_midnight(month_start),
                end_time=self._local_end_of_day(end_date),
                start_time_utc=self._local_midnight(month_start).astimezone(timezone.utc),
                end_time_utc=self._local_end_of_day(end_date).astimezone(timezone.utc),
            )

        normalized_range = range_name or "month"
        if normalized_range == "week":
            start_date = current_day - timedelta(days=7)
            label = "Previous 7 Days"
        elif normalized_range == "month":
            start_date = current_day - timedelta(days=30)
            label = "Previous 30 Days"
        elif normalized_range == "year":
            start_date = current_day - timedelta(days=365)
            label = "Previous 1 Year"
        else:
            raise ValueError("History range must be one of: week, month, year")

        return PerformancePeriod(
            label=label,
            start_date=start_date,
            end_date=current_day,
            start_time=self._local_midnight(start_date),
            end_time=self._local_end_of_day(current_day),
            start_time_utc=self._local_midnight(start_date).astimezone(timezone.utc),
            end_time_utc=self._local_end_of_day(current_day).astimezone(timezone.utc),
        )

    async def build_performance_report(
        self,
        range_name: Optional[str] = None,
        month: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fetch account history and calculate period performance."""
        if not self.account:
            raise ValueError("Account is not initialized")

        period = self.resolve_period(range_name=range_name, month=month)
        nlv_history = self.account.get_net_liquidating_value_history(
            self.session,
            start_time=period.start_time_utc.replace(tzinfo=None),
        )
        nlv_history = [
            item for item in nlv_history if self._history_point_time(item.time) <= period.end_time_utc
        ]
        transactions = self.account.get_history(
            self.session,
            sort="Asc",
            start_date=period.start_date,
            end_date=period.end_date,
            page_offset=None,
        )

        if not nlv_history:
            raise ValueError(
                f"No net liquidation history returned for {period.label} "
                f"({period.start_date.isoformat()} to {period.end_date.isoformat()})"
            )

        starting_value = Decimal(nlv_history[0].open)
        ending_value = Decimal(nlv_history[-1].close)
        high_value = max(Decimal(item.high) for item in nlv_history)
        low_value = min(Decimal(item.low) for item in nlv_history)

        external_flows = self._extract_external_flows(
            transactions,
            period_start=period.start_time_utc,
            period_end=period.end_time_utc,
        )
        net_external_flow = sum((flow["amount"] for flow in external_flows), Decimal("0"))
        adjusted_pnl = ending_value - starting_value - net_external_flow
        return_pct = self._modified_dietz_return(
            starting_value=starting_value,
            ending_value=ending_value,
            cash_flows=external_flows,
        )

        return {
            "label": period.label,
            "account_number": getattr(self.account, "account_number", self.account_number),
            "start_date": period.start_date,
            "end_date": period.end_date,
            "starting_value": starting_value,
            "ending_value": ending_value,
            "high_value": high_value,
            "low_value": low_value,
            "net_external_flow": net_external_flow,
            "adjusted_pnl": adjusted_pnl,
            "return_pct": return_pct,
            "external_flows": external_flows,
            "history_points": [
                {
                    "time": item.time,
                    "open": Decimal(item.open),
                    "high": Decimal(item.high),
                    "low": Decimal(item.low),
                    "close": Decimal(item.close),
                }
                for item in nlv_history
            ],
        }

    def _extract_external_flows(
        self,
        transactions: List[Any],
        period_start: datetime,
        period_end: datetime,
    ) -> List[Dict[str, Any]]:
        """Filter transactions down to deposits and withdrawals that distort returns."""
        flows: List[Dict[str, Any]] = []

        for tx in transactions:
            sub_type = getattr(tx, "transaction_sub_type", "")
            if sub_type not in EXTERNAL_FLOW_SUBTYPES:
                continue

            executed_at = self._normalize_utc_datetime(
                getattr(tx, "executed_at", None)
                or datetime.combine(getattr(tx, "transaction_date"), time.min, tzinfo=timezone.utc)
            )
            amount = Decimal(getattr(tx, "net_value"))
            flows.append(
                {
                    "date": getattr(tx, "transaction_date"),
                    "executed_at": executed_at,
                    "sub_type": sub_type,
                    "description": getattr(tx, "description", ""),
                    "amount": amount,
                    "weight": self._flow_weight(
                        period_start=period_start,
                        flow_time=executed_at,
                        period_end=period_end,
                    ),
                }
            )

        return flows

    def _modified_dietz_return(
        self,
        starting_value: Decimal,
        ending_value: Decimal,
        cash_flows: List[Dict[str, Any]],
    ) -> Decimal:
        """Calculate a cash-flow-adjusted return using the Modified Dietz method."""
        net_cash_flow = sum((flow["amount"] for flow in cash_flows), Decimal("0"))
        pnl = ending_value - starting_value - net_cash_flow
        weighted_flows = sum(
            (flow["amount"] * flow["weight"] for flow in cash_flows),
            Decimal("0"),
        )
        denominator = starting_value + weighted_flows
        if denominator == 0:
            return Decimal("0")
        return (pnl / denominator) * Decimal("100")

    def _flow_weight(
        self,
        period_start: datetime,
        flow_time: datetime,
        period_end: datetime,
    ) -> Decimal:
        """Return the remaining-period weight for Modified Dietz calculations."""
        total_seconds = Decimal((period_end - period_start).total_seconds())
        remaining_seconds = Decimal(max((period_end - flow_time).total_seconds(), 0))
        if total_seconds <= 0:
            return Decimal("0")
        return remaining_seconds / total_seconds

    def _history_point_time(self, timestamp: str) -> datetime:
        """Parse tastytrade history timestamps into comparable datetimes."""
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)

    def _normalize_utc_datetime(self, value: datetime) -> datetime:
        """Return a UTC-aware datetime for internal comparisons."""
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _local_midnight(self, day: date) -> datetime:
        """Return a New York-local midnight for the requested date."""
        return datetime.combine(day, time.min, tzinfo=NEW_YORK_TZ)

    def _local_end_of_day(self, day: date) -> datetime:
        """Return a New York-local end-of-day timestamp for the requested date."""
        return datetime.combine(day, time.max, tzinfo=NEW_YORK_TZ)

    def print_performance_report(self, report: Dict[str, Any], discord: bool = False) -> None:
        """Render a CLI-friendly account performance summary."""
        open_block = "```" if discord else ""
        close_block = "```" if discord else ""
        account_number = _format_account(report["account_number"])

        print(
            f"{open_block}ACCOUNT PERFORMANCE ({account_number})"
            f"\nPeriod:        {report['label']} ({report['start_date']} to {report['end_date']})"
            f"\nStart NLV:     ${_format_dollars(report['starting_value'])}"
            f"\nEnd NLV:       ${_format_dollars(report['ending_value'])}"
            f"\nHigh / Low:    ${_format_dollars(report['high_value'])} / ${_format_dollars(report['low_value'])}"
            f"\nNet Flows:     ${_format_dollars(report['net_external_flow'])}"
            f"\nAdj. P&L:      ${_format_dollars(report['adjusted_pnl'])}"
            f"\nReturn:        {float(report['return_pct']):.2f}%{close_block}"
        )

        flows = report["external_flows"]
        if not flows:
            print(f"{open_block}No deposits or withdrawals during this period.{close_block}")
            return

        print(f"{open_block}EXTERNAL CASH FLOWS")
        for flow in flows:
            print(
                f"{flow['date']} | {flow['sub_type']:<18} | "
                f"${_format_dollars(flow['amount'])} | {flow['description']}"
            )
        print(close_block)
