"""Regression tests for the code-validation review findings.

Each test here pins a defect that the suite passed straight through before:

P0-1  a navigation that never got a response reported as PASS (runner AND the
      ad-hoc recorder path), with the report printing "navigated to about:blank"
P0-2  the end-of-run a11y audit hung forever on an unresponsive page — no
      exception, so the try/except around it never fired
P1-3  once an event buffer hit its 1000-entry cap, every console/network/dialog
      event raised during a step disappeared from the report
P1-4  dismiss_banners clicked "주문 확인" because "확인" matched as a substring
P2-6  expect_popup/expect_download/switch_tab were missing from the recorder, so
      an ad-hoc flow that verified a download reported no trace of it
P2-7  report meta named the CONFIGURED browser binary, not the one the launch
      fallback chain actually used
P2-8  an interact step missing 'type' failed with "unknown action" instead of
      naming the missing field

(P2-5, CLI suite isolation, is covered in test_cli_isolation.py — it needs a
real suite run.)
"""
from __future__ import annotations

import asyncio
import dataclasses
import socket
import threading
import time

import pytest
from conftest import fixture_url

from blackbox_mcp.browser.listeners import ConsoleEntry, DialogEntry, EventBuffers, NetworkEntry
from blackbox_mcp.config import CONFIG


# ── P1-3: step attribution survives the buffer cap ───────────────
def _fill(buffers: EventBuffers, n: int) -> None:
    for i in range(n):
        buffers.add_console(ConsoleEntry(level="log", text=f"noise{i}",
                                         location="", ts=0.0))


def test_console_attribution_survives_the_cap():
    """A chatty page must not swallow the errors a step actually produced."""
    b = EventBuffers()
    _fill(b, 1000)                      # buffer is now pinned at the cap
    mark = b.mark()
    for i in range(3):
        b.add_console(ConsoleEntry(level="error", text=f"Uncaught BOOM{i}",
                                   location="", ts=0.0, source="pageerror"))

    console, _, _ = b.since(mark)
    assert [c.text for c in console] == ["Uncaught BOOM0", "Uncaught BOOM1",
                                         "Uncaught BOOM2"]
    # the old length-based slice, for contrast: len() never grew past the cap
    assert b.console[1000:] == []


def test_network_and_dialog_attribution_survive_the_cap():
    b = EventBuffers()
    for i in range(1000):
        b.add_network(NetworkEntry(url=f"http://x/{i}", method="GET", status=500))
        b.add_dialog(DialogEntry(type="alert", message=f"m{i}", handled="dismiss",
                                 expected=False, ts=0.0))
    mark = b.mark()
    b.add_network(NetworkEntry(url="http://x/late", method="GET", status=503))
    b.add_dialog(DialogEntry(type="confirm", message="late", handled="dismiss",
                             expected=False, ts=0.0))

    _, network, dialogs = b.since(mark)
    assert [n.url for n in network] == ["http://x/late"]
    assert [d.message for d in dialogs] == ["late"]


def test_mark_survives_a_clear_mid_step():
    """A step that resets the session must still report what the fresh page
    then raised — the wiped entries are gone, the new ones are not."""
    b = EventBuffers()
    _fill(b, 10)
    mark = b.mark()
    b.clear()                            # e.g. a reset_session step
    b.add_console(ConsoleEntry(level="error", text="after reset", location="", ts=0.0))
    console, _, _ = b.since(mark)
    assert [c.text for c in console] == ["after reset"]


def test_dropped_counter_tracks_evictions():
    b = EventBuffers()
    _fill(b, 1005)
    assert len(b.console) == 1000
    assert b.console_dropped == 5
    assert b.mark().console == 1005      # total ever appended


# ── P0-2: page.evaluate is bounded ───────────────────────────────
class _WedgedPage:
    """A page whose evaluate never returns — an unresponsive document."""

    def __init__(self) -> None:
        self.calls = 0

    async def evaluate(self, script, arg=None):
        self.calls += 1
        await asyncio.Event().wait()     # forever, and never raises
        return []                        # pragma: no cover


