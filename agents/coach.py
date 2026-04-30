"""AI coach: Claude Agent SDK driving tasty-coach as in-process tools.

Two entry points:
- ``run_briefing(ctx)`` — single-turn daily briefing (Opus).
- ``run_chat(ctx)`` — interactive REPL (Sonnet) with persistent context across turns.

Auth: requires ``CLAUDE_CODE_OAUTH_TOKEN`` (Claude Max subscription) OR
``ANTHROPIC_API_KEY`` (fallback). Subscription path is preferred.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Iterable

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

from agents import coach_context, coach_tools
from agents.coach_context import CoachContext

CHAT_MODEL = "claude-sonnet-4-6"
# Briefing uses the same fast model as chat by default — Opus is materially
# slower for marginal added depth. Override via TASTY_COACH_BRIEFING_MODEL env
# if you want Opus for a particular run.
BRIEFING_MODEL = os.environ.get("TASTY_COACH_BRIEFING_MODEL", "claude-sonnet-4-6")

PROMPT_PATH = Path(__file__).parent / "prompts" / "coach_system.md"

def _build_briefing_prompt(
    snapshot: dict[str, Any] | None,
    best_trades: dict[str, Any] | None = None,
) -> str:
    """Build a self-contained briefing prompt.

    When ``snapshot`` and ``best_trades`` are both supplied, the agent has
    everything it needs and only writes the prose — no tool calls, no waiting.
    This is the fast path. Falls back gracefully if either is missing.
    """
    import json as _json
    parts = ["Produce my morning trading briefing.\n"]

    if snapshot:
        compact = {
            "kpis": snapshot.get("kpis"),
            "positions": snapshot.get("positions"),
            "alerts": snapshot.get("alerts"),
        }
        parts.append(
            "Account snapshot (already fetched — do NOT call get_account_status or get_positions):\n"
            + _json.dumps(compact, default=str)
            + "\n"
        )

    if best_trades:
        compact_bt = {
            "top": best_trades.get("top"),
            "rejected_summary": best_trades.get("rejected_summary"),
            "rejected_count": best_trades.get("rejected_count"),
            "watchlists": best_trades.get("watchlists"),
        }
        parts.append(
            "Best-trades scan (already fetched — do NOT call run_best_trades):\n"
            + _json.dumps(compact_bt, default=str)
            + "\n"
        )

    parts.append("Steps:")
    if not snapshot:
        parts.append("- Call get_account_status and get_positions first.")
    if not best_trades:
        parts.append(
            "- Trade scan unavailable right now (likely market closed / no live data). "
            "Do NOT call run_best_trades — it will time out. Skip the 'top picks' section "
            "and tell the user trades will be scanned when the market re-opens."
        )
    parts.extend([
        "- Filter any picks against the account-fit rules in your system prompt (BP fit, no symbol-duplicates, sector overlap warnings, sizing).",
        "- Output (plain prose, not markdown):",
        "  - One-sentence summary of account state (NLV, BP%, position count).",
        "  - Top 1-3 actionable picks with strikes, credit, max loss, recommended contracts, and exit plan (50% profit / 21 DTE) — OR a note that trade scan is unavailable.",
        "  - Any positions worth reviewing (>21 DTE or near profit target).",
        "Keep total output under 400 words.",
    ])
    return "\n".join(parts)


def _silence_shutdown_recursion() -> None:
    """Swallow Python 3.14 asyncio Task.cancel(msg=msg) recursion noise on shutdown.

    The claude-agent-sdk transport spawns the Claude Code CLI subprocess and
    layers anyio task groups + read/write loops underneath. When the loop
    closes, Python 3.14's stricter `Task.cancel(msg=msg)` recursively cancels
    children deep enough to blow the recursion limit. The briefing/chat has
    already produced its output by the time these fire, so they're pure
    teardown noise — drop them at the loop level rather than letting them
    spam stderr.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    def handler(_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        # Narrow predicate: only swallow RecursionError originating in the SDK
        # transport teardown path (claude_agent_sdk / anyio frames). Real
        # RecursionErrors in tool code or our own logic should still surface.
        exc = context.get("exception")
        msg = str(context.get("message", ""))
        looks_like_sdk_teardown = (
            "claude_agent_sdk" in msg or "anyio" in msg or "task_group" in msg
        )
        if isinstance(exc, RecursionError) and looks_like_sdk_teardown:
            return
        if "RecursionError" in msg and looks_like_sdk_teardown:
            return
        _loop.default_exception_handler(context)

    loop.set_exception_handler(handler)


def _check_auth() -> None:
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return
    if os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "[coach] Using ANTHROPIC_API_KEY (pay-per-token). "
            "For Max-subscription billing, run `claude setup-token` and set CLAUDE_CODE_OAUTH_TOKEN.",
            file=sys.stderr,
        )
        return
    print(
        "ERROR: no Claude credentials found.\n"
        "  Run `claude setup-token` (Max subscription) and add CLAUDE_CODE_OAUTH_TOKEN to your .env,\n"
        "  or set ANTHROPIC_API_KEY for pay-per-token.",
        file=sys.stderr,
    )
    raise SystemExit(2)


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text()
    except FileNotFoundError:
        return "You are a tasty-coach options trading assistant."


