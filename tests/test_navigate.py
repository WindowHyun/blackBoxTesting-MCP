"""T1.3 — navigate integration + event buffers (CT-01, CT-06, CT-07, BR-02)."""
from __future__ import annotations

from conftest import fixture_url

from blackbox_mcp.tools.navigate import navigate
from blackbox_mcp.tools.console import get_console_logs
from blackbox_mcp.tools.network import get_network_errors


async def test_navigate_returns_title_and_url(session):
    result = await navigate(fixture_url("basic.html"), wait_until="load")
    assert result["title"] == "Blackbox Fixture"
    assert result["url"].endswith("basic.html")
    # file:// yields either no status or 200 depending on the engine
    assert result["status"] in (None, 200)


async def test_console_buffer_captures_error(session):
    await navigate(fixture_url("basic.html"), wait_until="load")
    errors = (await get_console_logs(level="error"))["logs"]
    assert any("fixture console error" in e["text"] for e in errors)


async def test_network_buffer_captures_failed_request(session):
    await navigate(fixture_url("basic.html"), wait_until="load")
    net = (await get_network_errors())["errors"]
    # the missing image should surface as a failed request
    assert any("does-not-exist.png" in e["url"] for e in net)


async def test_navigate_resets_frame_context(session):
    # a stale iframe context must not survive a top-level navigation
    session.set_frame("#some-frame")
    await navigate(fixture_url("basic.html"), wait_until="load")
    assert session._frame_selector is None


# ── navigate status-code verdict (QA blocker fix) ────────────────
import http.server
import threading

import pytest


class _StatusHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            code = int(self.path.strip("/") or "200")
        except ValueError:
            code = 200
        self.send_response(code)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<h1>x</h1>")

    def log_message(self, *a):  # silence
        pass


@pytest.fixture
def http_server():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _StatusHandler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        srv.shutdown()


async def test_navigate_500_is_a_failure(session, http_server):
    from blackbox_mcp.testing import runner
    res = await runner.run([{"action": "navigate", "url": f"{http_server}/500"}],
                           name="nav_500")
    step = res["steps"][0]
    assert step["passed"] is False        # was silently True before the fix
    assert step["severity"] == "error"


async def test_navigate_404_fails_unless_expected(session, http_server):
    from blackbox_mcp.testing import runner
    r1 = await runner.run([{"action": "navigate", "url": f"{http_server}/404"}],
                          name="nav_404a")
    assert r1["steps"][0]["passed"] is False
    # opt-in: a scenario that WANTS a 404 passes
    r2 = await runner.run(
        [{"action": "navigate", "url": f"{http_server}/404", "expect_status": 404}],
        name="nav_404b")
    assert r2["steps"][0]["passed"] is True


async def test_navigate_200_passes(session, http_server):
    from blackbox_mcp.testing import runner
    res = await runner.run([{"action": "navigate", "url": f"{http_server}/200"}],
                           name="nav_200")
    assert res["steps"][0]["passed"] is True
