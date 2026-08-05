"""File upload and download verification — the payoff steps of most internal
business flows, and previously untestable."""
from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from blackbox_mcp.tools.interact import interact


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/file.xlsx"):
            body, ctype = b"PK\x03\x04fake-xlsx-payload", "application/vnd.ms-excel"
            extra = [("Content-Disposition", 'attachment; filename="report.xlsx"')]
        elif self.path.startswith("/empty"):
            body, ctype = b"", "application/octet-stream"
            extra = [("Content-Disposition", 'attachment; filename="empty.csv"')]
        else:
            body, ctype = (b'<a id=dl href="/file.xlsx">download</a>'
                           b'<a id=none href="#">nothing</a>'
                           b'<a id=zero href="/empty">empty</a>'), "text/html"
            extra = []
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def dl_site():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}/"
    finally:
        srv.shutdown()


@pytest.fixture
def download_dir(tmp_path, monkeypatch):
    """Config is frozen, so swap the module's whole CONFIG for a copy."""
    import dataclasses

    from blackbox_mcp.tools import download as dl_mod
    monkeypatch.setattr(dl_mod, "CONFIG",
                        dataclasses.replace(dl_mod.CONFIG, download_dir=tmp_path))
    return tmp_path


# ── upload ───────────────────────────────────────────────────────
async def test_upload_sets_the_file_on_the_input(session, tmp_path):
    target = tmp_path / "청구서.txt"
    target.write_text("hello", encoding="utf-8")
    await session.page.set_content("<input data-testid=file type=file>")

    res = await interact("upload", "testid=file", str(target))
    assert res["ok"], res
    assert "청구서.txt" in res["detail"]

    name = await session.page.evaluate(
        "() => document.querySelector('input[type=file]').files[0].name")
    assert name == "청구서.txt"


async def test_upload_multiple_files(session, tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("a"); b.write_text("b")
    await session.page.set_content("<input data-testid=file type=file multiple>")

    res = await interact("upload", "testid=file", f"{a},{b}")
    assert res["ok"] and "2 file(s)" in res["detail"]
    count = await session.page.evaluate(
        "() => document.querySelector('input[type=file]').files.length")
    assert count == 2


async def test_upload_rejects_a_missing_path_before_touching_the_page(session):
    await session.page.set_content("<input data-testid=file type=file>")
    res = await interact("upload", "testid=file", "/nope/missing.pdf")
    assert not res["ok"] and "not found" in res["error"]


async def test_upload_requires_a_value(session):
    await session.page.set_content("<input data-testid=file type=file>")
    res = await interact("upload", "testid=file")
    assert not res["ok"] and "requires a value" in res["error"]


# ── download ─────────────────────────────────────────────────────
@pytest.mark.browser
async def test_download_is_saved_and_verified(session, dl_site, download_dir):
    from blackbox_mcp.tools.download import expect_download

    await session.page.goto(dl_site)
    res = await expect_download("css=#dl", expect_extension=".xlsx",
                                expect_name="report")
    assert res["passed"], res
    assert res["filename"] == "report.xlsx"
    assert res["size_bytes"] > 0
    assert (download_dir / "report.xlsx").exists()


@pytest.mark.browser
async def test_download_extension_mismatch_fails(session, dl_site, download_dir):
    from blackbox_mcp.tools.download import expect_download

    await session.page.goto(dl_site)
    res = await expect_download("css=#dl", expect_extension=".pdf")
    assert not res["passed"] and ".pdf" in res["error"]


@pytest.mark.browser
async def test_zero_byte_download_fails_min_bytes(session, dl_site, download_dir):
    """A server that answers a download with an error page/0 bytes must not
    read as a successful download."""
    from blackbox_mcp.tools.download import expect_download

    await session.page.goto(dl_site)
    res = await expect_download("css=#zero", min_bytes=1)
    assert not res["passed"] and "min_bytes" in res["error"]


@pytest.mark.browser
async def test_no_download_reports_clearly(session, dl_site, download_dir):
    from blackbox_mcp.tools.download import expect_download

    await session.page.goto(dl_site)
    started = time.monotonic()
    res = await expect_download("css=#none", timeout_ms=1000)
    assert not res["passed"] and "no download" in res["error"]
    assert time.monotonic() - started < 10
