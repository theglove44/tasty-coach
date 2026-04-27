"""OptionsResearcherAgent - Research and score option trade ideas"""

import logging
import asyncio
from types import SimpleNamespace
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime, date, timezone
from dataclasses import dataclass, asdict, field
from decimal import Decimal, InvalidOperation
import math

from tastytrade import Session
from tastytrade.instruments import get_option_chain, OptionType
from tastytrade.metrics import get_market_metrics
from tastytrade.market_data import MarketData
from tastytrade.streamer import DXLinkStreamer
from tastytrade.dxfeed import Greeks


def _is_standard_monthly(exp_date: date, chain_dates: set) -> bool:
    """Standard equity-option monthlies expire the 3rd Friday of the month.

    When the 3rd Friday is a market holiday (Juneteenth on 2026-06-19,
    Good Friday in some years), the chain instead lists the 3rd-week Thursday.
    Treat that Thursday as the monthly when no Friday in the same week is in
    the chain.
    """
    if not (15 <= exp_date.day <= 21):
        return False
    weekday = exp_date.weekday()
    if weekday == 4:  # Friday
        return True
    if weekday == 3:  # Thursday: monthly only when no Friday-in-3rd-week is listed
        try:
            friday = exp_date.replace(day=exp_date.day + 1)
        except ValueError:
            return False
        return friday not in chain_dates
    return False


def _to_decimal(v: Any) -> Optional[Decimal]:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _parse_market_data_item(item: Dict[str, Any]) -> Any:
    """Lenient parse: try strict MarketData, else SimpleNamespace with the fields we use.

    The TastyTrade /market-data/by-type endpoint occasionally omits summary-date /
    prev-close-date for newly listed weekly options, which makes the strict SDK model
    raise. We don't use those fields, so fall back rather than dropping the row.
    """
    try:
        return MarketData(**item)
    except Exception:
        return SimpleNamespace(
            symbol=item.get("symbol"),
            bid=_to_decimal(item.get("bid")),
            ask=_to_decimal(item.get("ask")),
            mark=_to_decimal(item.get("mark")),
            mid=_to_decimal(item.get("mid")),
            volume=_to_decimal(item.get("volume")),
            open_interest=_to_decimal(item.get("open-interest")),
        )

# Module-level constants
DEFAULT_DTE_TARGET = 45
DTE_FALLBACK_MIN = 25
DTE_FALLBACK_MAX = 75
MONTHLY_DTE_MIN = 25
MONTHLY_DTE_MAX = 75
TARGET_SHORT_DELTA = 0.30
SHORT_DELTA_MIN = 0.15
SHORT_DELTA_MAX = 0.45
MIN_CREDIT_RATIO = 0.25
SPREAD_WIDTHS = [1, 2.5, 5, 10]
GREEKS_TIMEOUT_SECONDS = 8
MARKET_DATA_BATCH_SIZE = 20
MARKET_DATA_MAX_URL_CHARS = 400
MAX_IDEAS_RETURNED = 20


@dataclass
class StrikeRow:
    """Data for a single strike option"""
    streamer_symbol: str
    occ_symbol: str
    expiration: date
    option_type: str  # 'CALL' or 'PUT'
    strike: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    mid: Optional[float] = None
    volume: Optional[int] = None
    open_interest: Optional[int] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    iv: Optional[float] = None


@dataclass
class TradeIdea:
    """Complete trade idea with all metrics and scoring"""
    strategy: str  # 'BULL_PUT_SPREAD' | 'BEAR_CALL_SPREAD' | 'IRON_CONDOR'
    symbol: str
    expiration: date
    dte: int
    short_strike: float
    long_strike: float
    short_strike_call: Optional[float] = None
    long_strike_call: Optional[float] = None
    width: float = 0.0
    credit: float = 0.0
    max_loss: float = 0.0
    credit_pct_of_width: float = 0.0
    short_delta: float = 0.0
    net_delta: float = 0.0
    net_theta: float = 0.0
    net_vega: float = 0.0
    net_gamma: float = 0.0
    breakeven: List[float] = field(default_factory=list)
    pop_estimate: float = 0.0
    score: float = 0.0
    score_breakdown: Dict[str, Any] = field(default_factory=dict)
    legs: List[Dict[str, Any]] = field(default_factory=list)


