"""Scenario execution engine (SM-01, SM-02).

Runs an ordered list of JSON steps, dispatching each to the same primitives the
core tools use, recording a per-step result, auto-capturing a screenshot on
failure, and honoring continue_on_fail.

Phase 0: signature + result shape are defined; step dispatch is implemented in
Phase 3 once interact/assert_ land in Phase 2.
"""
from __future__ import annotations

from typing import Any


def empty_result(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "steps": [],
        "summary": {"total": 0, "passed": 0, "failed": 0},
    }


async def run(
    steps: list[dict],
    *,
    name: str = "scenario",
    continue_on_fail: bool = False,
) -> dict[str, Any]:
    """Execute steps and return a structured result.

    TODO(Phase 3): dispatch each step to navigate/interact/assert_/wait/...,
    capture failure screenshots (SM-02), and aggregate the summary.
    """
    raise NotImplementedError("run_scenario lands in Phase 3.")
