"""Tool registry — NFR Maintainability: "adding a tool = adding one file".

Tool modules decorate their functions with ``@tool(...)``. Importing the
``tools`` package collects every decorated function into ``_PENDING``;
``register_all(mcp)`` then binds them onto the FastMCP instance. ``server.py``
never needs to change when a tool is added — only a new module + one import
line in ``tools/__init__.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class _PendingTool:
    fn: Callable
    name: str | None
    description: str | None


_PENDING: list[_PendingTool] = []


def tool(name: str | None = None, description: str | None = None):
    """Mark a function for registration as an MCP tool."""

    def decorator(fn: Callable) -> Callable:
        _PENDING.append(_PendingTool(fn=fn, name=name, description=description))
        return fn

    return decorator


def register_all(mcp) -> int:
    """Register every pending tool onto the given FastMCP instance.

    Returns the number of tools registered.
    """
    for pending in _PENDING:
        kwargs = {}
        if pending.name:
            kwargs["name"] = pending.name
        if pending.description:
            kwargs["description"] = pending.description
        mcp.tool(**kwargs)(pending.fn)
    return len(_PENDING)
