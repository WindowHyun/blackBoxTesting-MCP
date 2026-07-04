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


def browser_available() -> bool:
    """True when a launchable Chromium exists (pre-provisioned or installed)."""
    import os

    from blackbox_mcp.bootstrap import _browser_installed
    from blackbox_mcp.config import CONFIG

    if CONFIG.chromium_executable and os.path.exists(CONFIG.chromium_executable):
        return True
    return _browser_installed(CONFIG.browser)


def pytest_collection_modifyitems(items):
    """Auto-mark browser tests (anything using the session/cdp fixtures) and
    skip ALL browser-marked tests when no Chromium is launchable — one global
    guard instead of per-file ones, so the suite passes on browserless envs.
    Fast unit lane: pytest -m 'not browser' (no Chromium needed).

    NOTE: tests that drive a browser WITHOUT those fixtures (direct
    get_session()/BrowserSession()/cli.main) must carry an explicit
    ``pytestmark = pytest.mark.browser`` — the fixture heuristic can't see them.
    """
    browser_ok = browser_available()
    skip_no_browser = pytest.mark.skip(reason="browser unavailable")
    for item in items:
        if {"session", "cdp_chrome"} & set(getattr(item, "fixturenames", ())):
            item.add_marker(pytest.mark.browser)
        if item.get_closest_marker("browser") and not browser_ok:
            item.add_marker(skip_no_browser)


@pytest.fixture(autouse=True)
def _clean_module_globals():
    """Reset process-global state between tests so ordering can't couple them:
    the recorder log/counter and the resolved-secrets scrub registry."""
    yield
    from blackbox_mcp.testing import recorder, secrets
    recorder.reset()
    secrets.clear_registry()


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
