"""SL-01: generate_scenario — stub (Phase 5).

Design (agreed): the MCP server does NOT embed an LLM. It navigates + snapshots
and returns a deterministic "authoring kit": interactive elements with their
D2-resolved stable selectors, the echoed description, the strict step JSON
schema, and a few-shot example. Claude (the host LLM) composes the steps and
calls save_scenario.

Optional future path: if the client supports MCP sampling, generate the steps
server-side via sampling/createMessage and return them ready-to-run, falling
back to the kit when sampling is unavailable (Claude Desktop does not support
sampling).
"""
from __future__ import annotations

from ._registry import tool


@tool(description="Inspect a page for a natural-language test goal and return an "
                  "authoring kit (interactive elements + resolved selectors + step "
                  "schema) for Claude to compose a scenario, then save_scenario.")
async def generate_scenario(description: str, url: str) -> dict:
    raise NotImplementedError("generate_scenario lands in Phase 5.")
