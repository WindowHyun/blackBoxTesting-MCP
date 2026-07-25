"""MCP server entrypoint.

Boot order:
  1. start_background_bootstrap() — D1, auto-install the browser on first run,
     on a worker thread so a ~150MB download can't stall the MCP handshake.
     The first browser launch waits for it (session.start → await_bootstrap).
  2. register_all(mcp)  — bind every decorated tool from the tools package.
  3. mcp.run()          — stdio transport (default), used by Claude Desktop.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from .bootstrap import start_background_bootstrap
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
    # Kicked off, not awaited: the client's `initialize` must be answered in
    # milliseconds even when this is the very first run and the browser still
    # has to be downloaded (see bootstrap.start_background_bootstrap).
    start_background_bootstrap()
    count = register_all(mcp)
    log.info("Registered %d tools.", count)
    mcp.run()


if __name__ == "__main__":
    main()
