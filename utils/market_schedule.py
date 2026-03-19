
import logging
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

class MarketSchedule:
    """
    Handles interaction with the Tastytrade Market Sessions API.
    Provides methods to check if the market is open and get session times.
    """

    BASE_URL = "https://api.tastytrade.com"
    CERT_BASE_URL = "https://api.cert.tastyworks.com"
    ENDPOINT = "/market-time/equities/sessions/current"
    CACHE_DURATION = 60  # Cache for 60 seconds

    def __init__(self, session):
        """
        Args:
            session: tastytrade-sdk Session object (OAuthSession)
        """
        self.session = session
        self.logger = logging.getLogger(__name__)
        self._cache: Optional[Dict[str, Any]] = None
        self._last_fetch_time: Optional[datetime] = None

    def _get_base_url(self) -> str:
        """Return correct base URL based on session environment."""
        if getattr(self.session, 'is_test', False):
            return self.CERT_BASE_URL
        return self.BASE_URL

    def _fetch_session_data(self) -> Optional[Dict[str, Any]]:
        """Fetches the current market session data from the API."""
        now = datetime.now()
        if self._cache and self._last_fetch_time:
            if (now - self._last_fetch_time).total_seconds() < self.CACHE_DURATION:
                return self._cache

        token = getattr(self.session, 'session_token', None)
        if not token:
            self.logger.error("No session token available for MarketSchedule.")
            return None

        # Per API docs: Authorization header requires "Bearer " prefix,
        # User-Agent is required, Content-Type must be application/json
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'tasty-coach/1.0',
        }

        url = f"{self._get_base_url()}{self.ENDPOINT}"
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json().get('data')
            self._cache = data
            self._last_fetch_time = now
            return data
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                self.logger.warning("Market schedule token expired, clearing cache")
                self._cache = None
                self._last_fetch_time = None
            self.logger.error(f"Failed to fetch market session data: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Failed to fetch market session data: {e}")
            return None

    def get_market_state(self) -> str:
        """Returns the current market state (e.g., 'Open', 'Closed', 'Pre-Market', 'Post-Market')."""
        data = self._fetch_session_data()
        if not data:
            return "Unknown"
        return data.get('state', "Unknown")

    def is_market_open(self) -> bool:
        """Returns True if the market is currently Open."""
        return self.get_market_state() == "Open"

    def get_next_open(self) -> Optional[datetime]:
        """Returns the datetime of the next market open."""
        data = self._fetch_session_data()
        if not data:
            return None

        # Helper to parse ISO format
        def parse_time(t_str):
            if not t_str: return None
            return datetime.fromisoformat(t_str)

        # Check 'next-session'
        next_session = data.get('next-session', {})
        return parse_time(next_session.get('open-at'))

    def get_time_to_next_open(self) -> Optional[timedelta]:
        """Returns timedelta until the next open, or None if unknown."""
        next_open = self.get_next_open()
        if not next_open:
            return None

        # Ensure we compare timezone-aware datetimes
        now = datetime.now(next_open.tzinfo)
        return next_open - now

    def print_status(self) -> None:
        """Prints a user-friendly status report to stdout."""
        state = self.get_market_state()
        print(f"🏛️  Market Status: {state}")

        if state == "Closed":
            next_open = self.get_next_open()
            if next_open:
                now = datetime.now(next_open.tzinfo)
                diff = next_open - now
                hours, remainder = divmod(diff.seconds, 3600)
                minutes, _ = divmod(remainder, 60)
                days = diff.days

                time_str = f"{days}d " if days > 0 else ""
                time_str += f"{hours}h {minutes}m"
                print(f"⏳ Next Open: {next_open.strftime('%Y-%m-%d %H:%M %Z')} (in {time_str})")
