"""Action recorder — captures MCP tool calls so any flow can end with a report.

Tools that Claude invokes directly are wrapped (see tools/_registry.register_all)
to append a per-call step record here, shaped like DESIGN §6.1. ``save_report``
then renders the accumulated steps. run_scenario is unaffected: it calls the raw
tool *functions* (not the wrapped MCP entrypoints), so it never double-records.
"""
from __future__ import annotations

import time
from datetime import datetime

from . import report, secrets

# Tools whose calls become report steps. (snapshot/get_* are observational reads
# and intentionally excluded so they don't add noise to the report.)
RECORDABLE = {
    "navigate", "interact", "assert_", "screenshot", "wait",
    "switch_frame", "expect_dialog", "expect_popup", "expect_download",
    "switch_tab", "reset_session", "use_real_browser",
    "dismiss_banners", "save_state", "load_state", "mock_route", "unmock_route",
}

# Safety cap so a long-lived server can't grow the log without bound.
_MAX_STEPS = 1000

_LOG: list[dict] = []
# Monotonic step counter — unlike len(_LOG)+1 it stays unique after the cap
# trims old entries, so regression keys and screenshot names never collide.
_COUNTER = 0
# Per-recording-session run id, shared by this session's screenshots and (via
# build_result → save) its report files, so retention keeps them together.
_RUN_ID: str | None = None
# Wall clock of the FIRST recorded call in this flow. save_report used to stamp
# the report with runner._meta's started_at, i.e. the moment the report was
# saved, and with no duration at all — the header read "· 0 ms ·" on every
# ad-hoc report even though each step's duration was recorded.
_STARTED_AT: datetime | None = None


def reset() -> None:
    global _COUNTER, _RUN_ID, _STARTED_AT
    _LOG.clear()
    _COUNTER = 0
    _RUN_ID = None
    _STARTED_AT = None
    # A flow boundary is also the scrub-registry boundary: values re-register
    # on the next resolve(), so this only bounds growth/cross-flow bleed.
    secrets.clear_registry()


def steps() -> list[dict]:
    return list(_LOG)


