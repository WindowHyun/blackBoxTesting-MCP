"""CT-07: get_network_errors (4xx/5xx responses + failed requests)."""
from __future__ import annotations

from urllib.parse import urlparse

from ..browser import get_session
from ._registry import tool


@tool(description="Return buffered network errors (4xx/5xx responses + failed "
                  "requests), newest last. same_origin=True drops third-party "
                  "(ads/trackers) noise. Returns {errors, total, returned, "
                  "truncated, dropped}: at most `limit` newest (default 200) to "
                  "bound the response, with flags when older entries were cut or "
                  "evicted by the 1000-entry buffer cap.")
async def get_network_errors(same_origin: bool = False, limit: int = 200) -> dict:
    session = await get_session()

    page_host = ""
    if same_origin:
        try:
            page_host = urlparse(session.page.url).hostname or ""
        except Exception:
            page_host = ""

    matched: list[dict] = []
    for e in session.buffers.network:
        if same_origin and page_host:
            try:
                if (urlparse(e.url).hostname or "") != page_host:
                    continue
            except Exception:
                continue
        entry: dict = {"url": e.url, "method": e.method}
        if e.status is not None:
            entry["status"] = e.status
        if e.failure is not None:
            entry["failure"] = e.failure
        matched.append(entry)

    total = len(matched)
    lim = max(1, limit)
    errors = matched[-lim:]
    return {"errors": errors, "total": total, "returned": len(errors),
            "truncated": total > len(errors),
            "dropped": session.buffers.network_dropped}
