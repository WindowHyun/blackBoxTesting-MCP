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


# ── masking heuristic gaps (2026-07) ─────────────────────────────

def test_numbered_credential_field_is_masked():
    """`testid=pw2` tokenized to {"testid","pw2"}, matched nothing, and the
    typed password went into the report in plaintext."""
    from blackbox_mcp.testing.secrets import mask_step

    for selector in ("testid=pw2", "testid=pwd1", "css=#otp3"):
        masked = mask_step({"action": "interact", "type": "type",
                            "selector": selector, "value": "hunter2"})
        assert masked["value"] == "***", selector


def test_creds_style_names_are_recognised():
    """"credential" matched but "creds" did not, so ${ADMIN_CREDS} resolved to a
    real password that was never scrubbed from derived URLs/error text."""
    from blackbox_mcp.testing.secrets import is_sensitive_name

    for name in ("ADMIN_CREDS", "user_cred", "MY_PASSPHRASE", "JWT", "totp_code",
                 "ACCESS_KEY", "private_key"):
        assert is_sensitive_name(name), name


def test_secret_vars_env_forces_masking(monkeypatch):
    """A keyword list can never be complete and fails silently — SECRET_VARS is
    the deterministic override."""
    from blackbox_mcp.testing import secrets

    assert not secrets.is_sensitive_name("MAGIC_WORD")
    monkeypatch.setenv("SECRET_VARS", "magic_word, other")
    assert secrets.is_sensitive_name("MAGIC_WORD")

    monkeypatch.setenv("MAGIC_WORD", "s3cr3t-value")
    secrets.clear_registry()
    assert secrets.resolve("${MAGIC_WORD}") == "s3cr3t-value"
    # ...and the resolved value is now scrubbed out of derived text
    assert secrets.scrub("https://x/cb?t=s3cr3t-value") == "https://x/cb?t=${MAGIC_WORD}"
    secrets.clear_registry()


def test_value_masked_when_any_target_field_names_a_credential():
    """Only `selector` was consulted; a step authored with `field`/`label`
    leaked the typed value."""
    from blackbox_mcp.testing.secrets import mask_step

    for key in ("selector", "target", "name", "field", "label"):
        masked = mask_step({"action": "interact", "type": "type",
                            key: "비밀번호", "value": "hunter2"})
        assert masked["value"] == "***", key
