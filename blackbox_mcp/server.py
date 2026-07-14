"""MCP server entrypoint.

Boot order:
  1. register_all(mcp)  — bind every decorated tool from the tools package.
  2. mcp.run()          — stdio transport (default), used by Claude Desktop.

The browser is installed LAZILY on first use (BrowserSession.start →
bootstrap.ensure_chromium via a worker thread), NOT here: a ~150MB first-run
download before mcp.run() would stall the `initialize` handshake past the
client's timeout and the server would appear dead.
"""
from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from .browser.session import close_session
from .tools import register_all

# stderr only (stdout is the MCP JSON-RPC pipe) and WARNING+ so the SDK's
# per-request INFO lines don't spam the client's logs for a long session.
# Explicit stream + our own logger level — avoid basicConfig re-tuning the root
# logger to INFO for every library in the process.
logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
log = logging.getLogger("blackbox_mcp")
log.setLevel(logging.INFO)


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
    # No ensure_chromium() here — it runs lazily on first browser use so the
    # stdio handshake is answered immediately (see module docstring).
    count = register_all(mcp)
    log.info("Registered %d tools.", count)
    mcp.run()


if __name__ == "__main__":
    main()
