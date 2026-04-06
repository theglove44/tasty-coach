"""Account history: performance reporting and transaction/order management."""

import calendar
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from rich.console import Console
from rich.table import Table

from tastytrade import Account, Session
from tastytrade.account import Transaction
from tastytrade.order import PlacedOrder, OrderStatus
from tastytrade.utils import today_in_new_york

from utils.db import TradeDB
from utils.trade_grouper import TradeGrouper

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


# ---------------------------------------------------------------------------
# HistoryAgent — transaction/order history display and local SQLite sync
# ---------------------------------------------------------------------------

class HistoryAgent:
    """Fetches and displays transaction and order history for an account."""

    def __init__(self, session: Session, account_number: Optional[str] = None):
        self.session = session
        self.logger = logging.getLogger(__name__)
        self.account_number = account_number
        self.account: Optional[Account] = None

    async def init(self) -> "HistoryAgent":
        """Async initialization — call after creating instance."""
        self.account = await self._get_account()
        return self

    async def _get_account(self) -> Optional[Account]:
        try:
            accounts = Account.get(self.session)
            if not accounts:
                return None

            if self.account_number:
                for acct in accounts:
                    if getattr(acct, "account_number", None) == self.account_number:
                        return acct
                available = ", ".join(
                    [getattr(a, "account_number", "?") for a in accounts]
                )
                raise ValueError(
                    f"Account {self.account_number} not found. Available: {available}"
                )

            return accounts[0]
        except Exception as e:
            self.logger.error(f"Error fetching accounts: {e}")
            return None

    async def get_transactions(
        self,
        days: int = 30,
        symbol: Optional[str] = None,
        transaction_type: Optional[str] = None,
    ) -> List[Transaction]:
        """Fetch transaction history from the API."""
        if not self.account:
            return []
        try:
            start = date.today() - timedelta(days=days)
            return self.account.get_history(
                self.session,
                page_offset=None,
                sort="Desc",
                start_date=start,
                type=transaction_type,
                underlying_symbol=symbol,
            )
        except Exception as e:
            self.logger.error(f"Error fetching transactions: {e}")
            return []

    async def get_orders(
        self,
        days: int = 30,
        symbol: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[PlacedOrder]:
        """Fetch order history from the API."""
        if not self.account:
            return []
        try:
            start = date.today() - timedelta(days=days)
            statuses = None
            if status:
                try:
                    statuses = [OrderStatus(status)]
                except ValueError:
                    self.logger.warning(f"Unknown order status: {status}")

            return self.account.get_order_history(
                self.session,
                page_offset=None,
                sort="Desc",
                start_date=start,
                underlying_symbol=symbol,
                statuses=statuses,
            )
        except Exception as e:
            self.logger.error(f"Error fetching orders: {e}")
            return []

    def print_transactions(
        self, transactions: List[Transaction], discord: bool = False
    ) -> None:
        """Display transactions in a Rich table."""
        if not transactions:
            print("No transactions found.")
            return

        console = Console(width=200)
        table = Table(
            title=f"Transaction History ({len(transactions)} records)",
            show_lines=False,
        )
        table.add_column("Date", style="cyan", no_wrap=True)
        table.add_column("Type", style="dim")
        table.add_column("Symbol")
        table.add_column("Underlying")
        table.add_column("Action", style="bold")
        table.add_column("Qty", justify="right")
        table.add_column("Price", justify="right")
        table.add_column("Value", justify="right")
        table.add_column("Fees", justify="right", style="dim")
        table.add_column("Order ID", style="dim", justify="right")

        for txn in transactions:
            total_fees = sum(
                float(f or 0)
                for f in [txn.commission, txn.clearing_fees, txn.regulatory_fees]
            )
            value = float(txn.net_value)
            value_str = f"[green]${value:,.2f}[/green]" if value >= 0 else f"[red]${value:,.2f}[/red]"

            table.add_row(
                txn.executed_at.strftime("%Y-%m-%d %H:%M") if txn.executed_at else "",
                txn.transaction_sub_type or txn.transaction_type,
                txn.symbol or "",
                txn.underlying_symbol or "",
                str(txn.action.value) if txn.action else "",
                f"{float(txn.quantity):g}" if txn.quantity else "",
                f"${float(txn.price):,.2f}" if txn.price else "",
                value_str,
                f"${total_fees:,.2f}" if total_fees else "",
                str(txn.order_id) if txn.order_id else "",
            )

        console.print(table)

        trade_txns = [t for t in transactions if t.transaction_type == "Trade"]
        if trade_txns:
            total_value = sum(float(t.net_value) for t in trade_txns)
            total_fees = sum(
                sum(float(f or 0) for f in [t.commission, t.clearing_fees, t.regulatory_fees])
                for t in trade_txns
            )
            color = "green" if total_value >= 0 else "red"
            console.print(
                f"\n  Trades: {len(trade_txns)} | "
                f"Net Value: [{color}]${total_value:,.2f}[/{color}] | "
                f"Total Fees: ${total_fees:,.2f}"
            )

    def print_orders(
        self, orders: List[PlacedOrder], discord: bool = False
    ) -> None:
        """Display orders in a Rich table."""
        if not orders:
            print("No orders found.")
            return

        console = Console(width=200)
        table = Table(
            title=f"Order History ({len(orders)} orders)",
            show_lines=True,
        )
        table.add_column("Date", style="cyan", no_wrap=True)
        table.add_column("Status")
        table.add_column("Underlying")
        table.add_column("Type", style="dim")
        table.add_column("Legs")
        table.add_column("Size", justify="right")
        table.add_column("Price", justify="right")
        table.add_column("Value", justify="right")

        for order in orders:
            ts = order.terminal_at or order.received_at or order.updated_at
            date_str = ts.strftime("%Y-%m-%d %H:%M") if ts else ""

            status = order.status.value
            if order.status == OrderStatus.FILLED:
                status_str = f"[green]{status}[/green]"
            elif order.status in (OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED):
                status_str = f"[red]{status}[/red]"
            else:
                status_str = f"[yellow]{status}[/yellow]"

            leg_parts = []
            for leg in order.legs:
                action = leg.action.value if leg.action else "?"
                qty = f"{int(leg.quantity)}" if leg.quantity else "?"
                sym = leg.symbol or "?"
                fills_str = ""
                if leg.fills:
                    avg_fill = sum(float(f.fill_price) for f in leg.fills) / len(leg.fills)
                    fills_str = f" @ ${avg_fill:,.2f}"
                leg_parts.append(f"{action} {qty}x {sym}{fills_str}")
            legs_str = "\n".join(leg_parts)

            price = float(order.price) if order.price else None
            value = float(order.value) if order.value else None

            table.add_row(
                date_str,
                status_str,
                order.underlying_symbol or "",
                order.order_type.value if order.order_type else "",
                legs_str,
                str(int(order.size)) if order.size else "",
                f"${price:,.2f}" if price is not None else "",
                f"${value:,.2f}" if value is not None else "",
            )

        console.print(table)

    # --- Sync and local storage ---

    async def sync(self, full: bool = False) -> dict:
        """Sync transaction and order history to local SQLite DB.

        Args:
            full: If True, re-sync everything. If False, incremental from watermark.

        Returns:
            dict with counts: {"transactions": N, "orders": M, "groups": G}
        """
        if not self.account:
            return {"transactions": 0, "orders": 0, "groups": 0}

        db = TradeDB()
        acct_num = self.account.account_number

        try:
            sync_state = db.get_sync_state(acct_num)

            txn_start_date = None
            if not full and sync_state["last_sync_at"]:
                last = datetime.fromisoformat(sync_state["last_sync_at"])
                txn_start_date = (last - timedelta(days=1)).date()

            transactions = self.account.get_history(
                self.session,
                page_offset=None,
                sort="Asc",
                start_date=txn_start_date,
            )

            txn_dicts = []
            max_txn_id = sync_state["last_transaction_id"] or 0
            for txn in transactions:
                d = self._serialize_transaction(txn)
                txn_dicts.append(d)
                if d["id"] > max_txn_id:
                    max_txn_id = d["id"]

            txn_count = db.upsert_transactions(txn_dicts)

            orders = self.account.get_order_history(
                self.session,
                page_offset=None,
                sort="Asc",
                start_date=txn_start_date,
            )

            order_dicts = []
            max_order_id = sync_state["last_order_id"] or 0
            for order in orders:
                d = self._serialize_order(order)
                order_dicts.append(d)
                if d["id"] > max_order_id:
                    max_order_id = d["id"]

            order_count = db.upsert_orders(order_dicts)

            db.update_sync_state(acct_num, max_txn_id, max_order_id)

            grouper = TradeGrouper(db)
            group_count = grouper.build_groups(acct_num)

            return {
                "transactions": txn_count,
                "orders": order_count,
                "groups": group_count,
            }
        finally:
            db.close()

    def _serialize_transaction(self, txn: Transaction) -> dict:
        """Convert a Transaction SDK object to a dict for storage."""
        return {
            "id": txn.id,
            "account_number": txn.account_number,
            "transaction_type": txn.transaction_type,
            "transaction_sub_type": txn.transaction_sub_type,
            "description": txn.description,
            "executed_at": txn.executed_at.isoformat() if txn.executed_at else None,
            "transaction_date": txn.transaction_date.isoformat() if txn.transaction_date else None,
            "value": float(txn.value),
            "net_value": float(txn.net_value),
            "is_estimated_fee": txn.is_estimated_fee,
            "symbol": txn.symbol,
            "instrument_type": txn.instrument_type.value if txn.instrument_type else None,
            "underlying_symbol": txn.underlying_symbol,
            "action": txn.action.value if txn.action else None,
            "quantity": float(txn.quantity) if txn.quantity else None,
            "price": float(txn.price) if txn.price else None,
            "regulatory_fees": float(txn.regulatory_fees) if txn.regulatory_fees else None,
            "clearing_fees": float(txn.clearing_fees) if txn.clearing_fees else None,
            "commission": float(txn.commission) if txn.commission else None,
            "order_id": txn.order_id,
        }

    def _serialize_order(self, order: PlacedOrder) -> dict:
        """Convert a PlacedOrder SDK object to a dict for storage."""
        legs = []
        for leg in order.legs:
            leg_dict = {
                "instrument_type": leg.instrument_type.value if leg.instrument_type else None,
                "symbol": leg.symbol,
                "action": leg.action.value if leg.action else None,
                "quantity": float(leg.quantity) if leg.quantity else None,
                "remaining_quantity": float(leg.remaining_quantity) if leg.remaining_quantity else None,
            }
            if leg.fills:
                leg_dict["fills"] = [
                    {
                        "fill_id": f.fill_id,
                        "quantity": float(f.quantity),
                        "fill_price": float(f.fill_price),
                        "filled_at": f.filled_at.isoformat() if f.filled_at else None,
                    }
                    for f in leg.fills
                ]
            legs.append(leg_dict)

        return {
            "id": order.id,
            "account_number": order.account_number,
            "time_in_force": order.time_in_force.value if order.time_in_force else None,
            "order_type": order.order_type.value if order.order_type else None,
            "underlying_symbol": order.underlying_symbol,
            "underlying_instrument_type": order.underlying_instrument_type.value if order.underlying_instrument_type else None,
            "status": order.status.value,
            "size": float(order.size) if order.size else None,
            "price": float(order.price) if order.price else None,
            "value": float(order.value) if order.value else None,
            "received_at": order.received_at.isoformat() if order.received_at else None,
            "terminal_at": order.terminal_at.isoformat() if order.terminal_at else None,
            "cancelled_at": order.cancelled_at.isoformat() if order.cancelled_at else None,
            "replacing_order_id": order.replacing_order_id,
            "replaces_order_id": order.replaces_order_id,
            "legs": legs,
        }

    def print_trade_groups(
        self,
        account_number: str,
        underlying: Optional[str] = None,
        status: Optional[str] = None,
        discord: bool = False,
    ) -> None:
        """Display trade groups from local DB."""
        db = TradeDB()
        try:
            groups = db.get_trade_groups(account_number, underlying, status)
            if not groups:
                print("No trade groups found. Run --sync first.")
                return

            console = Console(width=200)
            table = Table(
                title=f"Trade Groups ({len(groups)} trades)",
                show_lines=True,
            )
            table.add_column("ID", style="dim", justify="right")
            table.add_column("Underlying", style="bold")
            table.add_column("Strategy")
            table.add_column("Status")
            table.add_column("Opened", style="cyan", no_wrap=True)
            table.add_column("Closed", style="cyan", no_wrap=True)
            table.add_column("Days", justify="right")
            table.add_column("Collected", justify="right", style="green")
            table.add_column("Paid", justify="right", style="red")
            table.add_column("Fees", justify="right", style="dim")
            table.add_column("P/L", justify="right")
            table.add_column("Chain", style="dim")

            for g in groups:
                pl = g["realized_pl"]
                if pl is not None:
                    pl_str = f"[green]${pl:,.2f}[/green]" if pl >= 0 else f"[red]${pl:,.2f}[/red]"
                else:
                    pl_str = ""

                status_val = g["status"]
                if status_val == "closed":
                    status_str = f"[green]{status_val}[/green]"
                elif status_val == "open":
                    status_str = f"[yellow]{status_val}[/yellow]"
                else:
                    status_str = f"[cyan]{status_val}[/cyan]"

                chain_str = ""
                if g["parent_group_id"]:
                    chain = db.get_roll_chain(g["id"])
                    chain_ids = [str(c["id"]) for c in chain]
                    chain_str = " -> ".join(chain_ids)

                opened = g["opened_at"][:10] if g["opened_at"] else ""
                closed = g["closed_at"][:10] if g["closed_at"] else ""

                table.add_row(
                    str(g["id"]),
                    g["underlying_symbol"],
                    g["strategy_type"] or "",
                    status_str,
                    opened,
                    closed,
                    str(g["holding_days"]) if g["holding_days"] is not None else "",
                    f"${g['total_premium_collected']:,.2f}" if g["total_premium_collected"] else "",
                    f"${g['total_premium_paid']:,.2f}" if g["total_premium_paid"] else "",
                    f"${g['total_fees']:,.2f}" if g["total_fees"] else "",
                    pl_str,
                    chain_str,
                )

            console.print(table)

            closed_groups = [g for g in groups if g["status"] != "open"]
            if closed_groups:
                total_pl = sum(g["realized_pl"] or 0 for g in closed_groups)
                winners = sum(1 for g in closed_groups if (g["realized_pl"] or 0) > 0)
                losers = len(closed_groups) - winners
                color = "green" if total_pl >= 0 else "red"
                console.print(
                    f"\n  Closed: {len(closed_groups)} | "
                    f"W/L: {winners}/{losers} | "
                    f"Total P/L: [{color}]${total_pl:,.2f}[/{color}]"
                )
        finally:
            db.close()
