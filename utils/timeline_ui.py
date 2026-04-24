"""Timeline renderer + CLI/launcher orchestrator for Phase D.

`render_timeline` is pure: list[TimelineEvent] -> rich.Panel. `run_timeline`
is the async entry point used by `main.py --timeline` and the launcher
action; it fetches via HistoryAgent, renders, prints, and returns an exit code.
"""

from __future__ import annotations

import sys
from datetime import datetime
from typing import List, Optional

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from agents.timeline import EventType, TimelineEvent
from utils.dashboard_ui import fmt_signed_money


MAX_ROWS: int = 100

ICON_BY_EVENT: dict = {
    "assignment":    "⚠",
    "exercise":      "❗",
    "expiration":    "⏰",
    "open":          "🟢",
    "close":         "🔴",
    "roll":          "🔄",
    "cash_movement": "💵",
    "dividend":      "💰",
    "fee":           "💸",
    "adjustment":    "~",
    "cancellation":  "✖",
    "other":         "•",
}


def _style_for(etype: EventType, is_roll: bool) -> str:
    if is_roll:
        return "magenta"
    if etype in ("assignment", "exercise"):
        return "bold red"
    if etype == "expiration":
        return "yellow"
    if etype == "open":
        return "green"
    if etype == "close":
        return "cyan"
    if etype == "cancellation":
        return "red"
    if etype in ("dividend", "cash_movement"):
        return "blue"
    return ""


def render_timeline(
    events: List[TimelineEvent],
    days: int,
    account_number: str,
) -> Panel:
    """Render classified events as a Rich Panel containing a Table.

    Pure — no I/O. Caller is responsible for passing events sorted
    newest-first. Caps at MAX_ROWS with a dim footer when truncated.
    """
    title = f"Event Timeline — {account_number} — last {days}d"

    if not events:
        body = Text(f"No events in the last {days} days.", style="dim")
        return Panel(body, title=title, border_style="blue")

    rows = events[:MAX_ROWS]
    truncated = len(events) > MAX_ROWS

    table = Table(expand=True, show_lines=False, header_style="bold")
    table.add_column("When", width=16, no_wrap=True)
    table.add_column("I", width=2, no_wrap=True)
    table.add_column("Type", width=12, no_wrap=True)
    table.add_column("Underlying", width=10, no_wrap=True)
    table.add_column("Symbol", width=22, overflow="fold")
    table.add_column("Qty", width=6, justify="right")
    table.add_column("Amount", width=12, justify="right")
    table.add_column("Description", ratio=1, overflow="fold")

    for e in rows:
        when = (
            e.occurred_at.strftime("%Y-%m-%d %H:%M")
            if e.occurred_at.replace(tzinfo=None) != datetime.min
            else "—"
        )
        icon = ICON_BY_EVENT.get(e.event_type, "•")
        etype_label = e.event_type
        if e.is_roll_leg:
            icon = ICON_BY_EVENT["roll"]
            etype_label = "roll"
        underlying = e.underlying_symbol or ""
        symbol = e.symbol or ""
        qty = f"{e.quantity:g}" if e.quantity is not None else ""
        amount = fmt_signed_money(e.amount) if e.amount is not None else ""
        desc = e.description or ""
        style = _style_for(e.event_type, e.is_roll_leg)
        table.add_row(when, icon, etype_label, underlying, symbol, qty, amount, desc, style=style)

    if truncated:
        footer = Text(f"(showing newest {MAX_ROWS} of {len(events)})", style="dim")
        body = Group(table, footer)
    else:
        body = table

    return Panel(body, title=title, border_style="blue")


async def run_timeline(
    session,
    account_number: str,
    days: int = 30,
    symbol: Optional[str] = None,
    console: Optional[Console] = None,
) -> int:
    """Fetch, render, and print the event timeline. Returns 0 on success, 1 on fetch error."""
    console = console or Console()
    try:
        from agents.history import HistoryAgent
        agent = await HistoryAgent(session, account_number).init()
        if getattr(agent, "account", None) is None:
            print(
                f"Error fetching timeline: account {account_number!r} could not be resolved.",
                file=sys.stderr,
            )
            return 1
        events = await agent.get_recent_events(days=days, symbol=symbol)
    except Exception as exc:
        print(f"Error fetching timeline: {exc}", file=sys.stderr)
        return 1

    console.print(render_timeline(events, days=days, account_number=account_number))
    return 0
