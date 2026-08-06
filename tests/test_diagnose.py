"""Failure classification — the gate that decides whether a test may be edited.

These are the highest-stakes assertions in the project. If `app_broken` ever
reclassifies as `ui_changed`, an autonomous loop will "repair" a real defect
out of the suite and every run after that is a lie.
"""
from __future__ import annotations

import pytest

from blackbox_mcp.testing import diagnose


def _step(**over):
    base = {
        "step": 1, "action": "assert", "selector_input": "testid=cart",
        "actual": "False", "passed": False, "severity": "assertion",
        "console_errors": [], "network_errors": [], "dialogs": [], "app_log": [],
    }
    base.update(over)
    return base


# ── app_broken wins over everything ──────────────────────────────
def test_pageerror_is_app_broken():
    step = _step(console_errors=[{"level": "error", "source": "pageerror",
                                  "text": "Uncaught TypeError: x is not a function"}])
    v = diagnose.classify(step)
    assert v["cause"] == diagnose.APP_BROKEN
    assert v["test_fix_allowed"] is False


def test_server_5xx_is_app_broken():
    step = _step(network_errors=[{"url": "https://x/api", "status": 503}])
    v = diagnose.classify(step)
    assert v["cause"] == diagnose.APP_BROKEN
    assert v["test_fix_allowed"] is False


def test_app_log_stack_is_app_broken():
    step = _step(app_log=["ERROR NullPointerException at com.corp.Svc.handle(Svc.java:42)"])
    v = diagnose.classify(step)
    assert v["cause"] == diagnose.APP_BROKEN
    assert "앱 로그" in " ".join(v["evidence"])


def test_app_broken_beats_a_missing_selector():
    """The critical case. The selector genuinely did not match — but the page
    also threw. Reading that as 'UI moved' would delete a real defect."""
    step = _step(actual="TimeoutError: locator not visible",
                 console_errors=[{"source": "pageerror", "text": "Uncaught Error: boom"}])
    v = diagnose.classify(step)
    assert v["cause"] == diagnose.APP_BROKEN
    assert v["test_fix_allowed"] is False


def test_4xx_alone_is_not_app_broken():
    """404s are ordinary on real pages (favicon, trackers). Only 5xx implicates
    the server."""
    step = _step(network_errors=[{"url": "https://x/favicon.ico", "status": 404}])
    assert diagnose.classify(step)["cause"] != diagnose.APP_BROKEN


# ── environment ──────────────────────────────────────────────────
@pytest.mark.parametrize("actual", [
    "Error: net::ERR_NAME_NOT_RESOLVED at https://intranet/",
    "Error: net::ERR_TUNNEL_CONNECTION_FAILED at https://x/",
    "Error: net::ERR_CERT_AUTHORITY_INVALID at https://staging/",
])
def test_unreachable_is_environment(actual):
    v = diagnose.classify(_step(action="navigate", actual=actual, severity="error"))
    assert v["cause"] == diagnose.ENVIRONMENT
    assert v["test_fix_allowed"] is False
    assert "프록시" in v["recommendation"]


# ── scenario bug ─────────────────────────────────────────────────
@pytest.mark.parametrize("actual", [
    "missing required field(s): selector",
    "unknown action: navigat",
    "unknown kind; expected ['count', 'element_visible']",
])
def test_malformed_step_is_scenario_bug(actual):
    v = diagnose.classify(_step(actual=actual, severity="error"))
    assert v["cause"] == diagnose.SCENARIO_BUG
    assert v["test_fix_allowed"] is True


# ── ui changed — the only auto-fixable app-side class ────────────
def test_plain_assertion_miss_is_ui_changed_but_needs_a_human():
    """The classifier's blind spot, stated out loud: a badge that stopped
    updating and a badge that was renamed produce identical structural
    signals. Eligible for a fix, but never without someone looking."""
    v = diagnose.classify(_step())
    assert v["cause"] == diagnose.UI_CHANGED
    assert v["test_fix_allowed"] is True
    assert v["confidence"] == "medium"
    assert v["requires_human_review"] is True
    assert "기능 결함일 수" in v["recommendation"]


def test_a_vanished_element_is_high_confidence():
    v = diagnose.classify(_step(action="interact", severity="error",
                                actual="TimeoutError: locator not visible"))
    assert v["cause"] == diagnose.UI_CHANGED
    assert v["confidence"] == "high"
    assert v["requires_human_review"] is False


def test_selector_timeout_is_ui_changed_when_app_is_healthy():
    v = diagnose.classify(_step(action="interact", severity="error",
                                actual="TimeoutError: locator.click timed out"))
    assert v["cause"] == diagnose.UI_CHANGED
    assert v["confidence"] == "high"


def test_unclassifiable_never_allows_a_fix():
    v = diagnose.classify(_step(severity="error", actual="something odd happened"))
    assert v["cause"] == diagnose.UNKNOWN
    assert v["test_fix_allowed"] is False


# ── whole-run verdict ────────────────────────────────────────────
def test_run_verdict_leads_with_app_defects():
    result = {"name": "s", "steps": [
        _step(step=1),                                            # ui_changed
        _step(step=2, console_errors=[{"source": "pageerror", "text": "boom"}]),
        {"step": 3, "passed": True},
    ]}
    d = diagnose.diagnose_result(result)
    assert d["failed_steps"] == 2
    assert d["causes"][diagnose.APP_BROKEN] == 1
    assert "테스트를 고치지 말" in d["verdict"]


def test_run_verdict_when_only_test_side():
    result = {"name": "s", "steps": [_step(step=1), _step(step=2)]}
    d = diagnose.diagnose_result(result)
    assert "테스트 갱신 대상" in d["verdict"]


def test_skipped_steps_are_not_diagnosed():
    result = {"name": "s", "steps": [
        _step(step=1), {"step": 2, "passed": False, "skipped": True}]}
    assert diagnose.diagnose_result(result)["failed_steps"] == 1


def test_memory_enriches_but_never_unlocks_the_gate():
    """A chronic app defect stays un-fixable no matter how often it recurs."""
    step = _step(console_errors=[{"source": "pageerror", "text": "boom"}],
                 memory={"status": "recurring", "seen_before": 9,
                         "first_seen": "2026-01-01T00:00:00"})
    d = diagnose.diagnose_result({"name": "s", "steps": [step]})
    finding = d["findings"][0]
    assert finding["test_fix_allowed"] is False
    assert any("9회째" in e for e in finding["evidence"])


def test_summary_text_is_readable():
    d = diagnose.diagnose_result({"name": "checkout", "steps": [_step()]})
    text = diagnose.summarize_for_prompt(d)
    assert "checkout" in text and "ui_changed" in text