def _build_options(model: str) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        system_prompt=_load_system_prompt(),
        model=model,
        mcp_servers={"tasty_coach": coach_tools.build_mcp_server()},
        allowed_tools=coach_tools.ALLOWED_TOOLS,
        permission_mode="bypassPermissions",
        tools=[],  # disable Claude Code native tools (Bash/Read/Write/etc.)
    )


def _print_text_blocks(blocks: Iterable) -> None:
    for block in blocks:
        if isinstance(block, TextBlock):
            sys.stdout.write(block.text)
            sys.stdout.flush()


_TOOL_LABELS = {
    "mcp__tasty_coach__get_account_status": "checking account status",
    "mcp__tasty_coach__get_positions": "loading positions",
    "mcp__tasty_coach__calculate_risk": "computing portfolio risk",
    "mcp__tasty_coach__run_best_trades": "scanning watchlists for trades",
    "mcp__tasty_coach__research_symbol": "researching symbol",
    "mcp__tasty_coach__review_position": "reviewing position",
    "mcp__tasty_coach__calculate_gex": "calculating gamma exposure",
    "mcp__tasty_coach__scan_watchlist": "scanning watchlist IVR",
    "mcp__tasty_coach__get_history": "fetching account history",
    "mcp__tasty_coach__record_decision": "saving decision to journal",
    "mcp__tasty_coach__recall_journal": "recalling prior decisions",
}


def _tool_status_label(name: str, input_args: dict) -> str:
    base = _TOOL_LABELS.get(name, name.replace("mcp__tasty_coach__", ""))
    sym = input_args.get("symbol") if isinstance(input_args, dict) else None
    if sym:
        return f"{base} ({sym})"
    return base


async def run_briefing(
    ctx: CoachContext,
    *,
    snapshot: dict[str, Any] | None = None,
    best_trades: dict[str, Any] | None = None,
) -> None:
    _check_auth()
    _silence_shutdown_recursion()
    coach_context.set_current(ctx)
    options = _build_options(BRIEFING_MODEL)

    prompt = _build_briefing_prompt(snapshot, best_trades)
    # Use ClaudeSDKClient (not query()) so __aexit__ runs disconnect() and
    # drains the Node subprocess deterministically — query()'s async generator
    # cleanup recurses on Python 3.14 task cancellation.
    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                _print_text_blocks(message.content)
            elif isinstance(message, ResultMessage):
                sys.stdout.write("\n")
                cost = getattr(message, "total_cost_usd", None)
                if cost is not None:
                    print(f"[coach] cost: ${cost:.4f}", file=sys.stderr)
                break


async def stream_briefing(
    ctx: CoachContext,
    *,
    snapshot: dict[str, Any] | None = None,
    best_trades: dict[str, Any] | None = None,
):
    """Yield (kind, text) tuples for SSE consumers.

    Kinds:
      - 'status': tool-call activity ("scanning watchlists for trades (AMD)")
      - 'token':  visible response text
      - 'cost':   final cost line
    """
    _check_auth()
    _silence_shutdown_recursion()
    coach_context.set_current(ctx)
    options = _build_options(BRIEFING_MODEL)
    prompt = _build_briefing_prompt(snapshot, best_trades)
    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        yield ("token", block.text)
                    elif isinstance(block, ToolUseBlock):
                        yield ("status", _tool_status_label(block.name, block.input or {}))
            elif isinstance(message, ResultMessage):
                cost = getattr(message, "total_cost_usd", None)
                if cost is not None:
                    yield ("cost", f"${cost:.4f}")
                break


async def stream_chat_turn(client: ClaudeSDKClient, prompt: str):
    """Yield (kind, text) tuples for one chat turn against an existing connected client."""
    await client.query(prompt)
    async for message in client.receive_response():
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    yield ("token", block.text)
                elif isinstance(block, ToolUseBlock):
                    yield ("status", _tool_status_label(block.name, block.input or {}))
        elif isinstance(message, ResultMessage):
            return


def build_chat_options() -> ClaudeAgentOptions:
    """Public accessor for chat options (used by the web server to construct ClaudeSDKClient)."""
    return _build_options(CHAT_MODEL)


async def run_chat(ctx: CoachContext) -> None:
    _check_auth()
    _silence_shutdown_recursion()
    coach_context.set_current(ctx)
    options = _build_options(CHAT_MODEL)

    print("Tasty Coach chat. Type your question (or 'exit' to quit).")
    async with ClaudeSDKClient(options=options) as client:
        while True:
            try:
                line = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if not line:
                continue
            if line.lower() in {"exit", "quit", ":q"}:
                return
            await client.query(line)
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    _print_text_blocks(message.content)
                elif isinstance(message, ResultMessage):
                    break
            sys.stdout.write("\n")
