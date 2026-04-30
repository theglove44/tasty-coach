"""Pure (no-LLM) data assembly for the web dashboard.

Pulls account state, positions, and risk alerts from existing agents into a
JSON-serialisable dict. The dashboard hits this on every page load; running it
costs only TastyTrade API calls.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from agents.coach_context import CoachContext
from agents.manager import RiskManager
from agents.portfolio import PortfolioAgent
from utils.sector_map import get_sector


_OCC_RE = re.compile(r"^([A-Z/]+)\s+(\d{6})([CP])(\d{8})$")


def _to_float(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _parse_occ(symbol: str) -> dict[str, Any] | None:
    m = _OCC_RE.match(symbol or "")
    if not m:
        return None
    root, yymmdd, cp, strike_str = m.groups()
    try:
        exp = datetime.strptime(yymmdd, "%y%m%d").date()
    except ValueError:
        return None
    return {
        "underlying": root,
        "expiration": exp.isoformat(),
        "type": "PUT" if cp == "P" else "CALL",
        "strike": float(strike_str) / 1000.0,
    }


def _serialize_position(pos: Any) -> dict[str, Any]:
    inst = getattr(pos, "instrument_type", None)
    inst_str = getattr(inst, "value", str(inst)) if inst is not None else None
    direction = getattr(getattr(pos, "quantity_direction", None), "value", None) or getattr(pos, "quantity_direction", None)
    qty = _to_float(getattr(pos, "quantity", 0))
    avg = _to_float(getattr(pos, "average_open_price", 0))
    sym = getattr(pos, "symbol", "") or ""
    parsed = _parse_occ(sym)
    # Prefer an explicit underlying_symbol; otherwise parse it out of the OCC
    # symbol. Falling back to the full OCC string would over-count
    # underlying_count and cause sector lookups to silently miss.
    underlying = getattr(pos, "underlying_symbol", None) or (parsed["underlying"] if parsed else sym)

    dte: int | None = None
    if parsed:
        try:
            exp = date.fromisoformat(parsed["expiration"])
            dte = (exp - date.today()).days
        except ValueError:
            pass

    return {
        "symbol": sym,
        "underlying": underlying,
        "instrument_type": inst_str,
        "direction": direction,
        "quantity": qty,
        "average_open_price": avg,
        "expiration": parsed["expiration"] if parsed else None,
        "strike": parsed["strike"] if parsed else None,
        "option_type": parsed["type"] if parsed else None,
        "dte": dte,
        "sector": get_sector(underlying),
    }


async def assemble_dashboard_data(ctx: CoachContext) -> dict[str, Any]:
    """Build the full dashboard payload.

    Returns a dict of:
      - kpis: NLV, BP usage, position count, portfolio delta/theta
      - positions: serialised position rows (with parsed OCC + DTE + sector)
      - alerts: structured alerts from RiskManager
      - warnings: legacy string warnings (BP/session/trade-size)
      - generated_at: ISO timestamp
    """
    risk = RiskManager(ctx.session, ctx.account_number)
    report = await risk.calculate_portfolio_risk()

    pf = await PortfolioAgent(ctx.session, ctx.account_number).init()
    positions = await pf.get_positions()

    serialised = [_serialize_position(p) for p in positions]
    serialised.sort(key=lambda r: (r.get("underlying") or "", r.get("expiration") or "", r.get("strike") or 0))

    nlv = _to_float(report.get("nlv"))
    bp_pct_raw = _to_float(report.get("bp_usage_pct"))
    # RiskManager returns (NLV - equity_buying_power) / NLV * 100. Negative
    # values mean EBP > NLV — genuine over-leverage on PM accounts, not noise.
    # Pass the raw value through and surface an explicit over_leveraged flag
    # so the UI can warn loudly instead of silently masking with abs().
    bp_pct = bp_pct_raw
    over_leveraged = bp_pct_raw < 0
    cash = _to_float(report.get("cash_balance"))
    delta = _to_float(report.get("portfolio_delta"))
    theta = _to_float(report.get("portfolio_theta"))

    kpis = {
        "nlv": nlv,
        "bp_usage_pct": bp_pct,
        "over_leveraged": over_leveraged,
        "cash_balance": cash,
        "position_count": len(serialised),
        "underlying_count": len({p["underlying"] for p in serialised if p.get("underlying")}),
        "portfolio_delta": delta,
        "portfolio_theta": theta,
        "bp_usage_status": report.get("bp_usage_status"),
        "theta_status": report.get("theta_status"),
        "day_trade_excess": _to_float(report.get("day_trade_excess")),
    }

    alerts_raw = report.get("alerts") or []
    alerts = []
    for a in alerts_raw:
        if isinstance(a, dict):
            alerts.append(a)
        else:
            alerts.append({
                "severity": getattr(a, "severity", "info"),
                "category": getattr(a, "category", ""),
                "message": getattr(a, "message", str(a)),
                "context": getattr(a, "context", {}) or {},
            })

    # Dedup: RiskManager emits the same content as both structured `alerts`
    # (with severity/category) and legacy `trade_size_warnings` strings.
    # Show structured alerts only; concat session_warnings (which are unique).
    return {
        "account_number": ctx.account_number,
        "kpis": kpis,
        "positions": serialised,
        "alerts": alerts,
        "warnings": list(report.get("session_warnings") or []),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
