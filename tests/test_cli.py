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


def test_cli_doctor_ok(capsys):
    assert cli.main(["doctor"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "doctor: OK" in out and "report_dir" in out
