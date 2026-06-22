"""CT-07: get_network_errors (4xx/5xx responses + failed requests)."""
from __future__ import annotations

from ..browser import get_session
from ._registry import tool


@tool(description="Return buffered network errors: 4xx/5xx responses and failed requests.")
async def get_network_errors() -> list[dict]:
    session = await get_session()
    out = []
    for e in session.buffers.network:
        entry = {"url": e.url, "method": e.method}
        if e.status is not None:
            entry["status"] = e.status
        if e.failure is not None:
            entry["failure"] = e.failure
        out.append(entry)
    return out