class OptionsResearcherAgent:
    """Research options chains and score trade ideas"""

    def __init__(
        self,
        session: Session,
        min_credit_ratio: Optional[float] = None,
        min_delta: Optional[float] = None,
        max_delta: Optional[float] = None,
    ) -> None:
        self.session = session
        self.logger = logging.getLogger(__name__)
        self.min_credit_ratio = (
            min_credit_ratio if min_credit_ratio is not None else MIN_CREDIT_RATIO
        )
        self.min_delta = min_delta if min_delta is not None else SHORT_DELTA_MIN
        self.max_delta = max_delta if max_delta is not None else SHORT_DELTA_MAX

    async def research(
        self,
        symbol: str,
        expiration: Optional[date] = None,
    ) -> Dict[str, Any]:
        """
        Research options chain for a symbol and return ranked trade ideas.

        Args:
            symbol: Underlying symbol (e.g., 'AAPL')
            expiration: Optional target expiration date

        Returns:
            Dict with status, trade ideas, and metadata
        """
        # Normalize symbol
        symbol = symbol.strip().upper()
        if not symbol:
            return self._to_report(
                symbol=symbol,
                expiration=None,
                resolution_mode='NONE',
                ivr=None,
                iv=None,
                rows=[],
                ideas=[],
                status='INVALID_SYMBOL',
                warnings=[]
            )

        # Get option chain
        try:
            chain = get_option_chain(self.session, symbol)
        except Exception as e:
            self.logger.error(f"Error fetching chain for {symbol}: {e}")
            return self._to_report(
                symbol=symbol,
                expiration=None,
                resolution_mode='NONE',
                ivr=None,
                iv=None,
                rows=[],
                ideas=[],
                status='NO_CHAIN',
                warnings=[str(e)]
            )

        if not chain:
            return self._to_report(
                symbol=symbol,
                expiration=None,
                resolution_mode='NONE',
                ivr=None,
                iv=None,
                rows=[],
                ideas=[],
                status='NO_CHAIN',
                warnings=[]
            )

        # Resolve expiration
        expiration_date, mode = await self._resolve_expiration(chain, expiration)

        warnings: List[str] = []

        # If explicit expiration requested but not found
        if expiration is not None and mode == 'NONE':
            available = sorted([d.isoformat() for d in chain.keys()])
            warnings.append(
                f"Requested expiration {expiration.isoformat()} not found in chain. "
                f"Available: {', '.join(available[:10])}"
            )
            return self._to_report(
                symbol=symbol,
                expiration=expiration,
                resolution_mode=mode,
                ivr=None,
                iv=None,
                rows=[],
                ideas=[],
                status='EXPIRATION_NOT_FOUND',
                warnings=warnings
            )

        # If no viable expiration found at all
        if expiration_date is None:
            return self._to_report(
                symbol=symbol,
                expiration=None,
                resolution_mode=mode,
                ivr=None,
                iv=None,
                rows=[],
                ideas=[],
                status='NO_VIABLE_EXPIRATION',
                warnings=[]
            )

        # Fetch metrics
        ivr, iv = await self._fetch_metrics(symbol)
        if ivr is None or iv is None:
            warnings.append("Could not fetch IV metrics")

        # Build enriched chain
        options = chain[expiration_date]
        try:
            rows = await self._build_enriched_chain(options, expiration_date)
        except Exception as e:
            self.logger.error(f"Error building enriched chain: {e}")
            return self._to_report(
                symbol=symbol,
                expiration=expiration_date,
                resolution_mode=mode,
                ivr=ivr,
                iv=iv,
                rows=[],
                ideas=[],
                status='NO_GREEKS',
                warnings=warnings + [str(e)]
            )

        if not rows:
            return self._to_report(
                symbol=symbol,
                expiration=expiration_date,
                resolution_mode=mode,
                ivr=ivr,
                iv=iv,
                rows=[],
                ideas=[],
                status='NO_GREEKS',
                warnings=warnings + ["No strikes with greeks data"]
            )

        # Calculate DTE
        dte = (expiration_date - date.today()).days

        # Build ideas
        ideas_list: List[TradeIdea] = []

        # Build Bull Put Spreads (put verticals)
        put_rows = [r for r in rows if r.option_type == 'PUT']
        put_idea = self._build_vertical(put_rows, 'PUT', symbol, expiration_date, dte)
        if put_idea:
            ideas_list.append(put_idea)

        # Build Bear Call Spreads (call verticals)
        call_rows = [r for r in rows if r.option_type == 'CALL']
        call_idea = self._build_vertical(call_rows, 'CALL', symbol, expiration_date, dte)
        if call_idea:
            ideas_list.append(call_idea)

        # Build Iron Condor
        if put_idea and call_idea:
            ic_idea = self._build_iron_condor(rows, symbol, expiration_date, dte)
            if ic_idea:
                ideas_list.append(ic_idea)

        # Rank and trim
        ranked_ideas = self._rank_and_trim(ideas_list)

        status = 'OK' if ranked_ideas else 'NO_VIABLE_IDEAS'

        return self._to_report(
            symbol=symbol,
            expiration=expiration_date,
            resolution_mode=mode,
            ivr=ivr,
            iv=iv,
            rows=rows,
            ideas=ranked_ideas,
            status=status,
            warnings=warnings
        )

    async def _resolve_expiration(
        self,
        chain: Dict[date, List],
        requested: Optional[date],
    ) -> Tuple[Optional[date], str]:
        """
        Resolve target expiration from chain. Defaults to standard monthlies only
        (3rd Friday, or 3rd-week Thursday when Friday is a market holiday like
        Juneteenth/Good Friday). Weeklies and quarterlies are ignored — they
        carry far less open interest at the ~30-delta strikes we screen.

        Returns:
            (expiration_date, resolution_mode)
            resolution_mode: 'EXPLICIT', 'MONTHLY', or 'NONE'
        """
        # If explicit expiration requested, honor it as-is (operator override)
        if requested is not None:
            if requested in chain:
                return (requested, 'EXPLICIT')
            else:
                return (None, 'NONE')

        today = date.today()
        chain_dates = set(chain.keys())
        candidates = []

        # Iterate sorted chain keys so candidate order is deterministic across
        # runs/processes (set iteration is hash-randomized).
        for exp_date in sorted(chain_dates):
            dte = (exp_date - today).days
            if not (MONTHLY_DTE_MIN <= dte <= MONTHLY_DTE_MAX):
                continue
            if not _is_standard_monthly(exp_date, chain_dates):
                continue
            candidates.append((abs(dte - DEFAULT_DTE_TARGET), dte, exp_date))

        if candidates:
            # Sort by (distance-from-target, dte, exp_date) — on a tie of equal
            # distance (e.g. 31 and 59 DTE both 14 from 45), prefer the earlier
            # expiration; exp_date is the final tiebreaker for absolute determinism.
            candidates.sort(key=lambda x: (x[0], x[1], x[2]))
            return (candidates[0][2], 'MONTHLY')

        return (None, 'NONE')

    async def _build_enriched_chain(
        self,
        options: List,
        expiration: date,
    ) -> List[StrikeRow]:
        """
        Build enriched strike rows with market data and greeks.

        Args:
            options: List of option objects from chain
            expiration: Expiration date

        Returns:
            List of StrikeRow objects, sorted by (option_type, strike)
        """
        if not options:
            return []

        # Collect streamer and OCC symbols
        streamer_symbols = [o.streamer_symbol for o in options]
        occ_symbols = [o.symbol for o in options]

        md_map = await self._fetch_market_data_batched(occ_symbols)

        # Fetch greeks
        greeks_map: Dict[str, Greeks] = {}
        try:
            greeks_map = await self._fetch_greeks(streamer_symbols, timeout=GREEKS_TIMEOUT_SECONDS)
        except Exception as e:
            self.logger.warning(f"Error fetching greeks: {e}")

        # Build rows
        rows: List[StrikeRow] = []
        dropped_count = 0

        for opt in options:
            # Get market data
            md = md_map.get(opt.symbol)
            bid = float(md.bid) if md and md.bid is not None else None
            ask = float(md.ask) if md and md.ask is not None else None
            mark = float(md.mark) if md and md.mark is not None else None

            # Calculate mid
            if bid is not None and ask is not None:
                mid = (bid + ask) / 2.0
            elif mark is not None:
                mid = mark
            else:
                mid = None

            # Get greeks
            greek = greeks_map.get(opt.streamer_symbol)
            delta = float(greek.delta) if greek and greek.delta is not None else None
            gamma = float(greek.gamma) if greek and greek.gamma is not None else None
            theta = float(greek.theta) if greek and greek.theta is not None else None
            vega = float(greek.vega) if greek and greek.vega is not None else None
            iv = float(greek.volatility) if greek and greek.volatility is not None else None

            # Skip if no delta
            if delta is None:
                dropped_count += 1
                continue

            # Get volume and OI (SDK returns Decimal; coerce to int for math safety)
            volume_raw = getattr(md, 'volume', None) if md else None
            oi_raw = getattr(md, 'open_interest', None) if md else None
            volume = int(volume_raw) if volume_raw is not None else None
            open_interest = int(oi_raw) if oi_raw is not None else None

            row = StrikeRow(
                streamer_symbol=opt.streamer_symbol,
                occ_symbol=opt.symbol,
                expiration=expiration,
                option_type='CALL' if opt.option_type == OptionType.CALL else 'PUT',
                strike=float(opt.strike_price),
                bid=bid,
                ask=ask,
                mid=mid,
                volume=volume,
                open_interest=open_interest,
                delta=delta,
                gamma=gamma,
                theta=theta,
                vega=vega,
                iv=iv,
            )
            rows.append(row)

        if dropped_count > 0:
            self.logger.info(f"Dropped {dropped_count} strikes without delta data")

        # Sort by (option_type, strike)
        rows.sort(key=lambda r: (r.option_type, r.strike))

        return rows

    async def _fetch_market_data_batched(self, occ_symbols: List[str]) -> Dict[str, Any]:
        """Fetch market data with URL-length-aware batching and halving retry on failure."""
        md_map: Dict[str, Any] = {}
        if not occ_symbols:
            return md_map

        batches: List[List[str]] = []
        current: List[str] = []
        current_chars = 0
        for sym in occ_symbols:
            sym_chars = len(sym) + 3
            if current and (
                len(current) >= MARKET_DATA_BATCH_SIZE
                or current_chars + sym_chars > MARKET_DATA_MAX_URL_CHARS
            ):
                batches.append(current)
                current = []
                current_chars = 0
            current.append(sym)
            current_chars += sym_chars
        if current:
            batches.append(current)

        def fetch(batch: List[str], depth: int = 0) -> None:
            if not batch:
                return
            try:
                params = {"equity-option": batch}
                data = self.session._get("/market-data/by-type", params=params)
                for item in data["items"]:
                    md = _parse_market_data_item(item)
                    if md.symbol:
                        md_map[md.symbol] = md
            except Exception as e:
                if len(batch) == 1 or depth >= 4:
                    self.logger.warning(
                        f"Error fetching market data batch (size={len(batch)}): {e}"
                    )
                    return
                self.logger.debug(
                    f"Batch failed (size={len(batch)}), splitting: {e}"
                )
                mid = len(batch) // 2
                fetch(batch[:mid], depth + 1)
                fetch(batch[mid:], depth + 1)

        for b in batches:
            fetch(b)

        return md_map

    async def _fetch_greeks(self, streamer_symbols: List[str], timeout: int) -> Dict[str, Greeks]:
        """Fetch Greeks for streamer symbols with timeout"""
        greeks_map: Dict[str, Greeks] = {}
        if not streamer_symbols:
            return greeks_map

        try:
            async with DXLinkStreamer(self.session) as streamer:
                await streamer.subscribe(Greeks, streamer_symbols)
                start_time = asyncio.get_running_loop().time()

                while len(greeks_map) < len(streamer_symbols):
                    if asyncio.get_running_loop().time() - start_time > timeout:
                        self.logger.warning(
                            f"Timeout reaching all greeks. Got {len(greeks_map)}/{len(streamer_symbols)}"
                        )
                        break

                    async for event in streamer.listen(Greeks):
                        if isinstance(event, Greeks):
                            greeks_map[event.event_symbol] = event

                        if len(greeks_map) >= len(streamer_symbols):
                            break

                        if asyncio.get_running_loop().time() - start_time > timeout:
                            break
        except Exception as e:
            self.logger.error(f"Error fetching greeks: {e}")

        return greeks_map

    def _find_short_leg(
        self,
        rows: List[StrikeRow],
        option_type: str,
        target_delta: float = TARGET_SHORT_DELTA,
    ) -> Optional[StrikeRow]:
        """
        Find best short leg (closest to target delta).

        Args:
            rows: List of StrikeRow objects
            option_type: 'CALL' or 'PUT'
            target_delta: Target delta (0.30)

        Returns:
            Best matching StrikeRow or None
        """
        candidates = [
            r for r in rows
            if r.option_type == option_type
            and r.delta is not None
            and self.min_delta <= abs(r.delta) <= self.max_delta
        ]

        if not candidates:
            return None

        # Pick the one with delta closest to target
        best = min(candidates, key=lambda r: abs(abs(r.delta) - target_delta))
        return best

    def _find_long_leg(
        self,
        rows: List[StrikeRow],
        option_type: str,
        short_strike: float,
        width: float,
    ) -> Optional[StrikeRow]:
        """
        Find long leg at appropriate width from short strike.

        Args:
            rows: List of StrikeRow objects
            option_type: 'CALL' or 'PUT'
            short_strike: Strike price of short leg
            width: Spread width

        Returns:
            StrikeRow if found, None otherwise
        """
        # Calculate target strike
        if option_type == 'PUT':
            target_strike = short_strike - width
        else:  # CALL
            target_strike = short_strike + width

        # Find exact match (with tolerance for float comparison)
        candidates = [
            r for r in rows
            if r.option_type == option_type
            and abs(r.strike - target_strike) < 0.001
            and r.mid is not None
        ]

        if candidates:
            return candidates[0]
        return None

    def _build_vertical(
        self,
        rows: List[StrikeRow],
        option_type: str,
        symbol: str,
        expiration: date,
        dte: int,
    ) -> Optional[TradeIdea]:
        """
        Build a vertical spread (bull put or bear call).

        Args:
            rows: List of StrikeRow objects for this option type
            option_type: 'PUT' or 'CALL'
            symbol: Underlying symbol
            expiration: Expiration date
            dte: Days to expiration

        Returns:
            TradeIdea if viable, None otherwise
        """
        # Find short leg
        short = self._find_short_leg(rows, option_type)
        if short is None:
            return None

        # Try each width
        best_idea: Optional[TradeIdea] = None
        best_score = -1.0

        for width in SPREAD_WIDTHS:
            # Find long leg
            long = self._find_long_leg(rows, option_type, short.strike, width)
            if long is None:
                continue

            # Calculate credit
            credit = short.mid - long.mid
            if credit <= 0:
                continue

            # Check minimum credit ratio
            credit_pct = credit / width
            if credit_pct < self.min_credit_ratio:
                self.logger.debug(
                    f"{symbol} {option_type} spread: credit {credit_pct:.2%} < {self.min_credit_ratio:.2%}"
                )
                continue

            # Calculate net Greeks (short = negative, long = positive)
            net_delta = -(short.delta or 0) + (long.delta or 0)
            net_gamma = -(short.gamma or 0) + (long.gamma or 0)
            net_theta = -(short.theta or 0) + (long.theta or 0)
            net_vega = -(short.vega or 0) + (long.vega or 0)

            # Calculate max loss and breakeven
            max_loss = width - credit
            if option_type == 'PUT':
                breakeven = [short.strike - credit]
            else:  # CALL
                breakeven = [short.strike + credit]

            # Probability of profit
            pop = 1.0 - abs(short.delta or 0)

            # Determine strategy type
            strategy_type = 'BULL_PUT_SPREAD' if option_type == 'PUT' else 'BEAR_CALL_SPREAD'

            # Build idea draft
            idea_draft = {
                'credit_pct_of_width': credit_pct,
                'short_delta': short.delta,
                'dte': dte,
                'legs': [short, long],
            }

            # Score it
            score, score_breakdown = self._score_idea(idea_draft)

            # Track best
            if score > best_score:
                best_score = score
                best_idea = TradeIdea(
                    strategy=strategy_type,
                    symbol=symbol,
                    expiration=expiration,
                    dte=dte,
                    short_strike=short.strike,
                    long_strike=long.strike,
                    width=width,
                    credit=credit,
                    max_loss=max_loss,
                    credit_pct_of_width=credit_pct,
                    short_delta=short.delta,
                    net_delta=net_delta,
                    net_theta=net_theta,
                    net_vega=net_vega,
                    net_gamma=net_gamma,
                    breakeven=breakeven,
                    pop_estimate=pop,
                    score=score,
                    score_breakdown=score_breakdown,
                    legs=[
                        {
                            'action': 'SELL',
                            'option_type': option_type,
                            'strike': short.strike,
                            'occ_symbol': short.occ_symbol,
                            'streamer_symbol': short.streamer_symbol,
                            'bid': short.bid,
                            'ask': short.ask,
                            'mid': short.mid,
                            'volume': short.volume,
                            'open_interest': short.open_interest,
                            'delta': short.delta,
                            'gamma': short.gamma,
                            'theta': short.theta,
                            'vega': short.vega,
                            'iv': short.iv,
                        },
                        {
                            'action': 'BUY',
                            'option_type': option_type,
                            'strike': long.strike,
                            'occ_symbol': long.occ_symbol,
                            'streamer_symbol': long.streamer_symbol,
                            'bid': long.bid,
                            'ask': long.ask,
                            'mid': long.mid,
                            'volume': long.volume,
                            'open_interest': long.open_interest,
                            'delta': long.delta,
                            'gamma': long.gamma,
                            'theta': long.theta,
                            'vega': long.vega,
                            'iv': long.iv,
                        },
                    ],
                )

        return best_idea

    def _build_iron_condor(
        self,
        rows: List[StrikeRow],
        symbol: str,
        expiration: date,
        dte: int,
    ) -> Optional[TradeIdea]:
        """
        Build an iron condor (bull put + bear call).

        Args:
            rows: List of all StrikeRow objects
            symbol: Underlying symbol
            expiration: Expiration date
            dte: Days to expiration

        Returns:
            TradeIdea if viable, None otherwise
        """
        # Build the two sides
        put_rows = [r for r in rows if r.option_type == 'PUT']
        call_rows = [r for r in rows if r.option_type == 'CALL']

        put_idea = self._build_vertical(put_rows, 'PUT', symbol, expiration, dte)
        call_idea = self._build_vertical(call_rows, 'CALL', symbol, expiration, dte)

        if put_idea is None or call_idea is None:
            return None

        # Combine
        total_credit = put_idea.credit + call_idea.credit
        ic_width = max(put_idea.width, call_idea.width)
        max_loss = ic_width - total_credit

        if max_loss <= 0:
            return None

        credit_pct = total_credit / ic_width
        pop = (1.0 - abs(put_idea.short_delta or 0)) * (1.0 - abs(call_idea.short_delta or 0))

        net_delta = put_idea.net_delta + call_idea.net_delta
        net_theta = put_idea.net_theta + call_idea.net_theta
        net_vega = put_idea.net_vega + call_idea.net_vega
        net_gamma = put_idea.net_gamma + call_idea.net_gamma

        breakevens = [
            put_idea.short_strike - total_credit,
            call_idea.short_strike + total_credit,
        ]

        # Score
        idea_draft = {
            'credit_pct_of_width': credit_pct,
            'short_delta': min(abs(put_idea.short_delta or 0), abs(call_idea.short_delta or 0)),
            'dte': dte,
            'legs': put_idea.legs + call_idea.legs,
        }
        score, score_breakdown = self._score_idea(idea_draft)

        return TradeIdea(
            strategy='IRON_CONDOR',
            symbol=symbol,
            expiration=expiration,
            dte=dte,
            short_strike=put_idea.short_strike,
            long_strike=put_idea.long_strike,
            short_strike_call=call_idea.short_strike,
            long_strike_call=call_idea.long_strike,
            width=ic_width,
            credit=total_credit,
            max_loss=max_loss,
            credit_pct_of_width=credit_pct,
            short_delta=min(abs(put_idea.short_delta or 0), abs(call_idea.short_delta or 0)),
            net_delta=net_delta,
            net_theta=net_theta,
            net_vega=net_vega,
            net_gamma=net_gamma,
            breakeven=breakevens,
            pop_estimate=pop,
            score=score,
            score_breakdown=score_breakdown,
            legs=put_idea.legs + call_idea.legs,
        )

    def _score_idea(self, idea_draft: Dict[str, Any]) -> Tuple[float, Dict[str, float]]:
        """
        Score a trade idea using the formula.

        Args:
            idea_draft: Dict with credit_pct_of_width, short_delta, dte, legs

        Returns:
            (score, score_breakdown)
        """
        credit_pct = idea_draft.get('credit_pct_of_width', 0.0)
        short_delta = idea_draft.get('short_delta', 0.3)
        dte = idea_draft.get('dte', 45)
        legs = idea_draft.get('legs', [])

        # Credit component
        if self.min_credit_ratio > 0:
            C = self._clamp((credit_pct - self.min_credit_ratio) / self.min_credit_ratio, 0, 1)
        else:
            C = 0.0

        # Delta component
        D = 1.0 - min(abs(abs(short_delta) - 0.30) / 0.10, 1.0)

        # DTE component
        if 30 <= dte <= 60:
            T = 1.0
        elif 21 <= dte < 30:
            T = (dte - 21) / 9.0
        elif 60 < dte <= 75:
            T = (75 - dte) / 15.0
        else:
            T = 0.0

        # Liquidity component
        L = self._calculate_liquidity_score(legs)

        # Overall score
        score = 40 * C + 25 * D + 20 * T + 15 * L

        score_breakdown = {
            'credit': 40 * C,
            'delta': 25 * D,
            'dte': 20 * T,
            'liquidity': 15 * L,
            'raw_components': {
                'credit_component': C,
                'delta_component': D,
                'dte_component': T,
                'liquidity_component': L,
            }
        }

        return score, score_breakdown

    def _calculate_liquidity_score(self, legs: List[Any]) -> float:
        """Calculate liquidity score for legs"""
        if not legs:
            return 0.5

        oi_scores = []
        spread_pcts = []

        for leg in legs:
            oi = leg.open_interest if isinstance(leg, StrikeRow) else leg.get('open_interest')
            bid = leg.bid if isinstance(leg, StrikeRow) else leg.get('bid')
            ask = leg.ask if isinstance(leg, StrikeRow) else leg.get('ask')
            mid = leg.mid if isinstance(leg, StrikeRow) else leg.get('mid')

            # OI score
            if oi is not None:
                oi_scores.append(min(oi / 500.0, 1.0))
            else:
                oi_scores.append(0.5)

            # Bid-ask spread (collect raw pct, take max across all legs)
            if bid is not None and ask is not None and mid is not None and mid > 0:
                spread_pcts.append((ask - bid) / mid)

        min_oi_score = min(oi_scores) if oi_scores else 0.5

        # Use WORST (max) spread across all legs, per plan formula
        if spread_pcts:
            worst_spread_pct = max(spread_pcts)
            spread_score = 1.0 - self._clamp(worst_spread_pct / 0.15, 0.0, 1.0)
        else:
            spread_score = 0.5  # neutral fallback when no bid/ask data

        return 0.5 * min_oi_score + 0.5 * spread_score

    def _rank_and_trim(self, ideas: List[TradeIdea]) -> List[TradeIdea]:
        """
        Sort ideas by score and trim to MAX_IDEAS_RETURNED.

        Args:
            ideas: List of TradeIdea objects

        Returns:
            Sorted, trimmed list
        """
        sorted_ideas = sorted(ideas, key=lambda i: i.score, reverse=True)
        return sorted_ideas[:MAX_IDEAS_RETURNED]

    def _to_report(
        self,
        symbol: str,
        expiration: Optional[date],
        resolution_mode: str,
        ivr: Optional[float],
        iv: Optional[float],
        rows: List[StrikeRow],
        ideas: List[TradeIdea],
        status: str,
        warnings: List[str],
    ) -> Dict[str, Any]:
        """
        Build final report dictionary for serialization.

        Args:
            All parameters as documented

        Returns:
            Report dict with all data serialized for JSON
        """
        # Calculate chain summary
        call_count = len([r for r in rows if r.option_type == 'CALL'])
        put_count = len([r for r in rows if r.option_type == 'PUT'])
        total_count = len(rows)
        strikes_with_greeks = len([r for r in rows if r.delta is not None])

        chain_summary = {
            'total_strikes': total_count,
            'calls': call_count,
            'puts': put_count,
            'strikes_with_greeks': strikes_with_greeks,
        }

        # Build trade ideas list with rank
        ideas_list = []
        for rank, idea in enumerate(ideas, 1):
            leg_dicts = []
            for leg in idea.legs:
                if isinstance(leg, StrikeRow):
                    leg_dict = {
                        'action': 'SELL',  # placeholder, will be overridden below
                        'option_type': leg.option_type,
                        'strike': leg.strike,
                        'occ_symbol': leg.occ_symbol,
                        'streamer_symbol': leg.streamer_symbol,
                        'bid': leg.bid,
                        'ask': leg.ask,
                        'mid': leg.mid,
                        'volume': leg.volume,
                        'open_interest': leg.open_interest,
                        'delta': leg.delta,
                        'gamma': leg.gamma,
                        'theta': leg.theta,
                        'vega': leg.vega,
                        'iv': leg.iv,
                    }
                else:
                    leg_dict = dict(leg)
                leg_dicts.append(leg_dict)

            idea_dict = {
                'rank': rank,
                'strategy': idea.strategy,
                'expiration': idea.expiration.isoformat(),
                'dte': idea.dte,
                'width': idea.width,
                'credit': idea.credit,
                'max_loss': idea.max_loss,
                'credit_pct_of_width': idea.credit_pct_of_width,
                'short_delta': idea.short_delta,
                'pop_estimate': idea.pop_estimate,
                'breakevens': idea.breakeven,
                'net_greeks': {
                    'delta': idea.net_delta,
                    'gamma': idea.net_gamma,
                    'theta': idea.net_theta,
                    'vega': idea.net_vega,
                },
                'legs': leg_dicts,
                'score': idea.score,
                'score_breakdown': idea.score_breakdown,
            }
            ideas_list.append(idea_dict)

        underlying = {'ivr': ivr, 'iv': iv}

        report = {
            'status': status,
            'symbol': symbol,
            'generated_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'expiration': expiration.isoformat() if expiration else None,
            'dte': (expiration - date.today()).days if expiration else None,
            'expiration_resolution': resolution_mode,
            'underlying': underlying,
            'chain_summary': chain_summary,
            'warnings': warnings,
            'trade_ideas': ideas_list,
        }

        return report

    async def _fetch_metrics(self, symbol: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Fetch IV metrics for underlying.

        Args:
            symbol: Underlying symbol

        Returns:
            (ivr, iv) or (None, None) if fetch fails
        """
        try:
            metrics = get_market_metrics(self.session, [symbol])
            if not metrics:
                return (None, None)

            m = metrics[0]

            ivr = None
            if m.implied_volatility_index_rank is not None:
                ivr = float(m.implied_volatility_index_rank) * 100

            iv = None
            if m.implied_volatility_index is not None:
                iv = float(m.implied_volatility_index)

            return (ivr, iv)
        except Exception as e:
            self.logger.error(f"Error fetching metrics for {symbol}: {e}")
            return (None, None)

    @staticmethod
    def _clamp(value: float, min_val: float, max_val: float) -> float:
        """Clamp value to [min_val, max_val]"""
        return max(min_val, min(max_val, value))
