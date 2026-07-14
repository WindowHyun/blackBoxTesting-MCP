"""SL-02 / SL-03 / SL-04: scenario library tools."""
from __future__ import annotations

import json

from ..testing import library
from ._registry import tool


@tool(description="Save a JSON step array under a name to scenarios/{name}.json. "
                  "Set overwrite=True to replace an existing scenario.")
async def save_scenario(name: str, steps: list[dict], overwrite: bool = False) -> dict:
    try:
        path = library.save(name, steps, overwrite=overwrite)
    except FileExistsError as e:
        return {"ok": False, "error": str(e), "exists": True}
    return {"ok": True, "path": path, "steps": len(steps)}


@tool(description="Load a saved scenario by name; returns its step array for run_scenario.")
async def load_scenario(name: str) -> dict:
    try:
        steps = library.load(name)
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e)}
    except (json.JSONDecodeError, ValueError) as e:
        # A hand-edited or half-written scenario file must surface as a tool
        # result, not crash the MCP call.
        return {"ok": False, "error": f"scenario '{name}' is corrupted: {e}"}
    return {"ok": True, "name": name, "steps": steps}


@tool(description="List saved scenarios with step counts and last-saved timestamps.")
async def list_scenarios() -> list[dict]:
    return library.listing()
