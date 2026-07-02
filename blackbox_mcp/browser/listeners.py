"""Console & network event buffers (BR-02).

Attached to a Page on creation; events accumulate until explicitly cleared
(via reset_session). HTTP 4xx/5xx arrive on the ``response`` event — Playwright
treats them as successful responses — while genuine network failures (DNS,
timeout, connection refused) arrive on ``requestfailed``. We capture both.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class ConsoleEntry:
    level: str
    text: str
    location: str
    ts: float


@dataclass
class NetworkEntry:
    url: str
    method: str
    # One of status (for 4xx/5xx) or failure (for requestfailed) is set.
    status: int | None = None
    failure: str | None = None


# Cap so a chatty page (SPA polling, ad errors) can't grow memory without
# bound on a long-lived session; the newest entries win. Step attribution in
# runner/recorder slices by index, so a trim mid-step can at worst drop a few
# old entries from that step's slice — never mis-attribute new ones.
_MAX_EVENTS = 1000


@dataclass
class EventBuffers:
    console: list[ConsoleEntry] = field(default_factory=list)
    network: list[NetworkEntry] = field(default_factory=list)

    def add_console(self, entry: ConsoleEntry) -> None:
        self.console.append(entry)
        if len(self.console) > _MAX_EVENTS:
            del self.console[:-_MAX_EVENTS]

    def add_network(self, entry: NetworkEntry) -> None:
        self.network.append(entry)
        if len(self.network) > _MAX_EVENTS:
            del self.network[:-_MAX_EVENTS]

    def clear(self) -> None:
        self.console.clear()
        self.network.clear()


def attach(page, buffers: EventBuffers) -> None:
    """Attach console/response/requestfailed listeners to a Page."""

    def on_console(msg) -> None:
        loc = ""
        try:
            location = msg.location  # {url, line, column} (lineNumber deprecated)
            if location:
                line = location.get("line", location.get("lineNumber", ""))
                loc = f"{location.get('url', '')}:{line}"
        except Exception:
            pass
        buffers.add_console(
            ConsoleEntry(level=msg.type, text=msg.text, location=loc, ts=time.time())
        )

    def on_response(resp) -> None:
        try:
            if resp.status >= 400:
                buffers.add_network(
                    NetworkEntry(
                        url=resp.url,
                        method=resp.request.method,
                        status=resp.status,
                    )
                )
        except Exception:
            pass

    def on_request_failed(req) -> None:
        try:
            buffers.add_network(
                NetworkEntry(
                    url=req.url,
                    method=req.method,
                    failure=(req.failure or "request failed"),
                )
            )
        except Exception:
            pass

    page.on("console", on_console)
    page.on("response", on_response)
    page.on("requestfailed", on_request_failed)
