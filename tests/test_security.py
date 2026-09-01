"""Security guards: HTML report escaping + credential masking."""
from __future__ import annotations

import pathlib

from blackbox_mcp.testing import report, secrets


def test_html_report_escapes_page_content():
    """Page-derived content (console/network/title/url) must not execute as HTML
    when the report is opened in a browser."""
    x = "<script>alert(1)</script>"
    result = {
        "name": x, "description": x,
        "summary": {"total": 1, "passed": 0, "failed": 1, "pass_rate": 0.0},
        "meta": {"os": x, "python": x, "playwright": x, "browser": x,
                 "headless": True, "started_at": x, "duration_ms": 1,
                 "credentials_masked": True},
        "steps": [{"step": 1, "action": x, "resolved_by": x, "expected": x,
                   "actual": x, "passed": False, "duration_ms": 1,
                   "screenshot": None, "severity": "error", "ai_reason": x,
                   "ai_suggestion": x,
                   "console_errors": [{"level": "error", "text": x}],
                   "network_errors": [{"url": x, "method": "GET", "failure": x}]}],
        "a11y_findings": [{"type": x, "tag": x, "name": x}],
        "regression": {"previous_run": x, "changed": [{"step": 1, "from": "p", "to": x}]},
    }
    html = report._render_html(result, pathlib.Path("/tmp"))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_secret_value_never_in_report():
    # ${VAR} is masked when the field/selector looks sensitive
    step = {"action": "interact", "type": "type",
            "selector": "testid=password", "value": "${PW}"}
    masked = secrets.mask_step(step)
    assert masked["value"] != "${PW}"  # masked
    # and the resolved secret never appears (placeholder is stored, not the value)
    assert "supersecret" not in str(masked)


# ── P2-08: masking must consult the element, not just the selector text ──
_PW_FORM = """
<form>
  <input id="u" name="user">
  <input id="p" type="password" name="pw2">
  <input id="tok" autocomplete="current-password">
  <input id="q" placeholder="검색">
  <button id="go">로그인</button>
</form>
"""


async def test_password_field_is_detected_by_element_not_selector(session):
    """"#p" carries no credential-looking word, so name matching missed it and
    the plaintext went into the report's raw.value."""
    from blackbox_mcp.tools.interact import interact

    await session.page.set_content(_PW_FORM)
    r = await interact("type", "#p", "hunter2")
    assert r["ok"] is True
    assert r["sensitive"] is True

    r2 = await interact("type", "#tok", "hunter2")     # autocomplete hint
    assert r2["sensitive"] is True

    r3 = await interact("type", "#q", "노트북")          # ordinary field
    assert r3["sensitive"] is False


async def test_report_masks_plaintext_password_for_opaque_selector(session, tmp_path):
    """End-to-end: the value must not survive into the saved scenario report."""
    import dataclasses
    import json

    from blackbox_mcp.testing import report, runner

    await session.page.set_content(_PW_FORM)
    res = await runner.run(
        [{"action": "interact", "type": "type", "selector": "#p",
          "value": "hunter2"},
         {"action": "interact", "type": "type", "selector": "#q",
          "value": "노트북"}],
        name="pw_masking", continue_on_fail=True)

    assert res["steps"][0]["raw"]["value"] == "***"
    assert res["steps"][1]["raw"]["value"] == "노트북"   # not over-masked

    cfg = dataclasses.replace(report.CONFIG, report_dir=tmp_path)
    report.CONFIG, old = cfg, report.CONFIG
    try:
        files = report.save(res, formats="all")
    finally:
        report.CONFIG = old
    for path in files.values():
        assert "hunter2" not in open(path, encoding="utf-8").read()
    assert "hunter2" not in json.dumps(res, ensure_ascii=False, default=str)


async def test_missing_element_does_not_stall_on_the_probe(session):
    """count() gates the probe, so a mistyped selector still fails fast
    instead of waiting out get_attribute's element timeout."""
    import time

    from blackbox_mcp.tools.interact import interact

    await session.page.set_content(_PW_FORM)
    t0 = time.monotonic()
    r = await interact("type", "#definitely-not-here", "x")
    elapsed = time.monotonic() - t0
    assert r["ok"] is False
    assert elapsed < 8       # one selector timeout, not two stacked ones
