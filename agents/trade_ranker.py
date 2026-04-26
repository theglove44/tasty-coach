"""Watchlist-wide trade ranking orchestrator.

Stub implementation for TCBT-2. Full pipeline is implemented across
TCBT-3..11; this module currently returns a canonical empty result so the
CLI and launcher entry points can be wired in isolation.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

from tastytrade import Session


DEFAULT_WATCHLISTS: tuple[str, ...] = (
    "Chris Historical Trades",
    "High Options Volume",
)

STUB_MARKER: str = "stub — full logic in TCBT-8/3/9/10/4/5/6/7"


async def run_best_trades(
    session: Session,
    *,
    watchlists: Optional[Sequence[str]] = None,
    top: int = 3,
    output_format: str = "text",
) -> dict[str, Any]:
    """Rank trade ideas across watchlists; stub returns an empty canonical result."""
    resolved = list(watchlists) if watchlists is not None else list(DEFAULT_WATCHLISTS)
    return {
        "top": [],
        "rejected": [],
        "warnings": [],
        "watchlists": resolved,
    }


def _print_best_trades_text(result: dict[str, Any], top: int) -> None:
    """Print a best-trades result dict in human-readable form including the stub marker."""
    print()
    print("=" * 80)
    print(f"Best Trades Today  ({STUB_MARKER})")
    print("=" * 80)
    watchlists = result["watchlists"]
    print(f"Watchlists: {', '.join(watchlists) if watchlists else '(none)'}")
    print(f"Top requested: {top}")
    print(f"Ranked: {len(result['top'])}   Rejected: {len(result['rejected'])}   Warnings: {len(result['warnings'])}")
    if not result["top"]:
        print()
        print("No trade ideas yet — orchestrator stub. Implementation lands in TCBT-3..11.")
    if result["warnings"]:
        print()
        print("Warnings:")
        for w in result["warnings"]:
            print(f"  • {w}")
