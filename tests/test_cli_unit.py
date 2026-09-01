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


# P0-03 — skipped steps must never be counted as passes in the suite total
def test_suite_line_does_not_count_skipped_as_passed():
    # 4 steps: 1 passed, 1 failed, 2 never ran (early stop)
    results = [{"summary": {"total": 4, "passed": 1, "failed": 1, "skipped": 2,
                            "pass_rate": 0.5}}]
    line = cli._suite_line(results)
    assert line.startswith("total: 1/4 passed")   # NOT 3/4 (total - failed)
    assert "1 failed" in line
    assert "2 skipped" in line


def test_suite_line_is_terse_when_all_green():
    results = [{"summary": {"total": 3, "passed": 3, "failed": 0, "skipped": 0,
                            "pass_rate": 1.0}}]
    assert cli._suite_line(results) == "total: 3/3 passed"


def test_suite_line_aggregates_across_scenarios():
    results = [
        {"summary": {"total": 2, "passed": 2, "failed": 0, "skipped": 0}},
        {"summary": {"total": 5, "passed": 1, "failed": 1, "skipped": 3}},
    ]
    line = cli._suite_line(results)
    assert line.startswith("total: 3/7 passed")
    assert "1 failed" in line and "3 skipped" in line


def test_suite_line_tolerates_errored_result_shape():
    # _errored_result is built by hand; the line must not KeyError on it
    line = cli._suite_line([cli._errored_result("boom", RuntimeError("x"))])
    assert line.startswith("total: 0/1 passed")
