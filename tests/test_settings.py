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
