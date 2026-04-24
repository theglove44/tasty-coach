"""Unified account dashboard: portfolio, performance, and risk in one view.

The dashboard aggregates data from multiple sources (portfolio, analytics, history,
risk manager) and renders a comprehensive account summary using Rich primitives.

Architecture:
- gather_dashboard_data() runs 4 independent coroutines concurrently via asyncio.gather()
  with per-section error capture (no exceptions raised).
- run_account_dashboard() awaits the gather and prints the result.
- Pure render functions (render_*_panel) never raise.
- All helpers handle None, NaN, and invalid inputs gracefully.
"""

import asyncio
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from agents.manager import RiskManager
from agents.portfolio import PortfolioAgent
from agents.analytics import AnalyticsAgent
from agents.history import HistoryAgent


# Constants
EM_DASH = "—"
MAX_POSITIONS_DISPLAYED = 5
MAX_EVENTS_DISPLAYED = 10
MAX_ALERTS_DISPLAYED = 8
EVENTS_LOOKBACK_DAYS = 30
DTE_WARN_THRESHOLD = 7
DEFAULT_POSITION_PCT_NLV_WARN = 0.15

logger = logging.getLogger(__name__)


@dataclass
class DashboardData:
    """Container for all dashboard data sections. Errors captured per section."""
    risk: Optional[dict] = None
    account_status: Optional[dict] = None
    performance: Optional[dict] = None
    positions: Optional[list] = None
    recent_events: Optional[list[dict]] = None
    nlv: Optional[Decimal] = None
    position_pct_nlv_warn: float = DEFAULT_POSITION_PCT_NLV_WARN
    errors: dict[str, str] = field(default_factory=dict)


# --- Formatting Helpers ---

def _is_nan(value: Any) -> bool:
    """Check if value is None, NaN float, or Decimal NaN."""
    if value is None:
        return True
    try:
        if isinstance(value, float) and math.isnan(value):
            return True
    except (ValueError, TypeError):
        pass
    try:
        if isinstance(value, Decimal):
            return value.is_nan()
    except (ValueError, InvalidOperation):
        pass
    return False


def fmt_money(value, *, sign: bool = False) -> str:
    """Format as currency. sign=True prefixes '+' for positive values.

    Args:
        value: numeric or None
        sign: if True, prefix positive values with '+'

    Returns:
        Formatted string like "$1,234.56" or EM_DASH if invalid.
    """
    if _is_nan(value):
        return EM_DASH
    try:
        fval = float(value)
        if fval < 0:
            return f"-${abs(fval):,.2f}"
        prefix = "+" if sign else ""
        return f"{prefix}${fval:,.2f}"
    except (ValueError, TypeError):
        return EM_DASH


def fmt_pct(value, *, decimals: int = 1) -> str:
    """Format as percentage. Assumes value is already in percent units (0-100).

    Args:
        value: numeric percent value (already in percent, not fraction) or None
        decimals: decimal places to show (default 1)

    Returns:
        Formatted string like "12.3%" or EM_DASH if invalid.
    """
    if _is_nan(value):
        return EM_DASH
    try:
        return f"{float(value):.{decimals}f}%"
    except (ValueError, TypeError):
        return EM_DASH


def fmt_num(value, *, decimals: int = 0) -> str:
    """Format as number with fixed decimal places.

    Args:
        value: numeric or None
        decimals: decimal places (default 0)

    Returns:
        Formatted string or EM_DASH if invalid.
    """
    if _is_nan(value):
        return EM_DASH
    try:
        return f"{float(value):.{decimals}f}"
    except (ValueError, TypeError):
        return EM_DASH


def fmt_signed_money(value) -> str:
    """Shortcut for fmt_money with sign=True."""
    return fmt_money(value, sign=True)


