"""Backlog — SM-07 regression, SM-09 a11y, T1.5 dom outline."""
from __future__ import annotations

import dataclasses

import pytest
from conftest import fixture_url

from blackbox_mcp.testing import report, runner
from blackbox_mcp.tools.snapshot import snapshot
from blackbox_mcp.tools.navigate import navigate


@pytest.fixture
def report_dir(tmp_path, monkeypatch):
    cfg = dataclasses.replace(report.CONFIG, report_dir=tmp_path)
    monkeypatch.setattr(report, "CONFIG", cfg)
    return tmp_path


# ── SM-07 regression ──────────────────────────────────────────────
async def test_regression_detects_status_change(session, report_dir):
    ok = [{"action": "navigate", "url": fixture_url("basic.html"), "wait_until": "load"},
          {"action": "assert", "kind": "text_visible", "target": "로그인"}]
    bad = [{"action": "navigate", "url": fixture_url("basic.html"), "wait_until": "load"},
           {"action": "assert", "kind": "text_visible", "target": "절대없는텍스트"}]

    r1 = await runner.run(ok, name="reg")
    assert r1["regression"]["previous_run"] is None      # first run, no baseline

    r2 = await runner.run(bad, name="reg", continue_on_fail=True)
    changed = r2["regression"]["changed"]
    assert any(c["step"] == 2 and c["to"] == "failed" for c in changed)


# ── SM-09 a11y ────────────────────────────────────────────────────
# content with deliberate accessibility defects (no alt, no label, empty button)
_BAD_A11Y = "<img src='x.png'><input type='text'><button></button>"


async def test_a11y_findings_surface(session, report_dir):
    await session.page.set_content(_BAD_A11Y)
    res = await runner.run([{"action": "wait", "ms": 10}], name="a11y", continue_on_fail=True)
    findings = res["a11y_findings"]
    types = {f["type"] for f in findings}
    assert "control-missing-label" in types
    assert "img-missing-alt" in types


async def test_report_html_includes_extras(session, report_dir):
    from blackbox_mcp.tools.scenario import run_scenario
    await session.page.set_content(_BAD_A11Y)
    await run_scenario([{"action": "wait", "ms": 10}], name="ex",
                       continue_on_fail=True, report_format="all")
    htmls = list(report_dir.glob("*.html"))
    txt = htmls[0].read_text(encoding="utf-8")
    assert "접근성 발견" in txt


# ── T1.5 dom outline ──────────────────────────────────────────────
async def test_dom_mode_is_structural_outline(session):
    await navigate(fixture_url("basic.html"), wait_until="load")
    out = await snapshot(mode="dom")
    # outline carries tags + testid annotations, not just raw text
    assert "button[testid=submit]" in out
    assert "input[testid=email]" in out
