"""Tool package.

``register_all(mcp)`` imports every tool module (whose ``@tool`` decorators
register them with the shared registry) and binds them onto the FastMCP
instance. To add a tool: create a module here and add one name to
``_TOOL_MODULES`` — server.py never changes (NFR Maintainability).

Imports are deliberately LAZY (inside register_all, not at package import):
the CLI path (`cli.py → testing.runner → tools.<action modules>`) must not
drag in the MCP SDK — screenshot.py/generate.py import `mcp.*`, and pulling
the whole SDK into "runs without any MCP client" would be a layering leak.
"""
from __future__ import annotations

_TOOL_MODULES = (
    "navigate",
    "snapshot",
    "screenshot",
    "interact",
    "assertion",
    "console",
    "network",
    "wait",
    "frame",
    "dialog",
    "session",
    "realbrowser",
    "overlays",
    "state",
    "mock",
    "scenario",
    "savereport",
    "generate",
    "library",
    "status",
)


def _import_all() -> None:
    from importlib import import_module

    for mod in _TOOL_MODULES:
        import_module(f".{mod}", __name__)
    import_module("._prompts", __name__)  # MCP prompts / slash commands


def register_all(mcp) -> int:
    """Import every tool module, then bind tools+prompts onto FastMCP."""
    _import_all()
    from ._registry import register_all as _register_all

    return _register_all(mcp)


__all__ = ["register_all"]