def _dte_from_occ(symbol: str, today: Optional[date] = None) -> Optional[int]:
    """Parse OCC symbol and return DTE; None if not OCC format.

    OCC format: ROOT YYMMDDCSTRIKE (example: SPY 260507C00500000)
    Regex captures: (ROOT) (YYMMDD) [CP] (STRIKE)
    """
    try:
        pattern = r"^([A-Z\./]{1,7})\s*(\d{6})[CP]\d{8}$"
        match = re.match(pattern, symbol.strip().upper())
        if not match:
            return None

        yymmdd = match.group(2)
        yy = int(yymmdd[:2])
        mm = int(yymmdd[2:4])
        dd = int(yymmdd[4:6])

        exp_date = date(2000 + yy, mm, dd)
        ref_date = today or date.today()
        return (exp_date - ref_date).days
    except Exception:
        return None


# --- Data Gathering ---

async def gather_dashboard_data(session, account_number=None) -> DashboardData:
    """Gather all dashboard data concurrently with per-section error capture.

    Args:
        session: tastytrade Session
        account_number: account to query (optional)

    Returns:
        DashboardData with all fields populated (or None) and errors dict.
    """
    data = DashboardData()

    async def _risk():
        try:
            rm = RiskManager(session, account_number=account_number)
            return await rm.calculate_portfolio_risk()
        except Exception as e:
            logger.error(f"Error fetching risk data: {e}")
            data.errors["risk"] = str(e)
            return None

    async def _portfolio():
        try:
            pa = await PortfolioAgent(session, account_number=account_number).init()
            status = await pa.get_account_status()
            positions = await pa.get_positions()
            return {"status": status, "positions": positions}
        except Exception as e:
            logger.error(f"Error fetching portfolio data: {e}")
            data.errors["portfolio"] = str(e)
            return None

    async def _performance():
        try:
            aa = AnalyticsAgent(session, account_number=account_number)
            if hasattr(aa, "init") and asyncio.iscoroutinefunction(aa.init):
                aa = await aa.init()
            return aa.get_performance_summary()
        except Exception as e:
            logger.error(f"Error fetching performance data: {e}")
            data.errors["performance"] = str(e)
            return None

    async def _history():
        try:
            ha = await HistoryAgent(session, account_number=account_number).init()
            result = ha.get_transactions(days=EVENTS_LOOKBACK_DAYS)
            if asyncio.iscoroutine(result):
                result = await result
            return result
        except Exception as e:
            logger.error(f"Error fetching history data: {e}")
            data.errors["history"] = str(e)
            return None

    # Run all 4 concurrently
    results = await asyncio.gather(_risk(), _portfolio(), _performance(), _history(), return_exceptions=True)

    risk_result, portfolio_result, perf_result, history_result = results

    # Unpack risk
    if isinstance(risk_result, dict):
        data.risk = risk_result
    elif isinstance(risk_result, Exception):
        data.errors["risk"] = str(risk_result)

    # Unpack portfolio
    if isinstance(portfolio_result, dict):
        data.account_status = portfolio_result.get("status")
        data.positions = portfolio_result.get("positions")
    elif isinstance(portfolio_result, Exception):
        data.errors["portfolio"] = str(portfolio_result)

    # Unpack performance
    if isinstance(perf_result, dict):
        data.performance = perf_result
    elif isinstance(perf_result, Exception):
        data.errors["performance"] = str(perf_result)

    # Unpack history (it's a list of Transaction objects)
    if isinstance(history_result, (list, tuple)):
        data.recent_events = _normalise_events(history_result)
    elif isinstance(history_result, Exception):
        data.errors["history"] = str(history_result)

    # Derive NLV: prefer data.risk, fall back to account_status
    try:
        if data.risk and "nlv" in data.risk:
            data.nlv = Decimal(str(data.risk["nlv"]))
        elif data.account_status and "net_liquidating_value" in data.account_status:
            data.nlv = Decimal(str(data.account_status["net_liquidating_value"]))
    except (InvalidOperation, ValueError, TypeError):
        pass

    return data


