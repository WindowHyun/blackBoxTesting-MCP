"""CT-06: get_console_logs."""
from __future__ import annotations

from typing import Literal

from ..browser import get_session
from ._registry import tool

Level = Literal["all", "error", "warn", "warning", "info", "debug", "log"]


@tool(description="Return buffered console messages, newest last. level filters "
                  "by severity ('all'|'error'|'warn'|...). Returns "
                  "{logs, total, returned, truncated, dropped}: at most `limit` "
                  "newest entries (default 200) to bound the response size, with "
                  "truncated/dropped flags when older events were cut or evicted "
                  "by the 1000-entry buffer cap.")
async def get_console_logs(level: Level = "all", limit: int = 200) -> dict:
    session = await get_session()
    # Playwright ConsoleMessage.type uses "warning" (not "warn"); accept both.
    want = {"warn": "warning"}.get(level, level)
    matched = [{"level": e.level, "text": e.text, "location": e.location, "ts": e.ts}
               for e in session.buffers.console
               if level == "all" or e.level == want]
    total = len(matched)
    lim = max(1, limit)
    logs = matched[-lim:]
    return {"logs": logs, "total": total, "returned": len(logs),
            "truncated": total > len(logs),
            "dropped": session.buffers.console_dropped}