async def test_safe_evaluate_gives_up_instead_of_hanging():
    from blackbox_mcp.browser.probe import safe_evaluate

    t0 = time.monotonic()
    out = await safe_evaluate(_WedgedPage(), "() => 1", timeout_s=0.2, default="fallback")
    assert out == "fallback"
    assert time.monotonic() - t0 < 5     # bounded, not "forever"


async def test_a11y_audit_gives_up_instead_of_hanging(monkeypatch):
    """The audit runs at the end of EVERY run — a hang here stops the run."""
    from blackbox_mcp.browser import probe
    from blackbox_mcp.testing import runner

    monkeypatch.setattr(probe, "EVAL_TIMEOUT_S", 0.2)
    session = type("S", (), {"page": _WedgedPage()})()

    t0 = time.monotonic()
    assert await runner._a11y_audit(session) == []
    assert time.monotonic() - t0 < 5


async def test_safe_evaluate_still_returns_real_results():
    from blackbox_mcp.browser.probe import safe_evaluate

    class _Page:
        async def evaluate(self, script, arg=None):
            return [{"type": "img-missing-alt"}] if arg is None else arg

    assert await safe_evaluate(_Page(), "() => 1") == [{"type": "img-missing-alt"}]
    assert await safe_evaluate(_Page(), "(a) => a", 42) == 42


# ── P0-1: a navigation that never committed is a failure ─────────
def test_recorder_reports_navigation_error_as_failure():
    """The ad-hoc (recorder) path ignored `error` entirely — status None read
    as 'reachable', so a DNS failure was recorded as a passing step."""
    from blackbox_mcp.testing import recorder

    result = {"title": None, "url": "about:blank", "status": None,
              "settled": False, "error": "net::ERR_NAME_NOT_RESOLVED"}
    _, actual, passed, _, reason, suggestion = recorder._interpret(
        "navigate", {}, result, None)

    assert passed is False
    assert "ERR_NAME_NOT_RESOLVED" in actual
    assert reason == "navigation failed before a response"
    assert suggestion


def test_recorder_still_passes_a_normal_navigation():
    from blackbox_mcp.testing import recorder

    result = {"title": "Home", "url": "http://x/", "status": 200,
              "settled": True, "error": None}
    assert recorder._interpret("navigate", {}, result, None)[2] is True


@pytest.fixture
def dead_server():
    """Accepts the TCP connection and never answers — a firewalled or hung app.
    Distinct from a refused connection, which fails fast and was already caught."""
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    held: list = []

    def accept_forever():
        while True:
            try:
                held.append(srv.accept()[0])   # hold it open, send nothing
            except OSError:
                return

    threading.Thread(target=accept_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.getsockname()[1]}/"
    finally:
        srv.close()
        for conn in held:
            conn.close()


@pytest.fixture
def fast_nav_timeout(monkeypatch):
    """Keep the no-response test to a few seconds instead of the 30s default."""
    from blackbox_mcp.tools import navigate as nav_mod

    monkeypatch.setattr(nav_mod, "CONFIG",
                        dataclasses.replace(CONFIG, nav_timeout_ms=3000))


async def test_unresponsive_server_fails_the_step(session, dead_server,
                                                  fast_nav_timeout, monkeypatch):
    """Was: PASSED, pass_rate 1.0, 'navigated to about:blank (status None)'."""
    from blackbox_mcp.browser import probe
    from blackbox_mcp.testing import runner

    monkeypatch.setattr(probe, "EVAL_TIMEOUT_S", 1.0)   # page is wedged; don't wait 10s
    res = await runner.run([{"action": "navigate", "url": dead_server}],
                           name="dead_server")

    step = res["steps"][0]
    assert step["passed"] is False
    assert step["severity"] == "error"
    assert "did not commit" in step["actual"]
    assert res["summary"]["failed"] == 1