def _interpret(name: str, kwargs: dict, result, exc: Exception | None):
    """Map a tool's result → (expected, actual, passed, resolved_by, reason, suggestion)."""
    if exc is not None:
        return (name, f"{type(exc).__name__}: {exc}", False, None,
                "tool raised", str(exc)[:160])

    if name == "navigate":
        r = result or {}
        status = r.get("status")
        # None on file:// or a settle-timeout (no response) — reachable; a real
        # 4xx/5xx is a failed load, not a pass.
        ok = status is None or status < 400
        return ("도착 (2xx/3xx)", f"“{r.get('title')}” · HTTP {status}", ok, None,
                f"navigated to {r.get('url')} (status {status})",
                None if ok else f"HTTP {status} — server error or missing page")
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
    if name in ("save_state", "load_state"):
        r = result or {}
        ok = bool(r.get("ok"))
        return (name, r.get("path") or r.get("error"), ok, None,
                f"{name} {'ok' if ok else 'failed'}",
                None if ok else "state file missing or real-browser mode")
    if name in ("mock_route", "unmock_route"):
        r = result or {}
        ok = bool(r.get("ok"))
        return (name, r.get("pattern") or f"active={r.get('active')}", ok, None,
                f"{name} {'ok' if ok else 'failed'}",
                None if ok else r.get("error"))
    if name == "expect_popup":
        r = result or {}
        ok = bool(r.get("passed"))
        return (kwargs.get("expect_url") or "popup", r.get("url") or r.get("error"),
                ok, r.get("resolved_by"),
                "popup opened" if ok else "popup not opened as expected",
                None if ok else "트리거가 새 창/탭을 여는지 확인 "
                                "(팝업 차단·target=_blank 여부)")
    if name == "expect_download":
        r = result or {}
        ok = bool(r.get("passed"))
        return (kwargs.get("expect_name") or kwargs.get("expect_extension") or "download",
                (f"{r.get('filename')} ({r.get('size_bytes')}B)" if ok
                 else r.get("error")),
                ok, r.get("resolved_by"),
                "download verified" if ok else "download not verified",
                None if ok else "트리거가 실제로 파일을 내려받는지, 서버가 에러 "
                                "페이지를 대신 반환하지 않는지 확인")
    if name == "switch_tab":
        r = result or {}
        ok = bool(r.get("ok"))
        return ("tab switch", r.get("url") or r.get("error"), ok, None,
                f"tab → {kwargs.get('index', 0)}",
                None if ok else "list_tabs로 열린 탭 인덱스를 확인")
    if name == "dismiss_banners":
        r = result or {}
        hit = r.get("dismissed") or []
        # Always ok=True (it is a best-effort sweep); WHAT it clicked is the
        # reportable fact — a click on an unrelated control shows up here.
        return ("banners dismissed", ", ".join(hit) or "none matched",
                bool(r.get("ok", True)), None,
                f"닫은 오버레이 {len(hit)}건", None)
    # Unmapped tool: read the verdict OUT of the result instead of assuming a
    # pass. A tool added to RECORDABLE without an _interpret branch used to be
    # recorded as passed=True unconditionally — a failing verification would
    # then land in the report as a green step (test_recorder guards against a
    # branchless RECORDABLE entry, this is the second line of defence).
    r = result if isinstance(result, dict) else {}
    passed = bool(r.get("passed", r.get("ok", True)))
    return (name, str(result)[:60], passed, None, name,
            None if passed else r.get("error"))


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
    d0 = len(session.buffers.dialogs) if session else 0

    global _STARTED_AT
    if _STARTED_AT is None:
        _STARTED_AT = datetime.now()
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
    new_dialogs = ([d.__dict__ for d in session.buffers.dialogs[d0:]] if session else [])

    global _COUNTER, _RUN_ID
    _COUNTER += 1
    idx = _COUNTER
    if _RUN_ID is None:
        _RUN_ID = report.new_run_id()
        # A new flow just began. Retention normally runs after a save, but this
        # flow may capture failure screenshots for hours and never reach
        # save_report — so apply it here too, or nothing ever bounds
        # reports/screenshots for interactive use. Best-effort, once per flow.
        report.prune_now()
    shot = None
    if session and not passed:
        shot = await report.capture_step_screenshot(session, f"{_RUN_ID}_session", idx)

    # Where the call actually ran. The runner records this and both renderers
    # print it on failures, but the recorder never set the key — and
    # scrub_record creates it as None, so the omission passed schema checks
    # while the "페이지:" line silently vanished from every ad-hoc report.
    # SPA routing is exactly what the interactive path is used to debug.
    page_url = None
    if session is not None:
        try:
            page_url = session.page.url
        except Exception:
            page_url = None

    _LOG.append(secrets.scrub_record({
        "step": idx,
        "action": name,
        "raw": secrets.mask_step(
            dict(kwargs),
            sensitive_value=bool(isinstance(result, dict) and result.get("sensitive"))),
        "selector_input": kwargs.get("selector") or kwargs.get("target"),
        "resolved_by": resolved_by,
        "expected": expected,
        "actual": actual,
        "passed": passed,
        "duration_ms": duration_ms,
        "screenshot": shot,
        "page_url": page_url,
        "console_errors": [e for e in new_console if e.get("level") == "error"],
        "network_errors": new_network,
        "dialogs": new_dialogs,
        "severity": None if passed else report.classify_failure(name, exc),
        "ai_reason": reason,
        "ai_suggestion": suggestion,
    }))

    if len(_LOG) > _MAX_STEPS:
        del _LOG[:-_MAX_STEPS]

    if exc is not None:
        raise exc
    return result


def build_result(name: str = "session", description: str = "") -> dict:
    s = steps()
    result = {"name": name, "description": description, "steps": s,
              "summary": report.summarize(s)}
    # Share the screenshots' run id with the report files so retention keeps
    # them together. None when no screenshot was captured — save() falls back.
    if _RUN_ID is not None:
        result["run_id"] = _RUN_ID
    # Timing the report header needs. duration_ms is the sum of the steps, i.e.
    # time actually spent driving the browser — NOT wall clock to now, which on
    # an interactive flow is dominated by how long the operator (or the host
    # LLM) thought between calls and would read as "the site is slow".
    meta: dict = {"duration_ms": sum(int(x.get("duration_ms") or 0) for x in s)}
    if _STARTED_AT is not None:
        meta["started_at"] = _STARTED_AT.isoformat(timespec="seconds")
    result["meta"] = meta
    return result
