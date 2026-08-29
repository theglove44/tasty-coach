#!/usr/bin/env python3
"""Build a real-data SPX morning snapshot for Hermes cron consumption.

Sources:
- Tastytrade REST market snapshot / metrics
- DXLink-backed GEX analysis (via existing GEXAgent)

Default output:
    ./output/spx_morning_snapshot.json

Usage:
    source venv/bin/activate
    python scripts/spx_morning_snapshot.py
    python scripts/spx_morning_snapshot.py --gex-underlying SPX
    python scripts/spx_morning_snapshot.py --pretty
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure project-root imports work when launched from scripts/
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.gex import GEXAgent  # noqa: E402
from agents.scanner import ScannerAgent, SnapshotData  # noqa: E402
from utils.market_schedule import MarketSchedule  # noqa: E402
from utils.private_paths import ARTIFACTS_DIR  # noqa: E402
from utils.tasty_client import TastyClient  # noqa: E402

DEFAULT_OUTPUT = ARTIFACTS_DIR / "spx_morning_snapshot.json"
DEFAULT_SYMBOLS = ["SPX", "SPY", "XSP", "VIX", "/ES", "/NQ"]
DEFAULT_WATCHLIST = "Snapshot"
DEFAULT_GEX_UNDERLYING = "SPY"

logger = logging.getLogger("spx_morning_snapshot")


def _warn_if_not_in_venv() -> None:
    if sys.prefix == getattr(sys, "base_prefix", sys.prefix):
        print(
            "⚠️  You are not running inside the project venv. "
            "If you see import/type errors, run: source venv/bin/activate",
            file=sys.stderr,
        )


def _safe_round(value: Any, digits: int = 2) -> Optional[float]:
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except Exception:
        return None


def _snapshot_item_to_dict(item: SnapshotData) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "last": _safe_round(item.last, 2),
        "prev_close": _safe_round(item.prev_close, 2),
        "net_change": _safe_round(item.net_change, 2),
        "percent_change": _safe_round(item.percent_change, 2),
    }
    if item.description:
        payload["description"] = item.description
    if item.iv_rank is not None:
        payload["iv_rank"] = _safe_round(item.iv_rank, 1)
    if item.iv_percentile is not None:
        payload["iv_percentile"] = _safe_round(item.iv_percentile, 1)
    return payload


def _normalize_symbols(snapshot_data: List[SnapshotData]) -> Dict[str, Dict[str, Any]]:
    symbols: Dict[str, Dict[str, Any]] = {}
    for item in snapshot_data:
        key = item.symbol
        payload = _snapshot_item_to_dict(item)

        # Normalize active future contracts back to canonical keys for downstream consumers.
        if key.startswith("/ES"):
            payload["symbol"] = key
            symbols["/ES"] = payload
        elif key.startswith("/NQ"):
            payload["symbol"] = key
            symbols["/NQ"] = payload
        else:
            symbols[key] = payload

    return symbols


def _derive_overnight_bias(symbols: Dict[str, Dict[str, Any]], warnings: List[str]) -> Optional[str]:
    es = symbols.get("/ES", {})
    vix = symbols.get("VIX", {})
    es_pct = es.get("percent_change")
    vix_pct = vix.get("percent_change")

    if es_pct is None or vix_pct is None:
        warnings.append("Overnight bias unavailable: missing /ES or VIX percent change")
        return None

    if es_pct <= -0.5 and vix_pct >= 3.0:
        return "risk_off"
    if es_pct >= 0.5 and vix_pct <= -2.0:
        return "risk_on"
    return "mixed"


def _derive_vol_regime(symbols: Dict[str, Dict[str, Any]]) -> Optional[str]:
    vix = symbols.get("VIX", {})
    vix_level = vix.get("last")
    if vix_level is None:
        return None
    if vix_level >= 30:
        return "very_elevated"
    if vix_level >= 22:
        return "elevated"
    if vix_level >= 16:
        return "moderate"
    return "calm"


def _derive_confidence(status_ok: bool, warnings: List[str], gex_ok: bool) -> str:
    if not status_ok:
        return "low"
    if warnings or not gex_ok:
        return "medium"
    return "high"


async def build_snapshot(
    output_path: Path,
    gex_underlying: str,
    gex_max_dte: int,
    gex_wait_seconds: float,
    symbols: Optional[List[str]] = None,
    watchlist_name: Optional[str] = None,
) -> Dict[str, Any]:
    client = TastyClient()
    if not client.authenticate():
        raise RuntimeError("Tastytrade authentication failed")

    session = client.get_session()
    if not session:
        raise RuntimeError("Failed to establish authenticated tastytrade session")

    scanner = ScannerAgent(session, threshold=client.config.ivr_threshold)
    market_schedule = MarketSchedule(session)
    gex_agent = GEXAgent(session)

    warnings: List[str] = []
    fallbacks_used: List[str] = []

    # 1) Resolve symbols
    if symbols is None and watchlist_name:
        try:
            resolved = await scanner.get_symbols_from_watchlist(watchlist_name, equity_only=False)
        except Exception as exc:
            resolved = []
            warnings.append(f"Watchlist '{watchlist_name}' lookup failed: {exc}")
        if resolved:
            symbols = resolved
        else:
            warnings.append(
                f"Watchlist '{watchlist_name}' not found or empty; falling back to DEFAULT_SYMBOLS"
            )
            fallbacks_used.append(f"watchlist:{watchlist_name}->DEFAULT_SYMBOLS")
    if not symbols:
        symbols = DEFAULT_SYMBOLS

    # 2) REST snapshot + IV metrics
    snapshot_data = await scanner.get_market_snapshot(symbols)
    if not snapshot_data:
        raise RuntimeError("Market snapshot returned no data")

    await scanner.enrich_with_iv(snapshot_data)
    symbols_dict = _normalize_symbols(snapshot_data)

    # Verify important data is present
    required_keys = ["SPX", "SPY", "VIX", "/ES"]
    missing_required = [key for key in required_keys if key not in symbols_dict]
    if missing_required:
        warnings.append(f"Missing required snapshot symbols: {', '.join(missing_required)}")

    # 2) GEX analysis
    gex_payload: Dict[str, Any]
    gex_ok = False
    try:
        gex_result = await gex_agent.calculate_gex(
            gex_underlying,
            max_dte=gex_max_dte,
            data_wait_seconds=gex_wait_seconds,
        )
        if gex_result.error:
            warnings.append(f"GEX unavailable for {gex_underlying}: {gex_result.error}")
            gex_payload = {
                "underlying": gex_underlying,
                "error": gex_result.error,
            }
        else:
            gex_ok = True
            regime = "POSITIVE" if gex_result.total_gex > 0 else "NEGATIVE"
            strategy = gex_result.strategy or {}
            gex_payload = {
                "underlying": gex_underlying,
                "spot_price": _safe_round(gex_result.spot_price, 2),
                "total_gex_millions": _safe_round(gex_result.total_gex, 2),
                "regime": regime,
                "signal": strategy.get("signal"),
                "message": strategy.get("message"),
                "call_wall": _safe_round(gex_result.call_wall, 2),
                "put_wall": _safe_round(gex_result.put_wall, 2),
                "zero_gamma": _safe_round(gex_result.zero_gamma_level, 2),
                "max_dte": gex_max_dte,
            }
    except Exception as exc:
        warnings.append(f"GEX calculation failed for {gex_underlying}: {exc}")
        gex_payload = {
            "underlying": gex_underlying,
            "error": str(exc),
        }

    # 3) Market session state
    try:
        market_session = market_schedule.get_market_state().lower().replace("-", "_").replace(" ", "_")
    except Exception as exc:
        market_session = "unknown"
        warnings.append(f"Market session lookup failed: {exc}")

    # 4) Simple derived layer for Hermes to use
    overnight_bias = _derive_overnight_bias(symbols_dict, warnings)
    vol_regime = _derive_vol_regime(symbols_dict)
    if vol_regime is None:
        warnings.append("Volatility regime unavailable: missing VIX level")

    snapshot: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "primary": "tastytrade_rest_dxlink",
            "gex_underlying": gex_underlying,
            "watchlist_used": watchlist_name,
            "symbols_requested": symbols,
            "build_version": "v1",
        },
        "status": {
            "ok": len(missing_required) == 0,
            "market_session": market_session,
            "warnings": warnings,
            "fallbacks_used": fallbacks_used,
        },
        "symbols": symbols_dict,
        "volatility": {
            "vix_level": symbols_dict.get("VIX", {}).get("last"),
            "vix_iv_percentile": symbols_dict.get("VIX", {}).get("iv_percentile"),
            "vix_trend_5d": None,
            "put_call_ratio": None,
        },
        "gex": gex_payload,
        "derived": {
            "overnight_bias": overnight_bias,
            "vol_regime": vol_regime,
            "confidence": _derive_confidence(len(missing_required) == 0, warnings, gex_ok),
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    return snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build SPX morning snapshot JSON")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--watchlist",
        type=str,
        default=DEFAULT_WATCHLIST,
        help=f"Watchlist name to pull symbols from (default: {DEFAULT_WATCHLIST})",
    )
    parser.add_argument(
        "--gex-underlying",
        default=DEFAULT_GEX_UNDERLYING,
        help="Underlying to use for GEX analysis (default: SPY for speed/reliability)",
    )
    parser.add_argument(
        "--gex-max-dte",
        type=int,
        default=7,
        help="Max DTE for GEX calculation (default: 7)",
    )
    parser.add_argument(
        "--gex-wait-seconds",
        type=float,
        default=3.0,
        help="How long to collect DXLink greeks for GEX (default: 3.0)",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON to stdout",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


async def async_main() -> int:
    _warn_if_not_in_venv()
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    snapshot = await build_snapshot(
        output_path=args.output,
        gex_underlying=args.gex_underlying,
        gex_max_dte=args.gex_max_dte,
        gex_wait_seconds=args.gex_wait_seconds,
        watchlist_name=args.watchlist,
    )

    if args.pretty:
        print(json.dumps(snapshot, indent=2))
    else:
        print(json.dumps(snapshot))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