def _g(obj, key, default=None):
    """Safe getter that works on both dicts and objects."""
    if obj is None:
        return default
    if hasattr(obj, "get"):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _normalise_events(raw_txns) -> list[dict]:
    """Convert transaction objects to normalized event dicts.

    Expected fields on transaction object:
    - executed_at (datetime): transaction execution time
    - transaction_type (str): e.g., 'Trade'
    - transaction_sub_type (str): e.g., specific transaction type
    - symbol (str): security symbol
    - underlying_symbol (str): underlying for options
    - net_value (Decimal): transaction P&L or value

    Returns:
        List of dicts with keys: date (YYYY-MM-DD), type, symbol, amount
        Sorted newest-first, truncated to MAX_EVENTS_DISPLAYED.
    """
    events = []
    for txn in raw_txns:
        try:
            # Extract date
            executed_at = _g(txn, "executed_at")
            if executed_at and hasattr(executed_at, "date"):
                date_str = executed_at.date().isoformat()
            else:
                date_str = ""

            # Extract type (prefer sub_type)
            txn_type = _g(txn, "transaction_sub_type") or _g(txn, "transaction_type", "Unknown")

            # Extract symbol (prefer symbol, fallback to underlying_symbol)
            symbol = _g(txn, "symbol") or _g(txn, "underlying_symbol", "—")

            # Extract amount
            try:
                amount = Decimal(str(_g(txn, "net_value", 0)))
            except (InvalidOperation, ValueError, TypeError):
                amount = None

            events.append({
                "date": date_str,
                "type": txn_type,
                "symbol": symbol,
                "amount": amount,
            })
        except Exception as e:
            logger.warning(f"Error normalizing event: {e}")
            continue

    # Sort newest-first (reverse by date string)
    events.sort(key=lambda e: e["date"], reverse=True)
    return events[:MAX_EVENTS_DISPLAYED]


# --- Panel Renderers ---

def render_kpi_panel(data: DashboardData) -> Panel:
    """Render key performance indicators table."""
    table = Table(show_header=False, box=None)

    # Use risk as primary source, fallback to account_status
    risk = data.risk or {}
    acct = data.account_status or {}

    nlv = risk.get("nlv") or acct.get("net_liquidating_value")
    bp_usage_pct = risk.get("bp_usage_pct")
    bp_status = risk.get("bp_usage_status", "")
    cash = risk.get("cash_balance") or acct.get("cash_balance")
    dte = risk.get("day_trade_excess")
    delta = risk.get("portfolio_delta")
    theta = risk.get("portfolio_theta")

    # Row data
    rows = [
        ("NLV", fmt_money(nlv)),
        ("BP Usage", f"{fmt_pct(bp_usage_pct)} [{bp_status}]"),
        ("Cash", fmt_money(cash)),
        ("Day Trade Excess", fmt_money(dte)),
        ("Portfolio Δ", fmt_num(delta, decimals=2)),
        ("Portfolio Θ", fmt_num(theta, decimals=2)),
    ]

    for label, value in rows:
        # Color BP row based on status
        if label == "BP Usage":
            if "BLOCK" in bp_status or (bp_usage_pct and bp_usage_pct > 50):
                style = "bold red"
            elif "WARN" in bp_status:
                style = "bold yellow"
            else:
                style = "bold green"
            table.add_row(label, value, style=style)
        else:
            table.add_row(label, value)

    return Panel(table, title="Account")


