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
from ..config import CONFIG, effective_browser
from ..tools.assertion import assert_
from ..tools.dialog import expect_dialog
from ..tools.frame import switch_frame
from ..tools.interact import interact
from ..tools.navigate import navigate
from ..tools.session import reset_session
from ..tools.snapshot import snapshot
from ..tools.state import load_state, save_state
from ..tools.wait import wait
from . import report, secrets


def empty_result(name: str) -> dict[str, Any]:
    return {"name": name, "steps": [], "summary": report.summarize([])}


# Single severity implementation lives in report.classify_failure.
_severity = report.classify_failure


async def _dispatch(step: dict) -> dict:
    """Execute a single step; return partial result fields (no I/O on buffers)."""
    action = step.get("action", "")
    out: dict[str, Any] = {
        "expected": None, "actual": None, "passed": False,
        "resolved_by": None, "ai_reason": "", "ai_suggestion": None,
    }

    # Clear errors for malformed steps (common with LLM-authored scenarios) —
    # better than a bare KeyError surfaced as a generic exception.
    _required = {"navigate": ["url"], "interact": ["selector"],
                 "assert": ["kind", "target"], "assert_": ["kind", "target"]}
    missing = [k for k in _required.get(action, []) if k not in step]
    if missing:
        out.update(actual=f"missing required field(s): {', '.join(missing)}",
                   passed=False, ai_reason="malformed step",
                   ai_suggestion=f"add {missing} to the '{action}' step")
        return out

    if action == "navigate":
        res = await navigate(secrets.resolve(step["url"]), step.get("wait_until"))
        status = res.get("status")
        expect = step.get("expect_status")  # opt-in: assert an exact status
        if expect is not None:
            ok = status == expect
            reason = f"expected HTTP {expect}, got {status}"
            suggestion = None if ok else f"server returned {status}, not {expect}"
        else:
            # status is None on file:// or when the settle timed out (no response
            # object) — treat as reachable. A real 4xx/5xx is a failed load.
            ok = status is None or status < 400
            reason = f"navigated to {res.get('url')} (status {status})"
            suggestion = None if ok else (f"navigation returned HTTP {status} — server "
                                          "error or missing page (set expect_status to allow)")
        out.update(expected=(f"HTTP {expect}" if expect is not None else "도착 (2xx/3xx)"),
                   actual=f"“{res.get('title')}” · HTTP {status}",
                   passed=ok, ai_reason=reason, ai_suggestion=suggestion)
        if not res.get("settled"):
            out["ai_reason"] += " · load not settled (proceeded on timeout)"
        missing_vars = secrets.unresolved_vars(step["url"])
        if missing_vars:
            out["ai_suggestion"] = (f"env var(s) not set: {', '.join(missing_vars)} — "
                                    "the literal ${...} placeholder was used")

    elif action == "interact":
        res = await interact(step.get("type"), step["selector"], step.get("value"))
        out.update(expected=f"{step.get('type')} ok", actual=res.get("detail") or res.get("error"),
                   passed=bool(res.get("ok")), resolved_by=res.get("resolved_by"))
        out["ai_reason"] = (f"{step.get('type')} via {res.get('resolved_by')} selector"
                            if res.get("ok") else "action failed")
        if not res.get("ok"):
            out["ai_suggestion"] = "element not found or not actionable — selector may have changed"
        missing_vars = secrets.unresolved_vars(step.get("value") or "")
        if missing_vars:
            out["ai_suggestion"] = (f"env var(s) not set: {', '.join(missing_vars)} — "
                                    "the literal ${...} placeholder was typed")

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

    elif action in ("save_state", "load_state"):
        fn = save_state if action == "save_state" else load_state
        res = await fn(step.get("name", "default"))
        ok = bool(res.get("ok"))
        out.update(expected=action, actual=res.get("path") or res.get("error"),
                   passed=ok, ai_reason=f"{action} {'ok' if ok else 'failed'}")
        if not ok:
            out["ai_suggestion"] = ("save_state로 먼저 저장했는지, 실 브라우저 모드가 "
                                    "아닌지 확인 (load_state는 번들/채널 전용)")

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
    description: str = "",
    continue_on_fail: bool = False,
    screenshot_each: bool = False,
) -> dict[str, Any]:
    """Execute steps and return a structured result (DESIGN §6.1)."""
    session = await get_session()
    t0 = time.monotonic()
    result = empty_result(name)
    result["description"] = description
    result["meta"] = _meta(session)
    # One run id shared by this run's screenshots AND its report files (below,
    # via result["run_id"]) so retention keeps/deletes them together. Id leads
    # the screenshot tag so _STAMP_RE extracts it, not a digit in `name`.
    run_id = report.new_run_id()
    result["run_id"] = run_id
    run_tag = f"{run_id}_{name}"

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
            shot = await report.capture_step_screenshot(session, run_tag, idx)

        result["steps"].append(secrets.scrub_record({
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
        }))

        if not passed and not continue_on_fail:
            break

    result["summary"] = report.summarize(result["steps"])
    result["meta"]["duration_ms"] = int((time.monotonic() - t0) * 1000)
    result["a11y_findings"] = await _a11y_audit(session)   # SM-09
    report.compute_regression(result)                      # SM-07
    # Records are already scrubbed at append time, so the run's resolved secrets
    # can be dropped now — bounds growth and stops cross-scenario over-scrub (L1).
    secrets.clear_registry()
    return result


_A11Y_JS = """
() => {
  const out = [];
  document.querySelectorAll('img:not([alt])').forEach(e =>
    out.push({type: 'img-missing-alt', tag: 'img', info: (e.getAttribute('src')||'').slice(-40)}));
  document.querySelectorAll('button, a[href]').forEach(e => {
    const name = (e.getAttribute('aria-label') || e.textContent || '').trim();
    if (!name) out.push({type: 'no-accessible-name', tag: e.tagName.toLowerCase()});
  });
  document.querySelectorAll('input:not([type=hidden]), select, textarea').forEach(e => {
    const hasLabel = e.id && document.querySelector('label[for="' + e.id + '"]');
    const aria = e.getAttribute('aria-label') || e.getAttribute('placeholder');
    if (!hasLabel && !aria)
      out.push({type: 'control-missing-label', tag: e.tagName.toLowerCase(), name: e.name || null});
  });
  return out.slice(0, 50);
}
"""


async def _a11y_audit(session) -> list[dict]:
    """SM-09: cheap accessibility findings as a by-product of the page state."""
    try:
        return await session.page.evaluate(_A11Y_JS)
    except Exception:
        return []


def _meta(session) -> dict[str, Any]:
    import platform
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
        "browser": effective_browser(CONFIG.browser),  # what actually ran, not the raw env
        "headless": CONFIG.headless,
        "executable": CONFIG.chromium_executable or "bundled",
        "credentials_masked": True,
    }
