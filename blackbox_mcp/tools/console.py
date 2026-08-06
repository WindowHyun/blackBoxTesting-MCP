"""CT-06: get_console_logs."""
from __future__ import annotations

from ..browser import get_session
from ._registry import tool


@tool(description="Return buffered console messages filtered by level "
                  "('error' | 'warn' | 'all'). source='pageerror' marks an UNCAUGHT "
                  "JS exception or unhandled promise rejection (an app bug), as "
                  "opposed to a deliberate console.error call.")
async def get_console_logs(level: str = "all") -> list[dict]:
    session = await get_session()
    # Playwright ConsoleMessage.type uses "warning" (not "warn"); accept both.
    want = {"warn": "warning"}.get(level, level)
    out = []
    for e in session.buffers.console:
        if level != "all" and e.level != want:
            continue
        out.append({"level": e.level, "text": e.text, "location": e.location,
                    "ts": e.ts, "source": e.source})
    return out
