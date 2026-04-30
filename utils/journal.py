"""Append-only JSONL journal for the coach's cross-session memory.

Lives at ``~/.tasty-coach/journal.jsonl``. Each line is one JSON object:

    {
      "ts": "2026-04-29T10:23:45",   # ISO-8601, local time
      "kind": "recommendation",       # recommendation | trade_open | trade_close
                                      # | note | outcome
      "symbol": "EWZ",                # optional underlying
      "strategy": "IRON_CONDOR",      # optional structure
      "rationale": "high IVR, ...",   # human-readable
      "details": {...},               # optional structured payload
      "outcome": null                  # filled later: won|lost|rolled|early_close
    }

The coach calls ``record`` after recommending or observing something notable, and
``recall`` to ground answers about prior decisions. Append-only; no edits.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path.home() / ".tasty-coach" / "journal.jsonl"

VALID_KINDS = {
    "recommendation",
    "trade_open",
    "trade_close",
    "note",
    "outcome",
}


def _path() -> Path:
    p = os.environ.get("TASTY_COACH_JOURNAL_PATH")
    return Path(p) if p else DEFAULT_PATH


def _ensure_parent(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


def record(entry: dict[str, Any], *, path: Optional[Path] = None) -> dict[str, Any]:
    """Append one entry. Adds ``ts`` if missing. Returns the persisted entry."""
    p = path or _path()
    _ensure_parent(p)

    out = dict(entry)
    out.setdefault("ts", datetime.now().isoformat(timespec="seconds"))
    kind = out.get("kind")
    if kind not in VALID_KINDS:
        logger.warning("journal: unknown kind %r; coercing to 'note'", kind)
        out["kind"] = "note"

    # Atomic append: a single os.write call up to PIPE_BUF (4096) is atomic on
    # POSIX, and JSONL lines are typically <1 KB. Use line buffering to be safe.
    line = json.dumps(out, default=str, ensure_ascii=False) + "\n"
    with p.open("a", encoding="utf-8") as f:
        f.write(line)
    return out


def _iter_entries(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                logger.warning("journal: skipping malformed line: %s", e)


def recall(
    *,
    since: Optional[datetime | str] = None,
    days: Optional[int] = None,
    symbol: Optional[str] = None,
    kind: Optional[str] = None,
    limit: int = 50,
    path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """Read journal entries, newest first.

    Filters:
    - ``since`` / ``days``: keep entries with ``ts >= since`` (or ``now - days``).
    - ``symbol``: case-insensitive match on the entry's ``symbol`` field.
    - ``kind``: exact match against ``VALID_KINDS``.
    - ``limit``: cap on returned entries (newest-first after sorting).
    """
    p = path or _path()

    cutoff: Optional[datetime] = None
    if isinstance(since, datetime):
        cutoff = since
    elif isinstance(since, str):
        try:
            cutoff = datetime.fromisoformat(since)
        except ValueError:
            cutoff = None
    if cutoff is None and days is not None and days >= 0:
        cutoff = datetime.now() - timedelta(days=days)

    sym = symbol.upper() if symbol else None
    out: list[dict[str, Any]] = []
    for e in _iter_entries(p):
        if kind and e.get("kind") != kind:
            continue
        if sym and (e.get("symbol") or "").upper() != sym:
            continue
        if cutoff is not None:
            ts_raw = e.get("ts")
            try:
                ts = datetime.fromisoformat(ts_raw) if ts_raw else None
            except (TypeError, ValueError):
                ts = None
            if ts is None or ts < cutoff:
                continue
        out.append(e)

    out.sort(key=lambda e: e.get("ts") or "", reverse=True)
    if limit and limit > 0:
        out = out[:limit]
    return out


def stats(*, path: Optional[Path] = None) -> dict[str, Any]:
    """Lightweight summary used by the dashboard feed header."""
    p = path or _path()
    total = 0
    by_kind: dict[str, int] = {}
    last_ts: Optional[str] = None
    for e in _iter_entries(p):
        total += 1
        k = e.get("kind") or "unknown"
        by_kind[k] = by_kind.get(k, 0) + 1
        ts = e.get("ts")
        if ts and (last_ts is None or ts > last_ts):
            last_ts = ts
    return {"total": total, "by_kind": by_kind, "last_ts": last_ts}
