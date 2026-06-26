"""CT-07: get_network_errors (4xx/5xx responses + failed requests)."""
from __future__ import annotations

from urllib.parse import urlparse

from ..browser import get_session
from ._registry import tool


@tool(description="Return buffered network errors: 4xx/5xx responses and failed "
                  "requests. Set same_origin=True to drop third-party (ads/"
                  "trackers/analytics) noise and keep only the page's own host.")
async def get_network_errors(same_origin: bool = False) -> list[dict]:
    session = await get_session()

    page_host = ""
    if same_origin:
        try:
            page_host = urlparse(session.page.url).hostname or ""
        except Exception:
            page_host = ""

    out = []
    for e in session.buffers.network:
        if same_origin and page_host:
            try:
                if (urlparse(e.url).hostname or "") != page_host:
                    continue
            except Exception:
                continue
        entry = {"url": e.url, "method": e.method}
        if e.status is not None:
            entry["status"] = e.status
        if e.failure is not None:
            entry["failure"] = e.failure
        out.append(entry)
    return out
