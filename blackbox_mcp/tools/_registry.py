"""Tool registry — NFR Maintainability: "adding a tool = adding one file".

Tool modules decorate their functions with ``@tool(...)``. Importing the
``tools`` package collects every decorated function into ``_PENDING``;
``register_all(mcp)`` then binds them onto the FastMCP instance. ``server.py``
never needs to change when a tool is added — only a new module + one import
line in ``tools/__init__.py``.
"""
from __future__ import annotations

import asyncio
import functools
import inspect
import typing
from dataclasses import dataclass
from typing import Callable

# Serializes ALL tool-call bodies. The server is single-tenant (one browser,
# one global recorder, one module-level secret-scrub map), but the MCP SDK
# dispatches each request as its own task with no serialization — so two tool
# calls could interleave at await points and corrupt that shared state:
#   • recorder _LOG/_COUNTER/_RUN_ID (a step vanishing / bleeding into the next
#     flow), and
#   • secrets._RESOLVED_SECRETS (one flow's end-of-flow clear wiping an in-flight
#     flow's map → a credential printed in plaintext).
# One lock at the tool boundary makes execution match the single-browser reality
# it already assumes. Lock order is _TOOL_LOCK → _SESSION_LOCK → _op_lock
# (session methods take theirs strictly inside a tool body), and run_scenario's
# internal calls use the RAW module functions (not these wrapped entrypoints),
# so holding the lock across a scenario never re-enters it.
_TOOL_LOCK = asyncio.Lock()


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


def _copy_schema_sig(wrapper: Callable, fn: Callable, *, drop_return: bool) -> Callable:
    """Make ``wrapper`` present ``fn``'s signature to FastMCP's schema builder
    (and keep Context injection working, which is annotation-based). Optionally
    drop the return annotation — some tools return Image, which pydantic can't
    schema-ify through a *args/**kwargs wrapper.

    Annotations are RESOLVED to real types here (via get_type_hints against
    ``fn``'s own module globals). With ``from __future__ import annotations`` the
    raw annotations are strings, and the wrapper's __globals__ is this registry
    module — which doesn't have the tools' Literal aliases (WaitUntil, Action,
    …). Copying the string forms would make pydantic fail to resolve them; the
    resolved types carry no such dependency."""
    try:
        hints = typing.get_type_hints(fn)
    except Exception:  # pragma: no cover - forward-ref edge cases
        hints = dict(getattr(fn, "__annotations__", {}))

    sig = inspect.signature(fn)
    params = [p.replace(annotation=hints[n]) if n in hints else p
              for n, p in sig.parameters.items()]
    ret = hints.get("return", sig.return_annotation)
    if drop_return:
        ret = inspect.Signature.empty
    wrapper.__signature__ = sig.replace(  # type: ignore[attr-defined]
        parameters=params, return_annotation=ret)

    ann = {k: v for k, v in hints.items() if not (drop_return and k == "return")}
    wrapper.__annotations__ = ann
    return wrapper


def _serialized(fn: Callable) -> Callable:
    """Run ``fn``'s body under the global tool lock (see _TOOL_LOCK)."""
    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        async with _TOOL_LOCK:
            return await fn(*args, **kwargs)

    # fn already carries the schema signature (raw fn or recorder-wrapped);
    # keep it (including any dropped return) so FastMCP sees the same shape.
    return _copy_schema_sig(wrapper, fn, drop_return=False)


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

    return _copy_schema_sig(wrapper, fn, drop_return=True)


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
        fn = _serialized(fn)  # serialize every tool body (concurrency safety)
        mcp.tool(**kwargs)(fn)
    for pending in _PENDING_PROMPTS:
        kwargs = {}
        if pending.name:
            kwargs["name"] = pending.name
        if pending.description:
            kwargs["description"] = pending.description
        mcp.prompt(**kwargs)(pending.fn)
    return len(_PENDING)
