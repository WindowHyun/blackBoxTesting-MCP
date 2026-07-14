"""CLI pure-logic guards — no browser (fast unit lane)."""
from __future__ import annotations

import xml.etree.ElementTree as ET

from blackbox_mcp import cli


# M2 — a signal-killed child (negative rc) must be ERROR, never a silent PASS
def test_norm_exit_maps_signal_death_to_error():
    assert cli._norm_exit(0) == cli.EXIT_OK
    assert cli._norm_exit(1) == cli.EXIT_FAILED
    assert cli._norm_exit(2) == cli.EXIT_ERROR
    assert cli._norm_exit(-9) == cli.EXIT_ERROR   # SIGKILL (OOM)
    assert cli._norm_exit(137) == cli.EXIT_ERROR  # unexpected


# M6 — control chars in captured text must not produce parser-rejected XML
def test_write_junit_strips_control_chars(tmp_path):
    results = [{
        "name": "esc\x1b[31m",
        "meta": {"duration_ms": 10},
        "summary": {"total": 1, "passed": 0, "failed": 1},
        "steps": [{"step": 1, "action": "assert", "passed": False,
                   "duration_ms": 5, "actual": "boom\x00\x1b bad",
                   "severity": "assertion", "ai_reason": "x", "ai_suggestion": "y"}],
    }]
    out = tmp_path / "j.xml"
    cli._write_junit(results, str(out))
    raw = out.read_text(encoding="utf-8")
    assert "\x00" not in raw and "\x1b" not in raw
    tree = ET.parse(out)  # must be well-formed
    assert tree.getroot().find("testsuite").get("failures") == "1"


# M5 — a scenario that raised still yields a countable failed result
def test_errored_result_shape():
    r = cli._errored_result("login", RuntimeError("browser gone"))
    assert r["summary"] == {"total": 1, "passed": 0, "failed": 1, "skipped": 0,
                            "pass_rate": 0.0}
    assert r["steps"][0]["severity"] == "error"
    assert "browser gone" in r["steps"][0]["actual"]
