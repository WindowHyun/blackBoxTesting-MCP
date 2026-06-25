"""Action recorder — captures MCP tool calls so any flow can end with a report.

Tools that Claude invokes directly are wrapped (see tools/_registry.register_all)
to append a per-call step record here, shaped like DESIGN §6.1. ``save_report``
then renders the accumulated steps. run_scenario is unaffected: it calls the raw
tool *functions* (not the wrapped MCP entrypoints), so it never double-records.
"""
from __future__ import annotations

import time

from . import report, secrets

# Tools whose calls become report steps. (snapshot/get_* are observational reads
# and intentionally excluded so they don't add noise to the report.)
RECORDABLE = {
    "navigate", "interact", "assert_", "screenshot", "wait",
    "switch_frame", "expect_dialog", "reset_session", "use_real_browser",
}

# Safety cap so a long-lived server can't grow the log without bound.
_MAX_STEPS = 1000

_LOG: list[dict] = []


def reset() -> None:
    _LOG.clear()


def steps() -> list[dict]:
    return list(_LOG)


def _interpret(name: str, kwargs: dict, result, exc: Exception | None):
    """Map a tool's result → (expected, actual, passed, resolved_by, reason, suggestion)."""
    if exc is not None:
        return (name, f"{type(exc).__name__}: {exc}", False, None,
                "tool raised", str(exc)[:160])

    if name == "navigate":
        r = result or {}
        return ("페이지 도착", f"“{r.get('title')}” · HTTP {r.get('status')}", True,
                None, f"navigated to {r.get('url')}", None)
    if name == "interact":
        r = result or {}
        ok = bool(r.get("ok"))
        return (f"{kwargs.get('action')} ok", r.get("detail") or r.get("error"),
                ok, r.get("resolved_by"),
                f"{kwargs.get('action')} via {r.get('resolved_by')}" if ok else "action failed",
                None if ok else "element not found / not actionable")
    if name in ("assert_", "assert"):
        r = result or {}
        ok = bool(r.get("passed"))
        return (r.get("expected") or r.get("kind"), r.get("actual"), ok, None,
                f"{r.get('kind')} {'held' if ok else 'did not hold'}",
                None if ok else f"check '{r.get('target')}'")
    if name == "snapshot":
        return ("snapshot", f"{len(result or '')} chars", True, None, "page snapshot", None)
    if name == "screenshot":
        return ("screenshot", "captured", True, None, "screenshot", None)
    if name == "wait":
        r = result or {}
        return ("wait", r.get("waited"), bool(r.get("ok")), None,
                f"waited {r.get('waited')}", None)
    if name == "switch_frame":
        r = result or {}
        return ("frame switch", r.get("context"), bool(r.get("ok")), None,
                f"context → {r.get('context')}", None)
    if name == "expect_dialog":
        r = result or {}
        return (r.get("message") or "dialog", r.get("message") or r.get("error"),
                bool(r.get("passed")), None, f"dialog {r.get('dialog_type')}",
                None if r.get("passed") else "dialog mismatch/absent")
    if name == "use_real_browser":
        r = result or {}
        return ("real browser", r.get("browser"), bool(r.get("ok")), None,
                "switched to real browser", None)
    if name == "reset_session":
        return ("reset", "ok", True, None, "session reset", None)
    return (name, str(result)[:60], True, None, name, None)


async def run_and_record(name: str, fn, args: tuple, kwargs: dict):
    """Execute a tool and append a step record (then return/raise as usual)."""
    from ..browser import get_session

    session = None
    try:
        session = await get_session()
    except Exception:
        pass
    c0 = len(session.buffers.console) if session else 0
    n0 = len(session.buffers.network) if session else 0

    t0 = time.monotonic()
    exc: Exception | None = None
    result = None
    try:
        result = await fn(*args, **kwargs)
    except Exception as e:
        exc = e

    duration_ms = int((time.monotonic() - t0) * 1000)
    expected, actual, passed, resolved_by, reason, suggestion = _interpret(
        name, kwargs, result, exc)

    new_console = ([c.__dict__ for c in session.buffers.console[c0:]] if session else [])
    new_network = ([n.__dict__ for n in session.buffers.network[n0:]] if session else [])

    idx = len(_LOG) + 1
    shot = None
    if session and not passed:
        shot = await report.capture_step_screenshot(session, "session", idx)

    _LOG.append({
        "step": idx,
        "action": name,
        "raw": secrets.mask_step(dict(kwargs)),
        "selector_input": kwargs.get("selector") or kwargs.get("target"),
        "resolved_by": resolved_by,
        "expected": expected,
        "actual": actual,
        "passed": passed,
        "duration_ms": duration_ms,
        "screenshot": shot,
        "console_errors": [e for e in new_console if e.get("level") == "error"],
        "network_errors": new_network,
        "severity": (None if passed else
                     ("timeout" if exc and "Timeout" in type(exc).__name__
                      else "assertion" if name.startswith("assert") else "error")),
        "ai_reason": reason,
        "ai_suggestion": suggestion,
    })

    if len(_LOG) > _MAX_STEPS:
        del _LOG[:-_MAX_STEPS]

    if exc is not None:
        raise exc
    return result


def build_result(name: str = "session", description: str = "") -> dict:
    s = steps()
    total = len(s)
    passed = sum(1 for x in s if x["passed"])
    return {
        "name": name,
        "description": description,
        "steps": s,
        "summary": {"total": total, "passed": passed, "failed": total - passed,
                    "pass_rate": round(passed / total, 3) if total else 0.0},
    }
