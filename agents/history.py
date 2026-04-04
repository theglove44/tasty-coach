"""Account history and performance reporting."""

import calendar
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from tastytrade import Account, Session
from tastytrade.utils import today_in_new_york

from utils import redact

EXTERNAL_FLOW_SUBTYPES = {
    "ACAT",
    "Balance Adjustment",
    "Deposit",
    "Transfer",
    "Withdrawal",
}


@dataclass
class PerformancePeriod:
    """Defines the start and end of a requested performance window."""

    label: str
    start_date: date
    end_date: date
    start_time: datetime
    end_time: datetime


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
        accounts = await Account.get(self.session)
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
            return PerformancePeriod(
                label=month_start.strftime("%B %Y"),
                start_date=month_start,
                end_date=min(month_end, current_day),
                start_time=datetime.combine(month_start, time.min),
                end_time=datetime.combine(min(month_end, current_day), time.max),
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
            start_time=datetime.combine(start_date, time.min),
            end_time=datetime.combine(current_day, time.max),
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
        nlv_history = await self.account.get_net_liquidating_value_history(
            self.session,
            start_time=period.start_time,
        )
        nlv_history = [
            item for item in nlv_history if self._history_point_time(item.time) <= period.end_time
        ]
        transactions = await self.account.get_history(
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
            period_start=period.start_time,
            period_end=period.end_time,
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

            executed_at = getattr(tx, "executed_at", None) or datetime.combine(
                getattr(tx, "transaction_date"),
                time.min,
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
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).replace(tzinfo=None)

    def print_performance_report(self, report: Dict[str, Any], discord: bool = False) -> None:
        """Render a CLI-friendly account performance summary."""
        open_block = "```" if discord else ""
        close_block = "```" if discord else ""
        account_number = redact.account(report["account_number"])

        print(
            f"{open_block}ACCOUNT PERFORMANCE ({account_number})"
            f"\nPeriod:        {report['label']} ({report['start_date']} to {report['end_date']})"
            f"\nStart NLV:     ${redact.dollars(report['starting_value'])}"
            f"\nEnd NLV:       ${redact.dollars(report['ending_value'])}"
            f"\nHigh / Low:    ${redact.dollars(report['high_value'])} / ${redact.dollars(report['low_value'])}"
            f"\nNet Flows:     ${redact.dollars(report['net_external_flow'])}"
            f"\nAdj. P&L:      ${redact.dollars(report['adjusted_pnl'])}"
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
                f"${redact.dollars(flow['amount'])} | {flow['description']}"
            )
        print(close_block)
