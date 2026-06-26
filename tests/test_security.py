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
