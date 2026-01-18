"""OpenAPI connection & Authentication for Tastytrade."""

import os
import logging
from typing import Optional, List

from dotenv import load_dotenv
from tastytrade import Session, OAuthSession, Account
from tastytrade.utils import now_in_new_york

load_dotenv()


class Config:
    """Configuration settings for the tastytrade API."""

    def __init__(self):
        self.client_secret = self._get_required_env("TASTYTRADE_CLIENT_SECRET")
        self.refresh_token = self._get_required_env("TASTYTRADE_REFRESH_TOKEN")

        # Preferred: account number like "5WW46136".
        # Back-compat: accept TASTY_ACCOUNT_ID if that's what exists in older .env.
        self.account_number = os.getenv("TASTY_ACCOUNT_NUMBER") or os.getenv("TASTY_ACCOUNT_ID")

        self.is_test = self._get_bool_env("TASTYTRADE_IS_TEST", False)

        # Scanner settings
        self.ivr_threshold = self._get_float_env("IVR_THRESHOLD", 25.0)
        self.cache_duration = self._get_int_env("CACHE_DURATION", 300)
        self.max_retries = self._get_int_env("MAX_RETRIES", 3)

        # Logging
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        self._setup_logging()

    def _get_required_env(self, key: str) -> str:
        value = os.getenv(key)
        if not value:
            raise ValueError(f"Required environment variable {key} is not set")
        return value

    def _get_bool_env(self, key: str, default: bool) -> bool:
        value = os.getenv(key, str(default)).lower()
        return value in ("true", "1", "yes", "on")

    def _get_int_env(self, key: str, default: int) -> int:
        try:
            return int(os.getenv(key, str(default)))
        except ValueError:
            return default

    def _get_float_env(self, key: str, default: float) -> float:
        try:
            return float(os.getenv(key, str(default)))
        except ValueError:
            return default

    def _setup_logging(self) -> None:
        log_level = getattr(logging, self.log_level.upper(), logging.INFO)
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler("tasty_auto.log"),
            ],
        )
        if log_level > logging.DEBUG:
            logging.getLogger("httpx").setLevel(logging.WARNING)
            logging.getLogger("tastytrade").setLevel(logging.WARNING)


class TastyClient:
    """Handles authentication and session management."""

    def __init__(self):
        self.config = Config()
        self.session: Optional[Session] = None
        self.logger = logging.getLogger(__name__)

    def authenticate(self) -> bool:
        try:
            self.logger.info(f"Authenticating (test mode: {self.config.is_test})")
            self.session = OAuthSession(
                self.config.client_secret,
                self.config.refresh_token,
                is_test=self.config.is_test,
            )
            return True
        except Exception as e:
            self.logger.error(f"Authentication failed: {e}")
            return False

    def get_session(self) -> Optional[Session]:
        if not self.session:
            if not self.authenticate():
                return None

        if self.is_session_expired():
            self.session.refresh()

        return self.session

    def is_session_expired(self) -> bool:
        if not self.session:
            return True
        try:
            return now_in_new_york() > self.session.session_expiration
        except Exception:
            return True

    def get_accounts(self) -> List[Account]:
        session = self.get_session()
        if not session:
            return []
        return Account.get(session)

    def get_account(self, account_number: Optional[str] = None) -> Account:
        """Return the selected account by number.

        If multiple accounts exist and none is specified, raise to avoid accidentally
        using the wrong one.
        """

        session = self.get_session()
        if not session:
            raise ValueError("Failed to establish session")

        accounts = Account.get(session)
        if not accounts:
            raise ValueError("No accounts found")

        target = account_number or self.config.account_number

        if target:
            for acct in accounts:
                if getattr(acct, "account_number", None) == target:
                    return acct
            available = ", ".join([getattr(a, "account_number", "?") for a in accounts])
            raise ValueError(f"Account {target} not found. Available: {available}")

        if len(accounts) > 1:
            available = ", ".join([getattr(a, "account_number", "?") for a in accounts])
            raise ValueError(
                "Multiple accounts found. Set TASTY_ACCOUNT_NUMBER in .env or pass --account. "
                f"Available: {available}"
            )

        return accounts[0]
