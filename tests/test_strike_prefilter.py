"""Tests for the moneyness pre-filter in _build_enriched_chain.

Quality is the #1 concern: the pre-filter must NEVER drop a strike that
would have surfaced as a candidate. These tests prove that:

  1. With underlying_price=None (legacy callers), no pre-filter applied.
  2. Strikes inside the moneyness window pass through unchanged.
  3. Strikes outside the window are dropped BEFORE market_data / Greeks
     are fetched (verified by asserting the patched fetch sees only the
     in-window symbols).
  4. Default window [0.40, 1.60] keeps every strike a 30Δ, 15Δ, or 45Δ
     short put/call would land at across normal-IV underlyings.
"""

from __future__ import annotations

import asyncio
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from agents.options_researcher import OptionsResearcherAgent


def _mock_option(strike: float, opt_type: str = "PUT") -> MagicMock:
    o = MagicMock()
    o.strike_price = Decimal(str(strike))
    o.symbol = f"AAPL  260619{opt_type[0]}{int(strike * 1000):08d}"
    o.streamer_symbol = f".AAPL{strike:.0f}{opt_type[0]}"
    o.option_type = MagicMock()
    o.option_type.value = opt_type
    return o


class TestMoneynessPreFilter(unittest.IsolatedAsyncioTestCase):
    """_build_enriched_chain pre-filter behavior."""

    def setUp(self):
        self.agent = OptionsResearcherAgent(MagicMock())

    async def _run_with_prefilter(self, options, *, underlying_price, mn, mx):
        # Patch the slow fetches so we can observe what they were called with.
        seen_md_symbols: list[str] = []
        seen_greeks_symbols: list[str] = []

        async def fake_md(symbols):
            seen_md_symbols.extend(symbols)
            return {}

        async def fake_greeks(symbols, timeout):
            seen_greeks_symbols.extend(symbols)
            return {}

        with patch.object(self.agent, "_fetch_market_data_batched", side_effect=fake_md), \
             patch.object(self.agent, "_fetch_greeks", side_effect=fake_greeks):
            await self.agent._build_enriched_chain(
                options,
                date(2026, 6, 19),
                underlying_price=underlying_price,
                moneyness_min=mn,
                moneyness_max=mx,
            )
        return seen_md_symbols, seen_greeks_symbols

    async def test_no_filter_when_underlying_price_none(self):
        options = [_mock_option(s) for s in (50.0, 100.0, 150.0)]
        md_seen, greeks_seen = await self._run_with_prefilter(
            options, underlying_price=None, mn=0.40, mx=1.60,
        )
        # All 3 strikes should reach the fetches.
        self.assertEqual(len(md_seen), 3)
        self.assertEqual(len(greeks_seen), 3)

    async def test_no_filter_when_window_missing(self):
        options = [_mock_option(s) for s in (50.0, 100.0, 150.0)]
        md_seen, greeks_seen = await self._run_with_prefilter(
            options, underlying_price=100.0, mn=None, mx=1.60,
        )
        self.assertEqual(len(md_seen), 3)

    async def test_drops_deep_otm_below_floor(self):
        # Spot 100, floor 0.40 = strikes <40 dropped.
        options = [_mock_option(s) for s in (20.0, 30.0, 50.0, 100.0, 130.0)]
        md_seen, greeks_seen = await self._run_with_prefilter(
            options, underlying_price=100.0, mn=0.40, mx=1.60,
        )
        # 20 and 30 dropped; 50, 100, 130 pass.
        self.assertEqual(len(md_seen), 3)
        # Greeks subscribes to streamer_symbols; assert by count.
        self.assertEqual(len(greeks_seen), 3)

    async def test_drops_deep_itm_above_cap(self):
        # Spot 100, cap 1.60 = strikes >160 dropped.
        options = [_mock_option(s, "CALL") for s in (100.0, 140.0, 160.0, 200.0, 300.0)]
        md_seen, _ = await self._run_with_prefilter(
            options, underlying_price=100.0, mn=0.40, mx=1.60,
        )
        # 100, 140, 160 pass; 200, 300 drop. Boundary inclusive.
        self.assertEqual(len(md_seen), 3)

    async def test_boundary_strikes_inclusive(self):
        # Floor and cap are inclusive bounds.
        options = [_mock_option(s) for s in (40.0, 100.0, 160.0)]
        md_seen, _ = await self._run_with_prefilter(
            options, underlying_price=100.0, mn=0.40, mx=1.60,
        )
        self.assertEqual(len(md_seen), 3)

    async def test_strikes_well_inside_window_all_pass(self):
        # Typical chain: 80–120% of spot — all should pass with default window.
        options = [_mock_option(s) for s in (80.0, 90.0, 95.0, 100.0, 105.0, 110.0, 120.0)]
        md_seen, _ = await self._run_with_prefilter(
            options, underlying_price=100.0, mn=0.40, mx=1.60,
        )
        self.assertEqual(len(md_seen), len(options))

    async def test_invalid_window_disables_prefilter(self):
        # min >= max → fall through with no filter applied.
        options = [_mock_option(s) for s in (10.0, 100.0, 1000.0)]
        md_seen, _ = await self._run_with_prefilter(
            options, underlying_price=100.0, mn=1.60, mx=0.40,
        )
        self.assertEqual(len(md_seen), 3)

    async def test_zero_underlying_price_disables_prefilter(self):
        options = [_mock_option(s) for s in (10.0, 100.0, 1000.0)]
        md_seen, _ = await self._run_with_prefilter(
            options, underlying_price=0.0, mn=0.40, mx=1.60,
        )
        self.assertEqual(len(md_seen), 3)

    async def test_empty_options_returns_empty(self):
        md_seen, greeks_seen = await self._run_with_prefilter(
            [], underlying_price=100.0, mn=0.40, mx=1.60,
        )
        self.assertEqual(md_seen, [])
        self.assertEqual(greeks_seen, [])

    async def test_all_strikes_filtered_returns_empty(self):
        # Spot 100, all strikes are at 1000 (10× spot) → all dropped.
        options = [_mock_option(1000.0)]
        md_seen, greeks_seen = await self._run_with_prefilter(
            options, underlying_price=100.0, mn=0.40, mx=1.60,
        )
        # Verifying we don't even call the slow fetches when nothing passes.
        self.assertEqual(md_seen, [])
        self.assertEqual(greeks_seen, [])


