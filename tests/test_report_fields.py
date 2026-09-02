"""Report enrichment: skipped steps, meta identity, trend, tags, flaky retry."""
from __future__ import annotations

import dataclasses
import pathlib
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
    await session.page.set_content(
        "<div id='d'></div><script>setTimeout(() => {"
        "document.getElementById('d').textContent = '늦은텍스트';}, 100)"
        "</script>")
    res = await runner.run(
        [{"action": "assert", "kind": "text_visible", "target": "늦은텍스트",
          "retry": 3}],
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


# ── P2-10: regression baselines were outside retention ───────────────
def test_prune_drops_history_of_pruned_runs(tmp_path, monkeypatch):
    """history/{name}.json is keyed by scenario NAME, not run id, so it was
    never pruned: one file per distinct name accumulated forever."""
    cfg = dataclasses.replace(report.CONFIG, report_dir=tmp_path,
                              report_retention=2)
    monkeypatch.setattr(report, "CONFIG", cfg)
    hist = tmp_path / "history"
    hist.mkdir(parents=True)
    (tmp_path / "screenshots").mkdir(exist_ok=True)

    ids = ["20260101_000000_000000", "20260102_000000_000000",
           "20260103_000000_000000", "20260104_000000_000000"]
    for rid in ids:
        (tmp_path / f"report_{rid}.json").write_text("{}", encoding="utf-8")

    stale = hist / "old_scenario.json"
    stale.write_text("{}", encoding="utf-8")
    import os
    old = report._run_id_time("20260101_000000_000000")
    os.utime(stale, (old, old))

    fresh = hist / "current_scenario.json"
    fresh.write_text("{}", encoding="utf-8")   # mtime = now

    report._prune(tmp_path)

    kept = sorted(p.name for p in tmp_path.glob("report_*.json"))
    assert kept == [f"report_{ids[2]}.json", f"report_{ids[3]}.json"]
    assert not stale.exists(), "baseline of a pruned run should go with it"
    assert fresh.exists(), "a baseline newer than the oldest kept run stays"


def test_prune_keeps_history_when_retention_disabled(tmp_path, monkeypatch):
    cfg = dataclasses.replace(report.CONFIG, report_dir=tmp_path,
                              report_retention=0)
    monkeypatch.setattr(report, "CONFIG", cfg)
    hist = tmp_path / "history"
    hist.mkdir(parents=True)
    keep = hist / "x.json"
    keep.write_text("{}", encoding="utf-8")
    report._prune(tmp_path)
    assert keep.exists()


# ── HTML report redesign (instrument-panel port) ──────────────────────
def test_html_report_has_no_external_dependencies():
    """DESIGN §6.2: the HTML report must run with zero external dependencies/
    network — this tool targets closed corporate networks. No <link> fetching
    a stylesheet/font, no <script src>, everything inline."""
    result = {
        "name": "x", "summary": {"total": 0, "passed": 0, "failed": 0,
                                 "skipped": 0, "pass_rate": 0.0},
        "meta": {}, "steps": [],
    }
    html_out = report._render_html(result, pathlib.Path("/tmp"))
    assert "<link" not in html_out
    assert "<script" not in html_out
    assert "fonts.googleapis" not in html_out
    assert "http://" not in html_out and "https://" not in html_out


def test_html_report_renders_with_minimal_result():
    """Every field the renderer reads is optional except summary/steps — a
    bare result (no trend/regression/a11y/run_id/most meta keys) must not
    KeyError."""
    result = {
        "name": "bare", "summary": {"total": 1, "passed": 1, "failed": 0,
                                    "skipped": 0, "pass_rate": 1.0},
        "meta": {}, "steps": [{"step": 1, "action": "navigate",
                               "passed": True, "duration_ms": 5}],
    }
    html_out = report._render_html(result, pathlib.Path("/tmp"))
    assert "bare" in html_out
    assert "100%" in html_out


def test_skipped_step_shows_dash_not_python_none():
    """A skipped step's expected/actual are None (runner._append_skipped) —
    that must render as a dash, not the literal word "None"."""
    result = {
        "name": "x", "summary": {"total": 1, "passed": 0, "failed": 0,
                                 "skipped": 1, "pass_rate": 0.0},
        "meta": {}, "steps": [{"step": 1, "action": "assert", "passed": False,
                               "skipped": True, "expected": None,
                               "actual": "not run (step 0 failed)",
                               "duration_ms": 0}],
    }
    html_out = report._render_html(result, pathlib.Path("/tmp"))
    assert ">None<" not in html_out
    assert "—" in html_out


def test_gauge_ring_is_red_when_any_step_failed():
    """Even a high pass rate must not read as fully green if something
    failed — the gauge color follows failed==0, not the rate value alone."""
    result = {
        "name": "x", "summary": {"total": 10, "passed": 9, "failed": 1,
                                 "skipped": 0, "pass_rate": 0.9},
        "meta": {}, "steps": [],
    }
    html_out = report._render_html(result, pathlib.Path("/tmp"))
    assert 'stroke="var(--crit)"' in html_out
    assert 'stroke="var(--good)"' not in html_out


def test_trend_bars_share_one_scale_across_runs():
    """Two runs with a different step COUNT must draw different total bar
    widths — an earlier version scaled each bar independently, which drew
    the same width regardless of how many steps that run had."""
    result = {
        "name": "x", "summary": {"total": 11, "passed": 8, "failed": 1,
                                 "skipped": 2, "pass_rate": 0.889},
        "meta": {}, "steps": [],
        "trend": {"recent": [{"ts": "2026-01-01T00:00:00", "passed": 8,
                              "failed": 0, "total": 8},
                             {"ts": "2026-01-02T00:00:00", "passed": 8,
                              "failed": 1, "total": 11}],
                 "consecutive_failures": 1},
    }
    html_out = report._render_html(result, pathlib.Path("/tmp"))
    # one <div class="trun">...</div> block per run; sum each run's own
    # segment widths to get that run's TOTAL bar width.
    runs = re.findall(r'<div class="trun[^"]*">(.*?)</div></div>', html_out)
    assert len(runs) == 2
    totals = [sum(float(w) for w in re.findall(r'style="width:([\d.]+)px', run))
             for run in runs]
    # both runs have the SAME passed count (8), so the green segment alone is
    # identical — only the run with more total steps (11 vs 8) draws wider
    # overall, because skip/fail segments are on the same shared scale.
    assert totals[1] > totals[0]


async def test_report_html_matches_live_run(session, report_dir):
    """End-to-end: a real scenario through runner.run + report.save produces
    an HTML file with no unescaped literal None and the right verdict text."""
    from conftest import fixture_url

    res = await runner.run(
        [{"action": "navigate", "url": fixture_url("basic.html")},
         {"action": "assert", "kind": "text_visible", "target": "존재하지 않는 텍스트"},
         {"action": "assert", "kind": "text_visible", "target": "Blackbox"}],
        name="port_e2e", continue_on_fail=False)
    files = report.save(res, formats="html")
    html_out = open(files["html"], encoding="utf-8").read()
    assert ">None<" not in html_out
    assert "FAIL" in html_out and "SKIP" in html_out
    assert "<script" not in html_out
