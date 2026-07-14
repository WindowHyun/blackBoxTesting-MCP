"""save_report — emit a report from the actions recorded so far.

Lets any flow (ad-hoc /ui-test, /ui-login, etc.) end with the same JSON/MD/HTML
report that run_scenario produces. Clears the recorder afterward so the next
flow starts fresh.
"""
from __future__ import annotations

from ..browser import get_session
from ..testing import recorder, report, runner
from ._registry import tool


@tool(description="지금까지 수행한 도구 동작들을 모아 JSON/MD/HTML 리포트로 저장한다. "
                  "모든 테스트 작업의 마지막에 호출해 결과를 남긴다. report_format ∈ "
                  "json|md|html|both|all. 저장 후 기록은 초기화된다.")
async def save_report(name: str = "session", description: str = "",
                      report_format: str = "all") -> dict:
    result = recorder.build_result(name=name, description=description)
    if result["summary"]["total"] == 0:
        return {"ok": False, "message": "기록된 동작이 없습니다. 먼저 도구로 작업을 수행하세요."}

    try:
        session = await get_session()
        result["meta"] = runner._meta(session)
        result["a11y_findings"] = await runner._a11y_audit(session)
    except Exception:
        result["meta"] = {}
        result["a11y_findings"] = []
    # Ad-hoc flows: derive the tested target from the first recorded navigate
    # (raw is already masked — ${VAR} placeholders, never resolved secrets).
    result["meta"]["target_url"] = next(
        (s.get("raw", {}).get("url") for s in result["steps"]
         if s.get("action") == "navigate" and s.get("raw", {}).get("url")),
        None)

    try:
        report.compute_regression(result)
        files = report.save(result, formats=report_format)
    except Exception as exc:
        # Disk-full / permission errors must surface as a tool result, and the
        # recorder must NOT be reset — the steps are still there to retry.
        return {"ok": False, "error": f"report save failed: {type(exc).__name__}: {exc}"}

    recorder.reset()  # only after a successful save
    return {"ok": True, "report_files": files, "summary": result["summary"]}
