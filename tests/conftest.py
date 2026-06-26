"""Shared fixtures for browser-integration tests.

Tests that need a real browser use the ``session`` fixture. If no browser can be
launched (e.g. neither a bundled nor pre-provisioned binary is available), the
fixture skips so the unit suite still passes anywhere.
"""
from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_url(name: str) -> str:
    return (FIXTURES / name).as_uri()


@pytest.fixture
async def session():
    from blackbox_mcp.browser import get_session
    from blackbox_mcp.browser.session import close_session

    try:
        s = await get_session()
    except Exception as exc:  # pragma: no cover - environment without a browser
        pytest.skip(f"browser unavailable: {exc}")

    await s.reset()  # clean context + buffers per test
    try:
        yield s
    finally:
        await close_session()
