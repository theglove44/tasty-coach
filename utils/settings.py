"""Settings management for Tasty-Coach."""

import json
import logging
import copy
import os
from pathlib import Path
from typing import Any

NUMERIC_KEYS: frozenset[str] = frozenset({
    "position_pct_nlv_warn",
    "bp_usage_warn",
    "bp_usage_block",
    "concentration_pct_nlv_warn",
})
OPTIONAL_NUMERIC_KEYS: frozenset[str] = frozenset({
    "theta_target",  # may be None
})

DEFAULTS: dict[str, Any] = {
    "position_pct_nlv_warn": 0.05,
    "bp_usage_warn": 0.50,
    "bp_usage_block": 0.50,
    "theta_target": None,
    "concentration_pct_nlv_warn": 0.15,
    "alert_toggles": {
        "position_size": True,
        "bp": True,
        "theta": True,
        "market": True,
        "concentration": True,
        "assignment": True,
    },
}
CONFIG_DIR = Path.home() / ".tasty-coach"
CONFIG_PATH = CONFIG_DIR / "config.json"
logger = logging.getLogger(__name__)


class Settings:
    """Load and access settings from JSON config file with defaults fallback."""

    def __init__(self, config_path: Path = CONFIG_PATH) -> None:
        self.config_path = config_path
        self._data = None

    def _load(self) -> dict[str, Any]:
        """Load config from file, auto-create if missing, merge with defaults."""
        if not self.config_path.exists():
            try:
                self.config_path.parent.mkdir(parents=True, exist_ok=True)
                self.config_path.write_text(json.dumps(DEFAULTS, indent=2))
            except OSError as e:
                logger.warning(
                    "Could not auto-create config at %s (%s); using in-memory defaults",
                    self.config_path,
                    e,
                )
            return copy.deepcopy(DEFAULTS)

        try:
            data = json.loads(self.config_path.read_text())
            if not isinstance(data, dict):
                raise ValueError(f"config root must be a JSON object, got {type(data).__name__}")
            toggles = data.get("alert_toggles", {})
            if not isinstance(toggles, dict):
                toggles = {}
            merged = {**DEFAULTS, **data}
            merged["alert_toggles"] = {**DEFAULTS["alert_toggles"], **toggles}
            return merged
        except (json.JSONDecodeError, OSError, ValueError, TypeError) as e:
            logger.warning(
                "Config unreadable at %s (%s); using defaults",
                self.config_path,
                e,
            )
            return copy.deepcopy(DEFAULTS)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value, lazy-loading on first access."""
        if self._data is None:
            self._data = self._load()
        if default is not None:
            return self._data.get(key, default)
        return self._data.get(key, DEFAULTS.get(key))

    def reload(self) -> None:
        """Force reload from disk."""
        self._data = None

    def set(self, key: str, value: Any) -> None:
        """Validate and persist a single setting. See set_many for details."""
        self.set_many({key: value})

    def set_many(self, updates: dict[str, Any]) -> None:
        """Validate all updates, then write once atomically.

        Supports dotted keys under `alert_toggles.*`. Raises ValueError on
        any invalid entry and writes nothing; on success the new values are
        persisted to disk and reflected in-memory.
        """
        if self._data is None:
            self._data = self._load()
        merged = copy.deepcopy(self._data)
        for key, raw in updates.items():
            coerced = self._validate_value(key, raw)
            self._apply_dotted(merged, key, coerced)
        self._atomic_write(merged)
        self._data = merged

    def _validate_value(self, key: str, value: Any) -> Any:
        """Coerce and validate a single key's value."""
        if key.startswith("alert_toggles."):
            return self._coerce_bool(key, value)
        if key == "alert_toggles":
            if not isinstance(value, dict):
                raise ValueError("alert_toggles must be a dict of bools")
            coerced = {k: self._coerce_bool(f"alert_toggles.{k}", v) for k, v in value.items()}
            existing = (self._data or {}).get("alert_toggles") or {}
            return {**DEFAULTS["alert_toggles"], **existing, **coerced}
        if key in OPTIONAL_NUMERIC_KEYS:
            if value is None or (isinstance(value, str) and value.strip() == ""):
                return None
            return self._coerce_nonneg_float(key, value)
        if key in NUMERIC_KEYS:
            return self._coerce_nonneg_float(key, value)
        if key in DEFAULTS:
            # Unknown behavior for non-numeric keys in DEFAULTS — pass through
            return value
        raise ValueError(f"unknown setting: {key!r}")

    @staticmethod
    def _coerce_bool(key: str, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and value in (0, 1):
            return bool(value)
        if isinstance(value, str) and value.lower() in ("true", "false", "1", "0", "yes", "no"):
            return value.lower() in ("true", "1", "yes")
        raise ValueError(f"{key}: expected a boolean, got {value!r}")

    @staticmethod
    def _coerce_nonneg_float(key: str, value: Any) -> float:
        try:
            f = float(value)
        except (TypeError, ValueError) as e:
            raise ValueError(f"{key}: not a number ({value!r})") from e
        if f < 0:
            raise ValueError(f"{key}: must be >= 0 (got {f})")
        return f

    @staticmethod
    def _apply_dotted(d: dict, dotted_key: str, value: Any) -> None:
        if "." not in dotted_key:
            d[dotted_key] = value
            return
        head, _, tail = dotted_key.partition(".")
        sub = d.get(head)
        if not isinstance(sub, dict):
            sub = {}
            d[head] = sub
        Settings._apply_dotted(sub, tail, value)

    def _atomic_write(self, merged: dict[str, Any]) -> None:
        """Write merged dict to <path>.tmp then os.rename to config_path."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.config_path.with_suffix(self.config_path.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(merged, indent=2))
            os.replace(tmp, self.config_path)
        except OSError:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            raise


settings = Settings()
