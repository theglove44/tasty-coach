"""FastAPI dashboard + chat sidebar for tasty-coach.

Endpoints:
  GET  /                — dashboard HTML
  GET  /api/snapshot    — JSON dashboard data (no LLM cost)
  GET  /api/briefing    — SSE one-shot briefing (LLM)
  GET  /api/chat        — SSE multi-turn chat (LLM); ?session_id=&q=...

Auth: every route checks ?token=... or X-Auth-Token header against the
TASTY_COACH_WEB_TOKEN env var. If unset at startup we mint a random hex
token and print it to stderr.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from claude_agent_sdk import ClaudeSDKClient
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from agents import coach_context as cc
from agents.coach import build_chat_options, stream_briefing, stream_chat_turn
from agents.coach_context import CoachContext
from agents.trade_ranker import run_best_trades
from server.snapshot import assemble_dashboard_data
from utils import journal
from utils.market_schedule import MarketSchedule
from utils.settings import (
    DEFAULTS as SETTINGS_DEFAULTS,
    INTEGER_KEYS,
    NUMERIC_KEYS,
    OPTIONAL_NUMERIC_KEYS,
    SETTINGS_DESCRIPTIONS,
    settings,
)
from utils.tasty_client import TastyClient

BT_CACHE_TTL_SEC = 900  # 15 min — best-trades is slow; reuse aggressively.

# Cap chat sessions to avoid leaking ClaudeSDKClient subprocesses if the
# frontend ever drifts session_ids without calling /api/chat/reset.
MAX_CHAT_SESSIONS = 8

# Editable settings, grouped for the UI. Keys must exist in utils.settings.DEFAULTS.
# Order within each group is the display order. alert_toggles (dict) is intentionally
# omitted from v1 — it needs a checkbox UI rather than a numeric input.
SETTINGS_GROUPS: list[dict[str, Any]] = [
    {
        "id": "sizing",
        "label": "Sizing & Account Fit",
        "keys": [
            "bt_per_trade_risk_pct",
            "bt_max_pct_nlv_per_trade",
            "bt_bp_cap_for_new",
            "bt_concentration_overlap_block_pct",
        ],
    },
    {
        "id": "quality",
        "label": "Quality Gates",
        "keys": [
            "bt_min_ivr",
            "bt_min_dte",
            "bt_max_dte",
            "bt_min_open_interest",
            "bt_max_spread_pct",
            "bt_earnings_blackout_days",
        ],
    },
    {
        "id": "scan",
        "label": "Scan Performance",
        "keys": [
            "bt_research_concurrency",
            "bt_research_timeout_seconds",
            "bt_max_per_symbol",
        ],
    },
    {
        "id": "alerts",
        "label": "Risk Alerts",
        "keys": [
            "position_pct_nlv_warn",
            "bp_usage_warn",
            "bp_usage_block",
            "concentration_pct_nlv_warn",
            "theta_target",
        ],
    },
]


def _setting_type(key: str) -> str:
    if key in INTEGER_KEYS:
        return "integer"
    if key in OPTIONAL_NUMERIC_KEYS:
        return "optional_number"
    if key in NUMERIC_KEYS:
        return "number"
    return "any"


def _serialize_settings() -> dict[str, Any]:
    """Return everything the UI needs to render and validate the settings form."""
    items: dict[str, dict[str, Any]] = {}
    for group in SETTINGS_GROUPS:
        for key in group["keys"]:
            if key not in SETTINGS_DEFAULTS:
                continue
            items[key] = {
                "key": key,
                "value": settings.get(key),
                "default": SETTINGS_DEFAULTS[key],
                "description": SETTINGS_DESCRIPTIONS.get(key, ""),
                "type": _setting_type(key),
            }
    return {"groups": SETTINGS_GROUPS, "settings": items}


def _data_feed_likely_alive(session: Any) -> bool:
    """True if it makes sense to run a watchlist scan right now.

    Pre-/post-market dxLink usually has data; overnight (after-hours close to
    pre-market open) has none and every greeks subscription times out. Use the
    SDK market-session info to decide. Fail-open if we can't determine.
    """
    try:
        sched = MarketSchedule(session)
        state = sched.get_market_state()
        # Tastytrade returns 'Open' / 'Closed' / 'Pre-Market' / 'After-Hours' / 'Extended'.
        return state in {"Open", "Pre-Market", "After-Hours", "Extended"}
    except Exception:
        return True

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(ROOT / "templates"))


TOKEN_FILE = Path.home() / ".tasty-coach" / "web_token"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
COOKIE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60  # 30 days


def _resolve_token() -> str:
    """Return a stable token across restarts.

    Resolution order:
      1. ``TASTY_COACH_WEB_TOKEN`` env var (highest precedence; lets ops pin it).
      2. ``~/.tasty-coach/web_token`` file (auto-created on first run).
      3. Mint a new one and write to (2).
    """
    tok = os.environ.get("TASTY_COACH_WEB_TOKEN")
    if tok:
        return tok
    try:
        if TOKEN_FILE.exists():
            tok = TOKEN_FILE.read_text().strip()
            if tok:
                os.environ["TASTY_COACH_WEB_TOKEN"] = tok
                return tok
    except OSError as e:
        logging.getLogger(__name__).warning("could not read %s: %s", TOKEN_FILE, e)

    tok = secrets.token_hex(16)
    try:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(tok)
        TOKEN_FILE.chmod(0o600)
        print(f"[server] minted stable web token → {TOKEN_FILE}", flush=True)
    except OSError as e:
        print(f"[server] could not persist web token to {TOKEN_FILE} ({e}); using in-memory only", flush=True)
    os.environ["TASTY_COACH_WEB_TOKEN"] = tok
    return tok


def _is_loopback(request: Request) -> bool:
    """True when the request originates from the same machine.

    Solo-LAN deployment: anyone with filesystem access already has TastyTrade
    creds in .env, so loopback bypass leaks nothing additional. LAN clients
    (phone/iPad on `--host 0.0.0.0`) still see auth.
    """
    client = getattr(request, "client", None)
    if client is None or client.host is None:
        return False
    return client.host in LOOPBACK_HOSTS


def _check_token(request: Request, token: str | None) -> None:
    if _is_loopback(request):
        return
    expected = request.app.state.token
    supplied = token or request.headers.get("X-Auth-Token") or request.cookies.get("tcw_token")
    if supplied:
        # Tolerate copy-paste artefacts: spaces, angle brackets, quotes.
        supplied = supplied.strip().strip("<>\"'`")
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="invalid or missing token")


CacheKey = tuple[str, frozenset[str]]


def _bt_key(account: str, watchlists: Any) -> CacheKey:
    """Normalise a watchlist selection into a stable cache key."""
    if not watchlists:
        return (account, frozenset())
    return (account, frozenset(str(w) for w in watchlists))


def _key_to_list(key: CacheKey) -> list[str]:
    return sorted(key[1])


def _bt_cached(app: FastAPI, key: CacheKey) -> dict[str, Any] | None:
    entry = app.state.bt_cache.get(key)
    if entry is None:
        return None
    ts, payload = entry
    if time.time() - ts > BT_CACHE_TTL_SEC:
        return None
    return payload


def _bt_inflight_for_account(app: FastAPI, account: str) -> CacheKey | None:
    """Return the (account, watchlists) key of any in-flight scan for this
    account, or None. Used to enforce 'one scan at a time per account'."""
    for k in app.state.bt_inflight:
        if k[0] == account:
            return k
    return None


async def _bt_run_and_cache(app: FastAPI, ctx: CoachContext, watchlists: list[str]) -> dict[str, Any]:
    """Run run_best_trades once for the given selection; store in the cache.

    Cache key is (account_number, frozenset[watchlists]) so distinct selections
    cache independently."""
    key = _bt_key(ctx.account_number, watchlists)
    try:
        result = await run_best_trades(
            ctx.session,
            watchlists=tuple(watchlists),
            top=3,
            output_format="json",
            account_number=ctx.account_number,
        )
        if isinstance(result.get("rejected"), list):
            rej = result["rejected"]
            summary: dict[str, int] = {}
            for r in rej:
                reason = r.get("reason") if isinstance(r, dict) else None
                if reason:
                    summary[reason] = summary.get(reason, 0) + 1
            result["rejected_summary"] = summary
            result["rejected_count"] = len(rej)
            result.pop("rejected", None)
        app.state.bt_cache[key] = (time.time(), result)
        logger.info(
            "best-trades cached for %s %s (%d picks)",
            ctx.account_number, sorted(watchlists), len(result.get("top") or []),
        )
        return result
    finally:
        app.state.bt_inflight.pop(key, None)


async def _build_ctx(app: FastAPI) -> CoachContext:
    """Refresh the TastyTrade session on every request — sessions auto-refresh
    via the SDK, but resolving the account ensures a usable handle."""
    client: TastyClient = app.state.tasty_client
    session = client.get_session()
    if session is None:
        raise HTTPException(status_code=503, detail="tastytrade session unavailable")
    account_number = app.state.account_number
    account = await client.get_account(account_number)
    return CoachContext(
        session=session,
        account=account,
        account_number=getattr(account, "account_number", account_number),
    )


def create_app(*, account_number: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = TastyClient()
        if not client.authenticate():
            raise RuntimeError("tastytrade authentication failed at startup")
        app.state.tasty_client = client
        app.state.account_number = account_number or client.config.account_number
        app.state.token = _resolve_token()
        # Cache-bust for static assets — bumps every server start so browsers
        # always pick up CSS/JS changes without a manual hard-refresh.
        app.state.asset_version = str(int(time.time()))
        # Per-session chat clients keyed by chat_session_id (in-memory; v1).
        app.state.chat_sessions: dict[str, ClaudeSDKClient] = {}
        app.state.chat_lock = asyncio.Lock()
        # Best-trades cache keyed on (account_number, frozenset[watchlists]).
        app.state.bt_cache: dict[CacheKey, tuple[float, dict[str, Any]]] = {}
        # Track the in-flight scan tasks (one allowed per account at a time).
        app.state.bt_inflight: dict[CacheKey, asyncio.Task] = {}
        # Watchlist-list cache (30s TTL) to avoid hammering TastyTrade on
        # rapid dashboard reloads.
        app.state.wl_cache: tuple[float, list[dict[str, str]]] | None = None
        yield
        # Drain chat clients on shutdown
        for sid, c in list(app.state.chat_sessions.items()):
            try:
                await c.disconnect()
            except Exception as e:
                logger.debug("chat session %s disconnect: %s", sid, e)

    app = FastAPI(lifespan=lifespan, title="tasty-coach")
    app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request, token: str | None = Query(default=None)) -> Any:
        _check_token(request, token)
        # Pass the token through to the page so JS calls work without query param.
        response = TEMPLATES.TemplateResponse(
            request,
            "dashboard.html",
            {
                "token": request.app.state.token,
                "account_number": request.app.state.account_number,
                "asset_version": request.app.state.asset_version,
            },
        )
        # Persistent cookie (30 days) so the browser remembers the token
        # across sessions. httponly=False because chat.js reads the value
        # for SSE bootstrap.
        response.set_cookie(
            "tcw_token",
            request.app.state.token,
            max_age=COOKIE_MAX_AGE_SECONDS,
            httponly=False,
            samesite="strict",
        )
        return response

    @app.get("/api/snapshot")
    async def api_snapshot(request: Request, token: str | None = Query(default=None)) -> JSONResponse:
        _check_token(request, token)
        ctx = await _build_ctx(request.app)
        data = await assemble_dashboard_data(ctx)
        data["data_feed_live"] = _data_feed_likely_alive(ctx.session)
        # Surface what's already scanned/scanning so the picker UI can hint.
        now = time.time()
        cached = []
        for k, (ts, payload) in request.app.state.bt_cache.items():
            if k[0] != ctx.account_number or now - ts > BT_CACHE_TTL_SEC:
                continue
            cached.append({
                "watchlists": _key_to_list(k),
                "age_sec": int(now - ts),
                "picks": len(payload.get("top") or []),
            })
        inflight = [
            {"watchlists": _key_to_list(k)}
            for k in request.app.state.bt_inflight
            if k[0] == ctx.account_number
        ]
        data["cached_scans"] = cached
        data["inflight_scans"] = inflight
        return JSONResponse(data)

    @app.get("/api/watchlists")
    async def api_watchlists(request: Request, token: str | None = Query(default=None)) -> JSONResponse:
        _check_token(request, token)
        ctx = await _build_ctx(request.app)

        # 30s in-process cache to dedupe rapid loads.
        cached = request.app.state.wl_cache
        if cached and time.time() - cached[0] < 30:
            return JSONResponse({"watchlists": cached[1]})

        def _fetch() -> list[dict[str, str]]:
            from tastytrade.watchlists import PrivateWatchlist, PublicWatchlist
            seen: dict[str, dict[str, str]] = {}
            try:
                for w in PrivateWatchlist.get(ctx.session) or []:
                    name = getattr(w, "name", None)
                    if name:
                        seen[name] = {"name": name, "kind": "private"}
            except Exception as e:
                logger.warning("PrivateWatchlist.get failed: %s", e)
            try:
                for w in PublicWatchlist.get(ctx.session) or []:
                    name = getattr(w, "name", None)
                    if name and name not in seen:  # private wins on collision
                        seen[name] = {"name": name, "kind": "public"}
            except Exception as e:
                logger.warning("PublicWatchlist.get failed: %s", e)
            return sorted(seen.values(), key=lambda d: (d["kind"] != "private", d["name"].lower()))

        items = await asyncio.to_thread(_fetch)
        request.app.state.wl_cache = (time.time(), items)
        return JSONResponse({"watchlists": items})

    def _scan_state(app: FastAPI, key: CacheKey) -> dict[str, Any]:
        """Synthesise a state dict for a (account, watchlists) selection.

        When state=='ready', also includes ``top`` (full pick payloads) and
        ``rejected_summary`` so the dashboard can render the picks without an
        extra round trip.
        """
        cached = _bt_cached(app, key)
        if cached is not None:
            ts = app.state.bt_cache[key][0]
            return {
                "state": "ready",
                "watchlists": _key_to_list(key),
                "age_sec": int(time.time() - ts),
                "picks": len(cached.get("top") or []),
                "top": cached.get("top") or [],
                "rejected_summary": cached.get("rejected_summary") or {},
                "rejected_count": cached.get("rejected_count") or 0,
                "warnings": cached.get("warnings") or [],
            }
        if key in app.state.bt_inflight:
            return {"state": "inflight", "watchlists": _key_to_list(key)}
        return {"state": "idle", "watchlists": _key_to_list(key)}

    @app.post("/api/scan/start")
    async def api_scan_start(
        request: Request,
        watchlists: list[str] = Query(default_factory=list),
        token: str | None = Query(default=None),
    ) -> JSONResponse:
        _check_token(request, token)
        if not watchlists:
            raise HTTPException(status_code=400, detail="watchlists query param is required")
        ctx = await _build_ctx(request.app)
        key = _bt_key(ctx.account_number, watchlists)

        # Already cached?
        if _bt_cached(request.app, key) is not None:
            return JSONResponse({"started": False, "status": "cached", **_scan_state(request.app, key)})

        # This exact selection already scanning?
        if key in request.app.state.bt_inflight:
            return JSONResponse({"started": False, "status": "inflight", **_scan_state(request.app, key)})

        # Cap at one in-flight scan per account.
        existing = _bt_inflight_for_account(request.app, ctx.account_number)
        if existing is not None:
            raise HTTPException(
                status_code=429,
                detail=f"another scan in progress for this account: {_key_to_list(existing)}",
            )

        if not _data_feed_likely_alive(ctx.session):
            raise HTTPException(status_code=409, detail="market closed — trade scan unavailable")

        task = asyncio.create_task(_bt_run_and_cache(request.app, ctx, list(watchlists)))
        request.app.state.bt_inflight[key] = task
        return JSONResponse({"started": True, "status": "started", **_scan_state(request.app, key)})

    @app.get("/api/scan/status")
    async def api_scan_status(
        request: Request,
        watchlists: list[str] = Query(default_factory=list),
        token: str | None = Query(default=None),
    ) -> JSONResponse:
        _check_token(request, token)
        if not watchlists:
            raise HTTPException(status_code=400, detail="watchlists query param is required")
        ctx = await _build_ctx(request.app)
        key = _bt_key(ctx.account_number, watchlists)
        return JSONResponse(_scan_state(request.app, key))

    @app.get("/api/briefing")
    async def api_briefing(
        request: Request,
        watchlists: list[str] = Query(default_factory=list),
        token: str | None = Query(default=None),
    ) -> EventSourceResponse:
        _check_token(request, token)
        if not watchlists:
            raise HTTPException(status_code=400, detail="watchlists query param is required")
        ctx = await _build_ctx(request.app)
        key = _bt_key(ctx.account_number, watchlists)

        async def event_source() -> AsyncIterator[dict[str, Any]]:
            try:
                yield {"event": "status", "data": "loading account snapshot…"}
                snapshot = await assemble_dashboard_data(ctx)

                bt = _bt_cached(request.app, key)
                if bt is None:
                    inflight = request.app.state.bt_inflight.get(key)
                    if inflight is not None:
                        yield {"event": "status", "data": "waiting for in-flight scan to complete…"}
                        try:
                            bt = await inflight
                        except Exception as e:
                            yield {"event": "error", "data": f"scan failed: {e}"}
                            return
                    else:
                        yield {"event": "error", "data": "no trade scan ready for this watchlist selection — start a scan first"}
                        return
                else:
                    age = int(time.time() - request.app.state.bt_cache[key][0])
                    yield {"event": "status", "data": f"using cached trades ({age}s old)"}

                yield {"event": "status", "data": "writing briefing…"}
                async for kind, text in stream_briefing(ctx, snapshot=snapshot, best_trades=bt):
                    yield {"event": kind, "data": text}
                yield {"event": "done", "data": ""}
            except Exception as e:
                logger.exception("briefing failed")
                yield {"event": "error", "data": str(e)}

        return EventSourceResponse(event_source())

    @app.get("/api/chat")
    async def api_chat(
        request: Request,
        q: str = Query(..., min_length=1, max_length=4000),
        session_id: str = Query(default="default"),
        token: str | None = Query(default=None),
    ) -> EventSourceResponse:
        _check_token(request, token)
        ctx = await _build_ctx(request.app)
        cc.set_current(ctx)

        sessions: dict[str, ClaudeSDKClient] = request.app.state.chat_sessions

        async def event_source() -> AsyncIterator[dict[str, Any]]:
            try:
                yield {"event": "status", "data": "thinking…"}
                async with request.app.state.chat_lock:
                    client = sessions.get(session_id)
                    if client is None:
                        # Evict oldest session if at cap.
                        if len(sessions) >= MAX_CHAT_SESSIONS:
                            oldest_id, oldest_client = next(iter(sessions.items()))
                            sessions.pop(oldest_id, None)
                            try:
                                await oldest_client.disconnect()
                            except Exception as e:
                                logger.debug("evicted chat %s disconnect: %s", oldest_id, e)
                        client = ClaudeSDKClient(options=build_chat_options())
                        await client.connect()
                        sessions[session_id] = client
                # Bind context within this request scope (ContextVar — race-safe).
                cc.set_current(ctx)
                async for kind, text in stream_chat_turn(client, q):
                    yield {"event": kind, "data": text}
                yield {"event": "done", "data": ""}
            except Exception as e:
                logger.exception("chat failed")
                yield {"event": "error", "data": str(e)}

        return EventSourceResponse(event_source())

    @app.post("/api/chat/reset")
    async def chat_reset(request: Request, session_id: str = Query(default="default"), token: str | None = Query(default=None)) -> JSONResponse:
        _check_token(request, token)
        sessions: dict[str, ClaudeSDKClient] = request.app.state.chat_sessions
        client = sessions.pop(session_id, None)
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass
        return JSONResponse({"reset": True, "session_id": session_id})

    @app.get("/api/settings")
    async def api_settings_get(request: Request, token: str | None = Query(default=None)) -> JSONResponse:
        _check_token(request, token)
        return JSONResponse(_serialize_settings())

    @app.post("/api/settings")
    async def api_settings_set(request: Request, token: str | None = Query(default=None)) -> JSONResponse:
        _check_token(request, token)
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="invalid JSON body")
        if not isinstance(body, dict) or not body:
            raise HTTPException(status_code=400, detail="body must be a non-empty object")
        # Only allow keys exposed in our groups.
        allowed = {k for g in SETTINGS_GROUPS for k in g["keys"]}
        unknown = [k for k in body if k not in allowed]
        if unknown:
            raise HTTPException(status_code=400, detail=f"unknown or non-editable keys: {unknown}")
        try:
            settings.set_many(body)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"invalid setting value: {e}")
        # Best-trades cache becomes stale once gates change — invalidate.
        request.app.state.bt_cache.clear()
        logger.info("settings updated: %s — bt_cache cleared", list(body.keys()))
        return JSONResponse(_serialize_settings())

    @app.get("/api/journal")
    async def api_journal(
        request: Request,
        days: int | None = Query(default=30, ge=0, le=365),
        symbol: str | None = Query(default=None),
        kind: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=500),
        token: str | None = Query(default=None),
    ) -> JSONResponse:
        _check_token(request, token)
        entries = await asyncio.to_thread(
            journal.recall, days=days, symbol=symbol, kind=kind, limit=limit,
        )
        stats = await asyncio.to_thread(journal.stats)
        return JSONResponse({"entries": entries, "stats": stats})

    @app.post("/api/settings/reset")
    async def api_settings_reset(request: Request, token: str | None = Query(default=None)) -> JSONResponse:
        _check_token(request, token)
        try:
            body = await request.json()
        except Exception:
            body = {}
        keys = body.get("keys") if isinstance(body, dict) else None
        allowed = {k for g in SETTINGS_GROUPS for k in g["keys"]}
        if keys is None:
            keys = list(allowed)
        else:
            keys = [k for k in keys if k in allowed]
        if not keys:
            raise HTTPException(status_code=400, detail="no valid keys to reset")
        defaults = {k: SETTINGS_DEFAULTS[k] for k in keys if k in SETTINGS_DEFAULTS}
        try:
            settings.set_many(defaults)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"reset failed: {e}")
        request.app.state.bt_cache.clear()
        logger.info("settings reset: %s — bt_cache cleared", keys)
        return JSONResponse(_serialize_settings())

    return app


def serve(*, host: str = "127.0.0.1", port: int = 8765, account_number: str | None = None) -> None:
    import socket
    import uvicorn

    token = _resolve_token()  # ensures TASTY_COACH_WEB_TOKEN is set before lifespan reads it
    app = create_app(account_number=account_number)

    def _local_ip() -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 53))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return host

    print()
    print("=" * 72)
    print("  tasty-coach dashboard")
    print(f"    http://127.0.0.1:{port}/                    (loopback — no token needed)")
    if host == "0.0.0.0":
        print(f"    http://{_local_ip()}:{port}/?token={token}    (LAN — phone/iPad)")
        print(f"    Token persisted to {TOKEN_FILE} (or pin TASTY_COACH_WEB_TOKEN in .env)")
    print("=" * 72)
    print()

    uvicorn.run(app, host=host, port=port, log_level="info")
