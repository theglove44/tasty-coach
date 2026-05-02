"""Settings management for Tasty-Coach."""

import json
import logging
import math
import copy
import os
from pathlib import Path
from typing import Any

NUMERIC_KEYS: frozenset[str] = frozenset({
    "position_pct_nlv_warn",
    "bp_usage_warn",
    "bp_usage_block",
    "concentration_pct_nlv_warn",
    "bt_max_spread_pct",
    "bt_max_pct_nlv_per_trade",
    "bt_bp_cap_for_new",
    "bt_concentration_overlap_block_pct",
    "bt_min_ivr",
    "bt_per_trade_risk_pct",
    "bt_csp_delta_min",
    "bt_csp_delta_max",
    "bt_csp_min_otm_pct",
    "bt_csp_min_annualized_return",
    "bt_csp_skew_warn_threshold",
    "bt_csp_max_pct_nlv_per_trade",
    "bt_chain_moneyness_min",
    "bt_chain_moneyness_max",
})
OPTIONAL_NUMERIC_KEYS: frozenset[str] = frozenset({
    "theta_target",  # may be None
    "bt_per_trade_risk_dollars",  # may be None — when set, overrides bt_per_trade_risk_pct
})
INTEGER_KEYS: frozenset[str] = frozenset({
    "bt_earnings_blackout_days",
    "bt_min_dte",
    "bt_max_dte",
    "bt_min_open_interest",
    "bt_max_per_symbol",
    "bt_research_concurrency",
    "bt_research_timeout_seconds",
    "bt_csp_max_per_symbol",
})

