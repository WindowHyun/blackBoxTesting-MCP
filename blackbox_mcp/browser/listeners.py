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


@dataclass
class EventBuffers:
    console: list[ConsoleEntry] = field(default_factory=list)
    network: list[NetworkEntry] = field(default_factory=list)

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
        buffers.console.append(
            ConsoleEntry(level=msg.type, text=msg.text, location=loc, ts=time.time())
        )

    def on_response(resp) -> None:
        try:
            if resp.status >= 400:
                buffers.network.append(
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
            buffers.network.append(
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