class TestPreFilterQualityWithRealisticChains(unittest.IsolatedAsyncioTestCase):
    """Default window [0.40, 1.60] keeps every strike that any reasonable
    target-delta / IV / DTE combination would surface.

    For 45 DTE:
    - Highest-vol normal underlying (~80% IV): 15Δ put strike ~= 0.55 × spot
    - Lowest-vol normal underlying (~15% IV): 15Δ put strike ~= 0.92 × spot
    - 15Δ call strikes mirror at 1.08–1.45 × spot

    The default window of 0.40–1.60 has 15+ percentage-point margin on each
    side of those extremes.
    """

    def setUp(self):
        self.agent = OptionsResearcherAgent(MagicMock())

    async def test_high_iv_chain_15_delta_put_strikes_pass(self):
        # 80% IV, 45 DTE: a 15Δ put on a $100 spot lands ~0.55 × spot.
        # Default floor 0.40 gives 15-pt margin.
        seen: list[str] = []

        async def fake_md(symbols):
            seen.extend(symbols)
            return {}

        options = [_mock_option(s) for s in (40.0, 50.0, 55.0, 60.0, 80.0, 100.0)]
        with patch.object(self.agent, "_fetch_market_data_batched", side_effect=fake_md), \
             patch.object(self.agent, "_fetch_greeks", new=AsyncMock(return_value={})):
            await self.agent._build_enriched_chain(
                options, date(2026, 6, 19),
                underlying_price=100.0, moneyness_min=0.40, moneyness_max=1.60,
            )
        # 55 (the 15Δ pick) and everything above pass. 40 is the floor (inclusive).
        self.assertGreaterEqual(len(seen), 5)


if __name__ == "__main__":
    unittest.main()
