"""Watchlist-wide trade ranking orchestrator."""

from __future__ import annotations

import asyncio
import logging
import re
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
from utils.sector_map import get_sector
from utils.settings import settings

logger = logging.getLogger(__name__)


DEFAULT_WATCHLISTS: tuple[str, ...] = (
    "Chris Historical Trades",
    "High Options Volume",
)

_BATCH_SIZE: int = 50

# Equity options carry $100 of underlying per contract.
# Researcher stores credit/max_loss in spread points; multiply by this to get
# actual dollar risk/credit per contract.
CONTRACT_MULTIPLIER: float = 100.0


def _dollar_max_loss(c: "Candidate") -> float:
    """Return actual dollar max loss per contract (Candidate.max_loss is in spread points)."""
    return float(c.max_loss) * CONTRACT_MULTIPLIER


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
    # Put/call IV ratio at ~25Δ; populated post-research, drives the
    # "elevated downside fear" warning surfaced by the put-selector.
    put_call_skew: Optional[float] = None


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
    occupied_sectors: frozenset[str] = field(default_factory=frozenset)


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
    concurrency: int = 1,
    timeout_seconds: Optional[float] = None,
    structure_filter: Optional[str] = None,
) -> tuple[list[Candidate], list[Rejection]]:
    """For each SymbolContext, call OptionsResearcherAgent.research; return candidates + rejections.

    `concurrency` caps simultaneous research calls (default 1 = sequential).
    `timeout_seconds` applies a per-symbol hard cap; on timeout the symbol becomes a
    research_timeout rejection instead of blocking the run.
    `structure_filter` (e.g. "CASH_SECURED_PUT") restricts emitted candidates to
    one structure type; ``None`` admits all structures the researcher emits.
    """
    candidates: list[Candidate] = []
    rejections: list[Rejection] = []

    if not contexts:
        return (candidates, rejections)

    if researcher is None:
        researcher = OptionsResearcherAgent(session)

    total = len(contexts)
    logger.info(
        "researching %d symbols (concurrency=%d, timeout=%s)",
        total,
        concurrency,
        f"{timeout_seconds}s" if timeout_seconds is not None else "none",
    )
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def research_one(idx: int, ctx: SymbolContext):
        async with semaphore:
            logger.info("[%d/%d] %s", idx, total, ctx.symbol)
            underlying_price = (
                float(ctx.current_price) if ctx.current_price is not None else None
            )
            # CSP screening requires a spot reference; without it the
            # researcher can't compute pct_otm and emits no CSP ideas. If the
            # caller is filtering for CSPs, surface this as a rejection rather
            # than letting the symbol disappear silently.
            if structure_filter == "CASH_SECURED_PUT" and underlying_price is None:
                return ctx, None, Rejection(
                    symbol=ctx.symbol,
                    reason="no_spot_for_csp",
                    detail="underlying spot unavailable; cannot compute pct_otm",
                )
            try:
                if timeout_seconds is not None:
                    report = await asyncio.wait_for(
                        researcher.research(ctx.symbol, underlying_price=underlying_price),
                        timeout=timeout_seconds,
                    )
                else:
                    report = await researcher.research(ctx.symbol, underlying_price=underlying_price)
            except asyncio.TimeoutError:
                logger.warning("[%d/%d] %s: timed out after %ss", idx, total, ctx.symbol, timeout_seconds)
                return ctx, None, Rejection(
                    symbol=ctx.symbol,
                    reason="research_timeout",
                    detail=f"exceeded {timeout_seconds}s",
                )
            except Exception as e:
                logger.warning("[%d/%d] %s: research failed - %s", idx, total, ctx.symbol, e)
                return ctx, None, Rejection(
                    symbol=ctx.symbol,
                    reason="researcher_exception",
                    detail=str(e),
                )
            return ctx, report, None

    tasks = [research_one(i + 1, ctx) for i, ctx in enumerate(contexts)]
    results = await asyncio.gather(*tasks)

    for ctx, report, rejection in results:
        if rejection is not None:
            rejections.append(rejection)
            continue
        status = report.get("status")
        if status != "OK":
            warnings = report.get("warnings") or []
            detail = warnings[0] if warnings else None
            logger.info("%s: %s", ctx.symbol, status)
            rejections.append(Rejection(symbol=ctx.symbol, reason=str(status), detail=detail))
            continue
        # Attach skew to context so the printer / scoring can reach it.
        ctx.put_call_skew = report.get("put_call_skew")
        ideas = report.get("trade_ideas") or []
        if structure_filter is not None:
            ideas = [i for i in ideas if i.get("strategy") == structure_filter]
        accepted = ideas[:max_per_symbol]
        logger.info("%s: %d ideas", ctx.symbol, len(accepted))
        for idea in accepted:
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
        try:
            wl_symbols = await scanner.get_symbols_from_watchlist(name, equity_only=True)
        except Exception as e:
            warnings.append(f"watchlist '{name}' fetch failed: {e}")
            continue
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
    """Read all best-trades threshold settings into a single dict."""
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
        "min_ivr": settings.get("bt_min_ivr"),
        "research_concurrency": settings.get("bt_research_concurrency"),
        "research_timeout_seconds": settings.get("bt_research_timeout_seconds"),
        "per_trade_risk_pct": settings.get("bt_per_trade_risk_pct"),
        "per_trade_risk_dollars": settings.get("bt_per_trade_risk_dollars"),
        "csp_min_otm_pct": settings.get("bt_csp_min_otm_pct"),
        "csp_min_annualized_return": settings.get("bt_csp_min_annualized_return"),
        "csp_skew_warn_threshold": settings.get("bt_csp_skew_warn_threshold"),
        "csp_max_pct_nlv_per_trade": settings.get("bt_csp_max_pct_nlv_per_trade"),
    }


