"""Recorder gating + report assembly (regression guards)."""
from __future__ import annotations

from blackbox_mcp.testing import recorder


def test_observational_tools_not_recorded():
    # reads must not become report steps; actions must
    assert "snapshot" not in recorder.RECORDABLE
    assert "get_console_logs" not in recorder.RECORDABLE
    assert "get_network_errors" not in recorder.RECORDABLE
    for action in ("navigate", "interact", "assert_", "screenshot", "wait"):
        assert action in recorder.RECORDABLE


def test_build_result_empty():
    recorder.reset()
    r = recorder.build_result(name="x")
    assert r["summary"] == {"total": 0, "passed": 0, "failed": 0, "pass_rate": 0.0}
