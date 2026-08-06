"""expect_download — click something and verify the file that comes back.

Downloading a report is the payoff step of most internal business flows
(엑셀/PDF 내려받기), and it is invisible to every other tool here: the click
"succeeds" whether or not a file ever arrives. Playwright surfaces it on the
``download`` event, which must be armed *around* the click.

Saved under DOWNLOAD_DIR (default ~/ui-blackbox/downloads) so the file survives
the browser context that produced it — Playwright deletes its temp copy on
context close.
"""
from __future__ import annotations

import os
import re

from ..browser import get_session
from ..browser.locator import resolve
from ..config import CONFIG
from ._registry import tool

_SAFE = re.compile(r"[^A-Za-z0-9._\-가-힣]")


def _dest(suggested: str, save_as: str | None) -> str:
    name = _SAFE.sub("_", (save_as or suggested or "download").strip()) or "download"
    CONFIG.download_dir.mkdir(parents=True, exist_ok=True)
    return str(CONFIG.download_dir / name)


@tool(description="Click a trigger and verify the file it downloads. Returns the "
                  "saved path, filename and size_bytes. expect_name (substring) and "
                  "expect_extension (e.g. '.xlsx') assert the file identity; "
                  "min_bytes catches a 0-byte/error-page download. Saved under "
                  "DOWNLOAD_DIR (~/ui-blackbox/downloads).")
async def expect_download(trigger: str, save_as: str | None = None,
                          expect_name: str | None = None,
                          expect_extension: str | None = None,
                          min_bytes: int = 1,
                          timeout_ms: int = 30000) -> dict:
    session = await get_session()
    page = session.page
    locator, resolved_by = await resolve(session.root, trigger)

    try:
        async with page.expect_download(timeout=timeout_ms) as info:
            await locator.click(timeout=CONFIG.selector_timeout_ms)
        download = await info.value
    except Exception as exc:
        return {"passed": False, "resolved_by": resolved_by, "path": None,
                "error": f"no download within {timeout_ms}ms ({type(exc).__name__})"}

    suggested = download.suggested_filename
    path = _dest(suggested, save_as)
    try:
        await download.save_as(path)
    except Exception as exc:
        # A download the browser aborted mid-flight still yields a Download
        # object; save_as is where that surfaces.
        return {"passed": False, "resolved_by": resolved_by, "path": None,
                "filename": suggested,
                "error": f"download failed to save ({type(exc).__name__}: {exc})"}

    size = os.path.getsize(path) if os.path.exists(path) else 0
    problems: list[str] = []
    if size < min_bytes:
        problems.append(f"size {size}B < min_bytes {min_bytes}")
    if expect_name and expect_name not in suggested:
        problems.append(f"filename {suggested!r} does not contain {expect_name!r}")
    if expect_extension and not suggested.lower().endswith(expect_extension.lower()):
        problems.append(f"filename {suggested!r} does not end with {expect_extension!r}")

    return {"passed": not problems, "resolved_by": resolved_by, "path": path,
            "filename": suggested, "size_bytes": size,
            "url": download.url,
            "error": "; ".join(problems) or None}
