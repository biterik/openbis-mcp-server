# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Erik Bitzek and Niklas Siemer.
#
# Authors:
#   Erik Bitzek    <e.bitzek@mpi-susmat.de>
#   Niklas Siemer
#
# This Source Code Form is subject to the terms of the Mozilla Public License,
# v. 2.0. If a copy of the MPL was not distributed with this file, You can
# obtain one at https://mozilla.org/MPL/2.0/.
#
# Implemented with assistance from Claude Code (Anthropic).
"""Thin wrapper around pyBIS that handles connection setup from environment variables.

The wrapper is intentionally minimal: it owns one ``Openbis`` instance and lazily
logs in on first use. A :class:`ConnectionManager` holds one client per configured
openBIS instance. Higher-level logic (search, create, upload, ...) lives in
``server.py`` so this file stays focused on connection management.
"""

from __future__ import annotations

import os
from pathlib import Path
from threading import Lock
from typing import Any


class OpenbisConfigError(RuntimeError):
    """Raised when required configuration is missing or inconsistent."""


class OpenbisAuthError(RuntimeError):
    """Raised when credentials are present but rejected by openBIS.

    The message is intended to be shown verbatim to the user: it explains how to
    mint a fresh personal access token and where to store it.
    """


def pat_setup_instructions(url: str, name: str | None = None) -> str:
    """Step-by-step help for creating a personal access token and storing it.

    Embedded in :class:`OpenbisAuthError` and in MCP tool error responses so an
    agent can relay actionable instructions instead of a bare stack trace.

    ``name`` is the instance name; when given (and not the implicit "default"),
    the instructions name the suffixed env var, e.g. ``OPENBIS_AACHEN_TOKEN``.
    """
    token_var = (
        f"OPENBIS_{name.upper()}_TOKEN" if name and name != "default" else "OPENBIS_TOKEN"
    )
    return (
        "How to create a new openBIS personal access token (PAT):\n"
        f"  1. Open the openBIS web UI in a browser:  {url}\n"
        "  2. Log in with your normal openBIS username and password.\n"
        '  3. Open the "Utilities" section in the main (left) menu and choose\n'
        '     "Personal Access Tokens". On some openBIS versions this lives in\n'
        "     the user-name menu in the top-right corner instead.\n"
        '  4. Click "New Personal Access Token", give it a session name (for\n'
        '     example "mcp-server") and an expiration date comfortably in the\n'
        "     future, then save.\n"
        "  5. Copy the generated token string.\n"
        "\n"
        "Where to put the new token:\n"
        "  - If you launch the server from a .env file: open that .env and set\n"
        f"        {token_var}=<paste the new token here>\n"
        "    (replacing the old value), then restart the server.\n"
        "  - If you configured it in your MCP client (e.g. Claude Desktop's\n"
        f"    claude_desktop_config.json), update the {token_var} value in the\n"
        '    "env" block for the "openbis" server, then restart the client so\n'
        "    the new environment is picked up.\n"
        f"  - You can also write the token to a file and point OPENBIS_TOKEN_FILE"
        " at it.\n"
        "\n"
        "After updating the token, start a new session or re-run the tool."
    )


class OpenbisClient:
    """Lazy, thread-safe wrapper around a single pyBIS ``Openbis`` connection."""

    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        username: str | None = None,
        password: str | None = None,
        verify_certificates: bool | None = None,
        name: str | None = None,
    ) -> None:
        self.name = name
        self._url = url or os.environ.get("OPENBIS_URL")
        self._token = token or os.environ.get("OPENBIS_TOKEN")
        # Support reading the token from a file (matches the pyBIS convention
        # of storing tokens under ~/.pybis/<host>.token). Used only if
        # OPENBIS_TOKEN is empty.
        if not self._token:
            token_file = os.environ.get("OPENBIS_TOKEN_FILE")
            if token_file:
                p = Path(token_file).expanduser()
                if p.is_file():
                    self._token = p.read_text().strip() or None
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

        suffix = f"_{name.upper()}" if name and name != "default" else ""
        if not self._url:
            raise OpenbisConfigError(
                f"OPENBIS{suffix}_URL is not set. Provide it via env var or constructor."
            )
        if not self._token and not (self._username and self._password):
            raise OpenbisConfigError(
                f"No credentials found. Set OPENBIS{suffix}_TOKEN (or "
                f"OPENBIS{suffix}_TOKEN_FILE pointing at a file containing the "
                f"token), or both OPENBIS{suffix}_USERNAME and OPENBIS{suffix}_PASSWORD."
            )

        self._openbis: Any | None = None
        self._lock = Lock()

    @property
    def url(self) -> str:
        assert self._url is not None  # checked in __init__
        return self._url

    @property
    def _label(self) -> str:
        """Human-readable instance tag for error messages, e.g. " (instance 'aachen')"."""
        return f" (instance '{self.name}')" if self.name else ""

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
                # This runs only on the first connect of a session (the result
                # is cached below), so it doubles as the "first use" validity
                # check: a lapsed PAT is caught before any real tool work.
                self._verify_token(ob)
            else:
                try:
                    ob.login(self._username, self._password, save_token=False)
                except Exception as e:  # pyBIS raises bare Exception on bad creds
                    raise OpenbisAuthError(
                        f"openBIS rejected the username/password login{self._label} "
                        f"for {self._url} ({e}).\n\n"
                        "A personal access token is the preferred way to "
                        "authenticate.\n\n"
                        + pat_setup_instructions(self.url, self.name)
                    ) from e

            self._openbis = ob
            return ob

    def _verify_token(self, ob: Any) -> None:
        """Reject an expired/invalid PAT early with actionable help.

        pyBIS exposes ``is_session_active`` (and ``is_token_valid``) which probe
        the token against the server. If either reports the token as invalid we
        raise :class:`OpenbisAuthError`; if neither is available we stay quiet
        and let the first real call surface any problem.
        """
        valid: bool | None = None
        for attr, args in (("is_session_active", ()), ("is_token_valid", (self._token,))):
            check = getattr(ob, attr, None)
            if not callable(check):
                continue
            try:
                valid = bool(check(*args))
            except Exception:  # noqa: BLE001 — treat probe failure as "unknown"
                continue
            break

        if valid is False:
            raise OpenbisAuthError(
                f"Your openBIS personal access token{self._label} is no longer "
                f"valid for {self.url} — it has most likely expired.\n\n"
                + pat_setup_instructions(self.url, self.name)
            )

    def close(self) -> None:
        """Log out and drop the connection."""
        with self._lock:
            if self._openbis is not None:
                try:
                    self._openbis.logout()
                finally:
                    self._openbis = None


