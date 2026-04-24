"""Tests for settings module."""

import json
import tempfile
import unittest
from pathlib import Path

from utils.settings import Settings, DEFAULTS


class TestSettings(unittest.TestCase):
    def test_get_returns_default_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            s = Settings(config_path=config_path)
            self.assertEqual(
                s.get("position_pct_nlv_warn"),
                DEFAULTS["position_pct_nlv_warn"],
            )

    def test_file_auto_created_with_defaults_on_first_read(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            s = Settings(config_path=config_path)
            s.get("position_pct_nlv_warn")
            self.assertTrue(config_path.exists())
            data = json.loads(config_path.read_text())
            self.assertEqual(data, DEFAULTS)

    def test_get_reads_existing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps({"position_pct_nlv_warn": 0.10}))
            s = Settings(config_path=config_path)
            self.assertEqual(s.get("position_pct_nlv_warn"), 0.10)

    def test_missing_key_falls_back_to_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps({"position_pct_nlv_warn": 0.10}))
            s = Settings(config_path=config_path)
            self.assertEqual(s.get("bp_usage_warn"), DEFAULTS["bp_usage_warn"])

    def test_corrupt_json_returns_defaults_and_logs_warning(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text("{invalid json}")
            s = Settings(config_path=config_path)
            with self.assertLogs("utils.settings", level="WARNING") as cm:
                result = s.get("position_pct_nlv_warn")
            self.assertEqual(result, DEFAULTS["position_pct_nlv_warn"])
            self.assertTrue(any("Config unreadable" in msg for msg in cm.output))
            # Bad file must not be overwritten
            self.assertEqual(config_path.read_text(), "{invalid json}")

    def test_corrupt_json_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text("{invalid json}")
            s = Settings(config_path=config_path)
            with self.assertLogs("utils.settings", level="WARNING"):
                s.get("position_pct_nlv_warn")

    def test_unknown_key_returns_none_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            s = Settings(config_path=config_path)
            self.assertIsNone(s.get("nonexistent"))

    def test_unknown_key_returns_explicit_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            s = Settings(config_path=config_path)
            self.assertEqual(s.get("nonexistent", "fallback"), "fallback")

    def test_alert_toggles_default_all_true(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            s = Settings(config_path=config_path)
            toggles = s.get("alert_toggles")
            self.assertEqual(
                set(toggles.keys()),
                {"position_size", "bp", "theta", "market", "concentration", "assignment"},
            )
            for v in toggles.values():
                self.assertTrue(v)

    def test_partial_alert_toggles_merged_with_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps({"alert_toggles": {"bp": False}}))
            s = Settings(config_path=config_path)
            toggles = s.get("alert_toggles")
            self.assertFalse(toggles["bp"])
            self.assertTrue(toggles["position_size"])
            self.assertTrue(toggles["theta"])

    def test_theta_target_default_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            s = Settings(config_path=config_path)
            self.assertIsNone(s.get("theta_target"))

    def test_theta_target_numeric_preserved(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps({"theta_target": 0.002}))
            s = Settings(config_path=config_path)
            self.assertEqual(s.get("theta_target"), 0.002)

    def test_reload_picks_up_file_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text(json.dumps({"position_pct_nlv_warn": 0.05}))
            s = Settings(config_path=config_path)
            self.assertEqual(s.get("position_pct_nlv_warn"), 0.05)
            config_path.write_text(json.dumps({"position_pct_nlv_warn": 0.15}))
            s.reload()
            self.assertEqual(s.get("position_pct_nlv_warn"), 0.15)

    def test_singleton_settings_importable(self):
        from utils.settings import settings
        self.assertIsNotNone(settings)
        self.assertIsInstance(settings, Settings)


class TestSettingsSet(unittest.TestCase):
    def test_set_updates_numeric_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "config.json"
            s = Settings(config_path=p)
            s.set("position_pct_nlv_warn", 0.10)
            self.assertEqual(s.get("position_pct_nlv_warn"), 0.10)
            reloaded = Settings(config_path=p)
            self.assertEqual(reloaded.get("position_pct_nlv_warn"), 0.10)

    def test_set_rejects_unknown_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "config.json"
            s = Settings(config_path=p)
            s.get("bp_usage_warn")  # force load
            before = p.read_text()
            with self.assertRaises(ValueError):
                s.set("nope", 1)
            self.assertEqual(p.read_text(), before)

    def test_set_rejects_negative_numeric(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            s = Settings(config_path=Path(tmpdir) / "config.json")
            with self.assertRaises(ValueError):
                s.set("bp_usage_warn", -0.1)

    def test_set_coerces_string_numeric(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            s = Settings(config_path=Path(tmpdir) / "config.json")
            s.set("concentration_pct_nlv_warn", "0.33")
            self.assertEqual(s.get("concentration_pct_nlv_warn"), 0.33)

    def test_set_nested_alert_toggle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "config.json"
            s = Settings(config_path=p)
            s.set("alert_toggles.bp", False)
            toggles = s.get("alert_toggles")
            self.assertFalse(toggles["bp"])
            self.assertTrue(toggles["position_size"])
            self.assertTrue(toggles["theta"])

    def test_set_many_atomic_on_validation_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "config.json"
            s = Settings(config_path=p)
            s.get("bp_usage_warn")
            before = p.read_text()
            with self.assertRaises(ValueError):
                s.set_many({"bp_usage_warn": 0.40, "bogus_key": 1})
            self.assertEqual(p.read_text(), before)
            self.assertEqual(s.get("bp_usage_warn"), DEFAULTS["bp_usage_warn"])

    def test_set_preserves_unknown_user_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p = Path(tmpdir) / "config.json"
            p.write_text(json.dumps({
                "position_pct_nlv_warn": 0.05,
                "custom_key": 42,
            }))
            s = Settings(config_path=p)
            s.set("position_pct_nlv_warn", 0.08)
            saved = json.loads(p.read_text())
            self.assertEqual(saved["custom_key"], 42)

    def test_set_alert_toggles_full_replace_preserves_other_categories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            s = Settings(config_path=Path(tmpdir) / "config.json")
            s.set("alert_toggles", {"bp": False})
            toggles = s.get("alert_toggles")
            self.assertFalse(toggles["bp"])
            # All other default categories must still be present
            for cat in ("position_size", "theta", "market", "concentration", "assignment"):
                self.assertIn(cat, toggles)
                self.assertTrue(toggles[cat])

    def test_set_theta_target_accepts_none_and_numeric(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            s = Settings(config_path=Path(tmpdir) / "config.json")
            s.set("theta_target", None)
            self.assertIsNone(s.get("theta_target"))
            s.set("theta_target", 0.002)
            self.assertEqual(s.get("theta_target"), 0.002)
            s.set("theta_target", "")
            self.assertIsNone(s.get("theta_target"))


class TestDecimalSettingFallback(unittest.TestCase):
    """Covers agents.manager._decimal_setting / _coerce_decimal safety net."""

    def test_coerce_handles_none_and_non_numeric(self):
        from agents.manager import _coerce_decimal
        self.assertIsNone(_coerce_decimal(None))
        self.assertIsNone(_coerce_decimal("not-a-number"))
        self.assertIsNone(_coerce_decimal(True))

    def test_decimal_setting_falls_back_on_bad_value(self):
        import json as _json
        from decimal import Decimal
        from agents.manager import _decimal_setting
        from utils.settings import Settings
        import utils.settings as settings_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text(_json.dumps({"position_pct_nlv_warn": "oops"}))
            s = Settings(config_path=config_path)
            original = settings_mod.settings
            try:
                settings_mod.settings = s
                import agents.manager as manager_mod
                manager_mod.settings = s
                with self.assertLogs("agents.manager", level="WARNING"):
                    result = _decimal_setting("position_pct_nlv_warn", Decimal("0.05"))
                self.assertEqual(result, Decimal("0.05"))
            finally:
                settings_mod.settings = original
                import agents.manager as manager_mod
                manager_mod.settings = original


if __name__ == "__main__":
    unittest.main()
