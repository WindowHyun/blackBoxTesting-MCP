"""Environment-dependent paths: CDP attach, stale-CDP fallback, persistent
profile launch/reuse, bootstrap install-failure, lifecycle concurrency."""
from __future__ import annotations

import asyncio
import dataclasses
import subprocess
import threading
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


def test_install_failure_reports_the_installer_reason(monkeypatch, caplog):
    """A failed auto-install must leave a diagnosable reason.

    stderr used to go to DEVNULL alongside stdout, so a blocked CDN / full disk
    / proxy rejection produced no explanation anywhere — the user only saw every
    later tool call die on a missing browser.
    """
    from blackbox_mcp import bootstrap

    def boom(cmd, *a, **k):
        raise subprocess.CalledProcessError(1, cmd,
                                            stderr=b"Download failed: 403 from cdn")

    monkeypatch.setattr(bootstrap.subprocess, "run", boom)
    monkeypatch.setattr(bootstrap, "_browser_installed", lambda name: False)
    monkeypatch.setattr(bootstrap, "CONFIG",
                        dataclasses.replace(bootstrap.CONFIG, chromium_executable=""))
    with caplog.at_level("WARNING"):
        bootstrap.ensure_chromium()
    assert "403 from cdn" in caplog.text


async def test_background_bootstrap_does_not_block_startup(monkeypatch):
    """The first-run browser download must not sit in front of mcp.run().

    An MCP client answers `initialize` or declares the server dead (~60s in
    Claude Desktop); a ~150MB download exceeds that on an ordinary connection,
    which broke the RECOMMENDED install path (uvx, no clone) on its very first
    launch. start_background_bootstrap() returns immediately and the first
    browser launch is what waits, via await_bootstrap().
    """
    from blackbox_mcp import bootstrap

    started = threading.Event()

    def slow_install() -> None:
        started.set()
        time.sleep(0.6)

    monkeypatch.setattr(bootstrap, "ensure_chromium", slow_install)
    monkeypatch.setattr(bootstrap, "_BOOTSTRAP_STARTED", False)
    monkeypatch.setattr(bootstrap, "_BOOTSTRAP_DONE", threading.Event())

    t0 = time.monotonic()
    bootstrap.start_background_bootstrap()
    kickoff = time.monotonic() - t0
    assert kickoff < 0.2, f"startup blocked for {kickoff:.2f}s"
    assert started.wait(2), "bootstrap thread never ran"

    # ...but a consumer can still wait for it, off the event loop.
    await bootstrap.await_bootstrap()
    assert bootstrap._BOOTSTRAP_DONE.is_set()


async def test_await_bootstrap_is_a_noop_without_a_background_run(monkeypatch):
    """The CLI runs ensure_chromium() synchronously before its loop exists;
    awaiting a bootstrap that was never started must return, not hang."""
    from blackbox_mcp import bootstrap

    monkeypatch.setattr(bootstrap, "_BOOTSTRAP_STARTED", False)
    await asyncio.wait_for(bootstrap.await_bootstrap(), timeout=2)


async def test_concurrent_lifecycle_ops_serialize(session):
    # Locks make concurrent resets safe: no exception, session stays usable.
    await asyncio.gather(session.reset(), session.reset(), session.reset())
    assert session.is_alive()
