"""CLI runner (CI entrypoint) — exit codes, reports, JUnit, doctor."""
from __future__ import annotations

import dataclasses
import json
import xml.etree.ElementTree as ET

import pytest
from conftest import fixture_url

from blackbox_mcp import cli
from blackbox_mcp.testing import report

# CLI runs drive a real browser without the session fixture — mark explicitly;
# conftest globally skips browser-marked tests when no Chromium is launchable.
pytestmark = pytest.mark.browser


def _steps_file(tmp_path, name, steps):
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps({"name": name, "steps": steps}), encoding="utf-8")
    return str(p)


def _patch_report_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(report, "CONFIG",
                        dataclasses.replace(report.CONFIG, report_dir=tmp_path))


def test_cli_run_pass_exit_0_and_junit(tmp_path, monkeypatch, capsys):
    _patch_report_dir(monkeypatch, tmp_path)
    f = _steps_file(tmp_path, "ok", [
        {"action": "navigate", "url": fixture_url("basic.html")},
        {"action": "assert", "kind": "element_visible", "target": "css=form"},
    ])
    junit = str(tmp_path / "junit.xml")
    code = cli.main(["run", f, "--format", "json", "--junit", junit])
    assert code == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "PASS 2/2" in out
    suite = ET.parse(junit).getroot().find("testsuite")
    assert suite.get("tests") == "2" and suite.get("failures") == "0"


def test_cli_run_fail_exit_1(tmp_path, monkeypatch):
    _patch_report_dir(monkeypatch, tmp_path)
    f = _steps_file(tmp_path, "bad", [
        {"action": "navigate", "url": fixture_url("basic.html")},
        {"action": "assert", "kind": "text_visible", "target": "존재하지않는텍스트XYZ"},
    ])
    assert cli.main(["run", f, "--format", "json"]) == cli.EXIT_FAILED


def test_cli_unknown_scenario_exit_2(tmp_path, monkeypatch, capsys):
    _patch_report_dir(monkeypatch, tmp_path)
    assert cli.main(["run", "no_such_scenario_xyz"]) == cli.EXIT_ERROR
    assert "error" in capsys.readouterr().err


def test_cli_junit_with_parallel_rejected(capsys):
    code = cli.main(["run", "a", "b", "--parallel", "2", "--junit", "x.xml"])
    assert code == cli.EXIT_ERROR
    assert "junit" in capsys.readouterr().err.lower()


def _visit_counter_page(tmp_path) -> str:
    """A page that counts its own visits in localStorage — so a scenario can
    observe whether the previous scenario's storage survived."""
    p = tmp_path / "counter.html"
    p.write_text(
        "<html><body><div id='out'></div><script>"
        "const n=(parseInt(localStorage.getItem('v')||'0',10))+1;"
        "localStorage.setItem('v',String(n));"
        "document.getElementById('out').textContent='visits:'+n;"
        "</script></body></html>", encoding="utf-8")
    return p.as_uri()


def test_cli_suite_isolates_scenarios_from_each_other(tmp_path, monkeypatch):
    """A sequential suite must not carry state from one scenario to the next.

    Scenarios share ONE browser context, so without a reset between them a login
    (or any localStorage write) in A leaked into B — making the suite
    order-dependent, and giving `--parallel` (isolated, one process each)
    different results from the exact same command run sequentially.
    """
    _patch_report_dir(monkeypatch, tmp_path)
    url = _visit_counter_page(tmp_path)
    first = _steps_file(tmp_path, "first", [{"action": "navigate", "url": url}])
    # Passes only if scenario 2 starts from a clean context.
    second = _steps_file(tmp_path, "second", [
        {"action": "navigate", "url": url},
        {"action": "assert", "kind": "text_visible", "target": "visits:1"},
    ])
    assert cli.main(["run", first, second, "--format", "json"]) == cli.EXIT_OK


def test_cli_no_reset_opts_out_of_isolation(tmp_path, monkeypatch):
    """--no-reset keeps state chaining for suites that deliberately want it
    (log in once in scenario 1, reuse it in 2..N)."""
    _patch_report_dir(monkeypatch, tmp_path)
    url = _visit_counter_page(tmp_path)
    first = _steps_file(tmp_path, "first", [{"action": "navigate", "url": url}])
    second = _steps_file(tmp_path, "second", [
        {"action": "navigate", "url": url},
        {"action": "assert", "kind": "text_visible", "target": "visits:2"},
    ])
    assert cli.main(["run", first, second, "--format", "json",
                     "--no-reset"]) == cli.EXIT_OK


def test_cli_doctor_ok(capsys):
    assert cli.main(["doctor"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "doctor: OK" in out and "report_dir" in out
