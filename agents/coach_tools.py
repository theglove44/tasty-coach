"""Tool wrappers exposing existing tasty-coach agents to the Claude Agent SDK.

Each tool is a thin async closure that pulls the live session/account from
``coach_context.current()``, calls the relevant agent, and returns a compact
JSON-text payload the LLM can reason over. We deliberately avoid Rich objects
and trim large dataclasses to small dicts.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from claude_agent_sdk import tool, create_sdk_mcp_server

from agents import coach_context
from agents.gex import GEXAgent
from agents.history import HistoryAgent
from agents.manager import RiskManager
from agents.options_researcher import OptionsResearcherAgent
from agents.portfolio import PortfolioAgent
from agents.reviewer import ReviewerAgent
from agents.scanner import ScannerAgent
from agents.trade_ranker import run_best_trades
from utils import journal

logger = logging.getLogger(__name__)


def _ok(payload: Any) -> dict:
    text = payload if isinstance(payload, str) else json.dumps(payload, default=str, indent=2)
    return {"content": [{"type": "text", "text": text}]}


def _err(msg: str) -> dict:
    return {"content": [{"type": "text", "text": f"ERROR: {msg}"}], "is_error": True}


def _serialize_position(p: Any) -> dict:
    g = lambda k, d=None: getattr(p, k, d)
    inst = g("instrument_type")
    inst_str = getattr(inst, "value", str(inst)) if inst is not None else None
    return {
        "symbol": g("symbol"),
        "instrument_type": inst_str,
        "quantity": str(g("quantity")) if g("quantity") is not None else None,
        "quantity_direction": getattr(g("quantity_direction"), "value", None) or g("quantity_direction"),
        "average_open_price": str(g("average_open_price")) if g("average_open_price") is not None else None,
        "underlying_symbol": g("underlying_symbol"),
        "expires_at": str(g("expires_at")) if g("expires_at") else None,
    }


@tool(
    "get_account_status",
    "Fetch live account status: NLV, buying power, BP usage, cash. Always call this before recommending new trades.",
    {},
)
async def get_account_status(_args: dict) -> dict:
    ctx = coach_context.current()
    pf = await PortfolioAgent(ctx.session, ctx.account_number).init()
    if pf.account is None:
        return _err("could not resolve account")
    status = await pf.get_account_status()
    return _ok(status)


@tool(
    "get_positions",
    "List current open positions with symbol, quantity, direction, and instrument type.",
    {},
)
async def get_positions(_args: dict) -> dict:
    ctx = coach_context.current()
    pf = await PortfolioAgent(ctx.session, ctx.account_number).init()
    positions = await pf.get_positions()
    return _ok([_serialize_position(p) for p in positions])


@tool(
    "calculate_risk",
    "Compute portfolio-level risk: BP usage, NLV, portfolio delta/theta, concentration, alerts.",
    {},
)
async def calculate_risk(_args: dict) -> dict:
    ctx = coach_context.current()
    rm = RiskManager(ctx.session, ctx.account_number)
    risk = await rm.calculate_portfolio_risk()
    return _ok(risk)


@tool(
    "run_best_trades",
    "Run the full Best-Trades pipeline: scan watchlists, generate candidates, apply quality gates, return top ranked ideas plus rejection summary.",
    {"top": int},
)
async def run_best_trades_tool(args: dict) -> dict:
    ctx = coach_context.current()
    top = int(args.get("top") or 3)
    result = await run_best_trades(
        ctx.session,
        top=top,
        output_format="json",
        account_number=ctx.account_number,
    )
    # Trim rejection list to a summary count to keep context small.
    if isinstance(result, dict) and isinstance(result.get("rejected"), list):
        rej = result["rejected"]
        summary: dict[str, int] = {}
        for r in rej:
            reason = r.get("reason") if isinstance(r, dict) else None
            if reason:
                summary[reason] = summary.get(reason, 0) + 1
        result["rejected_summary"] = summary
        result["rejected_count"] = len(rej)
        result.pop("rejected", None)
    return _ok(result)


@tool(
    "research_symbol",
    "Research one underlying symbol's options chain and return ranked credit-spread / iron-condor ideas. Use for symbol-specific questions.",
    {"symbol": str},
)
async def research_symbol(args: dict) -> dict:
    ctx = coach_context.current()
    symbol = (args.get("symbol") or "").strip().upper()
    if not symbol:
        return _err("symbol is required")
    agent = OptionsResearcherAgent(ctx.session)
    report = await agent.research(symbol)
    return _ok(report)


@tool(
    "review_position",
    "Review one underlying's open positions and produce roll scenarios (down / out / down-and-out).",
    {"symbol": str},
)
async def review_position(args: dict) -> dict:
    ctx = coach_context.current()
    symbol = (args.get("symbol") or "").strip().upper()
    if not symbol:
        return _err("symbol is required")
    rev = await ReviewerAgent(ctx.session, ctx.account_number).init()
    results = await rev.review_positions(underlying_filter=symbol)
    out = []
    for r in results:
        out.append({
            "underlying": getattr(r, "underlying", None),
            "summary": getattr(r, "summary", None) or str(r),
        })
    return _ok(out)


@tool(
    "calculate_gex",
    "Compute gamma-exposure profile for an underlying: spot, zero-gamma level, call/put walls, regime signal.",
    {"symbol": str, "max_dte": int},
)
async def calculate_gex_tool(args: dict) -> dict:
    ctx = coach_context.current()
    symbol = (args.get("symbol") or "SPY").strip().upper()
    max_dte = int(args.get("max_dte") or 30)
    gex = GEXAgent(ctx.session)
    result = await gex.calculate_gex(symbol=symbol, max_dte=max_dte)
    payload = {
        "symbol": getattr(result, "symbol", symbol),
        "spot_price": getattr(result, "spot_price", None),
        "total_gex": getattr(result, "total_gex", None),
        "zero_gamma_level": getattr(result, "zero_gamma_level", None),
        "regime": gex.analyze_regime(result),
        "walls": gex.get_gamma_walls(result),
    }
    return _ok(payload)


@tool(
    "scan_watchlist",
    "Scan a TastyTrade watchlist for IVR rank. Returns symbols sorted by IVR descending.",
    {"watchlist": str},
)
async def scan_watchlist(args: dict) -> dict:
    ctx = coach_context.current()
    watchlist = args.get("watchlist") or "PMCC Targets"
    sc = ScannerAgent(ctx.session)
    symbols = await sc.get_symbols_from_watchlist(watchlist)
    if not symbols:
        return _ok({"watchlist": watchlist, "symbols": [], "ivr": []})
    ivr_data = await sc.scan_ivr(symbols)
    ranked = sorted(
        ({"symbol": s, "ivr": getattr(d, "ivr", None)} for s, d in ivr_data.items()),
        key=lambda x: (x["ivr"] is None, -(x["ivr"] or 0)),
    )
    return _ok({"watchlist": watchlist, "symbols": symbols, "ivr": ranked})


@tool(
    "get_history",
    "Fetch recent account events (fills, closes, rolls, assignments) for the last N days.",
    {"days": int},
)
async def get_history(args: dict) -> dict:
    ctx = coach_context.current()
    days = int(args.get("days") or 14)
    h = await HistoryAgent(ctx.session, ctx.account_number).init()
    events = await h.get_recent_events(days=days)
    return _ok(events)


@tool(
    "record_decision",
    (
        "Persist a decision or notable observation to the journal so future "
        "conversations can recall it. Use AFTER recommending a trade, opening/"
        "closing a position, or making an analytical call worth remembering. "
        "Set 'kind' to one of: recommendation, trade_open, trade_close, note, "
        "outcome. Provide a clear 'rationale' in plain English."
    ),
    {"kind": str, "rationale": str, "symbol": str, "strategy": str},
)
async def record_decision(args: dict) -> dict:
    kind = (args.get("kind") or "").strip().lower()
    rationale = (args.get("rationale") or "").strip()
    if not kind or not rationale:
        return _err("kind and rationale are required")
    if kind not in journal.VALID_KINDS:
        return _err(f"kind must be one of {sorted(journal.VALID_KINDS)}")
    # Cap rationale to bound journal growth on runaway model loops or prompt
    # injection — the journal lives at ~/.tasty-coach/journal.jsonl and is
    # append-only, so unbounded entries can quickly bloat the file.
    if len(rationale) > 4096:
        rationale = rationale[:4096] + "…[truncated]"
    entry = {
        "kind": kind,
        "rationale": rationale,
    }
    sym = (args.get("symbol") or "").strip().upper()
    if sym:
        entry["symbol"] = sym
    strat = (args.get("strategy") or "").strip()
    if strat:
        entry["strategy"] = strat
    persisted = journal.record(entry)
    return _ok({"recorded": True, "entry": persisted})


@tool(
    "recall_journal",
    (
        "Recall prior decisions, recommendations, and notes from the journal. "
        "Use when the user asks 'what did I do last week?', 'why did I open X?', "
        "or any history-grounded question. Filters: days (lookback window), "
        "symbol (specific underlying), kind (recommendation|trade_open|"
        "trade_close|note|outcome), limit (default 20)."
    ),
    {"days": int, "symbol": str, "kind": str, "limit": int},
)
async def recall_journal(args: dict) -> dict:
    days = args.get("days")
    symbol = (args.get("symbol") or "").strip() or None
    kind = (args.get("kind") or "").strip().lower() or None
    limit = int(args.get("limit") or 20)
    entries = journal.recall(
        days=int(days) if days is not None else None,
        symbol=symbol,
        kind=kind,
        limit=limit,
    )
    return _ok({"entries": entries, "count": len(entries)})


def build_mcp_server():
    """Build the in-process MCP server that registers all coach tools."""
    return create_sdk_mcp_server(
        name="tasty_coach",
        version="0.2.0",
        tools=[
            get_account_status,
            get_positions,
            calculate_risk,
            run_best_trades_tool,
            research_symbol,
            review_position,
            calculate_gex_tool,
            scan_watchlist,
            get_history,
            record_decision,
            recall_journal,
        ],
    )


# Names the model is allowed to call (mcp__<server>__<tool>).
ALLOWED_TOOLS = [
    "mcp__tasty_coach__get_account_status",
    "mcp__tasty_coach__get_positions",
    "mcp__tasty_coach__calculate_risk",
    "mcp__tasty_coach__run_best_trades",
    "mcp__tasty_coach__research_symbol",
    "mcp__tasty_coach__review_position",
    "mcp__tasty_coach__calculate_gex",
    "mcp__tasty_coach__scan_watchlist",
    "mcp__tasty_coach__get_history",
    "mcp__tasty_coach__record_decision",
    "mcp__tasty_coach__recall_journal",
]
