"""MCP server entrypoint.

Boot order:
  1. ensure_chromium()  — D1, auto-install the browser on first run.
  2. register_all(mcp)  — bind every decorated tool from the tools package.
  3. mcp.run()          — stdio transport (default), used by Claude Desktop.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from .bootstrap import ensure_chromium
from .browser.session import close_session
from .tools import register_all

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("blackbox_mcp")


@asynccontextmanager
async def lifespan(_server: FastMCP):
    """Manage browser lifecycle. The session is created lazily on first use;
    here we guarantee it is torn down on shutdown so no browser process leaks."""
    try:
        yield {}
    finally:
        await close_session()
        log.info("Browser session closed on shutdown.")


mcp = FastMCP("ui-blackbox", lifespan=lifespan)


def main() -> None:
    ensure_chromium()
    count = register_all(mcp)
    log.info("Registered %d tools.", count)
    mcp.run()


if __name__ == "__main__":
    main()
