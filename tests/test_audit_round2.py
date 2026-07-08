"""Regression guards for the second full-codebase audit round.

Covers: launch fallback chain (stale executable / missing channel), lifecycle
lock discipline, page close-handler coverage, locator CSS-with-whitespace
handling, role parsing, scrub substring ordering, Markdown table escaping, and
HTML screenshot path containment.
"""
from __future__ import annotations

import dataclasses

import pytest

from blackbox_mcp.browser import session as session_mod
from blackbox_mcp.browser.locator import _parse_role, locate, resolve
from blackbox_mcp.browser.session import BrowserSession, _launch_attempts
from blackbox_mcp.config import CONFIG
from blackbox_mcp.testing import report, secrets


# ── launch fallback policy (unit) ─────────────────────────────────
def test_launch_attempts_skips_stale_executable(monkeypatch):
    monkeypatch.setattr(session_mod, "CONFIG", dataclasses.replace(
        CONFIG, browser_channel=None, chromium_executable="/definitely/not/here"))
    assert _launch_attempts() == [{}]  # straight to bundled


def test_launch_attempts_skips_executable_for_non_chromium(monkeypatch):
    monkeypatch.setattr(session_mod, "CONFIG", dataclasses.replace(
        CONFIG, browser="firefox", browser_channel=None))
    # a chromium binary must never be handed to firefox.launch
    assert all("executable_path" not in a for a in _launch_attempts())


def test_launch_attempts_order_channel_first(monkeypatch):
    monkeypatch.setattr(session_mod, "CONFIG", dataclasses.replace(
        CONFIG, browser_channel="chrome"))
    attempts = _launch_attempts()
    assert attempts[0] == {"channel": "chrome"}
    assert attempts[-1] == {}  # bundled is always the last resort


# ── launch fallback end-to-end: bogus channel must not brick start ──
@pytest.mark.browser
async def test_start_falls_back_past_missing_channel(monkeypatch):
    monkeypatch.setattr(session_mod, "CONFIG", dataclasses.replace(
        CONFIG, browser_channel="no-such-channel", cdp_url=None))
    s = BrowserSession()
    await s.start()
    try:
        assert s.is_alive()
    finally:
        await s.close()


# ── every active page carries a close-fallback handler ────────────
async def test_original_tab_close_falls_back_not_restart(session):
    """A(initial) → open B, C (adopted) → close C (falls back to A) → close A:
    the session must fall back to B instead of stranding on a dead page."""
    a = session.page
    b = await session._context.new_page()
    await a.wait_for_timeout(200)
    c = await session._context.new_page()
    await a.wait_for_timeout(200)
    assert session.page is c

    await c.close()
    await a.wait_for_timeout(200)
    assert session.page is a  # oldest remaining = original tab

    await a.close()
    await b.wait_for_timeout(200)
    assert session.page is b  # initial page had a close handler too
    assert session.is_alive()


# ── locator: CSS signal with whitespace ───────────────────────────
class _FakeLocator:
    def __init__(self, n: int):
        self._n = n

    async def count(self) -> int:
        if self._n < 0:
            raise ValueError("invalid selector")
        return self._n


class _FakeRoot:
    """Records which strategy was asked for; count map keyed by strategy."""

    def __init__(self, counts: dict):
        self.counts = counts
        self.calls: list[tuple[str, str]] = []

    def locator(self, sel):
        self.calls.append(("locator", sel))
        key = "testid" if sel.startswith('[data-testid') else "css"
        return _FakeLocator(self.counts.get(key, 0))

    def get_by_role(self, role, name=None):
        self.calls.append(("role", role))
        return _FakeLocator(self.counts.get("role", 0))

    def get_by_text(self, text):
        self.calls.append(("text", text))
        return _FakeLocator(self.counts.get("text", 0))


async def test_resolve_tries_css_first_for_spaced_structural_selector():
    root = _FakeRoot({"css": 2})
    _, by = await resolve(root, "#form input")
    assert by == "css"


async def test_resolve_spaced_css_falls_through_to_text():
    # "Home > Products" parses as CSS but matches nothing → text tier wins
    root = _FakeRoot({"css": 0, "text": 1})
    _, by = await resolve(root, "Home > Products")
    assert by == "text"


def test_locate_treats_spaced_structural_selector_as_css():
    root = _FakeRoot({})
    locate(root, "#form input")
    assert root.calls == [("locator", "#form input")]
    locate(root, "div > a")
    assert ("locator", "div > a") in root.calls


# ── role parsing degrades gracefully ──────────────────────────────
def test_parse_role_variants():
    assert _parse_role("button name=로그인") == ("button", "로그인")
    assert _parse_role('button name="Log in"') == ("button", "Log in")
    assert _parse_role("button submit") == ("button", "submit")  # no bogus role
    assert _parse_role("button") == ("button", None)


# ── scrub: longest secret value replaced first ────────────────────
def test_scrub_replaces_longest_secret_first(monkeypatch):
    monkeypatch.setenv("USER_PASSWORD", "abc123")
    monkeypatch.setenv("AUTH_TOKEN", "abc123-extended")
    secrets.clear_registry()
    secrets.resolve("${USER_PASSWORD}")
    secrets.resolve("${AUTH_TOKEN}")
    out = secrets.scrub("sent abc123-extended in header")
    assert out == "sent ${AUTH_TOKEN} in header"  # no ${USER_PASSWORD}-extended
    assert secrets.scrub("typed abc123 too") == "typed ${USER_PASSWORD} too"


# ── Markdown table survives '|' in captured text ──────────────────
def test_markdown_escapes_pipes_in_cells():
    result = {
        "name": "t", "summary": report.summarize([{"passed": True}]),
        "meta": {}, "steps": [{
            "step": 1, "action": "assert", "passed": True, "resolved_by": None,
            "expected": "a|b", "actual": "x | y", "severity": None,
        }],
    }
    md = report._render_markdown(result)
    row = next(line for line in md.splitlines() if line.startswith("| 1 |"))
    # 8 column separators for 7 columns — unescaped pipes would add more
    assert row.count("|") - row.count("\\|") == 8
    assert "a\\|b" in md


# ── HTML report embeds only files under the report dir ────────────
def test_b64_refuses_paths_outside_report_dir(tmp_path):
    base = tmp_path / "reports"
    base.mkdir()
    inside = base / "shot.png"
    inside.write_bytes(b"png")
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"nope")
    assert report._b64(inside, base) is not None
    assert report._b64(base / ".." / "secret.png", base) is None
