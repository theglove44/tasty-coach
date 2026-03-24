"""Trade history agent — fetches and displays transaction and order history."""

import json
import logging
from datetime import date, datetime, timedelta
from typing import Optional, List

from rich.console import Console
from rich.table import Table

from tastytrade import Session, Account
from tastytrade.account import Transaction
from tastytrade.order import PlacedOrder, OrderStatus

from utils.db import TradeDB
from utils.trade_grouper import TradeGrouper


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
        """Fetch transaction history from the API.

        Args:
            days: Number of days to look back.
            symbol: Filter by underlying symbol.
            transaction_type: Filter by type ("Trade", "Receive Deliver", etc.)
        """
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
        """Fetch order history from the API.

        Args:
            days: Number of days to look back.
            symbol: Filter by underlying symbol.
            status: Filter by status ("Filled", "Cancelled", etc.)
        """
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

        # Summary
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
            # Determine the best timestamp
            ts = order.terminal_at or order.received_at or order.updated_at
            date_str = ts.strftime("%Y-%m-%d %H:%M") if ts else ""

            # Status styling
            status = order.status.value
            if order.status == OrderStatus.FILLED:
                status_str = f"[green]{status}[/green]"
            elif order.status in (OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED):
                status_str = f"[red]{status}[/red]"
            else:
                status_str = f"[yellow]{status}[/yellow]"

            # Build legs description
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

            # Determine start point
            txn_start_date = None
            if not full and sync_state["last_sync_at"]:
                last = datetime.fromisoformat(sync_state["last_sync_at"])
                txn_start_date = (last - timedelta(days=1)).date()

            # Fetch transactions
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

            # Fetch orders
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

            # Update watermark
            db.update_sync_state(acct_num, max_txn_id, max_order_id)

            # Run trade grouper
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

            # Summary of closed groups
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
