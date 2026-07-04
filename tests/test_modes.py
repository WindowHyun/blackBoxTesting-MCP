"""Environment-dependent paths: CDP attach, stale-CDP fallback, persistent
profile launch/reuse, bootstrap install-failure, lifecycle concurrency."""
from __future__ import annotations

import asyncio
import dataclasses
import json
import subprocess
import time
import urllib.request

import pytest

from blackbox_mcp.browser import session as session_mod
from blackbox_mcp.browser.session import BrowserSession
from blackbox_mcp.config import CONFIG

CDP_PORT = 19777


def _chromium_bin() -> str | None:
    if CONFIG.chromium_executable:
        return CONFIG.chromium_executable
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            return p.chromium.executable_path
    except Exception:
        return None


@pytest.fixture
def cdp_chrome(tmp_path):
    """A real Chromium listening on a CDP port, launched outside Playwright."""
    exe = _chromium_bin()
    if not exe:
        pytest.skip("no chromium binary available")
    proc = subprocess.Popen(
        [exe, "--headless=new", "--no-sandbox", "--disable-gpu",
         f"--remote-debugging-port={CDP_PORT}",
         f"--user-data-dir={tmp_path / 'cdp-profile'}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{CDP_PORT}"
    for _ in range(50):  # wait for the debug endpoint
        try:
            with urllib.request.urlopen(f"{url}/json/version", timeout=1):
                break
        except Exception:
            time.sleep(0.2)
    else:
        proc.terminate()
        pytest.skip("chromium CDP endpoint did not come up")
    yield url, proc
    proc.terminate()
    proc.wait(timeout=10)


async def test_cdp_attach_and_detach_keeps_browser(cdp_chrome, monkeypatch):
    url, proc = cdp_chrome
    monkeypatch.setattr(session_mod, "CONFIG",
                        dataclasses.replace(CONFIG, cdp_url=url))
    s = BrowserSession()
    await s.start()
    try:
        assert s._cdp is True
        assert s.is_alive()
        await s.page.goto("about:blank")
    finally:
        await s.close()
    # Detach must NOT kill the user's browser.
    assert proc.poll() is None


@pytest.mark.browser
async def test_stale_cdp_falls_back_to_bundled(monkeypatch):
    monkeypatch.setattr(session_mod, "CONFIG",
                        dataclasses.replace(CONFIG, cdp_url="http://127.0.0.1:1"))
    s = BrowserSession()
    await s.start()
    try:
        assert s._cdp is False  # fell back to a normal launch
        assert s.is_alive()
    finally:
        await s.close()


@pytest.mark.browser
async def test_persistent_launch_and_idempotent_reuse():
    s = BrowserSession()
    r1 = await s.switch_to_persistent(headless=True, channel="")
    try:
        assert s._persistent is True and s.is_alive()
        assert r1["reused"] is False
        # Second call must reuse the live browser (no new window / re-login).
        r2 = await s.switch_to_persistent(headless=True, channel="")
        assert r2["reused"] is True
    finally:
        await s.close()


def test_bootstrap_survives_install_failure(monkeypatch):
    from blackbox_mcp import bootstrap

    def boom(*a, **k):
        raise OSError("network down")

    monkeypatch.setattr(bootstrap.subprocess, "run", boom)
    monkeypatch.setattr(bootstrap, "_browser_installed", lambda name: False)
    monkeypatch.setattr(bootstrap, "CONFIG",
                        dataclasses.replace(bootstrap.CONFIG, chromium_executable=""))
    bootstrap.ensure_chromium()  # must not raise


async def test_concurrent_lifecycle_ops_serialize(session):
    # Locks make concurrent resets safe: no exception, session stays usable.
    await asyncio.gather(session.reset(), session.reset(), session.reset())
    assert session.is_alive()