def _truthy_verify(value: str | None) -> bool:
    """Interpret a *_VERIFY_CERTIFICATES env value (default: verify)."""
    if value is None:
        return True
    return value.strip().lower() not in {"false", "0", "no"}


def _resolve_token(env: dict[str, str], prefix: str) -> str | None:
    """Read ``<prefix>TOKEN``, falling back to a file named by ``<prefix>TOKEN_FILE``."""
    token = env.get(f"{prefix}TOKEN") or None
    if token:
        return token
    token_file = env.get(f"{prefix}TOKEN_FILE")
    if token_file:
        p = Path(token_file).expanduser()
        if p.is_file():
            return p.read_text().strip() or None
    return None


def discover_instances(environ: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """Parse instance configs from environment variables.

    Recognises both the bare single-instance form (``OPENBIS_URL`` ... → instance
    ``"default"``) and the suffixed multi-instance form
    (``OPENBIS_<NAME>_URL`` ... → instance ``"<name>"`` lower-cased). Returns a
    mapping of instance name → kwargs suitable for :class:`OpenbisClient`.

    Credentials (token / token file / password) are resolved here and passed
    explicitly so each client is fully self-contained and never falls back to a
    different instance's environment variables.
    """
    env = os.environ if environ is None else environ
    configs: dict[str, dict[str, Any]] = {}

    for key, url in env.items():
        if not key.startswith("OPENBIS_") or not key.endswith("_URL"):
            continue
        middle = key[len("OPENBIS_") : -len("_URL")]  # "" for bare OPENBIS_URL
        if middle == "":
            name, prefix = "default", "OPENBIS_"
        else:
            name, prefix = middle.lower(), f"OPENBIS_{middle}_"
        if not url:
            continue
        configs[name] = {
            "name": name,
            "url": url,
            "token": _resolve_token(env, prefix),
            "username": env.get(f"{prefix}USERNAME") or None,
            "password": env.get(f"{prefix}PASSWORD") or None,
            "verify_certificates": _truthy_verify(env.get(f"{prefix}VERIFY_CERTIFICATES")),
        }
    return configs


def resolve_default(
    configs: dict[str, dict[str, Any]], environ: dict[str, str] | None = None
) -> str | None:
    """Pick the default instance name: explicit env > "default" > sole instance."""
    env = os.environ if environ is None else environ
    explicit = env.get("OPENBIS_DEFAULT_INSTANCE")
    if explicit:
        return explicit.strip().lower()
    if "default" in configs:
        return "default"
    if len(configs) == 1:
        return next(iter(configs))
    return None


class ConnectionManager:
    """Owns one :class:`OpenbisClient` per configured instance, built lazily.

    Connection/credential validation happens inside ``OpenbisClient.connect()``,
    so each instance is validated on its first use in the session.
    """

    def __init__(self, environ: dict[str, str] | None = None) -> None:
        self._configs = discover_instances(environ)
        self._default = resolve_default(self._configs, environ)
        self._clients: dict[str, OpenbisClient] = {}

    @property
    def default(self) -> str | None:
        return self._default

    def names(self) -> list[str]:
        return sorted(self._configs)

    def _resolve(self, instance: str | None) -> str:
        if instance is not None:
            name = instance.strip().lower()
        elif self._default is not None:
            name = self._default
        elif not self._configs:
            raise OpenbisConfigError(
                "No openBIS instance is configured. Set OPENBIS_URL (+ OPENBIS_TOKEN), "
                "or OPENBIS_<NAME>_URL for named instances."
            )
        else:
            raise OpenbisConfigError(
                "Multiple openBIS instances are configured but no default is set. "
                f"Pass an 'instance' argument (one of {self.names()}) or set "
                "OPENBIS_DEFAULT_INSTANCE."
            )
        if name not in self._configs:
            raise OpenbisConfigError(
                f"Unknown openBIS instance {name!r}. Configured instances: {self.names()}."
            )
        return name

    def client(self, instance: str | None = None) -> OpenbisClient:
        """Return (building if needed) the client for ``instance`` or the default."""
        name = self._resolve(instance)
        if name not in self._clients:
            self._clients[name] = OpenbisClient(**self._configs[name])
        return self._clients[name]

    def close(self) -> None:
        for client in self._clients.values():
            client.close()
        self._clients.clear()
