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

from agents.options_researcher import OptionsResearcherAgent
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


@dataclass
class Candidate:
    """A single trade idea ready for gates/scoring/ranking."""
    symbol: str
    structure: str
    expiration: date
    dte: int
    width: float
    credit: float
    max_loss: float
    credit_pct_of_width: float
    short_delta: float
    pop_estimate: float
    breakevens: list[float]
    net_greeks: dict[str, float]
    legs: list[dict[str, Any]]
    researcher_score: float
    researcher_score_breakdown: dict[str, Any]
    context: SymbolContext


@dataclass
class Rejection:
    """A symbol or candidate that was filtered out before scoring."""
    symbol: str
    reason: str
    detail: Optional[str] = None


def _idea_to_candidate(symbol: str, idea: dict[str, Any], context: SymbolContext) -> Candidate:
    """Translate a researcher trade_ideas dict into a Candidate, preserving the source SymbolContext."""
    expiration = date.fromisoformat(idea["expiration"])
    return Candidate(
        symbol=symbol,
        structure=idea["strategy"],
        expiration=expiration,
        dte=idea["dte"],
        width=idea["width"],
        credit=idea["credit"],
        max_loss=idea["max_loss"],
        credit_pct_of_width=idea["credit_pct_of_width"],
        short_delta=idea["short_delta"],
        pop_estimate=idea["pop_estimate"],
        breakevens=list(idea.get("breakevens") or []),
        net_greeks=dict(idea.get("net_greeks") or {}),
        legs=list(idea.get("legs") or []),
        researcher_score=idea["score"],
        researcher_score_breakdown=dict(idea.get("score_breakdown") or {}),
        context=context,
    )


async def generate_candidates(
    session: Session,
    contexts: Sequence[SymbolContext],
    *,
    researcher: Optional[OptionsResearcherAgent] = None,
    max_per_symbol: int = 3,
) -> tuple[list[Candidate], list[Rejection]]:
    """For each SymbolContext, call OptionsResearcherAgent.research; return candidates + rejections."""
    candidates: list[Candidate] = []
    rejections: list[Rejection] = []

    if not contexts:
        return (candidates, rejections)

    if researcher is None:
        researcher = OptionsResearcherAgent(session)

    for ctx in contexts:
        try:
            report = await researcher.research(ctx.symbol)
        except Exception as e:
            rejections.append(Rejection(symbol=ctx.symbol, reason="researcher_exception", detail=str(e)))
            continue

        status = report.get("status")
        if status != "OK":
            warnings = report.get("warnings") or []
            detail = warnings[0] if warnings else None
            rejections.append(Rejection(symbol=ctx.symbol, reason=str(status), detail=detail))
            continue

        ideas = report.get("trade_ideas") or []
        for idea in ideas[:max_per_symbol]:
            candidates.append(_idea_to_candidate(ctx.symbol, idea, ctx))

    return (candidates, rejections)


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
            ctx.iv_rank = (float(metric.implied_volatility_index_rank) * 100) if metric.implied_volatility_index_rank is not None else None
        except (ValueError, TypeError):
            ctx.iv_rank = None
        try:
            ctx.iv_percentile = (float(metric.implied_volatility_percentile) * 100) if metric.implied_volatility_percentile is not None else None
        except (ValueError, TypeError):
            ctx.iv_percentile = None
        try:
            ctx.current_iv = float(metric.implied_volatility_index) if metric.implied_volatility_index is not None else None
        except (ValueError, TypeError):
            ctx.current_iv = None
        try:
            ctx.beta = float(metric.beta) if metric.beta is not None else None
        except (ValueError, TypeError):
            ctx.beta = None
        try:
            ctx.liquidity_rank = float(metric.liquidity_rank) if metric.liquidity_rank is not None else None
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


