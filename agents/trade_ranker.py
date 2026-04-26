"""Watchlist-wide trade ranking orchestrator.

Stub implementation for TCBT-2. Full pipeline is implemented across
TCBT-3..11; this module currently returns a canonical empty result so the
CLI and launcher entry points can be wired in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Optional, Sequence

from tastytrade import Session
from tastytrade.metrics import get_market_metrics
from tastytrade.market_data import get_market_data_by_type

from agents.scanner import ScannerAgent


DEFAULT_WATCHLISTS: tuple[str, ...] = (
    "Chris Historical Trades",
    "High Options Volume",
)

STUB_MARKER: str = "stub — full logic in TCBT-8/3/9/10/4/5/6/7"

_BATCH_SIZE: int = 50


@dataclass
class SymbolContext:
    """Normalised per-symbol scan output ready for candidate generation."""
    symbol: str
    current_price: Optional[Decimal] = None
    volume: Optional[Decimal] = None
    iv_rank: Optional[float] = None
    iv_percentile: Optional[float] = None
    current_iv: Optional[float] = None
    beta: Optional[float] = None
    liquidity_rank: Optional[float] = None
    next_earnings_date: Optional[date] = None


async def scan_watchlists(
    session: Session,
    watchlists: Optional[Sequence[str]] = None,
    *,
    scanner: Optional[ScannerAgent] = None,
) -> tuple[list[SymbolContext], list[str]]:
    """Resolve watchlist symbols and fetch metric+price data; return (contexts, warnings)."""
    warnings: list[str] = []
    contexts: list[SymbolContext] = []

    if watchlists is None:
        names = list(DEFAULT_WATCHLISTS)
    else:
        names = list(watchlists)

    if not names:
        return ([], [])

    if scanner is None:
        scanner = ScannerAgent(session)

    seen: set[str] = set()
    symbols: list[str] = []
    for name in names:
        wl_symbols = await scanner.get_symbols_from_watchlist(name, equity_only=True)
        if not wl_symbols:
            warnings.append(f"watchlist '{name}' not found or empty")
            continue
        for s in wl_symbols:
            if s not in seen:
                seen.add(s)
                symbols.append(s)

    if not symbols:
        return (contexts, warnings)

    for i in range(0, len(symbols), _BATCH_SIZE):
        batch = symbols[i:i + _BATCH_SIZE]
        try:
            metrics_list = get_market_metrics(session, batch)
            prices_list = get_market_data_by_type(session, equities=batch)
        except Exception as e:
            warnings.append(f"batch fetch failed: {e}")
            continue

        metrics = {m.symbol: m for m in metrics_list}
        prices = {d.symbol: d for d in prices_list}

        for symbol in batch:
            metric = metrics.get(symbol)
            data = prices.get(symbol)
            ctx = _build_context(symbol, metric, data)
            if ctx is None:
                warnings.append(f"{symbol}: no market metrics or price data returned")
            else:
                contexts.append(ctx)

    return (contexts, warnings)


def _build_context(
    symbol: str,
    metric: Any,
    data: Any,
) -> Optional[SymbolContext]:
    """Transform a metric+price pair into a SymbolContext; returns None when both inputs are absent."""
    if metric is None and data is None:
        return None

    ctx = SymbolContext(symbol=symbol)

    if data is not None:
        ctx.current_price = data.mark if data.mark is not None else data.last
        ctx.volume = data.volume

    if metric is not None:
        try:
            ctx.iv_rank = (float(metric.implied_volatility_index_rank) * 100) if metric.implied_volatility_index_rank else None
        except (ValueError, TypeError):
            ctx.iv_rank = None
        try:
            ctx.iv_percentile = (float(metric.implied_volatility_percentile) * 100) if metric.implied_volatility_percentile else None
        except (ValueError, TypeError):
            ctx.iv_percentile = None
        try:
            ctx.current_iv = float(metric.implied_volatility_index) if metric.implied_volatility_index else None
        except (ValueError, TypeError):
            ctx.current_iv = None
        try:
            ctx.beta = float(metric.beta) if metric.beta else None
        except (ValueError, TypeError):
            ctx.beta = None
        try:
            ctx.liquidity_rank = float(metric.liquidity_rank) if metric.liquidity_rank else None
        except (ValueError, TypeError):
            ctx.liquidity_rank = None
        if metric.earnings and metric.earnings.expected_report_date:
            ctx.next_earnings_date = metric.earnings.expected_report_date

    return ctx


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