def filter_by_ivr(
    contexts: list[SymbolContext],
    min_ivr: float,
) -> tuple[list[SymbolContext], list[str]]:
    """Drop SymbolContexts whose iv_rank is None or below the threshold; return (passing, warnings)."""
    passing: list[SymbolContext] = []
    skipped_below = 0
    skipped_no_data = 0
    for ctx in contexts:
        if ctx.iv_rank is None:
            skipped_no_data += 1
            continue
        if ctx.iv_rank < min_ivr:
            skipped_below += 1
            continue
        passing.append(ctx)
    warnings: list[str] = []
    if skipped_below:
        warnings.append(f"skipped {skipped_below} symbols below IVR {min_ivr:.0f}")
    if skipped_no_data:
        warnings.append(f"skipped {skipped_no_data} symbols with no IVR data")
    return passing, warnings


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


def _candidate_to_dict(
    c: Candidate,
    account_state: Optional[AccountState] = None,
    per_trade_risk_pct: Optional[float] = None,
    per_trade_risk_dollars: Optional[float] = None,
) -> dict[str, Any]:
    """Serialize a Candidate to a JSON-safe dict for the top-trades output.

    When ``account_state`` is provided plus either ``per_trade_risk_dollars``
    (fixed-dollar budget, takes precedence) or ``per_trade_risk_pct`` (NLV
    fraction), emits ``recommended_contracts``, ``pct_nlv_at_risk``, and
    ``sector`` so the AI coach and text printer can show personalized sizing.
    """
    payload: dict[str, Any] = {
        "symbol": c.symbol,
        "structure": c.structure,
        "expiration": c.expiration.isoformat() if hasattr(c.expiration, "isoformat") else str(c.expiration),
        "dte": c.dte,
        "credit": float(c.credit),
        "max_loss": float(c.max_loss),
        "short_delta": float(c.short_delta),
        "pop_estimate": float(c.pop_estimate),
        "breakevens": [float(b) for b in c.breakevens],
        "score": float(c.score),
        "score_breakdown": dict(c.score_breakdown) if c.score_breakdown else {},
        "summary_reason": c.summary_reason or "",
        "legs": [dict(leg) for leg in (c.legs or [])],
        "sector": get_sector(c.symbol),
    }

    # CSP-specific metrics (article's "balanced" dimensions made visible).
    if c.structure == "CASH_SECURED_PUT":
        strike = _csp_short_strike(c)
        if strike > 0:
            payload["cash_required"] = strike * 100.0
            if c.dte > 0:
                payload["annualized_return"] = (c.credit * 365.0 / c.dte) / strike
                payload["premium_per_day"] = c.credit / c.dte
            spot = c.context.current_price
            if spot is not None and float(spot) > 0:
                payload["pct_otm"] = (float(spot) - strike) / float(spot)
                payload["spot_price"] = float(spot)
        skew = c.context.put_call_skew
        if skew is not None:
            payload["put_call_skew"] = float(skew)

    if account_state and account_state.nlv > 0 and c.max_loss > 0:
        dollar_risk = _dollar_max_loss(c)
        payload["max_loss_dollars"] = dollar_risk
        payload["pct_nlv_at_risk_one_contract"] = dollar_risk / account_state.nlv
        # Fixed-dollar budget takes precedence over the percentage-of-NLV
        # budget. The dollar form is more intuitive at small accounts where
        # "I want to risk $250" is sharper than "5% of NLV".
        budget: Optional[float] = None
        budget_basis: Optional[str] = None
        if per_trade_risk_dollars is not None and per_trade_risk_dollars > 0:
            budget = float(per_trade_risk_dollars)
            budget_basis = "dollars"
        elif per_trade_risk_pct and per_trade_risk_pct > 0:
            budget = account_state.nlv * per_trade_risk_pct
            budget_basis = "pct_nlv"
        if budget is not None:
            recommended = int(budget // dollar_risk)
            # If a single contract already exceeds the budget, recommend 0 (skip).
            payload["recommended_contracts"] = recommended
            payload["pct_nlv_at_risk"] = (
                recommended * dollar_risk / account_state.nlv
            )
            payload["risk_budget_dollars"] = budget
            payload["risk_budget_basis"] = budget_basis

    return payload


def _format_legs_from_dicts(legs: list[dict[str, Any]]) -> str:
    """Compact per-leg summary for text output: 'SELL PUT 105 Δ-0.30 / BUY PUT 100 Δ-0.18'."""
    parts: list[str] = []
    for leg in legs or []:
        action = leg.get("action") or leg.get("side") or "?"
        opt_type = leg.get("option_type") or leg.get("type") or "?"
        strike = leg.get("strike")
        delta = leg.get("delta")
        strike_s = f"{float(strike):g}" if strike is not None else "?"
        delta_s = f"Δ{float(delta):+.2f}" if delta is not None else "Δ?"
        parts.append(f"{action} {opt_type} {strike_s} {delta_s}")
    return " / ".join(parts)


def _position_dollar_exposure(pos: Any) -> float:
    """Conservative per-position dollar exposure for concentration accounting.

    - Short option: strike * 100 * |quantity| (cash-secured worst-case for puts; OK proxy for short calls).
    - Long option: 0 (premium is sunk cost; no further compounding risk on new picks).
    - Equity: |quantity| * average_open_price (cost basis).
    """
    inst = getattr(pos, "instrument_type", None)
    inst_str = getattr(inst, "value", str(inst)) if inst is not None else ""
    qty = getattr(pos, "quantity", 0) or 0
    try:
        qty_f = float(qty)
    except (TypeError, ValueError):
        qty_f = 0.0
    qty_f = abs(qty_f)

    if inst_str == "Equity":
        avg = getattr(pos, "average_open_price", 0) or 0
        try:
            return qty_f * float(avg)
        except (TypeError, ValueError):
            return 0.0

    if inst_str != "Equity Option":
        return 0.0

    direction = getattr(getattr(pos, "quantity_direction", None), "value", None) or getattr(pos, "quantity_direction", None)
    if direction != "Short":
        return 0.0

    sym = getattr(pos, "symbol", "") or ""
    m = re.match(r"^[A-Z/]+\s+\d{6}[CP](\d{8})$", sym)
    if not m:
        return 0.0
    strike = float(m.group(1)) / 1000.0
    return strike * 100.0 * qty_f


async def _build_account_state(session: Session, account_number: str) -> AccountState:
    """Build AccountState with real per-underlying exposures and occupied sectors."""
    risk_manager = RiskManager(session, account_number)
    report = await risk_manager.calculate_portfolio_risk()
    nlv = float(report["nlv"])
    bp_usage_pct = float(report["bp_usage_pct"]) / 100.0

    portfolio_agent = await PortfolioAgent(session, account_number).init()
    positions = await portfolio_agent.get_positions()

    # Only positions with non-zero dollar exposure (short options + equity) populate
    # exposures and occupied_sectors. A long-only position contributes 0 dollars and
    # would silently both (a) pollute the concentration check by creating an
    # exposures key that bypasses the sector gate's "rolling/adding" exception, and
    # (b) over-broadly mark the sector as occupied — see review notes on
    # TCBT-account-sizing.
    exposures: dict[str, float] = {}
    sectors: set[str] = set()
    for pos in positions:
        underlying = getattr(pos, "underlying_symbol", None) or getattr(pos, "symbol", None)
        if not underlying:
            continue
        dollars = _position_dollar_exposure(pos)
        if dollars <= 0:
            continue
        underlying = str(underlying).upper()
        exposures[underlying] = exposures.get(underlying, 0.0) + dollars
        sec = get_sector(underlying)
        if sec:
            sectors.add(sec)

    return AccountState(
        nlv=nlv,
        bp_usage_pct=bp_usage_pct,
        existing_exposures=exposures,
        occupied_sectors=frozenset(sectors),
    )


async def run_best_trades(
    session: Session,
    *,
    watchlists: Optional[Sequence[str]] = None,
    top: int = 3,
    output_format: str = "text",
    account_number: Optional[str] = None,
    today: Optional[date] = None,
    structure_filter: Optional[str] = None,
) -> dict[str, Any]:
    """Run the full Best-Trades pipeline and return a canonical result dict.

    ``structure_filter`` (e.g. "CASH_SECURED_PUT") restricts emitted candidates
    to one structure type. None admits all structures.
    """
    resolved_watchlists = list(watchlists) if watchlists is not None else list(DEFAULT_WATCHLISTS)
    result: dict[str, Any] = {
        "top": [],
        "rejected": [],
        "warnings": [],
        "watchlists": resolved_watchlists,
        "account": None,
    }

    logger.info("scanning watchlists: %s", resolved_watchlists)
    try:
        contexts, scan_warnings = await scan_watchlists(session, resolved_watchlists)
    except Exception as e:
        logger.warning("watchlist scan failed: %s", e)
        result["warnings"].append(f"watchlist scan failed: {e}")
        return result
    result["warnings"].extend(scan_warnings)
    logger.info("scan complete: %d symbols, %d warnings", len(contexts), len(scan_warnings))
    if not contexts:
        return result

    thresholds = _load_thresholds()

    contexts, ivr_warnings = filter_by_ivr(contexts, thresholds["min_ivr"])
    result["warnings"].extend(ivr_warnings)
    logger.info("after IVR>=%.0f prefilter: %d symbols remain", thresholds["min_ivr"], len(contexts))
    if not contexts:
        return result

    candidates, gen_rejections = await generate_candidates(
        session,
        contexts,
        max_per_symbol=thresholds["max_per_symbol"],
        concurrency=thresholds["research_concurrency"],
        timeout_seconds=thresholds["research_timeout_seconds"],
        structure_filter=structure_filter,
    )
    for r in gen_rejections:
        result["rejected"].append(_rejection_to_dict(r))

    if not candidates:
        return result

    logger.info("generated %d candidates from %d symbols", len(candidates), len(contexts))

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
    logger.info("after quality gates: %d passing, %d rejected", len(passing), len(gate_rejections))

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
            csp_max_pct_nlv_per_trade=thresholds.get("csp_max_pct_nlv_per_trade"),
        )
        for r in account_rejections:
            result["rejected"].append(_rejection_to_dict(r))
        logger.info("after account filters: %d passing, %d rejected", len(passing), len(account_rejections))

        if not passing:
            return result

    scored = score_candidates(
        passing,
        today=today,
        account_state=account_state,
        csp_min_otm_pct=thresholds.get("csp_min_otm_pct"),
        csp_min_annualized_return=thresholds.get("csp_min_annualized_return"),
    )
    selected = _select_top_per_symbol(scored, top)
    result["top"] = [
        _candidate_to_dict(
            c,
            account_state=account_state,
            per_trade_risk_pct=thresholds.get("per_trade_risk_pct"),
            per_trade_risk_dollars=thresholds.get("per_trade_risk_dollars"),
        )
        for c in selected
    ]
    result["csp_skew_warn_threshold"] = thresholds.get("csp_skew_warn_threshold")
    logger.info("done: %d top trades selected from %d scored candidates", len(result["top"]), len(scored))
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
        skew_warn_threshold = result.get("csp_skew_warn_threshold", 1.20)
        for idx, item in enumerate(top_items, start=1):
            symbol = item.get("symbol", "?")
            structure = item.get("structure", "?")
            expiration = item.get("expiration", "?")
            dte = item.get("dte", 0)
            credit = item.get("credit", 0.0)
            max_loss_pts = item.get("max_loss", 0.0)
            max_loss_dollars = item.get("max_loss_dollars", max_loss_pts * 100.0)
            score = item.get("score", 0.0)
            summary = item.get("summary_reason", "")
            breakdown = item.get("score_breakdown") or {}
            jid = item.get("_journal_id")
            jid_tag = f"  [journal #{jid}]" if jid else ""

            print(f"[{idx}] {symbol} {structure} {expiration} ({dte} DTE){jid_tag}")
            # Skew warning printed under the symbol line for CSPs so the
            # association is unambiguous when scrolling.
            skew = item.get("put_call_skew")
            if structure == "CASH_SECURED_PUT" and skew is not None and skew >= skew_warn_threshold:
                print(f"    ⚠ put/call skew {skew:.2f} — elevated downside fear; consider smaller size or vertical")
            legs_line = _format_legs_from_dicts(item.get("legs") or [])
            if legs_line:
                print(f"    Legs: {legs_line}")

            if structure == "CASH_SECURED_PUT":
                cash_required = item.get("cash_required")
                annualized = item.get("annualized_return")
                premium_per_day = item.get("premium_per_day")
                pct_otm = item.get("pct_otm")
                pop = item.get("pop_estimate")
                ann_str = f" / Annualized {annualized * 100:.1f}%" if annualized is not None else ""
                cash_str = f" / Cash required ${cash_required:,.0f}" if cash_required is not None else ""
                print(f"    Credit ${credit * 100:.0f}{cash_str}{ann_str}")
                buf = f"Buffer {pct_otm * 100:.1f}% OTM" if pct_otm is not None else ""
                pop_str = f"POP {pop * 100:.0f}%" if pop is not None else ""
                ppd = f"Premium/day ${premium_per_day * 100:.2f}" if premium_per_day is not None else ""
                line2 = " · ".join([s for s in (buf, pop_str, ppd) if s])
                if line2:
                    print(f"    {line2}")
            else:
                print(f"    Credit ${credit * 100:.0f} / Max risk ${max_loss_dollars:.0f} per contract")

            recommended = item.get("recommended_contracts")
            pct_at_risk = item.get("pct_nlv_at_risk")
            budget_dollars = item.get("risk_budget_dollars")
            budget_basis = item.get("risk_budget_basis")
            budget_tag = ""
            if budget_dollars is not None and budget_basis == "dollars":
                budget_tag = f" [budget ${budget_dollars:.0f}]"
            elif budget_dollars is not None and budget_basis == "pct_nlv":
                budget_tag = f" [budget ${budget_dollars:.0f} = pct NLV]"
            if recommended is not None:
                if recommended == 0:
                    one_pct = item.get("pct_nlv_at_risk_one_contract")
                    skip_str = f" (1 contract = {one_pct * 100:.1f}% NLV)" if one_pct is not None else ""
                    print(f"    Recommended size: SKIP — exceeds per-trade risk budget{skip_str}{budget_tag}")
                else:
                    pct_str = f" ({pct_at_risk * 100:.1f}% NLV at risk)" if pct_at_risk is not None else ""
                    print(f"    Recommended size: {recommended} contract{'s' if recommended != 1 else ''}{pct_str}{budget_tag}")
            sector_tag = item.get("sector")
            if sector_tag:
                print(f"    Sector: {sector_tag}")
            print(f"    Score: {score:.1f}/100 — {summary}")
            if breakdown:
                parts = [f"{k} {float(v):.1f}" for k, v in breakdown.items()]
                print(f"    Breakdown: {', '.join(parts)}")

    rejected = result.get("rejected") or []
    if rejected:
        counts: dict[str, int] = {}
        by_reason: dict[str, list[dict[str, Any]]] = {}
        for r in rejected:
            reason = r.get("reason", "unknown")
            counts[reason] = counts.get(reason, 0) + 1
            by_reason.setdefault(reason, []).append(r)
        print()
        print("Rejection summary:")
        for reason, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  {reason}: {n}")
        if not top_items:
            print()
            print("Rejection details (no trades passed):")
            for reason in sorted(by_reason, key=lambda k: (-counts[k], k)):
                print(f"  [{reason}]")
                for r in by_reason[reason]:
                    sym = r.get("symbol", "?")
                    detail = r.get("detail") or ""
                    print(f"    {sym}: {detail}" if detail else f"    {sym}")

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


