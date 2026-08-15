"""CLI suite isolation — a sequential run must mean what --parallel means.

`--parallel` gives each scenario its own process, so scenarios never see each
other's cookies. The sequential path shared one browser context across the whole
suite, so the same command produced different results depending on the flag and
state leaked forward. The repo's own examples are the case in point: every
saucedemo scenario starts with a plain navigate + login, so a two-scenario run
left the second one logged in as the first one's user.
"""
from __future__ import annotations

import dataclasses
import http.server
import json
import threading

import pytest

from blackbox_mcp import cli
from blackbox_mcp.testing import report

# Drives a real browser without the session fixture — mark explicitly.
pytestmark = pytest.mark.browser

# Counts its own loads in localStorage, which needs a real http origin
# (file:// has no persistent storage). "visits:1" on every fresh context.
_COUNTER_HTML = b"""<!doctype html><html lang="en"><body><p id="v">visits:?</p>
<script>
  const n = parseInt(localStorage.getItem('n') || '0', 10) + 1;
  localStorage.setItem('n', String(n));
  document.getElementById('v').textContent = 'visits:' + n;
</script></body></html>"""


class _CounterHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(_COUNTER_HTML)))
        self.end_headers()
        self.wfile.write(_COUNTER_HTML)

    def log_message(self, *a):
        pass


@pytest.fixture
def counter_server():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _CounterHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}/"
    finally:
        srv.shutdown()


def _scenario(tmp_path, name: str, url: str, expect: str) -> str:
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps({
        "name": name,
        "steps": [
            {"action": "navigate", "url": url},
            {"action": "assert", "kind": "text_visible", "target": expect},
        ],
    }), encoding="utf-8")
    return str(path)


@pytest.fixture
def report_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(report, "CONFIG",
                        dataclasses.replace(report.CONFIG, report_dir=tmp_path))


def test_sequential_suite_isolates_scenarios(tmp_path, counter_server, report_dir):
    """Second scenario must see a clean context — was: 'visits:2'."""
    first = _scenario(tmp_path, "first", counter_server, "visits:1")
    second = _scenario(tmp_path, "second", counter_server, "visits:1")

    code = cli.main(["run", first, second, "--format", "json"])
    assert code == cli.EXIT_OK


def test_no_isolate_keeps_the_old_continuing_flow(tmp_path, counter_server,
                                                  report_dir):
    """The escape hatch: a suite deliberately written as one flow still works,
    so isolation-by-default is not a one-way door."""
    first = _scenario(tmp_path, "first", counter_server, "visits:1")
    second = _scenario(tmp_path, "second", counter_server, "visits:2")

    code = cli.main(["run", first, second, "--format", "json", "--no-isolate"])
    assert code == cli.EXIT_OK


def test_isolation_failure_does_not_abort_the_suite(tmp_path, counter_server,
                                                    report_dir, monkeypatch, capsys):
    """A reset that blows up is a warning, not a lost suite."""
    import blackbox_mcp.browser as browser_pkg

    async def _boom():
        raise RuntimeError("browser gone")

    # Only the isolation helper resolves get_session at call time; runner bound
    # it at import, so the scenarios themselves still run.
    monkeypatch.setattr(browser_pkg, "get_session", _boom)
    first = _scenario(tmp_path, "first", counter_server, "visits:1")
    second = _scenario(tmp_path, "second", counter_server, "visits:2")  # unreset

    code = cli.main(["run", first, second, "--format", "json"])
    captured = capsys.readouterr()
    assert code == cli.EXIT_OK          # suite completed
    assert "초기화 실패" in captured.err  # and said so
