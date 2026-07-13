"""Tool registry — NFR Maintainability: "adding a tool = adding one file".

Tool modules decorate their functions with ``@tool(...)``. Importing the
``tools`` package collects every decorated function into ``_PENDING``;
``register_all(mcp)`` then binds them onto the FastMCP instance. ``server.py``
never needs to change when a tool is added — only a new module + one import
line in ``tools/__init__.py``.
"""
from __future__ import annotations

import functools
import inspect
from dataclasses import dataclass
from typing import Callable


@dataclass
class _PendingTool:
    fn: Callable
    name: str | None
    description: str | None


_PENDING: list[_PendingTool] = []
_PENDING_PROMPTS: list[_PendingTool] = []


def tool(name: str | None = None, description: str | None = None):
    """Mark a function for registration as an MCP tool."""

    def decorator(fn: Callable) -> Callable:
        _PENDING.append(_PendingTool(fn=fn, name=name, description=description))
        return fn

    return decorator


def prompt(name: str | None = None, description: str | None = None):
    """Mark a function for registration as an MCP prompt (slash command)."""

    def decorator(fn: Callable) -> Callable:
        _PENDING_PROMPTS.append(_PendingTool(fn=fn, name=name, description=description))
        return fn

    return decorator


def _with_recorder(name: str, fn: Callable) -> Callable:
    """Wrap an MCP-exposed tool so its call is recorded for the final report.

    Only wraps recordable action tools; preserves the original signature so
    FastMCP still builds the correct input schema. The module-level function
    stays unwrapped, so run_scenario's internal use is never double-recorded.
    """
    from ..testing import recorder

    if name not in recorder.RECORDABLE:
        return fn

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        return await recorder.run_and_record(name, fn, args, kwargs)

    # Preserve input params for FastMCP's schema, but drop the return annotation:
    # some tools return Image, which pydantic can't schema-ify through a wrapper.
    sig = inspect.signature(fn)
    wrapper.__signature__ = (  # type: ignore[attr-defined]
        sig.replace(return_annotation=inspect.Signature.empty))
    wrapper.__annotations__ = {k: v for k, v in getattr(fn, "__annotations__", {}).items()
                               if k != "return"}
    return wrapper


_REGISTERED = False


def register_all(mcp) -> int:
    """Register every pending tool and prompt onto the FastMCP instance.

    Idempotent: a second call is a no-op instead of double-registering every
    tool (which FastMCP rejects as duplicate names). Returns the tool count.
    """
    global _REGISTERED
    if _REGISTERED:
        return len(_PENDING)
    _REGISTERED = True
    for pending in _PENDING:
        kwargs = {}
        if pending.name:
            kwargs["name"] = pending.name
        if pending.description:
            kwargs["description"] = pending.description
        fn = _with_recorder(pending.name or pending.fn.__name__, pending.fn)
        mcp.tool(**kwargs)(fn)
    for pending in _PENDING_PROMPTS:
        kwargs = {}
        if pending.name:
            kwargs["name"] = pending.name
        if pending.description:
            kwargs["description"] = pending.description
        mcp.prompt(**kwargs)(pending.fn)
    return len(_PENDING)
