"""Scenario execution engine (SM-01, SM-02, SM-05~08, SM-10).

Runs an ordered list of JSON steps, dispatching each to the same primitives the
core tools use, and produces a result that conforms to DESIGN §6.1:

  step, action, raw, selector_input, resolved_by, expected, actual, passed,
  duration_ms, screenshot, console_errors, network_errors, severity,
  ai_reason, ai_suggestion

Notes
- The MCP server has no LLM, so ``ai_reason``/``ai_suggestion`` are rule-based
  (deterministic) hints here; a host LLM (Claude) can enrich them when driving
  interactively. They still give real value on failures.
- Console/network errors are attributed to the step that produced them by
  slicing the session buffers around each step (SM-06).
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from ..browser import get_session
from ..config import CONFIG
from ..tools.assertion import assert_
from ..tools.dialog import expect_dialog
from ..tools.frame import switch_frame
from ..tools.interact import interact
from ..tools.navigate import navigate
from ..tools.session import reset_session
from ..tools.snapshot import snapshot
from ..tools.wait import wait
from . import report, secrets


def empty_result(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "steps": [],
        "summary": {"total": 0, "passed": 0, "failed": 0, "pass_rate": 0.0},
    }


def _severity(action: str, exc: Exception | None) -> str | None:
    """Classify a *failed* step. (Only called when passed is False.)"""
    if exc is not None:
        return "timeout" if "Timeout" in type(exc).__name__ else "error"
    if action in ("assert", "assert_"):
        return "assertion"
    return "error"  # failed interact/wait/dialog/etc.


async def _dispatch(step: dict) -> dict:
    """Execute a single step; return partial result fields (no I/O on buffers)."""
    action = step.get("action", "")
    selector_input = step.get("selector") or step.get("target")
    out: dict[str, Any] = {
        "expected": None, "actual": None, "passed": False,
        "resolved_by": None, "ai_reason": "", "ai_suggestion": None,
    }

    if action == "navigate":
        res = await navigate(secrets.resolve(step["url"]), step.get("wait_until"))
        out.update(expected="navigation", actual=res, passed=True,
                   ai_reason=f"navigated to {res.get('url')} (status {res.get('status')})")

    elif action == "interact":
        res = await interact(step.get("type"), step["selector"], step.get("value"))
        out.update(expected=f"{step.get('type')} ok", actual=res.get("detail") or res.get("error"),
                   passed=bool(res.get("ok")), resolved_by=res.get("resolved_by"))
        out["ai_reason"] = (f"{step.get('type')} via {res.get('resolved_by')} selector"
                            if res.get("ok") else "action failed")
        if not res.get("ok"):
            out["ai_suggestion"] = "element not found or not actionable — selector may have changed"

    elif action in ("assert", "assert_"):
        res = await assert_(step["kind"], step["target"], step.get("expected"))
        out.update(expected=step.get("expected") or step["kind"], actual=res.get("actual"),
                   passed=bool(res.get("passed")))
        out["ai_reason"] = f"{step['kind']} {'held' if res.get('passed') else 'did not hold'}"
        if not res.get("passed"):
            out["ai_suggestion"] = f"expected {step['kind']} on '{step['target']}' — verify the target"

    elif action == "snapshot":
        snap = await snapshot(step.get("mode", "a11y"), step.get("focus"), step.get("depth"))
        out.update(expected="snapshot", actual=f"{len(snap)} chars", passed=True,
                   ai_reason="captured page snapshot")

    elif action == "wait":
        res = await wait(step.get("ms"), step.get("selector"))
        out.update(expected="wait", actual=res.get("waited"), passed=bool(res.get("ok")),
                   ai_reason=f"waited {res.get('waited')}")

    elif action == "switch_frame":
        res = await switch_frame(step.get("selector"))
        out.update(expected="frame switch", actual=res.get("context"),
                   passed=bool(res.get("ok")), ai_reason=f"context → {res.get('context')}")

    elif action == "reset_session":
        res = await reset_session()
        out.update(expected="reset", actual=res.get("message"), passed=bool(res.get("ok")),
                   ai_reason="session reset")

    elif action == "screenshot":
        # the actual capture happens in run() (it owns name/idx); flag it.
        out.update(expected="screenshot", actual="captured", passed=True,
                   ai_reason="explicit screenshot step", force_screenshot=True)

    elif action == "expect_dialog":
        res = await expect_dialog(step.get("dialog_action", "accept"),
                                  step.get("expected_text"), step.get("trigger"),
                                  step.get("accept_text"))
        out.update(expected=step.get("expected_text") or "dialog",
                   actual=res.get("message") or res.get("error"),
                   passed=bool(res.get("passed")),
                   ai_reason=f"dialog {res.get('dialog_type')} {res.get('handled')}")
        if not res.get("passed"):
            out["ai_suggestion"] = "expected dialog did not appear or text mismatch"

    else:
        out.update(actual=f"unknown action: {action}", passed=False,
                   ai_reason="unknown action", ai_suggestion="use a supported action verb")

    return out


async def run(
    steps: list[dict],
    *,
    name: str = "scenario",
    continue_on_fail: bool = False,
    screenshot_each: bool = False,
) -> dict[str, Any]:
    """Execute steps and return a structured result (DESIGN §6.1)."""
    session = await get_session()
    t0 = time.monotonic()
    result = empty_result(name)
    result["meta"] = _meta(session)

    for idx, step in enumerate(steps, start=1):
        c0 = len(session.buffers.console)
        n0 = len(session.buffers.network)
        s0 = time.monotonic()
        exc: Exception | None = None
        try:
            fields = await _dispatch(step)
        except Exception as e:  # a step blew up unexpectedly
            exc = e
            fields = {"expected": None, "actual": f"{type(e).__name__}: {e}",
                      "passed": False, "resolved_by": None,
                      "ai_reason": "step raised", "ai_suggestion": str(e)[:160]}

        duration_ms = int((time.monotonic() - s0) * 1000)
        passed = bool(fields["passed"])
        new_console = [c.__dict__ for c in session.buffers.console[c0:]]
        new_network = [n.__dict__ for n in session.buffers.network[n0:]]

        shot = None
        if not passed or screenshot_each or fields.get("force_screenshot"):
            shot = await report.capture_step_screenshot(session, name, idx)

        result["steps"].append({
            "step": idx,
            "action": step.get("action"),
            "raw": secrets.mask_step(step),
            "selector_input": step.get("selector") or step.get("target"),
            "resolved_by": fields.get("resolved_by"),
            "expected": fields.get("expected"),
            "actual": fields.get("actual"),
            "passed": passed,
            "duration_ms": duration_ms,
            "screenshot": shot,
            "console_errors": [e for e in new_console if e.get("level") == "error"],
            "network_errors": new_network,
            "severity": _severity(step.get("action", ""), exc) if not passed else None,
            "ai_reason": fields.get("ai_reason", ""),
            "ai_suggestion": fields.get("ai_suggestion"),
        })

        if not passed and not continue_on_fail:
            break

    total = len(result["steps"])
    passed_n = sum(1 for s in result["steps"] if s["passed"])
    result["summary"] = {
        "total": total, "passed": passed_n, "failed": total - passed_n,
        "pass_rate": round(passed_n / total, 3) if total else 0.0,
    }
    result["meta"]["duration_ms"] = int((time.monotonic() - t0) * 1000)
    return result


def _meta(session) -> dict[str, Any]:
    import platform
    import sys
    from importlib.metadata import PackageNotFoundError, version

    try:
        pw = version("playwright")
    except PackageNotFoundError:  # pragma: no cover
        pw = "?"
    return {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "os": platform.system(),
        "python": platform.python_version(),
        "playwright": pw,
        "browser": CONFIG.browser,
        "headless": CONFIG.headless,
        "executable": CONFIG.chromium_executable or "bundled",
        "credentials_masked": True,
    }
