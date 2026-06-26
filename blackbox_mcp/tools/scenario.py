"""SM-01: run_scenario — execute a JSON scenario and report results."""
from __future__ import annotations

from ..testing import report, runner
from ._registry import tool


@tool(description="Run a JSON scenario (array of steps) and report per-step results. "
                  "continue_on_fail controls whether execution stops at the first "
                  "failure; save_report writes JSON/MD/HTML under REPORT_DIR "
                  "(report_format ∈ json|md|html|both|all).")
async def run_scenario(
    steps: list[dict],
    name: str = "scenario",
    description: str = "",
    continue_on_fail: bool = False,
    save_report: bool = True,
    report_format: str = "both",
    screenshot_each: bool = False,
) -> dict:
    result = await runner.run(
        steps, name=name, description=description,
        continue_on_fail=continue_on_fail, screenshot_each=screenshot_each,
    )
    if save_report:
        result["report_files"] = report.save(result, formats=report_format)
    return result
