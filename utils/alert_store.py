"""SQLite-backed alert history + view tracking for Phase E.

Wraps a TradeDB (or raw sqlite3.Connection for testing). Never raises on
caller-visible paths — on sqlite3.Error we log a warning and return a safe
default so the dashboard / risk report can degrade gracefully.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from agents.alerts import Alert


logger = logging.getLogger(__name__)


def _conn(db) -> sqlite3.Connection:
    return getattr(db, "conn", db)


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class AlertStore:
    """Persistence layer for alerts and last-viewed markers."""

    def __init__(self, db) -> None:
        self._conn = _conn(db)

    def record_alerts(
        self,
        account_number: str,
        alerts: Iterable[Alert],
        *,
        now: Optional[datetime] = None,
    ) -> int:
        """Insert alerts with per-day dedup on (account, category, message).

        Same alert on the same day is a no-op (INSERT OR IGNORE). Returns the
        number of rows actually inserted.
        """
        when = _as_utc(now) or datetime.now(timezone.utc)
        recorded_at = when.isoformat()
        recorded_day = when.date().isoformat()
        inserted = 0
        try:
            with self._conn:
                for a in alerts:
                    ctx: Optional[str] = None
                    ctx_val = getattr(a, "context", None)
                    if ctx_val:
                        try:
                            ctx = json.dumps(ctx_val, default=str)
                        except (TypeError, ValueError):
                            ctx = None
                    cur = self._conn.execute(
                        "INSERT OR IGNORE INTO alert_history "
                        "(account_number, severity, category, message, context, "
                        "recorded_at, recorded_day) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (account_number, a.severity, a.category, a.message,
                         ctx, recorded_at, recorded_day),
                    )
                    inserted += cur.rowcount if cur.rowcount > 0 else 0
        except sqlite3.Error as e:
            logger.warning("record_alerts failed: %s", e)
            return 0
        return inserted

    def get_last_viewed(self, account_number: str) -> Optional[datetime]:
        """Return UTC-aware last_viewed_at or None."""
        try:
            row = self._conn.execute(
                "SELECT last_viewed_at FROM alert_views WHERE account_number = ?",
                (account_number,),
            ).fetchone()
        except sqlite3.Error as e:
            logger.warning("get_last_viewed failed: %s", e)
            return None
        if not row:
            return None
        try:
            return datetime.fromisoformat(row[0])
        except (TypeError, ValueError):
            return None

    def mark_viewed(
        self,
        account_number: str,
        when: Optional[datetime] = None,
    ) -> None:
        ts = (_as_utc(when) or datetime.now(timezone.utc)).isoformat()
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO alert_views (account_number, last_viewed_at) "
                    "VALUES (?, ?) ON CONFLICT(account_number) DO UPDATE "
                    "SET last_viewed_at = excluded.last_viewed_at",
                    (account_number, ts),
                )
        except sqlite3.Error as e:
            logger.warning("mark_viewed failed: %s", e)

    def get_history(self, account_number: str, limit: int = 50) -> list[dict]:
        """Most-recent-first list of dicts. Empty list on error."""
        try:
            rows = self._conn.execute(
                "SELECT id, severity, category, message, context, recorded_at "
                "FROM alert_history WHERE account_number = ? "
                "ORDER BY recorded_at DESC LIMIT ?",
                (account_number, limit),
            ).fetchall()
        except sqlite3.Error as e:
            logger.warning("get_history failed: %s", e)
            return []
        out: list[dict] = []
        for r in rows:
            ctx: Any = None
            if r["context"]:
                try:
                    ctx = json.loads(r["context"])
                except (TypeError, ValueError):
                    ctx = None
            try:
                recorded = datetime.fromisoformat(r["recorded_at"])
            except (TypeError, ValueError):
                recorded = None
            out.append({
                "id": r["id"],
                "severity": r["severity"],
                "category": r["category"],
                "message": r["message"],
                "context": ctx,
                "recorded_at": recorded,
            })
        return out

    def new_alert_keys_since(
        self,
        account_number: str,
        since: Optional[datetime],
    ) -> set:
        """Return {(category, message), ...} for alerts recorded after `since`.

        Returns an empty set if `since` is None (first ever view — avoid a
        wall of dots on every alert).
        """
        if since is None:
            return set()
        since_iso = _as_utc(since).isoformat()
        try:
            rows = self._conn.execute(
                "SELECT category, message FROM alert_history "
                "WHERE account_number = ? AND recorded_at > ?",
                (account_number, since_iso),
            ).fetchall()
        except sqlite3.Error as e:
            logger.warning("new_alert_keys_since failed: %s", e)
            return set()
        return {(r["category"], r["message"]) for r in rows}


def print_alert_history(
    store: AlertStore,
    account_number: str,
    limit: int = 50,
    *,
    console=None,
) -> None:
    """Render a Rich Table of recent alerts. Prints to stdout via Console."""
    from rich.console import Console
    from rich.table import Table

    console = console or Console()
    rows = store.get_history(account_number, limit=limit)
    if not rows:
        console.print(f"No alerts recorded for {account_number}.")
        return
    table = Table(title=f"Alert history — {account_number}")
    table.add_column("Recorded")
    table.add_column("Severity")
    table.add_column("Category")
    table.add_column("Message", overflow="fold")
    for r in rows:
        ts = r["recorded_at"].isoformat() if r["recorded_at"] else "—"
        table.add_row(ts, r["severity"], r["category"], r["message"])
    console.print(table)
