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


def test_token_file_env(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """OPENBIS_TOKEN_FILE should be read when OPENBIS_TOKEN is empty."""
    token_path = tmp_path / "tok"
    token_path.write_text("secret-token-from-file\n")
    monkeypatch.setenv("OPENBIS_URL", "https://example.invalid")
    monkeypatch.delenv("OPENBIS_TOKEN", raising=False)
    monkeypatch.setenv("OPENBIS_TOKEN_FILE", str(token_path))
    client = OpenbisClient()
    assert client._token == "secret-token-from-file"  # noqa: SLF001


def test_write_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Write tools must refuse to run when OPENBIS_MCP_ALLOW_WRITE is unset."""
    monkeypatch.delenv("OPENBIS_MCP_ALLOW_WRITE", raising=False)
    from openbis_mcp_server.server import _require_write, _write_enabled

    assert _write_enabled() is False
    with pytest.raises(RuntimeError, match="OPENBIS_MCP_ALLOW_WRITE"):
        _require_write()


def test_write_enabled_when_flag_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENBIS_MCP_ALLOW_WRITE", "1")
    from openbis_mcp_server.server import _require_write, _write_enabled

    assert _write_enabled() is True
    _require_write()  # must not raise
