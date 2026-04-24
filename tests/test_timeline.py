"""Tests for agents/timeline.py classification + roll annotation + HistoryAgent integration."""

import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from agents.timeline import TimelineEvent, annotate_rolls, classify_event
from agents.history import HistoryAgent


def make_txn(**kwargs):
    defaults = {
        "id": 1,
        "order_id": 1000,
        "transaction_type": "Trade",
        "transaction_sub_type": "Buy to Open",
        "description": "Test transaction",
        "net_value": Decimal("100.00"),
        "quantity": Decimal("1"),
        "symbol": "SPY   240101C00400000",
        "underlying_symbol": "SPY",
        "executed_at": datetime(2026, 4, 24, 10, 0, 0),
        "transaction_date": date(2026, 4, 24),
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _evt(event_type, dt, underlying="SPY", tid=0, raw_sub="", order_id=None):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return TimelineEvent(
        event_type=event_type,
        occurred_at=dt,
        symbol=underlying,
        underlying_symbol=underlying,
        description="",
        quantity=None,
        amount=None,
        transaction_id=tid,
        order_id=order_id,
        raw_type="Trade",
        raw_sub_type=raw_sub,
    )


class TestClassifyEvent(unittest.TestCase):
    def test_classify_assignment(self):
        self.assertEqual(classify_event(make_txn(transaction_sub_type="Assignment")).event_type, "assignment")

    def test_classify_cash_settled_assignment(self):
        self.assertEqual(classify_event(make_txn(transaction_sub_type="Cash Settled Assignment")).event_type, "assignment")

    def test_classify_exercise(self):
        self.assertEqual(classify_event(make_txn(transaction_sub_type="Exercise")).event_type, "exercise")

    def test_classify_cash_settled_exercise(self):
        self.assertEqual(classify_event(make_txn(transaction_sub_type="Cash Settled Exercise")).event_type, "exercise")

    def test_classify_expiration(self):
        self.assertEqual(classify_event(make_txn(transaction_sub_type="Expiration")).event_type, "expiration")

    def test_classify_buy_to_open(self):
        self.assertEqual(classify_event(make_txn(transaction_sub_type="Buy to Open")).event_type, "open")

    def test_classify_sell_to_open(self):
        self.assertEqual(classify_event(make_txn(transaction_sub_type="Sell to Open")).event_type, "open")

    def test_classify_buy_to_close(self):
        self.assertEqual(classify_event(make_txn(transaction_sub_type="Buy to Close")).event_type, "close")

    def test_classify_sell_to_close(self):
        self.assertEqual(classify_event(make_txn(transaction_sub_type="Sell to Close")).event_type, "close")

    def test_classify_dividend(self):
        self.assertEqual(classify_event(make_txn(transaction_sub_type="Dividend")).event_type, "dividend")

    def test_classify_fee(self):
        self.assertEqual(classify_event(make_txn(transaction_sub_type="Fee")).event_type, "fee")

    def test_classify_balance_adjustment(self):
        self.assertEqual(classify_event(make_txn(transaction_sub_type="Balance Adjustment")).event_type, "adjustment")

    def test_classify_deposit_cash_movement(self):
        self.assertEqual(classify_event(make_txn(transaction_sub_type="Deposit")).event_type, "cash_movement")

    def test_classify_withdrawal_cash_movement(self):
        self.assertEqual(classify_event(make_txn(transaction_sub_type="Withdrawal")).event_type, "cash_movement")

    def test_classify_transfer_cash_movement(self):
        self.assertEqual(classify_event(make_txn(transaction_sub_type="Transfer")).event_type, "cash_movement")

    def test_classify_acat_cash_movement(self):
        self.assertEqual(classify_event(make_txn(transaction_sub_type="ACAT")).event_type, "cash_movement")

    def test_classify_money_movement_type_fallback(self):
        txn = make_txn(transaction_type="Money Movement", transaction_sub_type="Unknown Sub")
        self.assertEqual(classify_event(txn).event_type, "cash_movement")

    def test_classify_cancellation_substring(self):
        self.assertEqual(classify_event(make_txn(transaction_sub_type="Trade Cancel")).event_type, "cancellation")

    def test_classify_other_unknown_sub(self):
        txn = make_txn(transaction_type="Trade", transaction_sub_type="Gibberish")
        self.assertEqual(classify_event(txn).event_type, "other")

    def test_classify_other_receive_deliver_unknown(self):
        txn = make_txn(transaction_type="Receive Deliver", transaction_sub_type="")
        self.assertEqual(classify_event(txn).event_type, "other")

    def test_classify_roll_placeholder(self):
        evt = classify_event(make_txn(transaction_sub_type="Sell to Close"))
        self.assertNotEqual(evt.event_type, "roll")
        self.assertEqual(evt.event_type, "close")

    def test_classify_preserves_signed_amount_positive(self):
        self.assertEqual(classify_event(make_txn(net_value=Decimal("12.34"))).amount, Decimal("12.34"))

    def test_classify_preserves_signed_amount_negative(self):
        self.assertEqual(classify_event(make_txn(net_value=Decimal("-8.00"))).amount, Decimal("-8.00"))

    def test_classify_amount_none_when_net_value_none(self):
        self.assertIsNone(classify_event(make_txn(net_value=None)).amount)

    def test_classify_prefers_executed_at_over_transaction_date(self):
        dt = datetime(2026, 4, 24, 15, 30, 45)
        evt = classify_event(make_txn(executed_at=dt, transaction_date=date(2026, 4, 23)))
        self.assertEqual(evt.occurred_at, dt.replace(tzinfo=timezone.utc))

    def test_classify_falls_back_to_transaction_date(self):
        evt = classify_event(make_txn(executed_at=None, transaction_date=date(2026, 4, 24)))
        self.assertEqual(
            evt.occurred_at,
            datetime(2026, 4, 24, 0, 0, 0, tzinfo=timezone.utc),
        )

    def test_classify_occurred_at_min_when_both_missing(self):
        evt = classify_event(make_txn(executed_at=None, transaction_date=None))
        self.assertEqual(evt.occurred_at, datetime.min.replace(tzinfo=timezone.utc))

    def test_classify_normalises_tz_aware_to_utc(self):
        aware = datetime(2026, 4, 24, 10, 0, 0, tzinfo=timezone.utc)
        evt = classify_event(make_txn(executed_at=aware))
        self.assertEqual(evt.occurred_at.tzinfo, timezone.utc)

    def test_classify_mixed_aware_and_naive_are_all_utc(self):
        # Regression: sorting a mix of rows must not raise.
        e1 = classify_event(make_txn(executed_at=datetime(2026, 4, 24, 10)))
        e2 = classify_event(make_txn(
            executed_at=datetime(2026, 4, 25, 10, tzinfo=timezone.utc)))
        # sort() would raise TypeError if one was naive
        sorted([e1, e2], key=lambda e: e.occurred_at)

    def test_classify_passes_description_through(self):
        evt = classify_event(make_txn(description="Special test description"))
        self.assertEqual(evt.description, "Special test description")

    def test_classify_accepts_dict_input(self):
        txn_dict = {
            "id": 99,
            "transaction_type": "Trade",
            "transaction_sub_type": "Buy to Open",
            "description": "Dict test",
            "net_value": Decimal("50.00"),
            "quantity": Decimal("5"),
            "symbol": "ABC",
            "underlying_symbol": "ABC",
            "executed_at": datetime(2026, 4, 24),
            "transaction_date": date(2026, 4, 24),
        }
        evt = classify_event(txn_dict)
        self.assertEqual(evt.event_type, "open")
        self.assertEqual(evt.transaction_id, 99)

    def test_classify_none_sub_type_safe(self):
        evt = classify_event(make_txn(transaction_sub_type=None))
        self.assertEqual(evt.event_type, "other")

    def test_classify_preserves_raw_fields(self):
        evt = classify_event(make_txn(transaction_type="MyType", transaction_sub_type="MySub"))
        self.assertEqual(evt.raw_type, "MyType")
        self.assertEqual(evt.raw_sub_type, "MySub")

    def test_classify_quantity_decimal_coercion(self):
        self.assertEqual(classify_event(make_txn(quantity=10)).quantity, Decimal("10"))


class TestAnnotateRolls(unittest.TestCase):
    def test_annotate_rolls_flags_same_order_pair(self):
        dt = datetime(2026, 4, 24, 10)
        events = [_evt("open", dt, tid=1, order_id=42),
                  _evt("close", dt, tid=2, order_id=42)]
        result = annotate_rolls(events)
        self.assertTrue(result[0].is_roll_leg)
        self.assertTrue(result[1].is_roll_leg)

    def test_annotate_rolls_ignores_different_order_ids(self):
        dt = datetime(2026, 4, 24, 10)
        events = [_evt("open", dt, tid=1, order_id=42),
                  _evt("close", dt, tid=2, order_id=43)]
        result = annotate_rolls(events)
        self.assertFalse(result[0].is_roll_leg)
        self.assertFalse(result[1].is_roll_leg)

    def test_annotate_rolls_ignores_same_day_different_orders(self):
        # Two unrelated trades on the same underlying / same day / different orders
        # must NOT be tagged as a roll.
        dt = datetime(2026, 4, 24, 10)
        events = [_evt("open", dt, tid=1, order_id=100),
                  _evt("close", dt, tid=2, order_id=200)]
        result = annotate_rolls(events)
        self.assertFalse(result[0].is_roll_leg)
        self.assertFalse(result[1].is_roll_leg)

    def test_annotate_rolls_only_opens_not_flagged(self):
        dt = datetime(2026, 4, 24, 10)
        events = [_evt("open", dt, tid=1, order_id=42),
                  _evt("open", dt, tid=2, order_id=42)]
        result = annotate_rolls(events)
        self.assertFalse(result[0].is_roll_leg)
        self.assertFalse(result[1].is_roll_leg)

    def test_annotate_rolls_only_closes_not_flagged(self):
        dt = datetime(2026, 4, 24, 10)
        events = [_evt("close", dt, tid=1, order_id=42),
                  _evt("close", dt, tid=2, order_id=42)]
        result = annotate_rolls(events)
        self.assertFalse(result[0].is_roll_leg)
        self.assertFalse(result[1].is_roll_leg)

    def test_annotate_rolls_multi_leg_all_flagged(self):
        # Iron condor roll: 2 closes + 2 opens under one order_id.
        dt = datetime(2026, 4, 24, 10)
        events = [
            _evt("close", dt, tid=1, order_id=42),
            _evt("close", dt, tid=2, order_id=42),
            _evt("open", dt, tid=3, order_id=42),
            _evt("open", dt, tid=4, order_id=42),
        ]
        result = annotate_rolls(events)
        for e in result:
            self.assertTrue(e.is_roll_leg)

    def test_annotate_rolls_empty_list(self):
        self.assertEqual(annotate_rolls([]), [])

    def test_annotate_rolls_does_not_mutate_input(self):
        dt = datetime(2026, 4, 24, 10)
        original = [_evt("open", dt, tid=1, order_id=42),
                    _evt("close", dt, tid=2, order_id=42)]
        result = annotate_rolls(original)
        self.assertFalse(original[0].is_roll_leg)
        self.assertFalse(original[1].is_roll_leg)
        self.assertTrue(result[0].is_roll_leg)
        self.assertTrue(result[1].is_roll_leg)

    def test_annotate_rolls_preserves_order(self):
        events = [
            _evt("open", datetime(2026, 4, 24, 10), tid=1, order_id=42),
            _evt("close", datetime(2026, 4, 24, 11), tid=2, order_id=42),
        ]
        result = annotate_rolls(events)
        self.assertEqual([e.transaction_id for e in result], [1, 2])

    def test_annotate_rolls_skips_none_order_id(self):
        dt = datetime(2026, 4, 24, 10)
        events = [_evt("open", dt, tid=1, order_id=None),
                  _evt("close", dt, tid=2, order_id=None)]
        result = annotate_rolls(events)
        self.assertFalse(result[0].is_roll_leg)
        self.assertFalse(result[1].is_roll_leg)

    def test_annotate_rolls_ignores_non_open_close_events(self):
        dt = datetime(2026, 4, 24, 10)
        events = [_evt("assignment", dt, tid=1, order_id=42),
                  _evt("expiration", dt, tid=2, order_id=42)]
        result = annotate_rolls(events)
        self.assertFalse(result[0].is_roll_leg)
        self.assertFalse(result[1].is_roll_leg)


class TestHistoryAgentGetRecentEvents(unittest.IsolatedAsyncioTestCase):
    async def test_get_recent_events_returns_empty_when_no_transactions(self):
        agent = HistoryAgent(MagicMock())
        agent.get_transactions = AsyncMock(return_value=[])
        result = await agent.get_recent_events(days=30, symbol=None)
        self.assertEqual(result, [])

    async def test_get_recent_events_sorts_newest_first(self):
        older = make_txn(id=1, executed_at=datetime(2026, 4, 20, 10),
                         transaction_date=date(2026, 4, 20))
        newer = make_txn(id=2, executed_at=datetime(2026, 4, 24, 15),
                         transaction_date=date(2026, 4, 24))
        agent = HistoryAgent(MagicMock())
        agent.get_transactions = AsyncMock(return_value=[older, newer])
        result = await agent.get_recent_events(days=30)
        self.assertEqual(result[0].transaction_id, 2)
        self.assertEqual(result[1].transaction_id, 1)

    async def test_get_recent_events_classifies_and_annotates(self):
        dt = datetime(2026, 4, 24, 10)
        close_txn = make_txn(id=1, order_id=500, transaction_sub_type="Sell to Close",
                             executed_at=dt, transaction_date=date(2026, 4, 24),
                             underlying_symbol="SPY")
        open_txn = make_txn(id=2, order_id=500, transaction_sub_type="Sell to Open",
                            executed_at=dt, transaction_date=date(2026, 4, 24),
                            underlying_symbol="SPY")
        agent = HistoryAgent(MagicMock())
        agent.get_transactions = AsyncMock(return_value=[close_txn, open_txn])
        result = await agent.get_recent_events(days=30)
        self.assertEqual(len(result), 2)
        self.assertEqual(sum(1 for e in result if e.is_roll_leg), 2)

    async def test_get_recent_events_forwards_days_and_symbol(self):
        agent = HistoryAgent(MagicMock())
        agent.get_transactions = AsyncMock(return_value=[])
        await agent.get_recent_events(days=60, symbol="QQQ")
        agent.get_transactions.assert_called_once_with(days=60, symbol="QQQ")

    async def test_get_recent_events_propagates_exceptions(self):
        agent = HistoryAgent(MagicMock())
        agent.get_transactions = AsyncMock(side_effect=ValueError("boom"))
        with self.assertRaises(ValueError):
            await agent.get_recent_events(days=30)


if __name__ == "__main__":
    unittest.main()
