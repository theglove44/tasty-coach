"""
Real-time data via dxLink.
"""

import logging
import asyncio
import time
from typing import Dict, List, Optional
from tastytrade import Session
from tastytrade.dxfeed import Greeks
from tastytrade.streamer import DXLinkStreamer

class DXFeed:
    """Manages real-time data streaming via dxLink."""

    def __init__(self, session: Session):
        self.session = session
        self.logger = logging.getLogger(__name__)

    async def get_realtime_iv(self, option_symbols: List[str], timeout: float = 10.0) -> Dict[str, float]:
        """Retrieves real-time IV for a list of option symbols."""
        if not option_symbols:
            return {}

        iv_results = {}
        try:
            async with DXLinkStreamer(self.session) as streamer:
                await streamer.subscribe(Greeks, option_symbols)
                
                start_time = time.time()
                symbols_to_find = set(option_symbols)
                
                while symbols_to_find and (time.time() - start_time) < timeout:
                    try:
                        greeks_event = await asyncio.wait_for(streamer.get_event(Greeks), timeout=2.0)
                        if greeks_event and greeks_event.symbol in symbols_to_find:
                            if greeks_event.volatility is not None:
                                iv_results[greeks_event.symbol] = float(greeks_event.volatility)
                                symbols_to_find.remove(greeks_event.symbol)
                    except asyncio.TimeoutError:
                        break
                    except Exception as e:
                        self.logger.debug(f"Streaming error: {e}")
                        break
                        
            return iv_results
        except Exception as e:
            self.logger.error(f"Failed Greek streaming: {e}")
            return {}
