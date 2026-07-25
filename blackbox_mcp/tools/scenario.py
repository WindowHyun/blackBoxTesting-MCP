"""SM-01: run_scenario — execute a JSON scenario and report results."""
from __future__ import annotations

from mcp.server.fastmcp import Context

from ..testing import report, runner
from ._registry import tool


def _progress_sink(ctx: Context | None):
    """Adapt the MCP Context to the runner's plain progress callback.

    A scenario is ONE tool call that can run for minutes (each step may burn
    NAV_TIMEOUT_MS), and a silent long call is exactly what clients time out on
    — the client gave up while the server kept driving the browser. Reporting
    per-step progress keeps the caller informed and refreshes its activity
    signal.

    The adapter lives here, not in the runner, so `testing/runner` stays free of
    the MCP SDK: the CLI imports it and tests/test_registry.py asserts that path
    never loads `mcp`.
    """
    if ctx is None:
        return None

    async def sink(done: int, total: int, message: str) -> None:
        await ctx.report_progress(progress=done, total=total, message=message)

    return sink


@tool(description="Run a JSON scenario (array of steps) and report per-step results. "
                  "continue_on_fail controls whether execution stops at the first "
                  "failure; save_report writes JSON/MD/HTML under REPORT_DIR "
                  "(report_format ∈ json|md|html|both|all). trace_on_failure "
                  "records a Playwright trace and keeps the .zip only when the "
                  "run fails (open with `playwright show-trace`). max_duration_s "
                  "bounds the whole call — steps past the budget are reported as "
                  "skipped instead of running on past the client's timeout.")
async def run_scenario(
    steps: list[dict],
    name: str = "scenario",
    description: str = "",
    continue_on_fail: bool = False,
    save_report: bool = True,
    report_format: str = "both",
    screenshot_each: bool = False,
    trace_on_failure: bool = False,
    max_duration_s: float | None = None,
    ctx: Context | None = None,
) -> dict:
    result = await runner.run(
        steps, name=name, description=description,
        continue_on_fail=continue_on_fail, screenshot_each=screenshot_each,
        trace_on_failure=trace_on_failure,
        on_progress=_progress_sink(ctx),
        max_duration_s=max_duration_s,
    )
    if save_report:
        result["report_files"] = report.save(result, formats=report_format)
    return result
