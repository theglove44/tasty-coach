"""Trade grouping algorithm — links related transactions into trade lifecycles."""

import logging
from datetime import datetime, timedelta
from typing import Optional

from utils.db import TradeDB

logger = logging.getLogger(__name__)

# Transactions with the same order_id or within this window are considered
# part of the same logical trade (e.g., multi-leg orders, rolls).
ROLL_TIME_WINDOW = timedelta(seconds=5)


class TradeGrouper:
    """Processes ungrouped transactions and assigns them to trade groups."""

    def __init__(self, db: TradeDB):
        self.db = db

    def build_groups(self, account_number: str) -> int:
        """Process ungrouped transactions and assign them to trade groups.

        Returns count of new groups created.
        """
        ungrouped = self.db.get_ungrouped_transactions(account_number)
        if not ungrouped:
            return 0

        new_groups = 0

        # Group transactions by order_id first so multi-leg orders
        # are processed together.
        order_batches = self._batch_by_order(ungrouped)

        for batch in order_batches:
            created = self._process_batch(account_number, batch)
            new_groups += created

        return new_groups

    def _batch_by_order(self, transactions: list) -> list[list]:
        """Group transactions that share an order_id into batches.
        Transactions without an order_id are each their own batch.
        Preserves chronological order within batches.
        """
        order_map: dict[int, list] = {}
        no_order: list[list] = []

        for txn in transactions:
            oid = txn["order_id"]
            if oid:
                order_map.setdefault(oid, []).append(txn)
            else:
                no_order.append([txn])

        # Sort batches by earliest executed_at
        batches = list(order_map.values()) + no_order
        batches.sort(key=lambda b: b[0]["executed_at"])
        return batches

    def _process_batch(self, account_number: str, batch: list) -> int:
        """Process a batch of transactions (all from the same order or a single txn).
        Returns 1 if a new group was created, 0 otherwise.
        """
        new_groups = 0
        underlying = self._get_underlying(batch)
        if not underlying:
            logger.warning(
                f"Cannot determine underlying for transaction batch "
                f"(ids: {[t['id'] for t in batch]})"
            )
            return 0

        # Classify the batch
        actions = [t["action"] or "" for t in batch]
        sub_types = [t["transaction_sub_type"] or "" for t in batch]

        has_opens = any("Open" in a for a in actions)
        has_closes = any("Close" in a for a in actions)
        is_expiration = any(st == "Expiration" for st in sub_types)
        is_assignment = any(st in ("Assignment", "Exercise", "Cash Settled Assignment", "Cash Settled Exercise") for st in sub_types)

        # Roll: batch contains both opens and closes
        if has_opens and has_closes:
            new_groups += self._handle_roll(account_number, underlying, batch)
        elif has_opens:
            new_groups += self._handle_open(account_number, underlying, batch)
        elif has_closes:
            self._handle_close(account_number, underlying, batch)
        elif is_expiration:
            self._handle_expiration(account_number, underlying, batch)
        elif is_assignment:
            self._handle_assignment(account_number, underlying, batch)
        else:
            # Unknown — log and skip
            logger.debug(
                f"Unhandled transaction batch for {underlying}: "
                f"sub_types={sub_types}, actions={actions}"
            )

        return new_groups

    def _handle_open(self, account_number: str, underlying: str, batch: list) -> int:
        """Handle opening transactions. Returns 1 if new group created."""
        # Check if there's already an open group for this underlying
        existing = self.db.get_open_group_for_underlying(account_number, underlying)
        if existing:
            group_id = existing["id"]
            for txn in batch:
                self.db.link_transaction(group_id, txn["id"], "open")
            self._update_group_totals(group_id)
            return 0

        # Create new group
        strategy = self._detect_strategy(batch)
        group_id = self.db.create_trade_group(
            account_number=account_number,
            underlying_symbol=underlying,
            strategy_type=strategy,
            opened_at=batch[0]["executed_at"],
        )
        for txn in batch:
            self.db.link_transaction(group_id, txn["id"], "open")
        self._update_group_totals(group_id)
        return 1

    def _handle_close(self, account_number: str, underlying: str, batch: list) -> None:
        """Handle closing transactions."""
        group = self.db.get_open_group_for_underlying(account_number, underlying)
        if not group:
            logger.warning(f"Close without open group for {underlying}, creating standalone group")
            group_id = self.db.create_trade_group(
                account_number=account_number,
                underlying_symbol=underlying,
                opened_at=batch[0]["executed_at"],
            )
            for txn in batch:
                self.db.link_transaction(group_id, txn["id"], "close")
            self._finalize_if_closed(group_id)
            return

        group_id = group["id"]
        for txn in batch:
            self.db.link_transaction(group_id, txn["id"], "close")
        self._update_group_totals(group_id)
        self._finalize_if_closed(group_id)

    def _handle_roll(self, account_number: str, underlying: str, batch: list) -> int:
        """Handle a roll: close old group, open new with parent_group_id link."""
        close_txns = [t for t in batch if "Close" in (t["action"] or "")]
        open_txns = [t for t in batch if "Open" in (t["action"] or "")]

        # Close the existing group
        old_group = self.db.get_open_group_for_underlying(account_number, underlying)
        old_group_id = None
        if old_group:
            old_group_id = old_group["id"]
            for txn in close_txns:
                self.db.link_transaction(old_group_id, txn["id"], "roll")
            self._update_group_totals(old_group_id)
            self._finalize_group(old_group_id, status="closed", closed_at=batch[0]["executed_at"])
        else:
            logger.warning(f"Roll without existing open group for {underlying}")

        # Open new group linked to old
        strategy = self._detect_strategy(open_txns)
        new_group_id = self.db.create_trade_group(
            account_number=account_number,
            underlying_symbol=underlying,
            strategy_type=strategy,
            opened_at=batch[0]["executed_at"],
            parent_group_id=old_group_id,
        )
        for txn in open_txns:
            self.db.link_transaction(new_group_id, txn["id"], "roll")
        self._update_group_totals(new_group_id)
        return 1

    def _handle_expiration(self, account_number: str, underlying: str, batch: list) -> None:
        """Handle expiration transactions."""
        group = self.db.get_open_group_for_underlying(account_number, underlying)
        if not group:
            logger.debug(f"Expiration without open group for {underlying}")
            return

        group_id = group["id"]
        for txn in batch:
            self.db.link_transaction(group_id, txn["id"], "expiration")
        self._update_group_totals(group_id)
        self._finalize_group(group_id, status="expired", closed_at=batch[0]["executed_at"])

    def _handle_assignment(self, account_number: str, underlying: str, batch: list) -> None:
        """Handle assignment/exercise transactions."""
        group = self.db.get_open_group_for_underlying(account_number, underlying)
        if not group:
            logger.debug(f"Assignment without open group for {underlying}")
            return

        group_id = group["id"]
        for txn in batch:
            self.db.link_transaction(group_id, txn["id"], "assignment")
        self._update_group_totals(group_id)
        self._finalize_group(group_id, status="assigned", closed_at=batch[0]["executed_at"])

    def _finalize_if_closed(self, group_id: int) -> None:
        """Check if a group's net quantity is zero and finalize if so."""
        net_qty = self.db.get_group_net_quantity(group_id)
        if abs(net_qty) < 0.001:
            txns = self.db.get_group_transactions(group_id)
            closed_at = txns[-1]["executed_at"] if txns else None
            self._finalize_group(group_id, status="closed", closed_at=closed_at)

    def _finalize_group(
        self, group_id: int, status: str, closed_at: Optional[str] = None
    ) -> None:
        """Mark a group as closed/expired/assigned and compute realized P/L."""
        txns = self.db.get_group_transactions(group_id)
        group = self.db.conn.execute(
            "SELECT * FROM trade_groups WHERE id = ?", (group_id,)
        ).fetchone()
        if not group:
            return

        # Compute holding days
        holding_days = None
        if group["opened_at"] and closed_at:
            try:
                opened = datetime.fromisoformat(group["opened_at"])
                closed = datetime.fromisoformat(closed_at)
                holding_days = (closed - opened).days
            except (ValueError, TypeError):
                pass

        self.db.update_trade_group(
            group_id,
            status=status,
            closed_at=closed_at,
            holding_days=holding_days,
        )

    def _update_group_totals(self, group_id: int) -> None:
        """Recompute premium collected/paid and fees for a group."""
        txns = self.db.get_group_transactions(group_id)

        collected = 0.0
        paid = 0.0
        fees = 0.0

        for txn in txns:
            net_value = float(txn["net_value"]) if txn["net_value"] else 0.0
            if net_value > 0:
                collected += net_value
            else:
                paid += abs(net_value)

            for fee_col in ("commission", "clearing_fees", "regulatory_fees"):
                f = txn[fee_col]
                if f:
                    fees += abs(float(f))

        realized_pl = collected - paid
        self.db.update_trade_group(
            group_id,
            total_premium_collected=collected,
            total_premium_paid=paid,
            total_fees=fees,
            realized_pl=realized_pl,
        )

    def _get_underlying(self, batch: list) -> Optional[str]:
        """Extract the underlying symbol from a batch of transactions."""
        for txn in batch:
            if txn["underlying_symbol"]:
                return txn["underlying_symbol"]
        return None

    def _detect_strategy(self, open_txns: list) -> Optional[str]:
        """Detect strategy type from opening transactions.

        Simple heuristic based on leg count and action types.
        """
        if not open_txns:
            return None

        count = len(open_txns)
        actions = set((t["action"] or "") for t in open_txns)
        instruments = set((t["instrument_type"] or "") for t in open_txns)

        has_equity = "Equity" in instruments
        has_option = "Equity Option" in instruments or "Future Option" in instruments

        if count == 1:
            if has_equity:
                return "Stock"
            return "Single Option"
        elif count == 2:
            if has_option:
                return "Vertical"
            return "Pair"
        elif count == 4:
            return "Iron Condor"
        elif count == 3:
            return "Butterfly"

        return f"{count}-Leg"
