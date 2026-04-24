"""Alert collection and filtering for risk management."""

from dataclasses import dataclass, field
from typing import Any, Literal

from utils.settings import settings

Severity = Literal["info", "warn", "critical"]
Category = Literal[
    "position_size", "bp", "theta", "market", "concentration", "assignment"
]


@dataclass(frozen=True)
class Alert:
    """Immutable alert record."""

    severity: Severity
    category: Category
    message: str
    context: dict[str, Any] = field(default_factory=dict)


class AlertCollector:
    """Collect alerts with deduplication by category and message."""

    def __init__(self):
        self._alerts: list[Alert] = []
        self._seen: set[tuple[str, str]] = set()

    def add(self, alert: Alert) -> None:
        """Add alert if not already seen and toggle is enabled."""
        toggles = settings.get("alert_toggles") or {}
        if not toggles.get(alert.category, True):
            return
        key = (alert.category, alert.message)
        if key in self._seen:
            return
        self._seen.add(key)
        self._alerts.append(alert)

    def get_active_alerts(self) -> list[Alert]:
        """Return all collected alerts."""
        return list(self._alerts)

    def __len__(self) -> int:
        """Return alert count."""
        return len(self._alerts)
