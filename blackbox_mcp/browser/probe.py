"""Bounded page-level evaluation.

``page.evaluate`` takes **no timeout** — unlike every locator/action API, it
waits forever. On a page with a navigation still in flight (a server that
accepts the connection and never answers) it neither returns nor raises, so a
bare ``try/except`` around it is not a guard at all: nothing is ever thrown, the
await simply never completes and the whole run stops there. Measured against a
socket that accepts and never responds, ``_a11y_audit`` was still hanging at 25s
while ``page.screenshot`` (which does take a timeout) exited cleanly at its own.

In the MCP server that means a tool call that never returns — the client only
sees a dead server. In the CLI it means a job that sits until the CI-level
timeout, since ``--timeout`` only watches ``--parallel`` children.

Every page-level evaluate in this codebase goes through :func:`safe_evaluate`.
Locator-level evaluates are already bounded by the locator timeout.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)

# Generous for the small introspection scripts we run through here (the a11y
# audit, the element collector), short enough that a wedged page costs one step
# instead of the whole run. Read at call time so tests can shorten it.
EVAL_TIMEOUT_S = 10.0


async def safe_evaluate(page, script: str, arg: Any = None, *,
                        timeout_s: float | None = None, default: Any = None) -> Any:
    """``page.evaluate(script)`` with a deadline; ``default`` on timeout/failure.

    The timeout is the point of this function — the ``except Exception`` is the
    same best-effort behaviour the call sites already had.
    """
    limit = EVAL_TIMEOUT_S if timeout_s is None else timeout_s
    try:
        coro = page.evaluate(script) if arg is None else page.evaluate(script, arg)
        return await asyncio.wait_for(coro, limit)
    except asyncio.TimeoutError:
        log.warning("page.evaluate exceeded %ss — page not responding; skipping.", limit)
        return default
    except Exception:
        return default