DEFAULTS: dict[str, Any] = {
    "position_pct_nlv_warn": 0.05,
    "bp_usage_warn": 0.50,
    "bp_usage_block": 0.50,
    "theta_target": None,
    "bt_per_trade_risk_dollars": None,
    "concentration_pct_nlv_warn": 0.15,
    "bt_earnings_blackout_days": 7,
    "bt_min_dte": 21,
    "bt_max_dte": 60,
    "bt_min_open_interest": 200,
    "bt_max_per_symbol": 3,
    "bt_max_spread_pct": 0.10,
    "bt_max_pct_nlv_per_trade": 0.05,
    "bt_bp_cap_for_new": 0.50,
    "bt_concentration_overlap_block_pct": 0.25,
    "bt_per_trade_risk_pct": 0.02,
    "bt_min_ivr": 30.0,
    "bt_research_concurrency": 5,
    "bt_research_timeout_seconds": 90,
    # Cash-secured-put screener (--put-selector). Income profile by default
    # (lower delta, expire-worthless preferred); raise the delta range for
    # wheel entries.
    "bt_csp_delta_min": 0.15,
    "bt_csp_delta_max": 0.30,
    "bt_csp_min_otm_pct": 0.03,
    "bt_csp_min_annualized_return": 0.10,
    "bt_csp_skew_warn_threshold": 1.20,
    "bt_csp_max_per_symbol": 5,
    # CSPs need a more permissive size cap than spreads — assignment-to-zero
    # max-loss is much larger than spread max-loss, but the user is choosing
    # to be cash-secured so they're underwriting the full strike. Default 0.30
    # = 30% of NLV per trade (per contract). Spread cap (bt_max_pct_nlv_per_trade)
    # stays at 5% for verticals.
    "bt_csp_max_pct_nlv_per_trade": 0.30,
    # Strike pre-filter: drop chain strikes outside [min, max] × spot before
    # the Greeks subscription. Generous default — every plausibly-tradeable
    # strike at any reasonable IV / DTE / target-delta combination falls
    # inside [0.40, 1.60]. Tightening shaves more time but risks dropping
    # legitimate candidates on very high-vol underlyings.
    "bt_chain_moneyness_min": 0.40,
    "bt_chain_moneyness_max": 1.60,
    "alert_toggles": {
        "position_size": True,
        "bp": True,
        "theta": True,
        "market": True,
        "concentration": True,
        "assignment": True,
    },
}
SETTINGS_DESCRIPTIONS: dict[str, str] = {
    # Phase A risk-management thresholds
    "position_pct_nlv_warn": "Warn when any single position exceeds this fraction of NLV (0.05 = 5%).",
    "bp_usage_warn": "Warn when buying-power usage exceeds this fraction (0.50 = 50%).",
    "bp_usage_block": "Block new trades when buying-power usage exceeds this fraction.",
    "concentration_pct_nlv_warn": "Warn when concentration in one underlying exceeds this fraction of NLV.",
    "theta_target": "Target portfolio theta (positive number). Set 'none' to disable the theta alert.",
    # Best-Trades-Today: quality gates
    "bt_earnings_blackout_days": "Reject candidates with earnings within this many days (forward only).",
    "bt_min_dte": "Reject candidates with DTE below this number (default 21).",
    "bt_max_dte": "Reject candidates with DTE above this number (default 60).",
    "bt_min_open_interest": "Reject if any leg's open interest is below this floor.",
    "bt_max_spread_pct": "Reject if worst leg's bid-ask spread / mid exceeds this fraction (0.10 = 10%).",
    # Best-Trades-Today: account fit (only active when --account is provided)
    "bt_max_pct_nlv_per_trade": "Reject candidates whose max-loss exceeds this fraction of NLV (0.05 = 5%).",
    "bt_bp_cap_for_new": "Reject if post-trade BP usage would exceed this fraction (0.50 = 50%).",
    "bt_concentration_overlap_block_pct": "Reject if combined exposure to one underlying exceeds this fraction of NLV.",
    "bt_per_trade_risk_pct": "Per-trade risk budget for sizing recommendations (0.02 = 2% of NLV per spread). Ignored when bt_per_trade_risk_dollars is set.",
    "bt_per_trade_risk_dollars": "Optional fixed-dollar per-trade risk budget. When set, takes precedence over bt_per_trade_risk_pct (handy for small accounts where 'I want to risk $250' is more intuitive than a percentage). Set to null/None to use the percentage instead.",
    # Best-Trades-Today: scan + research
    "bt_min_ivr": "Pre-filter watchlist symbols by IVR; symbols below this percentage are skipped before research (default 30).",
    "bt_max_per_symbol": "Cap candidate count per symbol from the researcher (default 3).",
    "bt_research_concurrency": "Number of symbols researched in parallel (default 5; raise for speed at the cost of API load).",
    "bt_research_timeout_seconds": "Per-symbol hard timeout in seconds; symbols exceeding this become research_timeout rejections (default 45).",
    # Cash-secured-put screener (--put-selector)
    "bt_csp_delta_min": "Minimum |short delta| for cash-secured-put candidates (default 0.15 = ~15Δ).",
    "bt_csp_delta_max": "Maximum |short delta| for cash-secured-put candidates (default 0.30 = ~30Δ; raise for wheel entries).",
    "bt_csp_min_otm_pct": "Minimum buffer below spot to qualify a CSP strike (0.03 = 3%).",
    "bt_csp_min_annualized_return": "Floor for the income score; (credit*365/dte)/strike below this earns 0 (default 0.10 = 10%).",
    "bt_csp_skew_warn_threshold": "Put/call IV ratio at ~25Δ that triggers the elevated-skew warning (default 1.20).",
    "bt_csp_max_per_symbol": "Cap on CSP ideas emitted per symbol per scan (default 5; trim by premium desc).",
    "bt_csp_max_pct_nlv_per_trade": "Per-trade size cap for CSPs as fraction of NLV (assignment-to-zero max-loss / NLV). Default 0.30 = 30% — separate from the spread cap because cash-secured assignment carries the full strike.",
    "bt_chain_moneyness_min": "Strike pre-filter floor: drop chain strikes below this fraction of spot before the Greeks subscription. Speed knob; widen if you trade very high-IV underlyings (default 0.40 keeps everything down to ~0.4× spot).",
    "bt_chain_moneyness_max": "Strike pre-filter cap: drop chain strikes above this fraction of spot before the Greeks subscription. Speed knob; widen for very high-IV underlyings (default 1.60 keeps everything up to ~1.6× spot).",
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
        if key in INTEGER_KEYS:
            return self._coerce_nonneg_int(key, value)
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
        if not math.isfinite(f):
            raise ValueError(f"{key}: must be finite (got {f})")
        if f < 0:
            raise ValueError(f"{key}: must be >= 0 (got {f})")
        return f

    @staticmethod
    def _coerce_nonneg_int(key: str, value: Any) -> int:
        """Coerce value to a non-negative int; reject bool, non-finite, non-whole, or negative."""
        if isinstance(value, bool):
            raise ValueError(f"{key}: expected int, got bool")
        if isinstance(value, int):
            i = value
        elif isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError(f"{key}: must be finite (got {value})")
            if not value.is_integer():
                raise ValueError(f"{key}: must be a whole number (got {value})")
            i = int(value)
        elif isinstance(value, str):
            try:
                f = float(value)
            except ValueError as e:
                raise ValueError(f"{key}: not a number ({value!r})") from e
            if not math.isfinite(f):
                raise ValueError(f"{key}: must be finite (got {f})")
            if not f.is_integer():
                raise ValueError(f"{key}: must be a whole number (got {f})")
            i = int(f)
        else:
            raise ValueError(f"{key}: not a number ({value!r})")
        if i < 0:
            raise ValueError(f"{key}: must be >= 0 (got {i})")
        return i

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