async def test_committed_but_unsettled_page_still_passes(session, fast_nav_timeout):
    """The other half of the timeout: the document IS there and only the settle
    condition ran out. That must stay a pass, or every ad-heavy page fails."""
    from blackbox_mcp.tools.navigate import navigate

    # 'load' never fires: the route handler never resolves this subresource.
    await session.page.route("**/never-finishes.png", lambda route: None)
    html = ("<html><head><title>Slow</title></head><body><h1>committed</h1>"
            "<img src='/never-finishes.png'></body></html>")
    await session.page.route(
        "**/slow-page", lambda route: route.fulfill(
            status=200, content_type="text/html", body=html))

    res = await navigate("http://127.0.0.1:9/slow-page", wait_until="load")
    assert res["error"] is None            # committed → not a failure
    assert res["settled"] is False         # but honestly reported as unsettled
    assert res["title"] == "Slow"


async def test_navigate_leaves_no_listener_behind(session):
    """navigate runs on every step; the commit probe must not accumulate."""
    from blackbox_mcp.tools.navigate import navigate

    url = fixture_url("basic.html")
    for _ in range(3):
        await navigate(url, wait_until="load")
    # Playwright keeps handlers on the impl object's emitter.
    listeners = session.page._impl_obj._events.get("framenavigated", [])
    assert len(listeners) == 0


# ── P1-4: dismiss_banners cannot fire business actions ───────────
async def test_dismiss_banners_ignores_in_page_business_buttons(session):
    """Was: clicked '주문 확인' (substring match on '확인') → ORDER SUBMITTED."""
    from blackbox_mcp.tools.navigate import navigate
    from blackbox_mcp.tools.overlays import dismiss_banners

    await navigate(fixture_url("banner.html"), wait_until="load")
    r = await dismiss_banners()

    assert await session.page.title() == "Banner Fixture"   # nothing submitted
    assert not any("확인" in d for d in r["dismissed"])


async def test_dismiss_banners_still_closes_a_real_banner(session):
    """The narrowing must not cost the tool its actual job."""
    from blackbox_mcp.tools.assertion import assert_
    from blackbox_mcp.tools.navigate import navigate
    from blackbox_mcp.tools.overlays import dismiss_banners

    await navigate(fixture_url("banner.html"), wait_until="load")
    r = await dismiss_banners()

    assert any("동의" in d for d in r["dismissed"])
    assert (await assert_("element_visible", "#cookie"))["passed"] is False
    assert (await assert_("element_visible", "testid=real"))["passed"] is True


async def test_dismiss_banners_reports_what_it_skipped(session):
    """A consent-worded control outside an overlay is left alone AND surfaced,
    so a banner this misses is debuggable instead of silent."""
    from blackbox_mcp.tools.overlays import dismiss_banners

    await session.page.set_content(
        "<div><button onclick=\"document.title='AGREED'\">동의</button></div>")
    r = await dismiss_banners()

    assert r["dismissed"] == []
    assert any("동의" in s for s in r["skipped_not_overlay"])
    assert await session.page.title() != "AGREED"


async def test_dismiss_banners_handles_a_dialog_role_modal(session):
    """role=dialog counts as an overlay even without fixed positioning."""
    from blackbox_mcp.tools.overlays import dismiss_banners

    await session.page.set_content(
        "<div role='dialog' id='m'>쿠키"
        "<button onclick=\"document.getElementById('m').remove()\">수락</button>"
        "</div>")
    r = await dismiss_banners()
    assert any("수락" in d for d in r["dismissed"])


# ── P2-6: verification tools reach the ad-hoc report ─────────────
def test_verification_tools_are_recordable():
    """A flow that verifies a popup or a download must leave a trace in the
    report save_report writes — these three were silently unrecorded."""
    from blackbox_mcp.testing import recorder

    assert {"expect_popup", "expect_download", "switch_tab"} <= recorder.RECORDABLE


def test_failed_download_records_as_a_failure():
    """The generic fallback branch marked every unknown tool passed=True, so a
    download that never arrived would have been recorded as a passing step."""
    from blackbox_mcp.testing import recorder

    result = {"passed": False, "resolved_by": "testid", "path": None,
              "error": "no download within 30000ms (TimeoutError)"}
    expected, actual, passed, resolved_by, reason, suggestion = recorder._interpret(
        "expect_download", {"expect_extension": ".xlsx"}, result, None)

    assert passed is False
    assert expected == ".xlsx"
    assert "no download" in actual
    assert resolved_by == "testid"
    assert suggestion


