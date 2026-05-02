"""Tests for server.app token persistence + loopback bypass + cookie max-age."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

import server.app as server_app


class TestResolveToken(unittest.TestCase):
    """_resolve_token persists across restarts via ~/.tasty-coach/web_token."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._patches = [
            patch.object(server_app, "TOKEN_FILE", Path(self.tmp.name) / "web_token"),
            patch.dict(os.environ, {}, clear=False),
        ]
        for p in self._patches:
            p.start()
        # Ensure the env var is unset for these tests.
        os.environ.pop("TASTY_COACH_WEB_TOKEN", None)

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        self.tmp.cleanup()
        os.environ.pop("TASTY_COACH_WEB_TOKEN", None)

    def test_env_var_takes_precedence(self):
        os.environ["TASTY_COACH_WEB_TOKEN"] = "from-env"
        # Pre-populate the file with a different value to prove env wins.
        server_app.TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        server_app.TOKEN_FILE.write_text("from-file")
        self.assertEqual(server_app._resolve_token(), "from-env")

    def test_reads_from_file_when_env_missing(self):
        server_app.TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        server_app.TOKEN_FILE.write_text("persisted-token-abc")
        self.assertEqual(server_app._resolve_token(), "persisted-token-abc")
        # Subsequent call returns the same value (no rotation).
        self.assertEqual(server_app._resolve_token(), "persisted-token-abc")

    def test_mints_and_persists_when_no_source(self):
        self.assertFalse(server_app.TOKEN_FILE.exists())
        tok = server_app._resolve_token()
        self.assertTrue(server_app.TOKEN_FILE.exists())
        self.assertEqual(server_app.TOKEN_FILE.read_text().strip(), tok)
        # Restart simulation: clear env, re-read; same token.
        os.environ.pop("TASTY_COACH_WEB_TOKEN", None)
        self.assertEqual(server_app._resolve_token(), tok)

    def test_minted_token_file_is_user_only(self):
        server_app._resolve_token()
        mode = server_app.TOKEN_FILE.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)


class TestLoopbackBypass(unittest.TestCase):
    """Requests from 127.0.0.1 / ::1 / localhost skip token auth."""

    def _request(self, host: str | None) -> MagicMock:
        req = MagicMock()
        if host is None:
            req.client = None
        else:
            req.client = MagicMock()
            req.client.host = host
        req.headers = {}
        req.cookies = {}
        req.app.state.token = "secret"
        return req

    def test_loopback_v4_bypasses_token(self):
        req = self._request("127.0.0.1")
        # No token supplied — should NOT raise.
        server_app._check_token(req, None)

    def test_loopback_v6_bypasses_token(self):
        req = self._request("::1")
        server_app._check_token(req, None)

    def test_localhost_string_bypasses_token(self):
        req = self._request("localhost")
        server_app._check_token(req, None)

    def test_lan_address_still_requires_token(self):
        req = self._request("192.168.1.42")
        with self.assertRaises(HTTPException) as ctx:
            server_app._check_token(req, None)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_lan_address_accepts_correct_token(self):
        req = self._request("192.168.1.42")
        server_app._check_token(req, "secret")  # must not raise

    def test_lan_address_rejects_wrong_token(self):
        req = self._request("192.168.1.42")
        with self.assertRaises(HTTPException):
            server_app._check_token(req, "wrong")

    def test_no_client_falls_through_to_token_check(self):
        req = self._request(None)
        # No client info AND no token → 401 (don't bypass on missing info)
        with self.assertRaises(HTTPException):
            server_app._check_token(req, None)


class TestCookieMaxAgeConstant(unittest.TestCase):
    """Cookie persists 30 days (vs. session-only)."""

    def test_max_age_is_thirty_days(self):
        self.assertEqual(server_app.COOKIE_MAX_AGE_SECONDS, 30 * 24 * 60 * 60)


if __name__ == "__main__":
    unittest.main()
