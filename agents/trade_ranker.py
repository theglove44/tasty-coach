"""Watchlist-wide trade ranking orchestrator.

Stub implementation for TCBT-2. Full pipeline is implemented across
TCBT-3..11; this module currently returns a canonical empty result so the
CLI and launcher entry points can be wired in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import Any, Optional, Sequence

from tastytrade import Session
from tastytrade.metrics import get_market_metrics
from tastytrade.market_data import get_market_data_by_type

from agents.manager import RiskManager
from agents.options_researcher import OptionsResearcherAgent
from agents.portfolio import PortfolioAgent
from agents.scanner import ScannerAgent
from utils.settings import settings


DEFAULT_WATCHLISTS: tuple[str, ...] = (
    "Chris Historical Trades",
    "High Options Volume",
)

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
    score: float = 0.0
    score_breakdown: dict[str, float] = field(default_factory=dict)
    summary_reason: str = ""


@dataclass
class Rejection:
    """A symbol or candidate that was filtered out before scoring."""
    symbol: str
    reason: str
    detail: Optional[str] = None


@dataclass(frozen=True)
class AccountState:
    """Snapshot of live account state used by the account-aware ranking layer.

    Built once per `run_best_trades` invocation and passed into
    `apply_account_filters` and `score_candidate(s)`. Floats (not Decimals)
    so scoring math stays uniform with the rest of `trade_ranker`.
    """
    nlv: float
    bp_usage_pct: float
    existing_exposures: dict[str, float] = field(default_factory=dict)


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


def _load_thresholds() -> dict[str, Any]:
    """Read all 9 best-trades threshold settings into a single dict."""
    return {
        "blackout_days": settings.get("bt_earnings_blackout_days"),
        "min_dte": settings.get("bt_min_dte"),
        "max_dte": settings.get("bt_max_dte"),
        "min_open_interest": settings.get("bt_min_open_interest"),
        "max_spread_pct": settings.get("bt_max_spread_pct"),
        "max_per_symbol": settings.get("bt_max_per_symbol"),
        "max_pct_nlv_per_trade": settings.get("bt_max_pct_nlv_per_trade"),
        "bp_cap_for_new": settings.get("bt_bp_cap_for_new"),
        "concentration_block_pct": settings.get("bt_concentration_overlap_block_pct"),
    }


def _select_top_per_symbol(candidates: list[Candidate], top: int) -> list[Candidate]:
    """Best score per symbol, sorted by (score desc, symbol asc), capped at `top`."""
    if not candidates or top <= 0:
        return []
    best_per_symbol: dict[str, Candidate] = {}
    for c in candidates:
        existing = best_per_symbol.get(c.symbol)
        if existing is None or c.score > existing.score:
            best_per_symbol[c.symbol] = c
    ranked = sorted(
        best_per_symbol.values(),
        key=lambda c: (-c.score, c.symbol),
    )
    return ranked[:top]


def _rejection_to_dict(r: Rejection) -> dict[str, Any]:
    """Serialize a Rejection to a JSON-safe dict."""
    return {
        "symbol": r.symbol,
        "reason": r.reason,
        "detail": r.detail,
    }


def _candidate_to_dict(c: Candidate) -> dict[str, Any]:
    """Serialize a Candidate to a JSON-safe dict for the top-trades output."""
    return {
        "symbol": c.symbol,
        "structure": c.structure,
        "expiration": c.expiration.isoformat() if hasattr(c.expiration, "isoformat") else str(c.expiration),
        "dte": c.dte,
        "credit": float(c.credit),
        "max_loss": float(c.max_loss),
        "short_delta": float(c.short_delta),
        "breakevens": [float(b) for b in c.breakevens],
        "score": float(c.score),
        "score_breakdown": dict(c.score_breakdown) if c.score_breakdown else {},
        "summary_reason": c.summary_reason or "",
    }


async def _build_account_state(session: Session, account_number: str) -> AccountState:
    """Build AccountState from RiskManager + PortfolioAgent (existing_exposures={} for v1)."""
    risk_manager = RiskManager(session, account_number)
    report = await risk_manager.calculate_portfolio_risk()
    nlv = float(report["nlv"])
    bp_usage_pct = float(report["bp_usage_pct"]) / 100.0
    portfolio_agent = await PortfolioAgent(session, account_number).init()
    _positions = await portfolio_agent.get_positions()
    return AccountState(
        nlv=nlv,
        bp_usage_pct=bp_usage_pct,
        existing_exposures={},
    )


async def run_best_trades(
    session: Session,
    *,
    watchlists: Optional[Sequence[str]] = None,
    top: int = 3,
    output_format: str = "text",
    account_number: Optional[str] = None,
    today: Optional[date] = None,
) -> dict[str, Any]:
    """Run the full Best-Trades pipeline and return a canonical result dict."""
    resolved_watchlists = list(watchlists) if watchlists is not None else list(DEFAULT_WATCHLISTS)
    result: dict[str, Any] = {
        "top": [],
        "rejected": [],
        "warnings": [],
        "watchlists": resolved_watchlists,
        "account": None,
    }

    contexts, scan_warnings = await scan_watchlists(session, resolved_watchlists)
    result["warnings"].extend(scan_warnings)
    if not contexts:
        return result

    thresholds = _load_thresholds()

    candidates, gen_rejections = await generate_candidates(
        session,
        contexts,
        max_per_symbol=thresholds["max_per_symbol"],
    )
    for r in gen_rejections:
        result["rejected"].append(_rejection_to_dict(r))

    if not candidates:
        return result

    passing, gate_rejections = apply_quality_gates(
        candidates,
        blackout_days=thresholds["blackout_days"],
        min_dte=thresholds["min_dte"],
        max_dte=thresholds["max_dte"],
        min_open_interest=thresholds["min_open_interest"],
        max_spread_pct=thresholds["max_spread_pct"],
        today=today,
    )
    for r in gate_rejections:
        result["rejected"].append(_rejection_to_dict(r))

    if not passing:
        return result

    account_state: Optional[AccountState] = None
    if account_number is not None:
        try:
            account_state = await _build_account_state(session, account_number)
            result["account"] = {
                "nlv": account_state.nlv,
                "bp_usage_pct": account_state.bp_usage_pct,
            }
        except Exception as e:
            result["warnings"].append(f"account state unavailable: {e}")
            account_state = None

    if account_state is not None:
        passing, account_rejections = apply_account_filters(
            passing,
            account_state,
            max_pct_nlv_per_trade=thresholds["max_pct_nlv_per_trade"],
            bp_cap_for_new=thresholds["bp_cap_for_new"],
            concentration_block_pct=thresholds["concentration_block_pct"],
        )
        for r in account_rejections:
            result["rejected"].append(_rejection_to_dict(r))

        if not passing:
            return result

    scored = score_candidates(passing, today=today, account_state=account_state)
    selected = _select_top_per_symbol(scored, top)
    result["top"] = [_candidate_to_dict(c) for c in selected]
    return result


def _print_best_trades_text(result: dict[str, Any], top: int) -> None:
    """Print a best-trades result dict in human-readable text form."""
    watchlists = result.get("watchlists") or []
    print(f"=== Best Trades Today (top {top}) ===")
    if watchlists:
        print(f"Watchlists: {', '.join(watchlists)}")

    account = result.get("account")
    if account is not None:
        nlv = account.get("nlv", 0.0)
        bp = account.get("bp_usage_pct", 0.0)
        print(f"Account: NLV ${nlv:,.0f}, BP usage {bp * 100:.1f}%")

    top_items = result.get("top") or []
    print()
    if not top_items:
        print("No trades passed all gates today.")
    else:
        for idx, item in enumerate(top_items, start=1):
            symbol = item.get("symbol", "?")
            structure = item.get("structure", "?")
            expiration = item.get("expiration", "?")
            dte = item.get("dte", 0)
            credit = item.get("credit", 0.0)
            max_loss = item.get("max_loss", 0.0)
            score = item.get("score", 0.0)
            summary = item.get("summary_reason", "")
            breakdown = item.get("score_breakdown") or {}
            print(f"[{idx}] {symbol} {structure} {expiration} ({dte} DTE)")
            print(f"    Credit ${credit:.2f} / Max risk ${max_loss:.0f}")
            print(f"    Score: {score:.1f}/100 — {summary}")
            if breakdown:
                parts = [f"{k} {float(v):.1f}" for k, v in breakdown.items()]
                print(f"    Breakdown: {', '.join(parts)}")

    rejected = result.get("rejected") or []
    if rejected:
        counts: dict[str, int] = {}
        for r in rejected:
            reason = r.get("reason", "unknown")
            counts[reason] = counts.get(reason, 0) + 1
        print()
        print("Rejection summary:")
        for reason, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  {reason}: {n}")

    warnings = result.get("warnings") or []
    if warnings:
        print()
        print("Warnings:")
        for w in warnings:
            print(f"  - {w}")


def _check_earnings_blackout(candidate: Candidate, blackout_days: int, today: date) -> Optional[Rejection]:
    """Reject if next_earnings_date is within the blackout window relative to today."""
    earnings = candidate.context.next_earnings_date
    if earnings is None:
        return None
    delta_days = (earnings - today).days
    if 0 <= delta_days <= blackout_days:
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


def apply_account_filters(
    candidates: list[Candidate],
    account_state: AccountState,
    *,
    max_pct_nlv_per_trade: float,
    bp_cap_for_new: float,
    concentration_block_pct: float,
) -> tuple[list[Candidate], list[Rejection]]:
    """Hard-reject candidates that worsen account state beyond configured caps."""
    survivors: list[Candidate] = []
    rejections: list[Rejection] = []

    nlv = account_state.nlv
    bp_usage = account_state.bp_usage_pct
    exposures = account_state.existing_exposures

    if nlv <= 0:
        for c in candidates:
            rejections.append(Rejection(
                symbol=c.symbol,
                reason="non_positive_nlv",
                detail=f"NLV ${nlv:.0f} is non-positive; cannot evaluate account fit",
            ))
        return survivors, rejections

    for c in candidates:
        size_pct = c.max_loss / nlv

        if size_pct > max_pct_nlv_per_trade:
            rejections.append(Rejection(
                symbol=c.symbol,
                reason="oversized_vs_nlv",
                detail=(
                    f"max_loss ${c.max_loss:.0f} = "
                    f"{size_pct * 100:.1f}% NLV above cap "
                    f"{max_pct_nlv_per_trade * 100:.1f}%"
                ),
            ))
            continue

        post_bp = bp_usage + size_pct
        if post_bp > bp_cap_for_new:
            rejections.append(Rejection(
                symbol=c.symbol,
                reason="bp_over_cap",
                detail=(
                    f"post-trade BP {post_bp * 100:.1f}% above cap "
                    f"{bp_cap_for_new * 100:.1f}%"
                ),
            ))
            continue

        existing = exposures.get(c.symbol, 0.0)
        post_exposure_pct = (existing + c.max_loss) / nlv
        if post_exposure_pct > concentration_block_pct:
            rejections.append(Rejection(
                symbol=c.symbol,
                reason="concentration_overlap",
                detail=(
                    f"{c.symbol} exposure ${existing:.0f} + ${c.max_loss:.0f} = "
                    f"{post_exposure_pct * 100:.1f}% NLV above cap "
                    f"{concentration_block_pct * 100:.1f}%"
                ),
            ))
            continue

        survivors.append(c)

    return survivors, rejections


_WEIGHT_REGIME_FIT: float = 15.0
_WEIGHT_LIQUIDITY: float = 20.0
_WEIGHT_VOLATILITY_EDGE: float = 25.0
_WEIGHT_EVENT_RISK: float = 10.0
_WEIGHT_STRUCTURE_QUALITY: float = 20.0
_WEIGHT_ACCOUNT_FIT: float = 10.0


def _score_regime_fit(candidate: Candidate) -> float:
    """Map IVR (0-100) linearly to [0, 15]; neutral 7.5 when iv_rank is None."""
    ivr = candidate.context.iv_rank
    if ivr is None:
        return 7.5
    factor = max(0.0, min(1.0, ivr / 100.0))
    return factor * _WEIGHT_REGIME_FIT


def _score_liquidity(candidate: Candidate) -> float:
    """Blend min-OI factor (full at 1000+) and worst-spread factor (zero at 10%) into [0, 20]."""
    legs = candidate.legs
    if not legs:
        return 0.0

    ois = [leg.get("open_interest") for leg in legs if leg.get("open_interest") is not None]
    min_oi = min(ois) if ois else 0
    oi_factor = min(1.0, min_oi / 1000.0)

    ratios: list[float] = []
    for leg in legs:
        bid = leg.get("bid")
        ask = leg.get("ask")
        mid = leg.get("mid")
        if bid is None or ask is None or mid is None or mid <= 0:
            continue
        ratios.append((ask - bid) / mid)
    if ratios:
        worst_spread = max(ratios)
        spread_factor = max(0.0, min(1.0, 1.0 - (worst_spread / 0.10)))
    else:
        spread_factor = 0.0

    return _WEIGHT_LIQUIDITY * (0.5 * oi_factor + 0.5 * spread_factor)


def _score_volatility_edge(candidate: Candidate) -> float:
    """Blend IVR factor (60%) and credit/width factor (40%) into [0, 25]."""
    ivr = candidate.context.iv_rank
    ivr_factor = max(0.0, min(1.0, (ivr or 0.0) / 100.0))
    credit_factor = max(
        0.0,
        min(1.0, (candidate.credit_pct_of_width - 0.20) / 0.30),
    )
    return _WEIGHT_VOLATILITY_EDGE * (0.6 * ivr_factor + 0.4 * credit_factor)


def _score_event_risk(candidate: Candidate, today: date) -> float:
    """Linear ramp 7d→21d to earnings; full 10 when no earnings or earnings past/>=21d away."""
    earnings = candidate.context.next_earnings_date
    if earnings is None:
        return _WEIGHT_EVENT_RISK
    delta_days = (earnings - today).days
    if delta_days < 0:
        return _WEIGHT_EVENT_RISK
    if delta_days >= 21:
        return _WEIGHT_EVENT_RISK
    if delta_days <= 7:
        return 0.0
    return ((delta_days - 7) / 14.0) * _WEIGHT_EVENT_RISK


def _score_structure_quality(candidate: Candidate) -> float:
    """Blend delta-band fit (peak at 0.25 magnitude) and credit/width (full at 40%+) into [0, 20]."""
    delta_factor = max(0.0, 1.0 - abs(abs(candidate.short_delta) - 0.25) / 0.20)
    credit_width_factor = max(0.0, min(1.0, candidate.credit_pct_of_width / 0.40))
    return _WEIGHT_STRUCTURE_QUALITY * (0.5 * delta_factor + 0.5 * credit_width_factor)


def _score_account_fit(
    candidate: Candidate,
    account_state: Optional[AccountState] = None,
) -> float:
    """Score 0..10 for trade-size fit; placeholder 10.0 when account_state is None or NLV non-positive."""
    if account_state is None or account_state.nlv <= 0:
        return _WEIGHT_ACCOUNT_FIT
    pct = candidate.max_loss / account_state.nlv
    return max(0.0, min(10.0, 10.0 * (0.05 - pct) / 0.03))


def _score_concentration_penalty(
    candidate: Candidate,
    account_state: Optional[AccountState] = None,
) -> float:
    """Subtractive penalty 0..10 for concentration; placeholder 0.0 when account_state is None or NLV non-positive."""
    if account_state is None or account_state.nlv <= 0:
        return 0.0
    existing = account_state.existing_exposures.get(candidate.symbol, 0.0)
    post_trade_pct = (existing + candidate.max_loss) / account_state.nlv
    return max(0.0, min(10.0, 10.0 * (post_trade_pct - 0.05) / 0.20))


def _format_summary_reason(
    candidate: Candidate,
    breakdown: dict[str, float],
    today: date,
) -> str:
    """Build a one-line plain-English string of the 2-4 strongest positive factors."""
    phrases: list[str] = []

    ivr = candidate.context.iv_rank
    if breakdown["regime_fit"] / _WEIGHT_REGIME_FIT >= 0.6 and ivr is not None:
        phrases.append(f"IVR {round(ivr)}")

    legs = candidate.legs
    ois = [leg.get("open_interest") for leg in legs if leg.get("open_interest") is not None]
    min_oi = min(ois) if ois else 0
    oi_factor = min(1.0, min_oi / 1000.0)
    ratios: list[float] = []
    for leg in legs:
        bid = leg.get("bid")
        ask = leg.get("ask")
        mid = leg.get("mid")
        if bid is None or ask is None or mid is None or mid <= 0:
            continue
        ratios.append((ask - bid) / mid)
    if ratios:
        worst_spread = max(ratios)
        spread_factor = max(0.0, min(1.0, 1.0 - (worst_spread / 0.10)))
    else:
        spread_factor = 0.0
    if breakdown["liquidity"] / _WEIGHT_LIQUIDITY >= 0.6:
        if spread_factor > oi_factor:
            phrases.append("tight spreads")
        else:
            phrases.append("deep liquidity")

    if breakdown["volatility_edge"] / _WEIGHT_VOLATILITY_EDGE >= 0.6:
        phrases.append(f"credit {round(candidate.credit_pct_of_width * 100)}% of width")

    earnings = candidate.context.next_earnings_date
    if breakdown["event_risk"] >= _WEIGHT_EVENT_RISK:
        if earnings is None:
            phrases.append("no earnings")
        else:
            delta_days = (earnings - today).days
            if delta_days >= 21 or delta_days < 0:
                phrases.append("clean event window")

    if breakdown["structure_quality"] / _WEIGHT_STRUCTURE_QUALITY >= 0.6:
        phrases.append(f"delta {candidate.short_delta:.2f}")

    if not phrases:
        return "weak across all factors"

    return ", ".join(phrases[:4])


def score_candidate(
    candidate: Candidate,
    *,
    today: Optional[date] = None,
    account_state: Optional[AccountState] = None,
) -> Candidate:
    """Return a new Candidate with score, score_breakdown, and summary_reason populated."""
    if today is None:
        today = date.today()

    regime = _score_regime_fit(candidate)
    liquidity = _score_liquidity(candidate)
    vol_edge = _score_volatility_edge(candidate)
    event = _score_event_risk(candidate, today)
    structure = _score_structure_quality(candidate)
    account = _score_account_fit(candidate, account_state)
    penalty = _score_concentration_penalty(candidate, account_state)

    breakdown: dict[str, float] = {
        "regime_fit": regime,
        "liquidity": liquidity,
        "volatility_edge": vol_edge,
        "event_risk": event,
        "structure_quality": structure,
        "account_fit": account,
        "concentration_penalty": penalty,
    }

    total = regime + liquidity + vol_edge + event + structure + account - penalty
    score = max(0.0, min(100.0, total))

    summary = _format_summary_reason(candidate, breakdown, today)

    return replace(
        candidate,
        score=score,
        score_breakdown=breakdown,
        summary_reason=summary,
    )


def score_candidates(
    candidates: list[Candidate],
    *,
    today: Optional[date] = None,
    account_state: Optional[AccountState] = None,
) -> list[Candidate]:
    """Score each candidate; preserve input order; pure (returns new list of new Candidates)."""
    if today is None:
        today = date.today()
    return [score_candidate(c, today=today, account_state=account_state) for c in candidates]