def test_successful_download_records_filename_and_size():
    from blackbox_mcp.testing import recorder

    result = {"passed": True, "resolved_by": "role=button",
              "filename": "report.xlsx", "size_bytes": 2048}
    _, actual, passed, _, reason, suggestion = recorder._interpret(
        "expect_download", {}, result, None)

    assert passed is True
    assert actual == "report.xlsx (2048B)"
    assert suggestion is None


def test_failed_popup_records_as_a_failure():
    from blackbox_mcp.testing import recorder

    result = {"passed": False, "url": None, "error": "no popup opened within 30000ms"}
    _, actual, passed, _, _, suggestion = recorder._interpret(
        "expect_popup", {"expect_url": "/terms"}, result, None)

    assert passed is False
    assert "no popup" in actual
    assert suggestion


def test_switch_tab_records_its_verdict():
    from blackbox_mcp.testing import recorder

    ok = recorder._interpret("switch_tab", {"index": 1},
                             {"ok": True, "index": 1, "url": "http://x/"}, None)
    assert ok[2] is True and ok[1] == "http://x/"

    bad = recorder._interpret("switch_tab", {"index": 9},
                              {"ok": False, "error": "tab 9 out of range"}, None)
    assert bad[2] is False and "out of range" in bad[1]


# ── P2-7: meta names the binary that actually ran ────────────────
class _StubSession:
    """Enough of a session for _meta; the rest is caught by its try/excepts."""

    def __init__(self, launched_via=None):
        if launched_via is not None:
            self.launched_via = launched_via


def test_meta_reports_the_binary_that_actually_launched(monkeypatch):
    """A stale CHROMIUM_EXECUTABLE falls through to the bundled browser; the
    report used to name the stale path anyway and call itself reproducible."""
    from blackbox_mcp.testing import runner

    monkeypatch.setattr(runner, "CONFIG", dataclasses.replace(
        CONFIG, chromium_executable="/gone/chrome"))

    assert runner._meta(_StubSession("bundled"))["executable"] == "bundled"
    assert runner._meta(_StubSession("chrome"))["executable"] == "chrome"


def test_meta_falls_back_when_the_session_never_started(monkeypatch):
    from blackbox_mcp.testing import runner

    monkeypatch.setattr(runner, "CONFIG", dataclasses.replace(
        CONFIG, chromium_executable="/opt/chrome"))
    assert runner._meta(_StubSession())["executable"] == "/opt/chrome"


async def test_session_records_how_it_launched(session):
    """The real chain sets it — not just the stub."""
    assert session.launched_via in ("bundled", CONFIG.chromium_executable,
                                    CONFIG.browser_channel, "cdp")
    assert session.launched_via


# ── P2-8: a missing interact verb names itself ───────────────────
async def test_interact_step_without_type_names_the_missing_field():
    """No browser needed: malformed steps are rejected before dispatch."""
    from blackbox_mcp.testing import runner

    out = await runner._dispatch({"action": "interact", "selector": "#login"})
    assert out["passed"] is False
    assert "type" in out["actual"]
    assert out["ai_reason"] == "malformed step"


async def test_interact_step_with_type_still_dispatches(monkeypatch):
    """Tightening the required set must not start rejecting valid steps."""
    from blackbox_mcp.testing import runner

    seen: dict = {}

    async def _fake_interact(action, selector, value=None):
        seen.update(action=action, selector=selector, value=value)
        return {"ok": True, "detail": "clicked", "resolved_by": "css"}

    monkeypatch.setattr(runner, "interact", _fake_interact)
    out = await runner._dispatch({"action": "interact", "selector": "#login",
                                  "type": "click"})

    assert out["passed"] is True
    assert seen == {"action": "click", "selector": "#login", "value": None}
