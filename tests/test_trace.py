"""trace_on_failure — Playwright trace kept only for failed runs."""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from conftest import fixture_url

from blackbox_mcp.testing import report, runner


@pytest.fixture
def report_dir(tmp_path, monkeypatch):
    cfg = dataclasses.replace(report.CONFIG, report_dir=tmp_path)
    monkeypatch.setattr(report, "CONFIG", cfg)
    return tmp_path


async def test_trace_kept_on_failure(session, report_dir):
    res = await runner.run(
        [{"action": "navigate", "url": fixture_url("basic.html")},
         {"action": "assert", "kind": "text_visible", "target": "절대없는텍스트"}],
        name="fail_trace", trace_on_failure=True)
    assert res["summary"]["failed"] == 1
    trace = res.get("trace")
    assert trace and trace.endswith(".zip") and Path(trace).exists()
    assert Path(trace).parent == report_dir / "traces"
    # run id leads the filename → retention can correlate it with the run
    assert Path(trace).name.startswith(res["run_id"])


async def test_trace_discarded_on_pass(session, report_dir):
    res = await runner.run(
        [{"action": "navigate", "url": fixture_url("basic.html")},
         {"action": "assert", "kind": "text_visible", "target": "로그인"}],
        name="pass_trace", trace_on_failure=True)
    assert res["summary"]["failed"] == 0
    assert res.get("trace") is None
    traces = report_dir / "traces"
    assert not traces.is_dir() or list(traces.glob("*.zip")) == []


async def test_trace_off_by_default(session, report_dir):
    res = await runner.run(
        [{"action": "assert", "kind": "text_visible", "target": "없는텍스트"}],
        name="no_trace")
    assert "trace" not in res


def test_prune_deletes_trace_with_its_run(report_dir):
    """Retention correlates traces by run id, same as screenshots."""
    keep_id, doomed_id = "20990101_000000_000001", "20000101_000000_000001"
    for rid in (keep_id, doomed_id):
        (report_dir / f"report_{rid}.json").write_text("{}", encoding="utf-8")
    traces = report_dir / "traces"
    traces.mkdir()
    (traces / f"{keep_id}_x.zip").write_bytes(b"z")
    (traces / f"{doomed_id}_x.zip").write_bytes(b"z")

    cfg = dataclasses.replace(report.CONFIG, report_retention=1)
    import unittest.mock as mock
    with mock.patch.object(report, "CONFIG", cfg):
        report._prune(report_dir)

    assert (traces / f"{keep_id}_x.zip").exists()
    assert not (traces / f"{doomed_id}_x.zip").exists()
