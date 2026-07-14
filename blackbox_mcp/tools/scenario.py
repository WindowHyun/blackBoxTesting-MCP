"""SM-01: run_scenario — execute a JSON scenario and report results."""
from __future__ import annotations

from typing import Literal

from ..testing import report, runner
from ._registry import tool

ReportFormat = Literal["json", "md", "html", "both", "all"]


@tool(description="Run a JSON scenario (array of steps) and report per-step results. "
                  "continue_on_fail controls whether execution stops at the first "
                  "failure; save_report writes JSON/MD/HTML under REPORT_DIR "
                  "(report_format ∈ json|md|html|both|all). trace_on_failure "
                  "records a Playwright trace and keeps the .zip only when the "
                  "run fails (open with `playwright show-trace`).")
async def run_scenario(
    steps: list[dict],
    name: str = "scenario",
    description: str = "",
    continue_on_fail: bool = False,
    save_report: bool = True,
    report_format: ReportFormat = "both",
    screenshot_each: bool = False,
    trace_on_failure: bool = False,
) -> dict:
    result = await runner.run(
        steps, name=name, description=description,
        continue_on_fail=continue_on_fail, screenshot_each=screenshot_each,
        trace_on_failure=trace_on_failure,
    )
    if save_report:
        try:
            result["report_files"] = report.save(result, formats=report_format)
        except ValueError as exc:
            # Bad report_format must not discard the run that already executed.
            result["report_files"] = {}
            result["report_error"] = str(exc)
    return result
