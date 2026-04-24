"""Tests for alerts module."""

import dataclasses
import unittest
from unittest.mock import patch

from agents.alerts import Alert, AlertCollector
from utils.settings import settings


class TestAlert(unittest.TestCase):
    def test_alert_dataclass_fields(self):
        alert = Alert(severity="info", category="bp", message="m", context={"k": 1})
        self.assertEqual(alert.severity, "info")
        self.assertEqual(alert.category, "bp")
        self.assertEqual(alert.message, "m")
        self.assertEqual(alert.context, {"k": 1})

    def test_alert_is_frozen(self):
        alert = Alert(severity="info", category="bp", message="m")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            alert.severity = "warn"


class TestAlertCollector(unittest.TestCase):
    def _toggles(self, toggles):
        """Helper: patch settings.get to return given toggles dict."""
        def side_effect(key, default=None):
            if key == "alert_toggles":
                return toggles
            return default
        return patch.object(settings, "get", side_effect=side_effect)

    def test_collector_starts_empty(self):
        c = AlertCollector()
        self.assertEqual(len(c), 0)
        self.assertEqual(c.get_active_alerts(), [])

    def test_add_single_alert(self):
        c = AlertCollector()
        a = Alert(severity="warn", category="position_size", message="m")
        with self._toggles({"position_size": True}):
            c.add(a)
        self.assertEqual(len(c), 1)
        self.assertEqual(c.get_active_alerts()[0], a)

    def test_dedup_same_category_and_message(self):
        c = AlertCollector()
        a1 = Alert(severity="warn", category="bp", message="x", context={"a": 1})
        a2 = Alert(severity="warn", category="bp", message="x", context={"b": 2})
        with self._toggles({"bp": True}):
            c.add(a1)
            c.add(a2)
        self.assertEqual(len(c), 1)

    def test_dedup_ignores_context_and_severity(self):
        c = AlertCollector()
        a1 = Alert(severity="warn", category="bp", message="x")
        a2 = Alert(severity="critical", category="bp", message="x", context={"z": 1})
        with self._toggles({"bp": True}):
            c.add(a1)
            c.add(a2)
        self.assertEqual(len(c), 1)
        self.assertEqual(c.get_active_alerts()[0].severity, "warn")

    def test_different_category_same_message_kept(self):
        c = AlertCollector()
        a1 = Alert(severity="warn", category="bp", message="msg")
        a2 = Alert(severity="warn", category="theta", message="msg")
        with self._toggles({"bp": True, "theta": True}):
            c.add(a1)
            c.add(a2)
        self.assertEqual(len(c), 2)

    def test_different_message_same_category_kept(self):
        c = AlertCollector()
        a1 = Alert(severity="warn", category="bp", message="m1")
        a2 = Alert(severity="warn", category="bp", message="m2")
        with self._toggles({"bp": True}):
            c.add(a1)
            c.add(a2)
        self.assertEqual(len(c), 2)

    def test_toggle_off_drops_alert_silently(self):
        c = AlertCollector()
        a = Alert(severity="warn", category="position_size", message="m")
        with self._toggles({"position_size": False}):
            c.add(a)
        self.assertEqual(len(c), 0)

    def test_toggle_on_keeps_alert(self):
        c = AlertCollector()
        a = Alert(severity="warn", category="position_size", message="m")
        with self._toggles({"position_size": True}):
            c.add(a)
        self.assertEqual(len(c), 1)

    def test_unknown_category_toggle_defaults_true(self):
        c = AlertCollector()
        a = Alert(severity="warn", category="bp", message="m")
        with self._toggles({}):
            c.add(a)
        self.assertEqual(len(c), 1)

    def test_get_active_alerts_returns_copy(self):
        c = AlertCollector()
        a = Alert(severity="warn", category="bp", message="m")
        with self._toggles({"bp": True}):
            c.add(a)
        l1 = c.get_active_alerts()
        l2 = c.get_active_alerts()
        self.assertIsNot(l1, l2)
        self.assertEqual(l1, l2)

    def test_len_matches_active_alerts(self):
        c = AlertCollector()
        a1 = Alert(severity="warn", category="bp", message="m1")
        a2 = Alert(severity="warn", category="theta", message="m2")
        with self._toggles({"bp": True, "theta": True}):
            c.add(a1)
            c.add(a2)
        self.assertEqual(len(c), len(c.get_active_alerts()))


if __name__ == "__main__":
    unittest.main()
