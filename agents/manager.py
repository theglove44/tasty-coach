"""Risk Management Agent."""

import logging
import asyncio
from decimal import Decimal, InvalidOperation
from typing import List, Dict, Any, Optional

from tastytrade import Session, Account
from tastytrade.dxfeed import Greeks
from tastytrade.streamer import DXLinkStreamer
from tastytrade.market_data import get_market_data_by_type
from tastytrade.instruments import get_option_chain

from utils.market_schedule import MarketSchedule
from agents.alerts import Alert, AlertCollector
from utils.settings import settings
from utils.correlation_buckets import group_by_bucket


class RiskManager:
    """Monitors portfolio health and risk metrics for a specific account."""

    def __init__(self, session: Session, account_number: Optional[str] = None):
        self.session = session
        self.logger = logging.getLogger(__name__)
        self.account_number = account_number
        self.account: Optional[Account] = None
        self.market_schedule = MarketSchedule(session)

    async def _get_account(self) -> Account:
        """Resolve and cache the target Account (by account_number if set, else first)."""
        if self.account:
            return self.account
        accounts = Account.get(self.session)
        if not accounts:
            raise ValueError("No accounts found.")
        if self.account_number:
            for acct in accounts:
                if getattr(acct, "account_number", None) == self.account_number:
                    self.account = acct
                    return acct
            available = ", ".join([getattr(a, "account_number", "?") for a in accounts])
            raise ValueError(f"Account {self.account_number} not found. Available: {available}")
        self.account = accounts[0]
        return self.account

    def _is_option(self, pos) -> bool:
        """Return True if the position is an equity option (enum-safe check)."""
        inst_type = getattr(pos, "instrument_type", None)
        if inst_type is None:
            return False
        type_str = getattr(inst_type, "value", str(inst_type))
        return "Equity Option" == type_str

    async def _fetch_marks(self, positions: List[Any]) -> Dict[str, float]:
        """Fetch live marks per symbol via the market-data-by-type endpoint.

        Position objects don't carry a mark field, so we split by instrument type
        and batch option requests (batch_size=50) to stay under URI limits.
        """
        marks: Dict[str, float] = {}
        equity_syms = []
        option_syms = []
        for pos in positions:
            type_str = getattr(getattr(pos, "instrument_type", None), "value", "")
            if type_str == "Equity":
                equity_syms.append(pos.symbol)
            elif type_str == "Equity Option":
                option_syms.append(pos.symbol)
        batch_size = 50
        try:
            if equity_syms:
                quotes = get_market_data_by_type(self.session, equities=equity_syms)
                for q in quotes:
                    marks[q.symbol] = float(q.mark) if q.mark else 0.0
            for i in range(0, len(option_syms), batch_size):
                batch = option_syms[i:i + batch_size]
                quotes = get_market_data_by_type(self.session, options=batch)
                for q in quotes:
                    marks[q.symbol] = float(q.mark) if q.mark else 0.0
        except Exception as e:
            self.logger.warning(f"Failed to fetch position marks: {e}")
        return marks

    async def calculate_portfolio_risk(self) -> Dict[str, Any]:
        """Compute NLV / BP / Δ / Θ snapshot and emit structured alerts alongside legacy string warnings."""
        account = await self._get_account()
        balances = account.get_balances(self.session)
        positions = account.get_positions(self.session)

        nlv = extract_decimal(getattr(balances, "net_liquidating_value", None))
        bp = extract_decimal(getattr(balances, "equity_buying_power", None))

        bp_used = nlv - bp
        bp_usage_pct = (bp_used / nlv) * 100 if nlv > 0 else Decimal(0)

        collector = AlertCollector()
        pos_pct_warn = _decimal_setting("position_pct_nlv_warn", Decimal("0.05"))
        bp_warn = _decimal_setting("bp_usage_warn", Decimal("0.50"))
        theta_target_cfg = settings.get("theta_target")
        if theta_target_cfg is not None and _coerce_decimal(theta_target_cfg) is None:
            self.logger.warning(
                "Invalid theta_target setting %r; falling back to default band",
                theta_target_cfg,
            )
            theta_target_cfg = None

        session_warnings: List[str] = []
        if not self.market_schedule.is_market_open():
            session_warnings.append("Market is CLOSED. Liquidity and spreads may be unreliable.")
            collector.add(Alert(
                severity="info",
                category="market",
                message="Market is CLOSED. Liquidity and spreads may be unreliable.",
                context={},
            ))

        trade_size_warnings: List[str] = []
        max_trade_pct = pos_pct_warn * Decimal(100)
        max_trade_pct_str = f"{float(max_trade_pct):g}"

        marks_map = await self._fetch_marks(positions)

        per_underlying_value: Dict[str, float] = {}

        option_positions: List[Any] = []
        occ_to_streamer: Dict[str, str] = {}

        for pos in positions:
            mark = Decimal(str(marks_map.get(pos.symbol, 0.0)))
            qty = extract_decimal(getattr(pos, "quantity", None))
            mult = extract_decimal(getattr(pos, "multiplier", None) or 1)

            market_value = abs(mark * qty * mult)
            trade_pct = (market_value / nlv) * 100 if nlv > 0 else Decimal(0)

            root = getattr(pos, "underlying_symbol", None) or getattr(pos, "symbol", "UNKNOWN")
            per_underlying_value[root] = per_underlying_value.get(root, 0.0) + float(market_value)

            if trade_pct > max_trade_pct:
                warning_msg = f"{pos.symbol}: {trade_pct:.2f}% of NLV (Limit: {max_trade_pct_str}%)"
                trade_size_warnings.append(warning_msg)
                collector.add(Alert(
                    severity="warn",
                    category="position_size",
                    message=warning_msg,
                    context={
                        "symbol": pos.symbol,
                        "pct_nlv": float(trade_pct),
                        "limit_pct": float(max_trade_pct),
                    },
                ))

            if self._is_option(pos):
                option_positions.append(pos)

        concentration_result = self._analyze_concentration(
            per_underlying_value, float(nlv), collector
        )

        if option_positions:
            occ_to_streamer = await self._resolve_streamer_symbols(option_positions)

        total_delta = Decimal(0)
        total_theta = Decimal(0)

        if occ_to_streamer:
            streamer_symbols = list(occ_to_streamer.values())
            greeks_data = await self._fetch_greeks(streamer_symbols)
            streamer_to_occ = {v: k for k, v in occ_to_streamer.items()}

            for pos in option_positions:
                streamer_sym = occ_to_streamer.get(pos.symbol)
                if not streamer_sym or streamer_sym not in greeks_data:
                    continue
                data = greeks_data[streamer_sym]
                if data and data.delta is not None and data.theta is not None:
                    contract_delta = extract_decimal(data.delta)
                    contract_theta = extract_decimal(data.theta)
                    qty = extract_decimal(getattr(pos, "quantity", None))
                    mult = extract_decimal(getattr(pos, "multiplier", None) or 1)
                    direction = getattr(pos, "quantity_direction", "Long")
                    sign = Decimal(-1) if direction == "Short" else Decimal(1)
                    total_delta += contract_delta * mult * qty * sign
                    total_theta += contract_theta * mult * qty * sign

        day_trade_excess = extract_decimal(getattr(balances, "day_trade_excess", None))
        day_trade_bp = extract_decimal(getattr(balances, "day_trading_buying_power", None))
        cash_balance = extract_decimal(getattr(balances, "cash_balance", None))

        if theta_target_cfg is None:
            theta_low_target = nlv * Decimal("0.001")
            theta_high_target = nlv * Decimal("0.005")
        else:
            tgt = Decimal(str(theta_target_cfg))
            theta_low_target = nlv * tgt * Decimal("0.5")
            theta_high_target = nlv * tgt * Decimal("1.5")

        theta_status = "OK"
        if total_theta < theta_low_target:
            theta_status = f"LOW (Current: {total_theta:.2f}, Target > {theta_low_target:.2f})"
        elif total_theta > theta_high_target:
            theta_status = f"HIGH (Current: {total_theta:.2f}, Target < {theta_high_target:.2f})"

        if theta_status != "OK":
            collector.add(Alert(
                severity="warn",
                category="theta",
                message=theta_status,
                context={
                    "theta": float(total_theta),
                    "low": float(theta_low_target),
                    "high": float(theta_high_target),
                },
            ))

        bp_threshold_pct = bp_warn * Decimal(100)
        bp_threshold_pct_str = f"{float(bp_threshold_pct):g}"
        bp_usage_status = f"WARNING (>{bp_threshold_pct_str}%)" if bp_usage_pct > bp_threshold_pct else "OK"
        if bp_usage_pct > bp_threshold_pct:
            collector.add(Alert(
                severity="critical",
                category="bp",
                message=bp_usage_status,
                context={
                    "bp_usage_pct": float(bp_usage_pct),
                    "threshold_pct": float(bp_threshold_pct),
                },
            ))

        if day_trade_excess < 0:
            session_warnings.append(f"Day Trade Excess is NEGATIVE: ${day_trade_excess:.2f}")
            collector.add(Alert(
                severity="warn",
                category="bp",
                message=f"Day Trade Excess is NEGATIVE: ${day_trade_excess:.2f}",
                context={"day_trade_excess": float(day_trade_excess)},
            ))

        return {
            "nlv": nlv,
            "bp_usage_pct": bp_usage_pct,
            "bp_usage_status": bp_usage_status,
            "day_trade_excess": day_trade_excess,
            "day_trading_buying_power": day_trade_bp,
            "cash_balance": cash_balance,
            "trade_size_warnings": trade_size_warnings,
            "session_warnings": session_warnings,
            "portfolio_delta": total_delta,
            "portfolio_theta": total_theta,
            "theta_status": theta_status,
            "alerts": collector.get_active_alerts(),
            "concentration": concentration_result["by_underlying"],
            "correlation_concentration": concentration_result["by_bucket"],
        }

    def _analyze_concentration(
        self,
        per_underlying_value: Dict[str, float],
        nlv: float,
        alerts: AlertCollector,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Compute per-underlying + per-bucket concentration; emit 'concentration' alerts.

        Never raises on zero NLV or empty input. All numeric values in the
        returned lists are plain floats (JSON-safe).
        """
        raw_threshold = settings.get("concentration_pct_nlv_warn")
        coerced = _coerce_decimal(raw_threshold)
        if coerced is None:
            self.logger.warning(
                "Invalid concentration_pct_nlv_warn=%r; using default 0.15", raw_threshold
            )
            threshold = 0.15
        else:
            threshold = float(coerced)
        by_underlying: List[Dict[str, Any]] = []
        for sym, val in per_underlying_value.items():
            pct = (val / nlv) if nlv > 0 else 0.0
            flagged = pct >= threshold and nlv > 0
            by_underlying.append({
                "underlying": sym,
                "value": float(val),
                "pct_nlv": float(pct),
                "flagged": flagged,
            })
            if flagged:
                alerts.add(Alert(
                    severity="warn",
                    category="concentration",
                    message=f"{sym} is {pct*100:.1f}% of NLV (threshold {threshold*100:.0f}%)",
                    context={
                        "underlying": sym,
                        "value": float(val),
                        "pct_nlv": float(pct),
                        "threshold": float(threshold),
                    },
                ))
        by_underlying.sort(key=lambda r: r["pct_nlv"], reverse=True)

        grouped = group_by_bucket(((s, v) for s, v in per_underlying_value.items()))
        by_bucket: List[Dict[str, Any]] = []
        for bucket, pairs in grouped.items():
            if len(pairs) < 2:
                continue
            total = sum(v for _, v in pairs)
            pct = (total / nlv) if nlv > 0 else 0.0
            flagged = pct >= threshold and nlv > 0
            symbols = [s for s, _ in pairs]
            by_bucket.append({
                "bucket": bucket,
                "symbols": symbols,
                "value": float(total),
                "pct_nlv": float(pct),
                "flagged": flagged,
            })
            if flagged:
                alerts.add(Alert(
                    severity="warn",
                    category="concentration",
                    message=f"Correlation bucket {bucket} ({', '.join(symbols)}) "
                            f"is {pct*100:.1f}% of NLV",
                    context={
                        "bucket": bucket,
                        "symbols": list(symbols),
                        "value": float(total),
                        "pct_nlv": float(pct),
                        "threshold": float(threshold),
                    },
                ))
        by_bucket.sort(key=lambda r: r["pct_nlv"], reverse=True)

        return {"by_underlying": by_underlying, "by_bucket": by_bucket}

    async def _resolve_streamer_symbols(self, positions: List[Any]) -> Dict[str, str]:
        """Map OCC position symbols to DXLink streamer symbols via option-chain lookup.

        DXLink uses streamer-symbol format (e.g. .SPY250321P500) while positions use
        OCC symbols (e.g. SPY   250321P00500000). Groups lookups by underlying to
        minimize API calls.
        """
        occ_to_streamer: Dict[str, str] = {}
        by_underlying: Dict[str, List[str]] = {}
        for pos in positions:
            underlying = getattr(pos, "underlying_symbol", None)
            if underlying:
                by_underlying.setdefault(underlying, []).append(pos.symbol)
        for underlying, occ_symbols in by_underlying.items():
            try:
                chain = get_option_chain(self.session, underlying)
                for exp_date, options in chain.items():
                    for opt in options:
                        if opt.symbol in occ_symbols:
                            occ_to_streamer[opt.symbol] = opt.streamer_symbol
                if len(occ_to_streamer) >= sum(len(v) for v in by_underlying.values()):
                    break
            except Exception as e:
                self.logger.warning(f"Failed to resolve streamer symbols for {underlying}: {e}")
        return occ_to_streamer

    async def _fetch_greeks(self, symbols: List[str]) -> Dict[str, Greeks]:
        """Snapshot greeks for the given streamer symbols with a 5s hard timeout.

        Args:
            symbols: DXLink streamer symbols (not OCC symbols).
        """
        if not symbols:
            return {}
        results: Dict[str, Greeks] = {}
        try:
            async with DXLinkStreamer(self.session) as streamer:
                await streamer.subscribe(Greeks, symbols)
                start_time = asyncio.get_running_loop().time()
                timeout_s = 5.0
                agen = streamer.listen(Greeks)
                while len(results) < len(symbols):
                    remaining = timeout_s - (asyncio.get_running_loop().time() - start_time)
                    if remaining <= 0:
                        break
                    try:
                        greeks = await asyncio.wait_for(agen.__anext__(), timeout=min(0.5, remaining))
                    except asyncio.TimeoutError:
                        continue
                    except StopAsyncIteration:
                        break
                    if greeks.event_symbol in symbols:
                        results[greeks.event_symbol] = greeks
        except Exception as e:
            self.logger.error(f"Error fetching greeks: {e}")
        if len(results) < len(symbols):
            self.logger.warning(f"Timeout waiting for greeks. Got {len(results)}/{len(symbols)}")
        return results


def extract_decimal(value):
    """Coerce a numeric-ish value to Decimal, returning Decimal(0) for None."""
    if value is None:
        return Decimal(0)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _coerce_decimal(value: Any) -> Optional[Decimal]:
    """Return Decimal(value) or None if value is not a valid numeric literal."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _decimal_setting(key: str, default: Decimal) -> Decimal:
    """Read a numeric setting as Decimal, falling back to default on missing/invalid values."""
    result = _coerce_decimal(settings.get(key))
    if result is None:
        logging.getLogger(__name__).warning(
            "Invalid setting %s=%r; using default %s", key, settings.get(key), default
        )
        return default
    return result
