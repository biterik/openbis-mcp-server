"""Entry point: `python -m openbis_mcp_server` and `openbis-mcp-server` console script."""

from __future__ import annotations

from .server import mcp


def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
