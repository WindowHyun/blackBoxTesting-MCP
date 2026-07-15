"""Report enrichment: skipped steps, meta identity, trend, tags, flaky retry."""
from __future__ import annotations

import dataclasses
import re

import pytest
from conftest import fixture_url

from blackbox_mcp.testing import report, runner


@pytest.fixture
def report_dir(tmp_path, monkeypatch):
    cfg = dataclasses.replace(report.CONFIG, report_dir=tmp_path)
    monkeypatch.setattr(report, "CONFIG", cfg)
    return tmp_path


# ── P1: early stop must not swallow the un-run steps ──────────────
async def test_skipped_steps_are_reported(session, report_dir):
    res = await runner.run(
        [{"action": "navigate", "url": fixture_url("basic.html")},
         {"action": "assert", "kind": "text_visible", "target": "절대없는텍스트"},
         {"action": "interact", "type": "click", "selector": "testid=submit"},
         {"action": "assert", "kind": "text_visible", "target": "로그인됨"}],
        name="early_stop")
    assert len(res["steps"]) == 4              # nothing vanishes
    assert res["steps"][2]["skipped"] is True
    assert res["steps"][3]["skipped"] is True
    assert res["summary"] == {"total": 4, "passed": 1, "failed": 1,
                              "skipped": 2, "pass_rate": 0.5}
    md = report._render_markdown(res)
    assert "⏭" in md and "2 skipped" in md
    # skipped steps are not listed as failures
    assert md.count("- **step") == 1


def test_junit_marks_skipped_not_failed(tmp_path):
    from blackbox_mcp import cli

    res = {"name": "s", "meta": {"duration_ms": 10},
           "summary": {"total": 3, "passed": 1, "failed": 1, "skipped": 1,
                       "pass_rate": 0.5},
           "steps": [
               {"step": 1, "action": "navigate", "passed": True, "duration_ms": 5},
               {"step": 2, "action": "assert", "passed": False, "duration_ms": 5,
                "actual": "boom", "severity": "assertion", "tag": "JIRA-42"},
               {"step": 3, "action": "assert", "passed": False, "skipped": True,
                "duration_ms": 0, "actual": "not run (step 2 failed)"}]}
    path = tmp_path / "junit.xml"
    cli._write_junit([res], str(path))
    xml = path.read_text(encoding="utf-8")
    assert 'skipped="1"' in xml and "<skipped" in xml
    assert xml.count("<failure") == 1          # the skipped step is NOT a failure
    assert "[JIRA-42]" in xml                  # tag reaches CI dashboards


# ── P2: report identity — what/where was tested ────────────────────
async def test_meta_identity_fields(session, report_dir):
    url = fixture_url("basic.html")
    res = await runner.run(
        [{"action": "navigate", "url": url},
         {"action": "assert", "kind": "text_visible", "target": "로그인"}],
        name="meta_check")
    meta = res["meta"]
    assert meta["target_url"] == url
    assert re.fullmatch(r"\d+x\d+", meta["viewport"] or "")
    assert meta["browser_version"]             # actual engine build
    assert res["steps"][1]["page_url"].endswith("basic.html")


# ── P3: trend across same-name runs ───────────────────────────────
async def test_trend_accumulates_and_counts_streak(session, report_dir):
    steps_fail = [{"action": "navigate", "url": fixture_url("basic.html")},
                  {"action": "assert", "kind": "text_visible", "target": "없는텍스트"}]
    await runner.run(steps_fail, name="trendy")
    res2 = await runner.run(steps_fail, name="trendy")
    trend = res2["trend"]
    assert len(trend["recent"]) == 2
    assert trend["consecutive_failures"] == 2
    md = report._render_markdown(res2)
    assert "최근 2회" in md and "연속 실패 2회" in md

    steps_pass = [{"action": "navigate", "url": fixture_url("basic.html")},
                  {"action": "assert", "kind": "text_visible", "target": "로그인"}]
    res3 = await runner.run(steps_pass, name="trendy")
    assert res3["trend"]["consecutive_failures"] == 0
    assert len(res3["trend"]["recent"]) == 3


# ── P4: tag / priority passthrough ─────────────────────────────────
async def test_tag_and_priority_passthrough(session, report_dir):
    res = await runner.run(
        [{"action": "navigate", "url": fixture_url("basic.html"),
          "tag": "REQ-7", "priority": "high"},
         {"action": "assert", "kind": "text_visible", "target": "없는텍스트",
          "tag": "REQ-8", "priority": "blocker"}],
        name="tagged")
    assert res["steps"][0]["tag"] == "REQ-7"
    assert res["steps"][1]["priority"] == "blocker"
    md = report._render_markdown(res)
    assert "REQ-8" in md and "[blocker]" in md


# ── P5: flaky retry ────────────────────────────────────────────────
async def test_retry_marks_flaky_pass(session, report_dir):
    # The text appears well after the first assert attempt so attempt-0 fails
    # and a retry succeeds. A generous delay (800ms) + large retry budget
    # (12 × 250ms backoff ≈ 3s window) keeps attempt-0 reliably BEFORE the
    # reveal even under heavy CI/parallel load, while the window comfortably
    # covers the reveal — deterministic, not a wall-clock race.
    await session.page.set_content(
        "<div id='d'></div><script>setTimeout(() => {"
        "document.getElementById('d').textContent = '늦은텍스트';}, 800)"
        "</script>")
    res = await runner.run(
        [{"action": "assert", "kind": "text_visible", "target": "늦은텍스트",
          "retry": 12}],
        name="flaky")
    st = res["steps"][0]
    assert st["passed"] is True
    assert st["retries"] >= 1
    assert "flaky" in st["ai_reason"]
    assert res["summary"]["failed"] == 0


async def test_retry_exhausted_still_fails(session, report_dir):
    res = await runner.run(
        [{"action": "assert", "kind": "text_visible", "target": "영원히없는텍스트",
          "retry": 2}],
        name="retry_fail")
    st = res["steps"][0]
    assert st["passed"] is False and st["retries"] == 2
