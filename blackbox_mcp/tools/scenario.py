"""SM-01: run_scenario — execute a JSON scenario and report results."""
from __future__ import annotations

from ..testing import report, runner
from ._registry import tool


@tool(description="Run a JSON scenario (array of steps) and report per-step results. "
                  "continue_on_fail controls whether execution stops at the first "
                  "failure; save_report writes JSON/MD/HTML under REPORT_DIR "
                  "(report_format ∈ json|md|html|both|all, or a combination like "
                  "'json,html'; an unknown value is rejected before the run). "
                  "trace_on_failure "
                  "records a Playwright trace and keeps the .zip only when the "
                  "run fails (open with `playwright show-trace`). "
                  "fail_on_js_error fails a step whose assertion held but whose "
                  "page threw an uncaught JS exception (default off — the error "
                  "is always recorded either way).")
async def run_scenario(
    steps: list[dict],
    name: str = "scenario",
    description: str = "",
    continue_on_fail: bool = False,
    save_report: bool = True,
    report_format: str = "both",
    screenshot_each: bool = False,
    trace_on_failure: bool = False,
    fail_on_js_error: bool = False,
) -> dict:
    # Reject a bad report_format before spending a browser run on it (the run
    # is the expensive part, and its result would otherwise be discarded by the
    # save error). resolve_formats is the same check save() applies.
    if save_report:
        try:
            report.resolve_formats(report_format)
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "steps": []}

    result = await runner.run(
        steps, name=name, description=description,
        continue_on_fail=continue_on_fail, screenshot_each=screenshot_each,
        trace_on_failure=trace_on_failure, fail_on_js_error=fail_on_js_error,
    )
    if save_report:
        try:
            result["report_files"] = report.save(result, formats=report_format)
        except Exception as exc:
            # Disk full / permissions: the run itself still happened, so return
            # its result with the failure attached rather than raising it away.
            result["report_error"] = f"{type(exc).__name__}: {exc}"
    return result
