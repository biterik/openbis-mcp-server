"""Thin wrapper around pyBIS that handles connection setup from environment variables.

The wrapper is intentionally minimal: it owns one ``Openbis`` instance and lazily
logs in on first use. Higher-level logic (search, create, upload, ...) lives in
``server.py`` so this file stays focused on connection management.
"""

from __future__ import annotations

import os
from threading import Lock
from typing import Any


class OpenbisConfigError(RuntimeError):
    """Raised when required configuration is missing or inconsistent."""


class OpenbisClient:
    """Lazy, thread-safe wrapper around a single pyBIS ``Openbis`` connection."""

    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        username: str | None = None,
        password: str | None = None,
        verify_certificates: bool | None = None,
    ) -> None:
        self._url = url or os.environ.get("OPENBIS_URL")
        self._token = token or os.environ.get("OPENBIS_TOKEN")
        self._username = username or os.environ.get("OPENBIS_USERNAME")
        self._password = password or os.environ.get("OPENBIS_PASSWORD")

        verify_env = os.environ.get("OPENBIS_VERIFY_CERTIFICATES", "true")
        if verify_certificates is None:
            self._verify_certificates = verify_env.strip().lower() not in {
                "false",
                "0",
                "no",
            }
        else:
            self._verify_certificates = verify_certificates

        if not self._url:
            raise OpenbisConfigError(
                "OPENBIS_URL is not set. Provide it via env var or constructor."
            )
        if not self._token and not (self._username and self._password):
            raise OpenbisConfigError(
                "No credentials found. Set OPENBIS_TOKEN, or both "
                "OPENBIS_USERNAME and OPENBIS_PASSWORD."
            )

        self._openbis: Any | None = None
        self._lock = Lock()

    @property
    def url(self) -> str:
        assert self._url is not None  # checked in __init__
        return self._url

    def connect(self) -> Any:
        """Return a logged-in pyBIS ``Openbis`` instance, creating it on first call."""
        if self._openbis is not None:
            return self._openbis

        with self._lock:
            if self._openbis is not None:
                return self._openbis

            # Imported lazily so module import doesn't require pybis to be installed.
            from pybis import Openbis  # type: ignore[import-not-found]

            ob = Openbis(self._url, verify_certificates=self._verify_certificates)
            if self._token:
                ob.set_token(self._token)
            else:
                ob.login(self._username, self._password, save_token=False)

            self._openbis = ob
            return ob

    def close(self) -> None:
        """Log out and drop the connection."""
        with self._lock:
            if self._openbis is not None:
                try:
                    self._openbis.logout()
                finally:
                    self._openbis = None
