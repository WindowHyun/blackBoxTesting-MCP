"""SM-01: run_scenario — stub (Phase 3).

Executes a JSON step array, records per-step results, auto-captures a screenshot
on failure (SM-02), and optionally writes a JSON+MD report (SM-03).
"""
from __future__ import annotations

from ..testing import report, runner
from ._registry import tool


@tool(description="Run a JSON scenario (array of steps) and report per-step results. "
                  "continue_on_fail controls whether execution stops at the first "
                  "failure; save_report writes JSON+MD under REPORT_DIR.")
async def run_scenario(
    steps: list[dict],
    name: str = "scenario",
    continue_on_fail: bool = False,
    save_report: bool = True,
    report_format: str = "both",
) -> dict:
    result = await runner.run(steps, name=name, continue_on_fail=continue_on_fail)
    if save_report:
        result["report_files"] = report.save(result, formats=report_format)
    return result
