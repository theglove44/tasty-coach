"""
Market Quality Dashboard — "Should I Be Trading Today?"

Scores the market across 5 pillars (Volatility, Trend, Breadth, Momentum, Macro)
to produce a composite 0–100 score and a YES / CAUTION / NO trading decision.
"""

import logging
import asyncio
import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from tastytrade import Session
from tastytrade.market_data import get_market_data_by_type
from tastytrade.metrics import get_market_metrics
from tastytrade.streamer import DXLinkStreamer
from tastytrade.dxfeed import Candle, Underlying

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns
from rich.text import Text
from rich import box

# ── Symbol Universe ──────────────────────────────────────────────────────────
SECTOR_ETFS = ['XLB', 'XLC', 'XLE', 'XLF', 'XLI', 'XLK', 'XLP', 'XLRE', 'XLU', 'XLV', 'XLY']
SECTOR_NAMES = {
    'XLB': 'Materials', 'XLC': 'Comms', 'XLE': 'Energy', 'XLF': 'Financials',
    'XLI': 'Industrials', 'XLK': 'Technology', 'XLP': 'Staples', 'XLRE': 'Real Estate',
    'XLU': 'Utilities', 'XLV': 'Healthcare', 'XLY': 'Cons. Disc.',
}
CYCLICAL_SECTORS = {'XLY', 'XLF', 'XLI', 'XLK', 'XLB', 'XLE'}
DEFENSIVE_SECTORS = {'XLU', 'XLV', 'XLP', 'XLRE', 'XLC'}
ALL_EQUITIES = ['SPY', 'QQQ'] + SECTOR_ETFS + ['UUP', 'TLT']

# ── Scoring Weights ──────────────────────────────────────────────────────────
WEIGHTS = {
    'volatility': 0.25,
    'trend': 0.20,
    'breadth': 0.20,
    'momentum': 0.25,
    'macro': 0.10,
}

# ── Scoring Constants ────────────────────────────────────────────────────────
VIX_BREAKPOINTS = [(15, 100), (20, 80), (25, 60), (30, 40), (35, 0)]
DEFAULT_SCORE = 50  # Used when data is missing

logger = logging.getLogger(__name__)


