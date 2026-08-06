"""Runner-level coverage for the actions added in this pass, and for the
navigate failure path that used to raise instead of failing the step."""
from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from blackbox_mcp.testing import runner


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/slow"):
            time.sleep(0.4)
            body = b"<h1 data-testid=pop>POPUP</h1>"
        else:
            body = (b"<button id=b onclick=\"window.open('/slow')\">go</button>"
                    b"<div data-testid=opener>OPENER</div>"
                    b"<button id=warn onclick=\"alert('\xec\xa3\xbc\xec\x9d\x98')\">warn</button>")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def site():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}/"
    finally:
        srv.shutdown()


@pytest.mark.browser
async def test_popup_and_tab_steps(session, site):
    result = await runner.run([
        {"action": "navigate", "url": site, "wait_until": "load"},
        {"action": "expect_popup", "trigger": "css=#b", "expect_url": "/slow"},
        {"action": "assert", "kind": "element_visible", "target": "testid=pop"},
        {"action": "switch_tab", "index": 0},
        {"action": "assert", "kind": "element_visible", "target": "testid=opener"},
    ], name="popup-flow")

    assert result["summary"]["failed"] == 0, result["steps"]


@pytest.mark.browser
async def test_expect_popup_requires_a_trigger(session, site):
    result = await runner.run([{"action": "expect_popup"}], name="bad")
    step = result["steps"][0]
    assert not step["passed"] and "trigger" in step["actual"]


@pytest.mark.browser
async def test_unexpected_dialog_is_reported_on_a_passing_step(session, site):
    """The step passes (the dialog was auto-dismissed so the flow continued),
    but the report must still surface it — otherwise it is a silent defect."""
    result = await runner.run([
        {"action": "navigate", "url": site, "wait_until": "load"},
        {"action": "interact", "type": "click", "selector": "css=#warn"},
    ], name="surprise-dialog", continue_on_fail=True)

    click_step = result["steps"][1]
    assert click_step["passed"]
    assert click_step["dialogs"], click_step
    assert click_step["dialogs"][0]["expected"] is False
    assert "예상치 못한" in click_step["ai_reason"]

    from blackbox_mcp.testing import report
    md = report._render_markdown(result)
    assert "예상치 못한 dialog" in md
    assert "주의" in md          # the dialog's own text, not just a count


@pytest.mark.browser
async def test_navigate_failure_fails_the_step_instead_of_raising(session):
    """DNS/refused/TLS/proxy failures are the signature closed-network problem.
    They used to raise out of the tool as an opaque error; now the step fails
    with the browser's own reason and an intranet-oriented suggestion."""
    result = await runner.run([
        {"action": "navigate", "url": "http://127.0.0.1:9/", "wait_until": "load"},
    ], name="unreachable")

    step = result["steps"][0]
    assert not step["passed"]
    assert step["actual"]                     # carries the browser's error text
    assert "프록시" in (step["ai_suggestion"] or "")


@pytest.mark.browser
async def test_download_step_verifies_the_file(session, tmp_path, monkeypatch):
    import dataclasses

    from blackbox_mcp.tools import download as dl_mod
    monkeypatch.setattr(dl_mod, "CONFIG",
                        dataclasses.replace(dl_mod.CONFIG, download_dir=tmp_path))

    class _DL(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/f.csv"):
                body = "이름,값\n가,1\n".encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/csv")
                self.send_header("Content-Disposition",
                                 'attachment; filename="data.csv"')
            else:
                body = b'<a id=dl href="/f.csv">get</a>'
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), _DL)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        result = await runner.run([
            {"action": "navigate", "url": f"http://127.0.0.1:{srv.server_address[1]}/",
             "wait_until": "load"},
            {"action": "expect_download", "trigger": "css=#dl",
             "expect_extension": ".csv", "min_bytes": 5},
        ], name="download-flow")
    finally:
        srv.shutdown()

    assert result["summary"]["failed"] == 0, result["steps"]
    assert (tmp_path / "data.csv").exists()


@pytest.mark.browser
async def test_upload_step_runs_through_interact(session, tmp_path):
    doc = tmp_path / "증빙.txt"
    doc.write_text("evidence", encoding="utf-8")

    result = await runner.run([
        {"action": "navigate", "url": "data:text/html,<input data-testid=f type=file>",
         "wait_until": "load"},
        {"action": "interact", "type": "upload", "selector": "testid=f",
         "value": str(doc)},
    ], name="upload-flow")

    assert result["summary"]["failed"] == 0, result["steps"]
    assert "증빙.txt" in result["steps"][1]["actual"]
