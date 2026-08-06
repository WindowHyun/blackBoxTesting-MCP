"""Console, network & dialog event buffers (BR-02).

Attached to a Page on creation; events accumulate until explicitly cleared
(via reset_session). HTTP 4xx/5xx arrive on the ``response`` event — Playwright
treats them as successful responses — while genuine network failures (DNS,
timeout, connection refused) arrive on ``requestfailed``. We capture both.

Uncaught JS exceptions and unhandled promise rejections do **not** surface as
``console`` messages in Playwright — they only arrive on ``pageerror``. Without
that listener the single most valuable black-box signal (the app threw) is
invisible and a broken page reports as a clean pass, so we capture it as an
error-level console entry tagged ``source="pageerror"``.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ConsoleEntry:
    level: str
    text: str
    location: str
    ts: float
    # "console" for console.*; "pageerror" for uncaught exceptions/rejections.
    # Defaulted so existing constructions (and older records) stay valid.
    source: str = "console"


@dataclass
class DialogEntry:
    """A native dialog (alert/confirm/prompt/beforeunload) the page raised."""
    type: str
    message: str
    handled: str        # accept | dismiss
    expected: bool      # True when expect_dialog was armed for it
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
    dialogs: list[DialogEntry] = field(default_factory=list)
    # Set by expect_dialog for the duration of one triggering action. When set,
    # the recorder below hands the dialog to it instead of dismissing.
    #
    # Why an override slot instead of expect_dialog registering its own
    # page.once("dialog", ...): Playwright runs EVERY registered listener, and
    # the always-on recorder is registered first — it would dismiss the dialog
    # before expect_dialog could accept it. One handler, one decision.
    dialog_handler: Callable[[Any], Any] | None = None

    def add_console(self, entry: ConsoleEntry) -> None:
        self.console.append(entry)
        if len(self.console) > _MAX_EVENTS:
            del self.console[:-_MAX_EVENTS]

    def add_network(self, entry: NetworkEntry) -> None:
        self.network.append(entry)
        if len(self.network) > _MAX_EVENTS:
            del self.network[:-_MAX_EVENTS]

    def add_dialog(self, entry: DialogEntry) -> None:
        self.dialogs.append(entry)
        if len(self.dialogs) > _MAX_EVENTS:
            del self.dialogs[:-_MAX_EVENTS]

    def clear(self) -> None:
        self.console.clear()
        self.network.clear()
        self.dialogs.clear()
        # Not dialog_handler: it belongs to an in-flight expect_dialog, and a
        # buffer clear mid-action must not silently turn its accept into a
        # dismiss. expect_dialog always restores it in a finally.


def attach(page, buffers: EventBuffers) -> None:
    """Attach console/pageerror/response/requestfailed/dialog listeners to a Page."""

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

    def on_page_error(err) -> None:
        """Uncaught exception / unhandled rejection — recorded as an error-level
        console entry so every existing consumer (get_console_logs, the step's
        console_errors, the HTML report) picks it up with no schema change."""
        try:
            # err is an Error object on modern Playwright, a plain string on
            # older builds — str() covers both without version sniffing.
            message = getattr(err, "message", None) or str(err)
            stack = getattr(err, "stack", "") or ""
            first_frame = next(
                (ln.strip() for ln in stack.splitlines()[1:] if ln.strip()), "")
            buffers.add_console(ConsoleEntry(
                level="error", text=f"Uncaught {message}", location=first_frame,
                ts=time.time(), source="pageerror",
            ))
        except Exception:
            pass

    async def on_dialog(dialog) -> None:
        """Always-on dialog handler.

        With no listener at all Playwright auto-dismisses dialogs, so an
        unexpected alert on page load vanished entirely — no record, no
        failure, a silent pass. Recording every dialog (and dismissing the ones
        nobody armed expect_dialog for) makes them visible while keeping the
        page unblocked.
        """
        handler = buffers.dialog_handler
        dtype = getattr(dialog, "type", "")
        message = getattr(dialog, "message", "")
        if handler is not None:
            try:
                await handler(dialog)          # expect_dialog decides + records
            except Exception:
                pass
            return
        try:
            await dialog.dismiss()
            handled = "dismiss"
        except Exception:
            handled = "unhandled"
        buffers.add_dialog(DialogEntry(type=dtype, message=message,
                                       handled=handled, expected=False,
                                       ts=time.time()))

    page.on("console", on_console)
    page.on("pageerror", on_page_error)
    page.on("response", on_response)
    page.on("requestfailed", on_request_failed)
    page.on("dialog", on_dialog)
