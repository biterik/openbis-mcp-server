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
"""Entry point: `python -m openbis_mcp_server` and `openbis-mcp-server` console script."""

from __future__ import annotations

from .server import mcp


def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