def _format_legs(candidate: Candidate) -> str:
    """Compact per-leg summary with expiration prefix."""
    parts: list[str] = []
    exp_prefix = f"{candidate.expiration.isoformat()} ({candidate.dte}d) "
    for leg in candidate.legs:
        action = leg.get("action") or leg.get("side") or "?"
        opt_type = leg.get("option_type") or leg.get("type") or "?"
        strike = leg.get("strike")
        delta = leg.get("delta")
        oi = leg.get("open_interest")
        strike_s = f"{float(strike):g}" if strike is not None else "?"
        delta_s = f"Δ{float(delta):+.2f}" if delta is not None else "Δ?"
        oi_s = f"OI {int(oi)}" if oi is not None else "OI ?"
        parts.append(f"{action} {opt_type} {strike_s} {delta_s} {oi_s}")
    return exp_prefix + " / ".join(parts)


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
            detail=f"min OI {min_oi} below floor {min_open_interest} | {_format_legs(candidate)}",
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
            detail=f"max spread {worst:.3f} above cap {max_spread_pct:.3f} | {_format_legs(candidate)}",
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
    csp_max_pct_nlv_per_trade: Optional[float] = None,
) -> tuple[list[Candidate], list[Rejection]]:
    """Hard-reject candidates that worsen account state beyond configured caps.

    CSPs use a separate (more permissive) per-trade size cap because their
    assignment-to-zero max-loss is the full strike — applying the spread cap
    of 5% NLV would reject every CSP on small accounts. Pass
    ``csp_max_pct_nlv_per_trade`` (typically 0.30) to gate CSPs separately.
    """
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
        dollar_risk = _dollar_max_loss(c)
        size_pct = dollar_risk / nlv
        # CSPs get their own (more permissive) cap — the spread cap is meant
        # for vertical max-loss, not assignment-to-zero capital risk.
        cap_for_this = (
            csp_max_pct_nlv_per_trade
            if c.structure == "CASH_SECURED_PUT" and csp_max_pct_nlv_per_trade is not None
            else max_pct_nlv_per_trade
        )

        if size_pct > cap_for_this:
            rejections.append(Rejection(
                symbol=c.symbol,
                reason="oversized_vs_nlv",
                detail=(
                    f"max_loss ${dollar_risk:.0f} = "
                    f"{size_pct * 100:.1f}% NLV above cap "
                    f"{cap_for_this * 100:.1f}%"
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
        post_exposure_pct = (existing + dollar_risk) / nlv
        if post_exposure_pct > concentration_block_pct:
            rejections.append(Rejection(
                symbol=c.symbol,
                reason="concentration_overlap",
                detail=(
                    f"{c.symbol} exposure ${existing:.0f} + ${dollar_risk:.0f} = "
                    f"{post_exposure_pct * 100:.1f}% NLV above cap "
                    f"{concentration_block_pct * 100:.1f}%"
                ),
            ))
            continue

        # Sector gate: block candidates whose sector is already represented by an
        # OPEN position, but allow rolling/adding into an underlying we already
        # hold (the `c.symbol in exposures` exception). Only checks against the
        # existing portfolio, not against other survivors in this batch — multiple
        # new picks in the same sector can survive a single run.
        candidate_sector = get_sector(c.symbol)
        if (
            candidate_sector
            and candidate_sector in account_state.occupied_sectors
            and c.symbol not in exposures
        ):
            rejections.append(Rejection(
                symbol=c.symbol,
                reason="sector_overlap",
                detail=(
                    f"sector '{candidate_sector}' already represented by an open position"
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

# Cash-Secured-Put scoring weights — five article dimensions plus account_fit.
# Total is 100 before any concentration penalty (subtractive, shared with
# spreads). Income < Distance reflects "survival first, gains second".
_WEIGHT_CSP_INCOME: float = 20.0
_WEIGHT_CSP_DISTANCE: float = 25.0
_WEIGHT_CSP_POP: float = 20.0
_WEIGHT_CSP_VOL_ENV: float = 15.0
_WEIGHT_CSP_TIME_EFFICIENCY: float = 10.0
# 90 from CSP-specific dimensions; remaining 10 reuses _WEIGHT_ACCOUNT_FIT.


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
    """Score 0..10 for trade-size fit; placeholder 10.0 when account_state is None or NLV non-positive.

    CSPs use a wider linear ramp (10..0 over [10%, 25%] of NLV) because
    their assignment-to-zero max-loss is fundamentally larger than spread
    max-loss. Spreads keep the original 10..0 over [2%, 5%] ramp.
    """
    if account_state is None or account_state.nlv <= 0:
        return _WEIGHT_ACCOUNT_FIT
    pct = _dollar_max_loss(candidate) / account_state.nlv
    if candidate.structure == "CASH_SECURED_PUT":
        # 10 at <=10% NLV; 0 at >=25% NLV; linear in between.
        return max(0.0, min(10.0, 10.0 * (0.25 - pct) / 0.15))
    return max(0.0, min(10.0, 10.0 * (0.05 - pct) / 0.03))


def _score_concentration_penalty(
    candidate: Candidate,
    account_state: Optional[AccountState] = None,
) -> float:
    """Subtractive penalty 0..10 for concentration; placeholder 0.0 when account_state is None or NLV non-positive."""
    if account_state is None or account_state.nlv <= 0:
        return 0.0
    existing = account_state.existing_exposures.get(candidate.symbol, 0.0)
    post_trade_pct = (existing + _dollar_max_loss(candidate)) / account_state.nlv
    return max(0.0, min(10.0, 10.0 * (post_trade_pct - 0.05) / 0.20))


def _csp_short_strike(candidate: Candidate) -> float:
    """Pull the short-put strike off the candidate's single SELL leg."""
    for leg in candidate.legs or []:
        if leg.get("action") == "SELL":
            strike = leg.get("strike")
            if strike is not None:
                return float(strike)
    return 0.0


def _csp_annualized_return(candidate: Candidate) -> float:
    """(credit * 365 / dte) / strike. Yield on cash-secured capital."""
    strike = _csp_short_strike(candidate)
    if strike <= 0 or candidate.dte <= 0:
        return 0.0
    return (candidate.credit * 365.0 / candidate.dte) / strike


def _score_csp_income(candidate: Candidate, min_annualized_return: float) -> float:
    """0..20 by annualized return, ramping from min_annualized_return up to 0.30 (30%).

    Saturates at the cap when the user-tuned floor exceeds the cap (avoid
    div-by-zero / negative-range artefacts).
    """
    ann = _csp_annualized_return(candidate)
    if ann <= min_annualized_return:
        return 0.0
    span = 0.30 - min_annualized_return
    if span <= 0:
        return _WEIGHT_CSP_INCOME
    factor = min(1.0, (ann - min_annualized_return) / span)
    return _WEIGHT_CSP_INCOME * factor


def _score_csp_distance(candidate: Candidate, min_otm_pct: float) -> float:
    """0..25 by buffer below spot, ramping from min_otm_pct up to 0.15 (15% OTM)."""
    spot = candidate.context.current_price
    if spot is None or float(spot) <= 0:
        return 0.0
    strike = _csp_short_strike(candidate)
    if strike <= 0:
        return 0.0  # malformed candidate — no SELL leg
    pct_otm = (float(spot) - strike) / float(spot)
    if pct_otm < min_otm_pct:
        return 0.0
    span = 0.15 - min_otm_pct
    if span <= 0:
        return _WEIGHT_CSP_DISTANCE
    factor = min(1.0, (pct_otm - min_otm_pct) / span)
    return _WEIGHT_CSP_DISTANCE * factor


def _score_csp_pop(candidate: Candidate) -> float:
    """0..20 by 1 - |delta|, ramping over [0.65, 0.85]."""
    pop = 1.0 - abs(candidate.short_delta or 0.0)
    factor = max(0.0, min(1.0, (pop - 0.65) / 0.20))
    return _WEIGHT_CSP_POP * factor


def _score_csp_vol_env(candidate: Candidate) -> float:
    """0..15 by IVR ramping over [30, 70]; placeholder 7.5 when IVR is None."""
    ivr = candidate.context.iv_rank
    if ivr is None:
        return _WEIGHT_CSP_VOL_ENV * 0.5
    factor = max(0.0, min(1.0, (ivr - 30.0) / 40.0))
    return _WEIGHT_CSP_VOL_ENV * factor


def _score_csp_time_efficiency(candidate: Candidate) -> float:
    """0..10 by DTE bucket fit. Peaks 30..45 DTE.

    Sub-21 DTE is penalised harder than >60 DTE — the article calls out gamma
    risk on short-DTE puts as more dangerous than the slow time decay of
    longer-dated. Floor 0.10 below 21d, 0.40 above 60d.
    """
    dte = candidate.dte
    if dte <= 0:
        return 0.0
    if 30 <= dte <= 45:
        factor = 1.0
    elif 21 <= dte < 30:
        factor = (dte - 21) / 9.0  # ramp 0..1
    elif 45 < dte <= 60:
        factor = 1.0 - (dte - 45) / 15.0  # ramp 1..0
    elif dte < 21:
        factor = 0.10  # gamma risk
    else:  # dte > 60
        factor = 0.40  # slow theta but not blow-up territory
    return _WEIGHT_CSP_TIME_EFFICIENCY * factor


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


def _score_csp_candidate(
    candidate: Candidate,
    *,
    today: date,
    account_state: Optional[AccountState] = None,
    min_otm_pct: float = 0.03,
    min_annualized_return: float = 0.10,
) -> Candidate:
    """CSP scoring path — five article dimensions plus account_fit + penalty.

    Total score is bounded to [0, 100]. Concentration penalty is shared with
    spreads (subtractive). Earnings risk is folded into the time_efficiency
    + distance components rather than its own bucket — CSPs near earnings
    typically blow through buffer regardless of DTE bucket.
    """
    income = _score_csp_income(candidate, min_annualized_return)
    distance = _score_csp_distance(candidate, min_otm_pct)
    pop = _score_csp_pop(candidate)
    vol_env = _score_csp_vol_env(candidate)
    time_eff = _score_csp_time_efficiency(candidate)
    account = _score_account_fit(candidate, account_state)
    penalty = _score_concentration_penalty(candidate, account_state)
    # Earnings within 7d → drop time_efficiency to floor (matches spread gate intent).
    if candidate.context.next_earnings_date is not None:
        days_to_earnings = (candidate.context.next_earnings_date - today).days
        if 0 <= days_to_earnings <= 7:
            time_eff = 0.0

    breakdown: dict[str, float] = {
        "csp_income": income,
        "csp_distance": distance,
        "csp_pop": pop,
        "csp_vol_env": vol_env,
        "csp_time_efficiency": time_eff,
        "account_fit": account,
        "concentration_penalty": penalty,
    }

    total = income + distance + pop + vol_env + time_eff + account - penalty
    score = max(0.0, min(100.0, total))

    summary = _format_csp_summary_reason(candidate, breakdown)

    return replace(
        candidate,
        score=score,
        score_breakdown=breakdown,
        summary_reason=summary,
    )


def _format_csp_summary_reason(candidate: Candidate, breakdown: dict[str, float]) -> str:
    """One-line plain-English string of the strongest CSP factors."""
    phrases: list[str] = []
    ivr = candidate.context.iv_rank
    if breakdown["csp_vol_env"] / _WEIGHT_CSP_VOL_ENV >= 0.6 and ivr is not None:
        phrases.append(f"IVR {round(ivr)}")

    spot = candidate.context.current_price
    if spot is not None and float(spot) > 0:
        pct_otm = (float(spot) - _csp_short_strike(candidate)) / float(spot)
        if pct_otm >= 0.05:
            phrases.append(f"{pct_otm * 100:.1f}% OTM buffer")

    pop = 1.0 - abs(candidate.short_delta or 0.0)
    if pop >= 0.75:
        phrases.append(f"POP {pop * 100:.0f}%")

    ann = _csp_annualized_return(candidate)
    if ann >= 0.12:
        phrases.append(f"{ann * 100:.1f}% annualized")

    if 30 <= candidate.dte <= 45:
        phrases.append("prime DTE")

    skew = candidate.context.put_call_skew
    if skew is not None and skew >= 1.20:
        phrases.append(f"⚠ skew {skew:.2f}")

    if not phrases:
        return "weak across CSP factors"
    return ", ".join(phrases[:5])


def score_candidate(
    candidate: Candidate,
    *,
    today: Optional[date] = None,
    account_state: Optional[AccountState] = None,
    csp_min_otm_pct: Optional[float] = None,
    csp_min_annualized_return: Optional[float] = None,
) -> Candidate:
    """Return a new Candidate with score, score_breakdown, and summary_reason populated.

    Dispatches to the CSP-specific scoring path when the candidate's structure
    is ``CASH_SECURED_PUT``; spreads/iron-condors keep the original 7-component
    formula.
    """
    if today is None:
        today = date.today()

    if candidate.structure == "CASH_SECURED_PUT":
        return _score_csp_candidate(
            candidate,
            today=today,
            account_state=account_state,
            min_otm_pct=csp_min_otm_pct if csp_min_otm_pct is not None else 0.03,
            min_annualized_return=csp_min_annualized_return if csp_min_annualized_return is not None else 0.10,
        )

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
    csp_min_otm_pct: Optional[float] = None,
    csp_min_annualized_return: Optional[float] = None,
) -> list[Candidate]:
    """Score each candidate; preserve input order; pure (returns new list of new Candidates)."""
    if today is None:
        today = date.today()
    return [
        score_candidate(
            c,
            today=today,
            account_state=account_state,
            csp_min_otm_pct=csp_min_otm_pct,
            csp_min_annualized_return=csp_min_annualized_return,
        )
        for c in candidates
    ]
