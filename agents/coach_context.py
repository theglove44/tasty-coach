"""Shared runtime context for the AI coach.

Holds the live TastyTrade session, resolved account, and journal path so the
SDK tool wrappers (which run as in-process MCP tools and receive only their
JSON args) can reach back into application state.

Stored in a ``contextvars.ContextVar`` so concurrent web requests (each calling
``set_current`` with their own context) don't trample each other. Tool callbacks
run in the same task tree as the request handler, so the var propagates
correctly without explicit threading.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class CoachContext:
    session: Any           # tastytrade.Session
    account: Any           # tastytrade.Account
    account_number: str
    journal_path: Path = field(
        default_factory=lambda: Path.home() / ".tasty-coach" / "journal.jsonl"
    )


_CURRENT: ContextVar[Optional[CoachContext]] = ContextVar("coach_context", default=None)


def set_current(ctx: CoachContext) -> None:
    _CURRENT.set(ctx)


def current() -> CoachContext:
    ctx = _CURRENT.get()
    if ctx is None:
        raise RuntimeError(
            "CoachContext not initialised. Call coach_context.set_current() before invoking tools."
        )
    return ctx
