"""Settings management for Tasty-Coach."""

import json
import logging
import copy
from pathlib import Path
from typing import Any

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


settings = Settings()
