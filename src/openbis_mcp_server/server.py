"""FastMCP server definition for openbis-mcp-server.

Tools are intentionally read-only at this stage. Each tool is a thin wrapper
around pyBIS that returns plain Python types (str / dict / list of dict) so
they serialize cleanly to MCP clients.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from . import __version__
from .openbis_client import OpenbisClient, OpenbisConfigError

mcp = FastMCP("openbis-mcp-server")

# A single client instance is shared across all tool invocations. It connects
# lazily on the first call that needs it, so importing this module never
# touches the network.
_client: OpenbisClient | None = None


def _get_client() -> OpenbisClient:
    global _client
    if _client is None:
        _client = OpenbisClient()
    return _client


@mcp.tool()
def get_server_info() -> dict[str, Any]:
    """Return openBIS server URL, server version, and this MCP server's version.

    Use this as a smoke test to verify connectivity and authentication before
    issuing any other calls.
    """
    try:
        client = _get_client()
        ob = client.connect()
    except OpenbisConfigError as e:
        return {"ok": False, "error": f"configuration: {e}"}
    except Exception as e:  # pyBIS raises bare Exception on auth failure
        return {"ok": False, "error": f"connection: {e}"}

    info: dict[str, Any] = {
        "ok": True,
        "url": client.url,
        "mcp_server_version": __version__,
    }
    # Different pyBIS versions expose this differently; try a couple.
    for attr in ("get_server_information", "server_information"):
        fn_or_val = getattr(ob, attr, None)
        if fn_or_val is None:
            continue
        try:
            info["server_information"] = (
                fn_or_val() if callable(fn_or_val) else fn_or_val
            )
            break
        except Exception:  # noqa: BLE001 — best-effort metadata
            continue
    return info


@mcp.tool()
def list_spaces() -> list[dict[str, Any]]:
    """List all openBIS spaces visible to the authenticated user.

    Returns a list of {code, description, registrator, registration_date} dicts.
    """
    ob = _get_client().connect()
    spaces = ob.get_spaces()

    # pyBIS returns a Things wrapper around a DataFrame; normalise to plain dicts.
    df = getattr(spaces, "df", None)
    if df is None:
        # Defensive fallback: iterate.
        return [{"code": getattr(s, "code", str(s))} for s in spaces]

    records = df.to_dict(orient="records")
    return [{str(k): _stringify(v) for k, v in row.items()} for row in records]


def _stringify(value: Any) -> Any:
    """Make pandas/openBIS values JSON-friendly without losing useful info."""
    # pandas Timestamps -> ISO strings; NaN -> None; everything else passthrough.
    import math

    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        try:
            return iso()
        except Exception:  # noqa: BLE001
            pass
    return value
