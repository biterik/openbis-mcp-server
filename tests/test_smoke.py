"""Smoke tests that don't require a live openBIS instance."""

from __future__ import annotations

import pytest

from openbis_mcp_server.openbis_client import OpenbisClient, OpenbisConfigError


def test_missing_url_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENBIS_URL", raising=False)
    monkeypatch.delenv("OPENBIS_TOKEN", raising=False)
    monkeypatch.delenv("OPENBIS_USERNAME", raising=False)
    monkeypatch.delenv("OPENBIS_PASSWORD", raising=False)
    with pytest.raises(OpenbisConfigError, match="OPENBIS_URL"):
        OpenbisClient()


def test_missing_credentials_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENBIS_URL", "https://example.invalid")
    monkeypatch.delenv("OPENBIS_TOKEN", raising=False)
    monkeypatch.delenv("OPENBIS_USERNAME", raising=False)
    monkeypatch.delenv("OPENBIS_PASSWORD", raising=False)
    with pytest.raises(OpenbisConfigError, match="No credentials"):
        OpenbisClient()


def test_token_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENBIS_URL", "https://example.invalid")
    monkeypatch.setenv("OPENBIS_TOKEN", "tok")
    # Should not raise; lazy connect is not triggered.
    client = OpenbisClient()
    assert client.url == "https://example.invalid"


def test_server_module_imports() -> None:
    """Importing the server module must not require a live connection."""
    import openbis_mcp_server.server as server  # noqa: F401

    assert server.mcp is not None
