"""Detection scorecard against the defect lab (examples/defect-lab).

The lab injects six defect classes, including three this tool is NOT expected
to catch. Asserting the misses matters as much as asserting the hits: it pins
the tool's real coverage so a future change cannot quietly claim more (or lose
what works) without this file failing.

See docs/CASE-STUDY-saucedemo.md for the write-up.
"""
from __future__ import annotations

import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from blackbox_mcp.testing import runner

LAB = Path(__file__).parent.parent / "examples" / "defect-lab"
pytestmark = pytest.mark.browser


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def lab_url():
    srv = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(_Quiet, directory=str(LAB.resolve())))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


@pytest.fixture
def lab_env(lab_url, monkeypatch):
    monkeypatch.setenv("LAB_URL", lab_url)
    monkeypatch.setenv("LAB_PASSWORD", "secret_sauce")
    return lab_url


def _steps():
    return json.loads((LAB / "scenario.json").read_text(encoding="utf-8"))["steps"]


async def _run(user: str, monkeypatch, **kw):
    monkeypatch.setenv("LAB_USER", user)
    return await runner.run(_steps(), name=f"lab-{user}",
                            continue_on_fail=True, **kw)


def _failed_tags(result):
    return {s.get("tag") for s in result["steps"] if not s["passed"]}


# ── baseline ─────────────────────────────────────────────────────
async def test_standard_user_is_clean(session, lab_env, monkeypatch):
    """The control. If this ever fails, the lab or the scenario drifted — and
    every 'we detected a defect' claim below becomes meaningless."""
    result = await _run("standard_user", monkeypatch)
    assert result["summary"]["failed"] == 0, [
        (s["step"], s["actual"]) for s in result["steps"] if not s["passed"]]
    js = [c for s in result["steps"] for c in s["console_errors"]]
    assert js == [], f"baseline should be console-clean: {js}"


# ── what the tool DOES catch ─────────────────────────────────────
async def test_problem_user_defects_are_caught(session, lab_env, monkeypatch):
    result = await _run("problem_user", monkeypatch)
    failed = _failed_tags(result)

    # D-4: add-to-cart succeeded but the badge never updated.
    assert "REQ-CART-01" in failed
    # D-2: the last-name field silently ate the input, so checkout never
    # completed. Note the failure surfaces two steps AFTER the cause.
    assert "REQ-CHECKOUT-02" in failed


async def test_uncaught_js_exception_is_recorded(session, lab_env, monkeypatch):
    """D-5. Regression guard for the pageerror listener: before it existed the
    page threw and the run reported a clean pass."""
    result = await _run("problem_user", monkeypatch)
    page_errors = [c for s in result["steps"] for c in s["console_errors"]
                   if c.get("source") == "pageerror"]
    assert page_errors, "uncaught exception was not captured"
    assert "render" in page_errors[0]["text"]


def _js_error_steps(result):
    """Steps the pageerror was attributed to.

    Looked up by content, never by index: the exception is thrown from a
    timer, so it lands on whichever step happens to be in flight when it
    fires. The step NUMBER for an async JS error is therefore approximate —
    a real property of buffer-slice attribution, not a test detail.
    """
    return [s for s in result["steps"]
            if any(c.get("source") == "pageerror" for c in s["console_errors"])]


async def test_js_error_does_not_fail_a_step_by_default(session, lab_env, monkeypatch):
    """Recorded, but not fatal — documented behaviour, opt in to change it."""
    result = await _run("problem_user", monkeypatch)
    carriers = _js_error_steps(result)
    assert carriers, "no step carried the pageerror"
    # every carrier passed on its own assertion; the error alone changed nothing
    assert all(s["passed"] for s in carriers)


async def test_fail_on_js_error_makes_it_fatal(session, lab_env, monkeypatch):
    """Opt-in gate: CI must be able to go red on a page that threw."""
    default = await _run("problem_user", monkeypatch)
    strict = await _run("problem_user", monkeypatch, fail_on_js_error=True)

    assert strict["summary"]["failed"] == default["summary"]["failed"] + 1
    carriers = _js_error_steps(strict)
    assert carriers, "no step carried the pageerror"
    failed_by_js = [s for s in carriers if s["severity"] == "js_error"]
    assert failed_by_js, [(s["step"], s["passed"], s["severity"]) for s in carriers]
    assert not failed_by_js[0]["passed"]


# ── what the tool does NOT catch (the honest half) ───────────────
async def test_wrong_images_are_missed(session, lab_env, monkeypatch):
    """D-1. Every product shows the same wrong picture. The <img> is present,
    named and loads, so no structural assertion can see it — visual regression
    is out of scope (ROADMAP P6). Pinned so the gap stays visible."""
    result = await _run("problem_user", monkeypatch)
    assert "REQ-CATALOG-01" not in _failed_tags(result)


async def test_broken_sort_is_missed(session, lab_env, monkeypatch):
    """D-3. The select succeeds and fires change; nothing reorders. There is no
    assertion kind for 'the Nth item is X', so ordering cannot be verified."""
    result = await _run("problem_user", monkeypatch)
    assert "REQ-CATALOG-02" not in _failed_tags(result)


async def test_slow_page_passes_but_is_visibly_slower(session, lab_env, monkeypatch):
    """D-6. No performance-threshold assertion exists, so a 2x slowdown passes.
    It IS measured — duration_ms is the evidence a human can act on."""
    fast = await _run("standard_user", monkeypatch)
    slow = await _run("performance_glitch_user", monkeypatch)

    assert slow["summary"]["failed"] == 0          # functionally fine
    assert slow["meta"]["duration_ms"] > fast["meta"]["duration_ms"] * 1.4


# ── report quality ───────────────────────────────────────────────
async def test_password_never_reaches_the_report(session, lab_env, monkeypatch):
    result = await _run("problem_user", monkeypatch)
    blob = json.dumps(result, ensure_ascii=False)
    assert "secret_sauce" not in blob
    pw_step = next(s for s in result["steps"] if s["selector_input"] == "#password")
    assert pw_step["raw"]["value"] == "***"


async def test_failures_carry_tag_priority_and_severity(session, lab_env, monkeypatch):
    """A report a PM can triage: what broke, how bad, which requirement."""
    result = await _run("problem_user", monkeypatch)
    for step in result["steps"]:
        if not step["passed"]:
            assert step["tag"], step
            assert step["severity"], step
            assert step["ai_suggestion"], step
