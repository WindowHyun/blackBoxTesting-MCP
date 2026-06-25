"""Tool package.

Importing this package imports every tool module, whose ``@tool`` decorators
register them with the shared registry. To add a tool: create a module here and
add one import line below — server.py never changes (NFR Maintainability).
"""
from . import (  # noqa: F401  (imported for side-effect registration)
    navigate,
    snapshot,
    screenshot,
    interact,
    assertion,
    console,
    network,
    wait,
    frame,
    dialog,
    session,
    realbrowser,
    scenario,
    savereport,
    generate,
    library,
)
from . import _prompts  # noqa: F401  (registers MCP prompts / slash commands)
from ._registry import register_all

__all__ = ["register_all"]