def render_performance_panel(data: DashboardData) -> Panel:
    """Render performance metrics table. Missing values render as EM_DASH."""
    perf = data.performance or {}

    table = Table(show_header=False, box=None)

    total_trades = perf.get("total_trades")
    win_rate = perf.get("win_rate")
    total_pl = perf.get("total_pl")
    total_fees = perf.get("total_fees")
    expectancy = perf.get("expectancy")
    profit_factor = perf.get("profit_factor")
    avg_holding = perf.get("avg_holding_days")

    if profit_factor is None:
        pf_str = EM_DASH
    elif isinstance(profit_factor, float) and math.isinf(profit_factor):
        pf_str = "∞"
    else:
        pf_str = fmt_num(profit_factor, decimals=2)

    avg_hold_str = EM_DASH if avg_holding is None else f"{fmt_num(avg_holding, decimals=1)} days"

    rows = [
        ("Trades", fmt_num(total_trades)),
        ("Win Rate", fmt_pct(win_rate)),
        ("Total P/L", fmt_money(total_pl)),
        ("Fees", fmt_money(total_fees)),
        ("Expectancy", fmt_money(expectancy)),
        ("Profit Factor", pf_str),
        ("Avg Hold", avg_hold_str),
    ]

    for label, value in rows:
        # Color P/L row
        if label == "Total P/L" and total_pl is not None:
            try:
                tpl_float = float(total_pl)
                style = "bold green" if tpl_float > 0 else "bold red" if tpl_float < 0 else ""
                table.add_row(label, value, style=style)
            except (ValueError, TypeError):
                table.add_row(label, value)
        else:
            table.add_row(label, value)

    return Panel(table, title="Performance")


def render_positions_panel(data: DashboardData) -> Panel:
    """Render open positions table."""
    if not data.positions:
        return Panel(Text(EM_DASH, justify="center"), title="Positions")

    # Filter and sort by abs market value desc
    positions = data.positions
    positions_sorted = sorted(
        positions,
        key=lambda p: abs(float(_g(p, "market_value", 0) or 0)),
        reverse=True
    )[:MAX_POSITIONS_DISPLAYED]

    if not positions_sorted:
        return Panel(Text(EM_DASH, justify="center"), title="Positions")

    table = Table(show_header=True, box=None)
    table.add_column("Symbol")
    table.add_column("Qty", justify="right")
    table.add_column("Avg Open", justify="right")
    table.add_column("Mark", justify="right")
    table.add_column("Mkt Value", justify="right")
    table.add_column("DTE", justify="right")
    table.add_column("Flag")

    for pos in positions_sorted:
        symbol = _g(pos, "symbol", "?")
        qty_raw = _g(pos, "quantity")
        qty_dir = _g(pos, "quantity_direction", "")
        qty_prefix = "+" if qty_dir == "Long" else "-" if qty_dir == "Short" else ""
        if qty_raw is None:
            qty_str = EM_DASH
        else:
            try:
                qty_str = f"{qty_prefix}{fmt_num(abs(float(qty_raw)))}"
            except (ValueError, TypeError):
                qty_str = EM_DASH

        avg_open = _g(pos, "average_open_price")
        mark = _g(pos, "close_price")
        mkt_val = _g(pos, "market_value")
        instr_type = _g(pos, "instrument_type", "")

        # Check if option
        is_option = "Option" in str(instr_type)

        # Calculate DTE
        dte_val = _dte_from_occ(symbol) if is_option else None
        dte_str = fmt_num(dte_val) if dte_val is not None else EM_DASH

        # Determine flag
        flag = ""
        if data.nlv and data.nlv > 0:
            try:
                pct_of_nlv = abs(float(mkt_val or 0)) / float(data.nlv)
                if pct_of_nlv > data.position_pct_nlv_warn:
                    flag = "🔴"
            except (ValueError, TypeError, ZeroDivisionError):
                pass

        if not flag and is_option and dte_val is not None and dte_val <= DTE_WARN_THRESHOLD:
            flag = "⚠"

        table.add_row(
            symbol,
            qty_str,
            fmt_money(avg_open),
            fmt_money(mark),
            fmt_money(mkt_val),
            dte_str,
            flag,
        )

    return Panel(table, title="Positions")


