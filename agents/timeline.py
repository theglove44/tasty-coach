"""Event classification and roll annotation for the Phase D timeline.

Pure, I/O-free: classifies a TastyTrade SDK Transaction (or dict-like row) into
a domain-level TimelineEvent, and a post-pass flags open/close pairs on the
same day+underlying as roll legs.
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, List, Literal, Optional


EventType = Literal[
    "assignment",
    "exercise",
    "expiration",
    "open",
    "close",
    "roll",
    "cash_movement",
    "dividend",
    "fee",
    "adjustment",
    "cancellation",
    "other",
]


def _g(obj: Any, key: str, default: Any = None) -> Any:
    """Read `key` from obj as attribute or dict item; return default if missing/None."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        val = obj.get(key, default)
    else:
        val = getattr(obj, key, default)
    return default if val is None else val


@dataclass
class TimelineEvent:
    """A classified, render-ready event derived from a single SDK Transaction."""

    event_type: EventType
    occurred_at: datetime
    symbol: Optional[str]
    underlying_symbol: Optional[str]
    description: str
    quantity: Optional[Decimal]
    amount: Optional[Decimal]
    transaction_id: Optional[int]
    order_id: Optional[int]
    raw_type: str
    raw_sub_type: str
    is_roll_leg: bool = False


def classify_event(txn: Any) -> TimelineEvent:
    """Classify a single SDK Transaction (or dict) into a TimelineEvent.

    Pure: no I/O. Never raises on unknown fields — falls back to "other".
    """
    t_type = str(_g(txn, "transaction_type", "") or "")
    sub = str(_g(txn, "transaction_sub_type", "") or "")
    desc = str(_g(txn, "description", "") or "")

    executed = _g(txn, "executed_at")
    if isinstance(executed, datetime):
        occurred_at = executed
    else:
        d = _g(txn, "transaction_date")
        if isinstance(d, datetime):
            occurred_at = d
        elif isinstance(d, date):
            occurred_at = datetime(d.year, d.month, d.day)
        else:
            occurred_at = datetime.min

    # Normalize to UTC-aware so sort() never crashes on mixed aware/naive inputs.
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)
    else:
        occurred_at = occurred_at.astimezone(timezone.utc)

    nv_raw = _g(txn, "net_value")
    amount: Optional[Decimal]
    if nv_raw is None:
        amount = None
    else:
        try:
            amount = Decimal(str(nv_raw))
        except Exception:
            amount = None

    qty_raw = _g(txn, "quantity")
    quantity: Optional[Decimal]
    if qty_raw is None:
        quantity = None
    else:
        try:
            quantity = Decimal(str(qty_raw))
        except Exception:
            quantity = None

    sub_l = sub.lower()
    if "cancel" in sub_l:
        etype: EventType = "cancellation"
    elif sub in ("Assignment", "Cash Settled Assignment"):
        etype = "assignment"
    elif sub in ("Exercise", "Cash Settled Exercise"):
        etype = "exercise"
    elif sub == "Expiration":
        etype = "expiration"
    elif sub in ("Buy to Open", "Sell to Open"):
        etype = "open"
    elif sub in ("Buy to Close", "Sell to Close"):
        etype = "close"
    elif sub == "Dividend":
        etype = "dividend"
    elif sub == "Fee":
        etype = "fee"
    elif sub == "Balance Adjustment":
        etype = "adjustment"
    elif sub in ("Deposit", "Withdrawal", "Transfer", "ACAT"):
        etype = "cash_movement"
    elif t_type == "Money Movement":
        etype = "cash_movement"
    else:
        etype = "other"

    return TimelineEvent(
        event_type=etype,
        occurred_at=occurred_at,
        symbol=_g(txn, "symbol"),
        underlying_symbol=_g(txn, "underlying_symbol"),
        description=desc,
        quantity=quantity,
        amount=amount,
        transaction_id=_g(txn, "id"),
        order_id=_g(txn, "order_id"),
        raw_type=t_type,
        raw_sub_type=sub,
        is_roll_leg=False,
    )


def annotate_rolls(events: List[TimelineEvent]) -> List[TimelineEvent]:
    """Flag open+close legs from the same TastyTrade order as roll legs.

    TastyTrade submits a multi-leg roll as a single order, so events sharing
    an `order_id` that contain BOTH an open and a close leg are authoritative
    roll pairs. Unrelated trades on the same day/underlying (different orders)
    are left alone.

    Returns a new list; does not mutate inputs.
    """
    out = [dataclasses.replace(e) for e in events]
    buckets: dict = defaultdict(lambda: {"open": [], "close": []})
    for i, e in enumerate(out):
        if e.order_id is None:
            continue
        if e.event_type not in ("open", "close"):
            continue
        buckets[e.order_id][e.event_type].append(i)
    for groups in buckets.values():
        if groups["open"] and groups["close"]:
            for idx in groups["open"] + groups["close"]:
                out[idx].is_roll_leg = True
    return out
