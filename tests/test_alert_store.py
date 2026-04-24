"""Tests for utils.alert_store (Phase E)."""

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from agents.alerts import Alert
from utils.alert_store import AlertStore, print_alert_history
from utils.db import TradeDB


def _a(category, message, severity="warn", context=None):
    return Alert(severity=severity, category=category, message=message,
                 context=context or {})


class TestAlertStore(unittest.TestCase):
    def setUp(self):
        self.db = TradeDB(db_path=Path(":memory:"))
        self.store = AlertStore(self.db)

    def tearDown(self):
        self.db.close()

    def test_record_alerts_inserts_rows(self):
        alerts = [_a("bp", "m1"), _a("theta", "m2"), _a("market", "m3")]
        n = self.store.record_alerts("ACCT", alerts)
        self.assertEqual(n, 3)
        self.assertEqual(len(self.store.get_history("ACCT")), 3)

    def test_record_alerts_dedupes_same_day(self):
        alerts = [_a("bp", "dup")]
        when = datetime(2026, 4, 24, 10, tzinfo=timezone.utc)
        self.store.record_alerts("ACCT", alerts, now=when)
        self.store.record_alerts("ACCT", alerts, now=when)
        self.assertEqual(len(self.store.get_history("ACCT")), 1)

    def test_record_alerts_redup_next_day(self):
        alerts = [_a("bp", "dup")]
        d1 = datetime(2026, 4, 24, 10, tzinfo=timezone.utc)
        d2 = datetime(2026, 4, 25, 10, tzinfo=timezone.utc)
        self.store.record_alerts("ACCT", alerts, now=d1)
        self.store.record_alerts("ACCT", alerts, now=d2)
        self.assertEqual(len(self.store.get_history("ACCT")), 2)

    def test_record_alerts_account_scoped(self):
        alerts = [_a("bp", "same")]
        self.store.record_alerts("A1", alerts)
        self.store.record_alerts("A2", alerts)
        self.assertEqual(len(self.store.get_history("A1")), 1)
        self.assertEqual(len(self.store.get_history("A2")), 1)

    def test_record_alerts_empty_iterable_is_noop(self):
        self.assertEqual(self.store.record_alerts("ACCT", []), 0)

    def test_record_alerts_handles_non_json_context(self):
        # Decimal isn't JSON-native — default=str handles it.
        alerts = [_a("bp", "with ctx", context={"value": Decimal("1.5")})]
        n = self.store.record_alerts("ACCT", alerts)
        self.assertEqual(n, 1)
        hist = self.store.get_history("ACCT")
        self.assertEqual(len(hist), 1)

    def test_get_last_viewed_returns_none_initially(self):
        self.assertIsNone(self.store.get_last_viewed("ACCT"))

    def test_mark_viewed_then_get_last_viewed_roundtrip(self):
        when = datetime(2026, 4, 24, 10, tzinfo=timezone.utc)
        self.store.mark_viewed("ACCT", when)
        got = self.store.get_last_viewed("ACCT")
        self.assertEqual(got, when)

    def test_mark_viewed_upserts(self):
        d1 = datetime(2026, 4, 24, 10, tzinfo=timezone.utc)
        d2 = datetime(2026, 4, 25, 10, tzinfo=timezone.utc)
        self.store.mark_viewed("ACCT", d1)
        self.store.mark_viewed("ACCT", d2)
        self.assertEqual(self.store.get_last_viewed("ACCT"), d2)
        rows = self.db.conn.execute(
            "SELECT COUNT(*) FROM alert_views WHERE account_number = ?",
            ("ACCT",),
        ).fetchone()
        self.assertEqual(rows[0], 1)

    def test_new_alert_keys_since_returns_only_after_timestamp(self):
        d1 = datetime(2026, 4, 24, 10, tzinfo=timezone.utc)
        d2 = datetime(2026, 4, 24, 11, tzinfo=timezone.utc)
        self.store.record_alerts("ACCT", [_a("bp", "old")], now=d1)
        self.store.record_alerts("ACCT", [_a("theta", "new")], now=d2)
        keys = self.store.new_alert_keys_since(
            "ACCT", d1 + timedelta(minutes=1)
        )
        self.assertEqual(keys, {("theta", "new")})

    def test_new_alert_keys_since_returns_empty_when_since_is_none(self):
        self.store.record_alerts("ACCT", [_a("bp", "m")])
        self.assertEqual(self.store.new_alert_keys_since("ACCT", None), set())

    def test_get_history_orders_desc_and_respects_limit(self):
        now = datetime(2026, 4, 24, 10, tzinfo=timezone.utc)
        for i in range(5):
            self.store.record_alerts(
                "ACCT", [_a("bp", f"m{i}")],
                now=now + timedelta(days=i),
            )
        hist = self.store.get_history("ACCT", limit=3)
        self.assertEqual(len(hist), 3)
        # Newest first: m4, m3, m2
        self.assertEqual(hist[0]["message"], "m4")
        self.assertEqual(hist[-1]["message"], "m2")

    def test_first_seen_alert_is_marked_new_after_persist(self):
        # Regression: the dashboard flow records alerts BEFORE computing
        # new_alert_keys_since(), so a brand-new alert must appear as "new"
        # on this refresh. Simulate that order here.
        d0 = datetime(2026, 4, 24, 10, tzinfo=timezone.utc)
        d1 = datetime(2026, 4, 24, 11, tzinfo=timezone.utc)
        self.store.mark_viewed("ACCT", d0)
        last = self.store.get_last_viewed("ACCT")
        self.store.record_alerts(
            "ACCT", [_a("bp", "brand new")], now=d1,
        )
        keys = self.store.new_alert_keys_since("ACCT", last)
        self.assertIn(("bp", "brand new"), keys)

    def test_schema_version_advances_to_2(self):
        row = self.db.conn.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()
        self.assertEqual(row[0], 2)

    def test_print_alert_history_empty(self):
        from io import StringIO
        from rich.console import Console
        buf = StringIO()
        console = Console(file=buf, width=120, force_terminal=False)
        print_alert_history(self.store, "ACCT", console=console)
        self.assertIn("No alerts recorded", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
