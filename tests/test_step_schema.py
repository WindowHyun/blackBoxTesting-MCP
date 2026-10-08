"""Step-record schema parity and the per-step evidence cap.

Regression guards for two review findings:
  - the recorder emitted a step record missing skipped/tag/priority/retries,
    which only went unnoticed because every renderer read is a .get();
  - one step on a chatty page could carry hundreds of console/network entries
    into both the JSON report and run_scenario's MCP response.
"""
from __future__ import annotations

import pytest

from blackbox_mcp.testing import report


# ── step schema parity ───────────────────────────────────────────
def test_step_record_fills_every_schema_key():
    rec = report.step_record(step=1, action="navigate")
    assert set(rec) == set(report._STEP_DEFAULTS)
    assert rec["step"] == 1 and rec["action"] == "navigate"
    # defaults, not omissions
    assert rec["skipped"] is False and rec["retries"] == 0
    assert rec["tag"] is None and rec["priority"] is None


def test_step_record_rejects_a_key_outside_the_schema():
    """A typo'd field would otherwise land in the report as a dead key while
    the real one silently kept its default."""
    with pytest.raises(KeyError) as excinfo:
        report.step_record(step=1, sevrity="error")
    assert "sevrity" in str(excinfo.value)


def test_step_record_does_not_share_mutable_defaults():
    a, b = report.step_record(), report.step_record()
    a["console_errors"].append({"text": "x"})
    assert b["console_errors"] == []


def test_both_producers_emit_the_same_shape():
    """The runner and the recorder are one schema (DESIGN §6.1) — the point of
    routing both through step_record."""
    import inspect

    from blackbox_mcp.testing import recorder, runner

    for src in (inspect.getsource(runner.run),
                inspect.getsource(runner._append_skipped),
                inspect.getsource(recorder.run_and_record)):
        assert "report.step_record(" in src


# ── per-step evidence cap ────────────────────────────────────────
def test_cap_evidence_trims_and_reports_what_it_dropped():
    rec = report.step_record(
        console_errors=[{"text": f"e{i}"} for i in range(120)],
        network_errors=[{"url": f"u{i}"} for i in range(60)],
        dialogs=[{"type": "alert"}],
    )
    report.cap_evidence(rec)

    cap = report._MAX_STEP_EVIDENCE
    assert len(rec["console_errors"]) == cap
    assert len(rec["network_errors"]) == cap
    assert rec["dialogs"] == [{"type": "alert"}]          # under the cap, untouched
    assert rec["evidence_dropped"] == {"console_errors": 120 - cap,
                                       "network_errors": 60 - cap}
    # the FIRST entries survive: within a step the earliest error is the cause
    assert rec["console_errors"][0] == {"text": "e0"}


def test_cap_evidence_is_a_noop_under_the_cap():
    rec = report.step_record(console_errors=[{"text": "only"}])
    report.cap_evidence(rec)
    assert rec["evidence_dropped"] is None
    assert rec["console_errors"] == [{"text": "only"}]


def test_truncation_is_visible_in_both_renderers(tmp_path):
    result = {
        "name": "chatty", "meta": {},
        "summary": {"total": 1, "passed": 0, "failed": 1, "skipped": 0,
                    "pass_rate": 0.0},
        "steps": [report.cap_evidence(report.step_record(
            step=1, action="interact", passed=False, severity="error",
            console_errors=[{"text": f"e{i}"} for i in range(70)]))],
    }
    md = report._render_markdown(result)
    html_out = report._render_html(result, tmp_path)
    # a partial report must never read as a complete one
    assert "생략" in md and f"+{70 - report._MAX_STEP_EVIDENCE}" in md
    assert "생략" in html_out
