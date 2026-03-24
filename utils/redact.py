"""Redaction utilities for screenshot-safe output."""

import re

_enabled = False


def enable():
    """Enable redaction globally."""
    global _enabled
    _enabled = True


def is_enabled() -> bool:
    return _enabled


def account(value: str) -> str:
    """Mask account numbers when redaction is enabled."""
    if not _enabled:
        return value
    return "XXXXXXXXX"


def dollars(value: float, fmt: str = ",.2f") -> str:
    """Format a dollar amount, replacing digits with X when redacting.

    Returns the formatted string (without leading $).
    Caller is responsible for the $ prefix.
    """
    formatted = format(value, fmt)
    if not _enabled:
        return formatted
    return re.sub(r'\d', 'X', formatted)