def _check_earnings_blackout(candidate: Candidate, blackout_days: int, today: date) -> Optional[Rejection]:
    """Reject if next_earnings_date is within the blackout window relative to today."""
    earnings = candidate.context.next_earnings_date
    if earnings is None:
        return None
    delta_days = (earnings - today).days
    if delta_days <= blackout_days:
        return Rejection(
            symbol=candidate.symbol,
            reason="earnings_blackout",
            detail=f"earnings {earnings.isoformat()} within {blackout_days}d window",
        )
    return None


def _check_dte_bounds(candidate: Candidate, min_dte: int, max_dte: int) -> Optional[Rejection]:
    """Reject if candidate.dte falls outside [min_dte, max_dte]."""
    if candidate.dte < min_dte:
        return Rejection(
            symbol=candidate.symbol,
            reason="dte_out_of_range",
            detail=f"dte={candidate.dte} below min={min_dte}",
        )
    if candidate.dte > max_dte:
        return Rejection(
            symbol=candidate.symbol,
            reason="dte_out_of_range",
            detail=f"dte={candidate.dte} above max={max_dte}",
        )
    return None


def _check_broken_pricing(candidate: Candidate) -> Optional[Rejection]:
    """Reject if credit is non-positive or any SELL leg has missing/non-positive bid."""
    if candidate.credit <= 0:
        return Rejection(
            symbol=candidate.symbol,
            reason="broken_pricing",
            detail=f"credit={candidate.credit}",
        )
    for leg in candidate.legs:
        if leg.get("action") != "SELL":
            continue
        bid = leg.get("bid")
        if bid is None or bid <= 0:
            return Rejection(
                symbol=candidate.symbol,
                reason="broken_pricing",
                detail=f"sell-leg bid={bid if bid is not None else 0.0}",
            )
    return None


def _check_open_interest(candidate: Candidate, min_open_interest: int) -> Optional[Rejection]:
    """Reject if the minimum non-None open interest across legs falls below the floor."""
    ois = [leg.get("open_interest") for leg in candidate.legs if leg.get("open_interest") is not None]
    if not ois:
        return None
    min_oi = min(ois)
    if min_oi < min_open_interest:
        return Rejection(
            symbol=candidate.symbol,
            reason="low_open_interest",
            detail=f"min OI {min_oi} below floor {min_open_interest}",
        )
    return None


def _check_spread(candidate: Candidate, max_spread_pct: float) -> Optional[Rejection]:
    """Reject if the worst (ask-bid)/mid across legs with full pricing exceeds the cap."""
    ratios: list[float] = []
    for leg in candidate.legs:
        bid = leg.get("bid")
        ask = leg.get("ask")
        mid = leg.get("mid")
        if bid is None or ask is None or mid is None or mid <= 0:
            continue
        ratios.append((ask - bid) / mid)
    if not ratios:
        return None
    worst = max(ratios)
    if worst > max_spread_pct:
        return Rejection(
            symbol=candidate.symbol,
            reason="wide_spread",
            detail=f"max spread {worst:.3f} above cap {max_spread_pct:.3f}",
        )
    return None


def apply_quality_gates(
    candidates: list[Candidate],
    *,
    blackout_days: int,
    min_dte: int,
    max_dte: int,
    min_open_interest: int,
    max_spread_pct: float,
    today: Optional[date] = None,
) -> tuple[list[Candidate], list[Rejection]]:
    """Filter candidates through 5 hard gates; return (passing, rejections) preserving input order."""
    if today is None:
        today = date.today()
    passing: list[Candidate] = []
    rejections: list[Rejection] = []
    for c in candidates:
        rejection = (
            _check_earnings_blackout(c, blackout_days, today)
            or _check_dte_bounds(c, min_dte, max_dte)
            or _check_broken_pricing(c)
            or _check_open_interest(c, min_open_interest)
            or _check_spread(c, max_spread_pct)
        )
        if rejection is None:
            passing.append(c)
        else:
            rejections.append(rejection)
    return (passing, rejections)
