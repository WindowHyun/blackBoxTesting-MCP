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
    assert r["summary"] == {"total": 0, "passed": 0, "failed": 0, "skipped": 0,
                            "pass_rate": 0.0}


def test_verification_tools_are_recorded():
    """expect_popup / expect_download / switch_tab are actions WITH a verdict.

    Leaving them out of RECORDABLE meant an ad-hoc flow whose popup or download
    verification FAILED still saved a report reading "1/1 passed · 100%" — the
    failing step was simply absent.
    """
    for action in ("expect_popup", "expect_download", "switch_tab"):
        assert action in recorder.RECORDABLE


def test_every_recordable_tool_has_an_interpret_branch():
    """A RECORDABLE name with no _interpret branch falls through to the generic
    tail, which cannot describe the tool — guard the pairing structurally."""
    import inspect

    src = inspect.getsource(recorder._interpret)
    missing = [n for n in recorder.RECORDABLE if f'"{n}"' not in src]
    assert not missing, f"no _interpret branch for: {sorted(missing)}"


def test_interpret_reads_the_verdict_of_the_new_tools():
    def passed_of(name, result, kwargs=None):
        return recorder._interpret(name, kwargs or {}, result, None)[2]

    assert passed_of("expect_popup", {"passed": True, "url": "u"}) is True
    assert passed_of("expect_popup", {"passed": False, "error": "no popup"}) is False
    assert passed_of("expect_download", {"passed": True, "filename": "a.xlsx",
                                         "size_bytes": 10}) is True
    assert passed_of("expect_download", {"passed": False, "error": "no download"}) is False
    assert passed_of("switch_tab", {"ok": True, "url": "u"}) is True
    assert passed_of("switch_tab", {"ok": False, "error": "out of range"}) is False


def test_unmapped_tool_does_not_default_to_passed():
    """The generic tail used to hard-code passed=True, so any tool added to
    RECORDABLE without a branch recorded as green no matter what it returned."""
    assert recorder._interpret("brand_new", {}, {"passed": False}, None)[2] is False
    assert recorder._interpret("brand_new", {}, {"ok": False}, None)[2] is False
    # A non-dict result (e.g. screenshot's Image) has no verdict to read → pass.
    assert recorder._interpret("brand_new", {}, "some text", None)[2] is True


async def test_recorded_step_carries_the_page_url(session):
    """P1-06 — the field is in the schema and both renderers print it on a
    failure, but the recorder never set it, so ad-hoc reports lost the one
    piece of context SPA debugging needs."""
    from conftest import fixture_url

    from blackbox_mcp.testing import recorder as rec
    from blackbox_mcp.tools.assertion import assert_
    from blackbox_mcp.tools.navigate import navigate

    rec.reset()
    url = fixture_url("basic.html")
    await rec.run_and_record("navigate", navigate, (), {"url": url})
    await rec.run_and_record("assert_", assert_, (),
                             {"kind": "text_visible", "target": "존재하지 않는 텍스트"})
    steps = rec.steps()
    assert [s["passed"] for s in steps] == [True, False]
    assert all(s["page_url"] == url for s in steps)

    # and it reaches the rendered failure detail
    from blackbox_mcp.testing import report as rep
    md = rep._render_markdown(rec.build_result(name="adhoc"))
    assert "페이지: " in md


async def test_adhoc_report_carries_real_timing(session, tmp_path, monkeypatch):
    """P2-09 — save_report stamped runner._meta's started_at (= the moment the
    report was saved) and no duration at all, so every ad-hoc report header
    read "· 0 ms ·" even though each step's duration was recorded."""
    import dataclasses

    from conftest import fixture_url

    from blackbox_mcp.testing import recorder as rec
    from blackbox_mcp.testing import report as rep
    from blackbox_mcp.tools.navigate import navigate
    from blackbox_mcp.tools.savereport import save_report

    rec.reset()
    started_before = rec._STARTED_AT
    assert started_before is None
    await rec.run_and_record("navigate", navigate, (),
                             {"url": fixture_url("basic.html")})
    flow_start = rec._STARTED_AT
    assert flow_start is not None

    built = rec.build_result(name="timing")
    assert built["meta"]["duration_ms"] == sum(
        s["duration_ms"] for s in built["steps"])
    assert built["meta"]["duration_ms"] > 0

    cfg = dataclasses.replace(rep.CONFIG, report_dir=tmp_path)
    monkeypatch.setattr(rep, "CONFIG", cfg)
    out = await save_report(name="timing", report_format="md")
    assert out["ok"] is True
    md = open(out["report_files"]["md"], encoding="utf-8").read()
    assert "· 0 ms ·" not in md
    # the header timestamp is the flow's start, not the save moment
    assert flow_start.isoformat(timespec="seconds") in md