# ── Helper: linear interpolation between breakpoints ─────────────────────────
def _interp(value: float, breakpoints: List[Tuple[float, float]]) -> float:
    """Linearly interpolate a value through a list of (threshold, score) pairs."""
    if value <= breakpoints[0][0]:
        return breakpoints[0][1]
    for i in range(1, len(breakpoints)):
        x0, y0 = breakpoints[i - 1]
        x1, y1 = breakpoints[i]
        if value <= x1:
            t = (value - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return breakpoints[-1][1]


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


# ── Technical helpers ────────────────────────────────────────────────────────
def _sma(closes: List[float], period: int) -> Optional[float]:
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def _rsi(closes: List[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(-period, 0)]
    gains = [d for d in deltas if d > 0]
    losses = [-d for d in deltas if d < 0]
    avg_gain = sum(gains) / period if gains else 0.0
    avg_loss = sum(losses) / period if losses else 0.001
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _slope_5d(closes: List[float]) -> Optional[float]:
    """Simple 5-day percent change as trend proxy."""
    if len(closes) < 6:
        return None
    return (closes[-1] - closes[-6]) / closes[-6] * 100


def _slope_20d(closes: List[float]) -> Optional[float]:
    """20-day percent change."""
    if len(closes) < 21:
        return None
    return (closes[-1] - closes[-21]) / closes[-21] * 100


class DashboardAgent:
    """Fetches market data and computes a composite trading quality score."""

    def __init__(self, session: Session):
        self.session = session
        self.console = Console()
        self.warnings: List[str] = []

        # Raw data containers
        self.equity_data: Dict = {}   # symbol -> market data object
        self.index_data: Dict = {}    # VIX, TNX
        self.vix_metrics: Optional[object] = None
        self.candles: Dict[str, List[float]] = {}  # symbol -> sorted closes
        self.put_call_ratio: Optional[float] = None

        # Scores
        self.pillar_scores: Dict[str, float] = {}
        self.pillar_details: Dict[str, Dict] = {}
        self.composite: float = 0.0

    # ── Data Fetching ────────────────────────────────────────────────────

    def _fetch_rest_data(self) -> None:
        """Fetch all REST data (synchronous SDK calls)."""
        try:
            eq_data = await get_market_data_by_type(self.session, equities=ALL_EQUITIES)
            self.equity_data = {d.symbol: d for d in eq_data}
        except Exception as e:
            logger.error(f"Failed to fetch equity data: {e}")
            self.warnings.append("Equity market data unavailable")

        try:
            idx_data = await get_market_data_by_type(self.session, indices=['VIX', 'TNX'])
            self.index_data = {d.symbol: d for d in idx_data}
        except Exception as e:
            logger.error(f"Failed to fetch index data: {e}")
            self.warnings.append("Index data unavailable")

        try:
            metrics = get_market_metrics(self.session, ['VIX'])
            self.vix_metrics = metrics[0] if metrics else None
        except Exception as e:
            logger.error(f"Failed to fetch VIX metrics: {e}")
            self.warnings.append("VIX metrics unavailable")

    async def _fetch_streaming_data(self) -> None:
        """Open one DXLinkStreamer session for candles + underlying."""
        # VIX is an index — candle data may not be available; TLT replaces TNX
        candle_symbols = ['SPY', 'QQQ', 'UUP', 'TLT'] + SECTOR_ETFS
        optional_candle_symbols = ['VIX']
        all_candle_symbols = candle_symbols + optional_candle_symbols
        start_time = datetime.now() - timedelta(days=300)

        try:
            async with DXLinkStreamer(self.session) as streamer:
                # Subscribe to candles for all symbols
                await streamer.subscribe_candle(all_candle_symbols, '1d', start_time)
                # Subscribe to Underlying for put/call ratio
                await streamer.subscribe(Underlying, ['SPY'])

                raw_candles: Dict[str, Dict[int, float]] = {s: {} for s in all_candle_symbols}

                # Phase 1: drain candle events (bulk arrives quickly)
                idle_count = 0
                deadline = time.time() + 25.0
                while time.time() < deadline and idle_count < 5:
                    try:
                        ev = await asyncio.wait_for(streamer.get_event(Candle), timeout=2.0)
                        if ev and ev.event_symbol:
                            ticker = ev.event_symbol.split('{')[0]
                            if ticker in raw_candles and ev.close and float(ev.close) > 0:
                                raw_candles[ticker][ev.time] = float(ev.close)
                            idle_count = 0
                        else:
                            idle_count += 1
                    except asyncio.TimeoutError:
                        idle_count += 1
                        # Check if we have enough for required symbols
                        required_done = all(len(raw_candles[s]) >= 50 for s in candle_symbols)
                        if required_done:
                            break

                # Phase 2: grab Underlying event (usually arrives quickly)
                for _ in range(5):
                    try:
                        uev = await asyncio.wait_for(streamer.get_event(Underlying), timeout=1.0)
                        if uev and uev.put_call_ratio is not None:
                            self.put_call_ratio = float(uev.put_call_ratio)
                            break
                    except asyncio.TimeoutError:
                        break

                # Convert raw candles to sorted close arrays
                for symbol, time_close_map in raw_candles.items():
                    if time_close_map:
                        sorted_closes = [c for _, c in sorted(time_close_map.items())]
                        self.candles[symbol] = sorted_closes

                received = {s: len(v) for s, v in raw_candles.items() if v}
                logger.debug(f"Candle data received: {received}")

        except Exception as e:
            logger.error(f"Streaming failed: {e}")
            self.warnings.append(f"Streaming data partial or unavailable: {e}")

    async def fetch_all(self) -> None:
        """Fetch REST + streaming data."""
        self._fetch_rest_data()
        await self._fetch_streaming_data()

    # ── Scoring Engine ───────────────────────────────────────────────────

    def _get_price(self, symbol: str) -> Optional[float]:
        d = self.equity_data.get(symbol) or self.index_data.get(symbol)
        if d and d.last:
            return float(d.last)
        return None

    def _get_prev_close(self, symbol: str) -> Optional[float]:
        d = self.equity_data.get(symbol) or self.index_data.get(symbol)
        if d and d.prev_close:
            return float(d.prev_close)
        return None

    def _score_with_default(self, value: Optional[float], scorer, label: str) -> float:
        if value is None:
            self.warnings.append(f"{label}: using default score ({DEFAULT_SCORE})")
            return DEFAULT_SCORE
        return _clamp(scorer(value))

    def score_volatility(self) -> float:
        details: Dict = {}

        # VIX Level
        vix = self._get_price('VIX')
        vix_score = self._score_with_default(
            vix, lambda v: _interp(v, VIX_BREAKPOINTS), "VIX level"
        )
        details['vix_level'] = vix
        details['vix_level_score'] = vix_score

        # VIX 5d Trend
        vix_closes = self.candles.get('VIX', [])
        vix_slope = _slope_5d(vix_closes)
        if vix_slope is None and vix is not None:
            # Fallback: compare current to prev_close
            prev = self._get_prev_close('VIX')
            if prev and prev > 0:
                vix_slope = (vix - prev) / prev * 100
        vix_trend_score = self._score_with_default(
            vix_slope,
            lambda s: _interp(-s, [(-5, 0), (-2, 30), (0, 60), (2, 80), (5, 100)]),
            "VIX trend"
        )
        details['vix_trend'] = vix_slope
        details['vix_trend_score'] = vix_trend_score

        # VIX IV Percentile
        vix_ivp = None
        if self.vix_metrics and self.vix_metrics.implied_volatility_percentile:
            vix_ivp = float(self.vix_metrics.implied_volatility_percentile) * 100
        vix_ivp_score = self._score_with_default(
            vix_ivp,
            lambda p: _interp(p, [(30, 100), (50, 50), (90, 0)]),
            "VIX IV %ile"
        )
        details['vix_ivp'] = vix_ivp
        details['vix_ivp_score'] = vix_ivp_score

        # Put/Call Ratio — inverted U: 0.7-1.0 is ideal
        pcr = self.put_call_ratio
        pcr_score = self._score_with_default(
            pcr,
            lambda r: max(0, 100 - abs(r - 0.85) * 200),
            "Put/Call ratio"
        )
        details['pcr'] = pcr
        details['pcr_score'] = pcr_score

        pillar = (vix_score + vix_trend_score + vix_ivp_score + pcr_score) / 4
        self.pillar_details['volatility'] = details
        return pillar

    def score_trend(self) -> float:
        details: Dict = {}
        spy_closes = self.candles.get('SPY', [])
        qqq_closes = self.candles.get('QQQ', [])
        spy_price = spy_closes[-1] if spy_closes else self._get_price('SPY')

        score = 0.0

        # SPY vs MAs
        spy_20 = _sma(spy_closes, 20)
        spy_50 = _sma(spy_closes, 50)
        spy_200 = _sma(spy_closes, 200)
        qqq_50 = _sma(qqq_closes, 50)

        details['spy_price'] = spy_price
        details['spy_20ma'] = spy_20
        details['spy_50ma'] = spy_50
        details['spy_200ma'] = spy_200

        above_20 = spy_price and spy_20 and spy_price > spy_20
        above_50 = spy_price and spy_50 and spy_price > spy_50
        above_200 = spy_price and spy_200 and spy_price > spy_200

        if above_20:
            score += 25
        if above_50:
            score += 25
        if above_200:
            score += 25

        details['spy_above_20'] = above_20
        details['spy_above_50'] = above_50
        details['spy_above_200'] = above_200

        # QQQ > 50d MA
        qqq_price = qqq_closes[-1] if qqq_closes else self._get_price('QQQ')
        qqq_above_50 = qqq_price and qqq_50 and qqq_price > qqq_50
        if qqq_above_50:
            score += 10
        details['qqq_above_50'] = qqq_above_50

        # RSI-14
        rsi = _rsi(spy_closes)
        details['rsi'] = rsi
        if rsi is not None:
            # 40-60 is ideal (15 pts), taper outside
            distance = abs(rsi - 50)
            rsi_pts = max(0, 15 - distance * 0.5)
            score += rsi_pts
            details['rsi_score'] = rsi_pts
        else:
            score += 7.5  # half credit
            self.warnings.append("RSI: insufficient data")

        # Regime label
        ma_count = sum([above_20 or False, above_50 or False, above_200 or False])
        if ma_count == 3:
            details['regime'] = 'Strong Uptrend'
        elif ma_count == 2:
            details['regime'] = 'Uptrend'
        elif ma_count == 1:
            details['regime'] = 'Choppy'
        else:
            details['regime'] = 'Downtrend'

        self.pillar_details['trend'] = details
        return _clamp(score)

    def score_breadth(self) -> float:
        details: Dict = {}
        above_50 = 0
        sector_status = {}

        for etf in SECTOR_ETFS:
            closes = self.candles.get(etf, [])
            ma50 = _sma(closes, 50)
            price = closes[-1] if closes else self._get_price(etf)
            is_above = price is not None and ma50 is not None and price > ma50
            sector_status[etf] = is_above
            if is_above:
                above_50 += 1

        details['sectors_above_50ma'] = above_50
        details['sector_status'] = sector_status

        base = (above_50 / 11) * 80
        if above_50 > 8:
            bonus = 20
        elif above_50 >= 5:
            bonus = 10
        else:
            bonus = 0

        details['base_score'] = base
        details['bonus'] = bonus

        self.pillar_details['breadth'] = details
        return _clamp(base + bonus)

    def score_momentum(self) -> float:
        details: Dict = {}
        sector_returns: Dict[str, Optional[float]] = {}

        for etf in SECTOR_ETFS:
            closes = self.candles.get(etf, [])
            ret = _slope_5d(closes)
            sector_returns[etf] = ret

        details['sector_returns'] = sector_returns
        valid_returns = {k: v for k, v in sector_returns.items() if v is not None}

        if not valid_returns:
            self.warnings.append("Momentum: no sector return data")
            self.pillar_details['momentum'] = details
            return DEFAULT_SCORE

        # % sectors positive (5d)
        positive = sum(1 for v in valid_returns.values() if v > 0)
        pct_positive_score = (positive / 11) * 40
        details['sectors_positive'] = positive
        details['pct_positive_score'] = pct_positive_score

        # Leader/laggard spread
        vals = list(valid_returns.values())
        spread = max(vals) - min(vals)
        details['spread'] = spread
        if spread < 3:
            spread_score = 30
        elif spread < 10:
            spread_score = 30 * (1 - (spread - 3) / 7)
        else:
            spread_score = 0
        details['spread_score'] = spread_score

        # Sector rotation: are top 3 cyclical or defensive?
        sorted_sectors = sorted(valid_returns.items(), key=lambda x: x[1], reverse=True)
        top3 = [s[0] for s in sorted_sectors[:3]]
        cyclical_count = sum(1 for s in top3 if s in CYCLICAL_SECTORS)
        if cyclical_count >= 2:
            rotation_score = 30  # risk-on
        elif cyclical_count == 0:
            rotation_score = 10  # defensive
        else:
            rotation_score = 20  # mixed
        details['top3'] = top3
        details['cyclical_leading'] = cyclical_count
        details['rotation_score'] = rotation_score

        self.pillar_details['momentum'] = details
        return _clamp(pct_positive_score + spread_score + rotation_score)

    def score_macro(self) -> float:
        details: Dict = {}

        # Bond trend via TLT (inverse of yield: TLT rising = yields falling = bullish)
        tlt_closes = self.candles.get('TLT', [])
        tlt_slope = _slope_20d(tlt_closes)
        # TLT rising → yields falling → favorable
        bond_score = self._score_with_default(
            tlt_slope,
            lambda s: _interp(s, [(-3, 20), (0, 60), (3, 90)]),
            "Bond trend (TLT)"
        )
        details['tlt_slope'] = tlt_slope
        details['bond_score'] = bond_score

        # TLT price for display context
        tlt_price = tlt_closes[-1] if tlt_closes else self._get_price('TLT')
        details['tlt_price'] = tlt_price

        # Dollar trend (UUP 20d)
        uup_closes = self.candles.get('UUP', [])
        uup_slope = _slope_20d(uup_closes)
        dollar_score = self._score_with_default(
            uup_slope,
            lambda s: _interp(-s, [(-2, 40), (0, 70), (2, 100)]),
            "Dollar trend"
        )
        details['dollar_slope'] = uup_slope
        details['dollar_score'] = dollar_score

        # Simple average of bond trend and dollar trend
        pillar = (bond_score + dollar_score) / 2

        self.pillar_details['macro'] = details
        return _clamp(pillar)

    def compute_scores(self) -> None:
        """Run all pillar scorers and compute weighted composite."""
        self.pillar_scores['volatility'] = self.score_volatility()
        self.pillar_scores['trend'] = self.score_trend()
        self.pillar_scores['breadth'] = self.score_breadth()
        self.pillar_scores['momentum'] = self.score_momentum()
        self.pillar_scores['macro'] = self.score_macro()

        self.composite = sum(
            self.pillar_scores[k] * WEIGHTS[k] for k in WEIGHTS
        )

    def decision(self) -> Tuple[str, str]:
        """Return (label, color) based on composite score."""
        if self.composite >= 80:
            return 'YES', 'green'
        elif self.composite >= 60:
            return 'CAUTION', 'yellow'
        else:
            return 'NO', 'red'

    # ── Rich Terminal Output ─────────────────────────────────────────────

    def render(self) -> None:
        """Print the full dashboard to terminal."""
        c = self.console
        label, color = self.decision()

        # ── Hero ─────────────────────────────────────────────────────────
        score_display = f"{self.composite:.0f}"
        hero = Text()
        hero.append("  MARKET QUALITY SCORE  ", style="bold white on dark_green" if color == "green" else ("bold white on yellow" if color == "yellow" else "bold white on red"))
        hero.append(f"  {score_display} / 100  ", style=f"bold {color}")
        hero.append(f"  {label}  ", style=f"bold white on {color}")
        c.print()
        c.print(Panel(hero, title="Should I Be Trading Today?", border_style=color, expand=False))

        # ── Decision guidance ────────────────────────────────────────────
        if label == 'YES':
            guidance = "[green]Full size, press risk. Conditions favor premium selling.[/green]"
        elif label == 'CAUTION':
            guidance = "[yellow]Half size, A+ setups only. Mixed signals — be selective.[/yellow]"
        else:
            guidance = "[red]Sit on hands. Preserve capital. Wait for conditions to improve.[/red]"
        c.print(f"  {guidance}")
        c.print()

        # ── Pillar Cards ─────────────────────────────────────────────────
        cards = []
        cards.append(self._render_volatility_card())
        cards.append(self._render_trend_card())
        cards.append(self._render_breadth_card())
        cards.append(self._render_momentum_card())
        cards.append(self._render_macro_card())
        c.print(Columns(cards, equal=True, expand=True))

        # ── Sector Performance ───────────────────────────────────────────
        c.print()
        self._render_sector_chart()

        # ── Weight Breakdown ─────────────────────────────────────────────
        c.print()
        self._render_weight_table()

        # ── Warnings ─────────────────────────────────────────────────────
        if self.warnings:
            c.print()
            c.print(Panel(
                "\n".join(f"[dim]• {w}[/dim]" for w in self.warnings),
                title="[yellow]Data Warnings[/yellow]",
                border_style="yellow",
                expand=False,
            ))

        # ── Summary Line ─────────────────────────────────────────────────
        c.print()
        regime = self.pillar_details.get('trend', {}).get('regime', '?')
        vix = self.pillar_details.get('volatility', {}).get('vix_level')
        vix_str = f"{vix:.1f}" if vix else "N/A"
        breadth_n = self.pillar_details.get('breadth', {}).get('sectors_above_50ma', '?')
        c.print(f"[dim]┌─ {regime} regime │ VIX {vix_str} │ {breadth_n}/11 sectors above 50d MA │ {datetime.now().strftime('%Y-%m-%d %H:%M ET')} ─┘[/dim]")
        c.print()

    def _score_color(self, score: float) -> str:
        if score >= 75:
            return "green"
        elif score >= 50:
            return "yellow"
        return "red"

    def _render_volatility_card(self) -> Panel:
        d = self.pillar_details.get('volatility', {})
        score = self.pillar_scores.get('volatility', 0)
        sc = self._score_color(score)

        lines = []
        vix = d.get('vix_level')
        lines.append(f"VIX Level:   {vix:.1f}" if vix else "VIX Level:   N/A")
        lines.append(f"  Score: [{sc}]{d.get('vix_level_score', 0):.0f}[/{sc}]")

        trend = d.get('vix_trend')
        trend_str = f"{trend:+.1f}%" if trend is not None else "N/A"
        lines.append(f"VIX 5d:      {trend_str}")
        lines.append(f"  Score: [{sc}]{d.get('vix_trend_score', 0):.0f}[/{sc}]")

        ivp = d.get('vix_ivp')
        lines.append(f"VIX IV %ile: {ivp:.0f}%" if ivp else "VIX IV %ile: N/A")
        lines.append(f"  Score: [{sc}]{d.get('vix_ivp_score', 0):.0f}[/{sc}]")

        pcr = d.get('pcr')
        lines.append(f"Put/Call:    {pcr:.2f}" if pcr else "Put/Call:    N/A")
        lines.append(f"  Score: [{sc}]{d.get('pcr_score', 0):.0f}[/{sc}]")

        return Panel(
            "\n".join(lines),
            title=f"[bold]Volatility [{sc}]{score:.0f}[/{sc}][/bold]",
            subtitle=f"wt {WEIGHTS['volatility']:.0%}",
            border_style=sc,
            width=30,
        )

    def _render_trend_card(self) -> Panel:
        d = self.pillar_details.get('trend', {})
        score = self.pillar_scores.get('trend', 0)
        sc = self._score_color(score)
        regime = d.get('regime', '?')

        lines = []
        lines.append(f"Regime: [bold]{regime}[/bold]")
        lines.append("")
        check = lambda b: "✓" if b else "✗"
        lines.append(f"SPY > 20d MA: {check(d.get('spy_above_20'))}  (+25)")
        lines.append(f"SPY > 50d MA: {check(d.get('spy_above_50'))}  (+25)")
        lines.append(f"SPY >200d MA: {check(d.get('spy_above_200'))}  (+25)")
        lines.append(f"QQQ > 50d MA: {check(d.get('qqq_above_50'))}  (+10)")

        rsi = d.get('rsi')
        rsi_str = f"{rsi:.1f}" if rsi else "N/A"
        rsi_pts = d.get('rsi_score', 0)
        lines.append(f"RSI-14:      {rsi_str}  (+{rsi_pts:.0f})")

        return Panel(
            "\n".join(lines),
            title=f"[bold]Trend [{sc}]{score:.0f}[/{sc}][/bold]",
            subtitle=f"wt {WEIGHTS['trend']:.0%}",
            border_style=sc,
            width=30,
        )

    def _render_breadth_card(self) -> Panel:
        d = self.pillar_details.get('breadth', {})
        score = self.pillar_scores.get('breadth', 0)
        sc = self._score_color(score)
        n = d.get('sectors_above_50ma', 0)

        lines = []
        lines.append(f"Sectors > 50d MA: [bold]{n}[/bold] / 11")
        lines.append(f"Base score:  {d.get('base_score', 0):.0f}")
        lines.append(f"Participation: +{d.get('bonus', 0)}")
        lines.append("")

        status = d.get('sector_status', {})
        for etf in SECTOR_ETFS:
            name = SECTOR_NAMES.get(etf, etf)
            above = status.get(etf, False)
            icon = "[green]▲[/green]" if above else "[red]▼[/red]"
            lines.append(f"  {icon} {name:<12}")

        return Panel(
            "\n".join(lines),
            title=f"[bold]Breadth [{sc}]{score:.0f}[/{sc}][/bold]",
            subtitle=f"wt {WEIGHTS['breadth']:.0%}",
            border_style=sc,
            width=30,
        )

    def _render_momentum_card(self) -> Panel:
        d = self.pillar_details.get('momentum', {})
        score = self.pillar_scores.get('momentum', 0)
        sc = self._score_color(score)

        lines = []
        pos = d.get('sectors_positive', 0)
        lines.append(f"Sectors positive (5d): {pos}/11")
        lines.append(f"  Score: {d.get('pct_positive_score', 0):.0f}")

        spread = d.get('spread')
        lines.append(f"Leader/Laggard spread: {spread:.1f}%" if spread else "Spread: N/A")
        lines.append(f"  Score: {d.get('spread_score', 0):.0f}")

        cyc = d.get('cyclical_leading', 0)
        top3 = d.get('top3', [])
        top3_str = ", ".join(top3) if top3 else "N/A"
        rotation = "Risk-On" if cyc >= 2 else ("Defensive" if cyc == 0 else "Mixed")
        lines.append(f"Rotation: {rotation}")
        lines.append(f"  Top 3: {top3_str}")
        lines.append(f"  Score: {d.get('rotation_score', 0):.0f}")

        return Panel(
            "\n".join(lines),
            title=f"[bold]Momentum [{sc}]{score:.0f}[/{sc}][/bold]",
            subtitle=f"wt {WEIGHTS['momentum']:.0%}",
            border_style=sc,
            width=30,
        )

    def _render_macro_card(self) -> Panel:
        d = self.pillar_details.get('macro', {})
        score = self.pillar_scores.get('macro', 0)
        sc = self._score_color(score)

        lines = []
        tlt = d.get('tlt_price')
        lines.append(f"TLT (bonds): ${tlt:.2f}" if tlt else "TLT: N/A")
        ts = d.get('tlt_slope')
        lines.append(f"Bond 20d:    {ts:+.1f}%" if ts is not None else "Bond 20d:    N/A")
        lines.append(f"  Score: {d.get('bond_score', 0):.0f}")
        lines.append("")

        ds = d.get('dollar_slope')
        lines.append(f"Dollar 20d:  {ds:+.1f}%" if ds is not None else "Dollar 20d:  N/A")
        lines.append(f"  Score: {d.get('dollar_score', 0):.0f}")

        return Panel(
            "\n".join(lines),
            title=f"[bold]Macro [{sc}]{score:.0f}[/{sc}][/bold]",
            subtitle=f"wt {WEIGHTS['macro']:.0%}",
            border_style=sc,
            width=30,
        )

    def _render_sector_chart(self) -> None:
        """Horizontal bar chart of sector 5d returns."""
        returns = self.pillar_details.get('momentum', {}).get('sector_returns', {})
        if not returns:
            return

        sorted_sectors = sorted(returns.items(), key=lambda x: x[1] or 0, reverse=True)
        table = Table(title="Sector 5-Day Returns", box=box.SIMPLE, expand=False)
        table.add_column("Sector", style="bold", width=14)
        table.add_column("Return", justify="right", width=8)
        table.add_column("", width=30)

        for etf, ret in sorted_sectors:
            if ret is None:
                continue
            name = SECTOR_NAMES.get(etf, etf)
            color = "green" if ret >= 0 else "red"
            bar_len = min(25, int(abs(ret) * 5))
            bar = "█" * bar_len if bar_len > 0 else "▏"
            table.add_row(name, f"[{color}]{ret:+.1f}%[/{color}]", f"[{color}]{bar}[/{color}]")

        self.console.print(table)

    def _render_weight_table(self) -> None:
        """Show weighted score breakdown."""
        table = Table(title="Score Breakdown", box=box.ROUNDED, expand=False)
        table.add_column("Pillar", style="bold")
        table.add_column("Score", justify="right")
        table.add_column("Weight", justify="right")
        table.add_column("Weighted", justify="right")

        for pillar in WEIGHTS:
            s = self.pillar_scores.get(pillar, 0)
            w = WEIGHTS[pillar]
            ws = s * w
            sc = self._score_color(s)
            table.add_row(
                pillar.capitalize(),
                f"[{sc}]{s:.0f}[/{sc}]",
                f"{w:.0%}",
                f"{ws:.1f}",
            )

        table.add_section()
        label, color = self.decision()
        table.add_row(
            "[bold]COMPOSITE[/bold]",
            f"[bold {color}]{self.composite:.0f}[/bold {color}]",
            "100%",
            f"[bold {color}]{self.composite:.1f}[/bold {color}]",
        )

        self.console.print(table)


async def run_dashboard(session: Session, html: bool = False) -> int:
    """Entry point for the dashboard command."""
    console = Console()
    console.print("[dim]Fetching market data...[/dim]")

    agent = DashboardAgent(session)
    await agent.fetch_all()
    agent.compute_scores()

    if html:
        from agents.dashboard_html import open_dashboard_html
        path = open_dashboard_html(agent)
        console.print(f"[green]Dashboard opened in browser[/green] ({path})")
    else:
        agent.render()
    return 0
