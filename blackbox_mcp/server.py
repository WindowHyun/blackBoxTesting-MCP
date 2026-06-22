"""MCP server entrypoint.

Boot order:
  1. ensure_chromium()  — D1, auto-install the browser on first run.
  2. register_all(mcp)  — bind every decorated tool from the tools package.
  3. mcp.run()          — stdio transport (default), used by Claude Desktop.
"""
from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from .bootstrap import ensure_chromium
from .tools import register_all

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("blackbox_mcp")

mcp = FastMCP("ui-blackbox")


def main() -> None:
    ensure_chromium()
    count = register_all(mcp)
    log.info("Registered %d tools.", count)
    mcp.run()


if __name__ == "__main__":
    main()