def render_alerts_panel(data: DashboardData) -> Panel:
    """Render alerts panel with severity ranking."""
    alerts = []

    # Collect from risk alerts
    if data.risk and "alerts" in data.risk:
        raw_alerts = data.risk["alerts"] or []
        for alert in raw_alerts:
            alerts.append(alert)

    # Add session warnings as synthetic alerts
    if data.risk and "session_warnings" in data.risk:
        for msg in data.risk["session_warnings"] or []:
            alerts.append({
                "severity": "info",
                "category": "session",
                "message": msg,
            })

    # Add trade size warnings as synthetic alerts
    if data.risk and "trade_size_warnings" in data.risk:
        for msg in data.risk["trade_size_warnings"] or []:
            alerts.append({
                "severity": "info",
                "category": "position_size",
                "message": msg,
            })

    # Sort by severity rank
    severity_rank = {"critical": 0, "warn": 1, "info": 2}
    alerts.sort(key=lambda a: severity_rank.get(str(_g(a, "severity", "")).lower(), 3))

    original_count = len(alerts)
    alerts = alerts[:MAX_ALERTS_DISPLAYED]
    truncated = original_count > MAX_ALERTS_DISPLAYED

    # Build title
    title = "Alerts"
    if truncated:
        title = f"Alerts (showing {len(alerts)} of {original_count})"

    if not alerts and "risk" not in data.errors:
        return Panel(Text("No active alerts", justify="center"), title=title)

    if not alerts and "risk" in data.errors:
        return Panel(Text(EM_DASH, justify="center"), title=title)

    # Build table
    table = Table(show_header=False, box=None)

    severity_color = {
        "critical": "bold red",
        "warn": "bold yellow",
        "info": "bold blue",
    }

    for alert in alerts:
        severity = str(_g(alert, "severity", "info")).lower()
        category = _g(alert, "category", "")
        message = _g(alert, "message", "")

        color = severity_color.get(severity, "white")
        severity_upper = severity.upper()

        row = Text()
        row.append(severity_upper, style=color)
        row.append(f"  {category}  {message}")
        table.add_row(row)

    return Panel(table, title=title)


def render_events_panel(data: DashboardData) -> Panel:
    """Render recent transaction events."""
    if not data.recent_events:
        return Panel(Text(EM_DASH, justify="center"), title="Recent events (30d)")

    table = Table(show_header=True, box=None)
    table.add_column("Date")
    table.add_column("Type")
    table.add_column("Symbol")
    table.add_column("Amount", justify="right")

    for event in data.recent_events:
        table.add_row(
            event["date"],
            event["type"],
            event["symbol"],
            fmt_signed_money(event["amount"]),
        )

    return Panel(table, title="Recent events (30d)")


def render_dashboard(data: DashboardData) -> Layout:
    """Render complete dashboard layout."""
    layout = Layout()
    layout.split_column(
        Layout(name="top", size=10),
        Layout(name="mid", ratio=2),
        Layout(name="bot", ratio=1),
    )

    layout["top"].split_row(
        Layout(name="kpi"),
        Layout(name="perf"),
    )
    layout["bot"].split_row(
        Layout(name="alerts"),
        Layout(name="events"),
    )

    layout["kpi"].update(render_kpi_panel(data))
    layout["perf"].update(render_performance_panel(data))
    layout["mid"].update(render_positions_panel(data))
    layout["alerts"].update(render_alerts_panel(data))
    layout["events"].update(render_events_panel(data))

    return layout


# --- Main Entry Point ---

async def run_account_dashboard(session, account_number=None) -> int:
    """Run the unified account dashboard.

    Args:
        session: tastytrade Session
        account_number: account to query (optional)

    Returns:
        0 on success, 1 if all sections failed
    """
    data = await gather_dashboard_data(session, account_number=account_number)
    console = Console()
    console.print(render_dashboard(data))

    if len(data.errors) == 4:
        console.print("[bold red]All dashboard sections failed. See logs.[/bold red]")
        return 1

    return 0
