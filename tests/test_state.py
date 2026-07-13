"""save_state / load_state — storage-state auth reuse (cookies + localStorage)."""
from __future__ import annotations

import os

from blackbox_mcp.tools import state as state_mod

_MOCK_PAGE = "<h1>state fixture</h1>"


def _serve(route):
    return route.fulfill(body=_MOCK_PAGE, content_type="text/html")


async def _fake_origin(session):
    """A route-mocked http origin: storage_state does NOT capture file://
    localStorage (verified against Playwright 1.61), so tests need http."""
    await session._context.route("**/state.test/**", _serve)


async def test_state_roundtrip_restores_login(session, tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "_state_dir", lambda: tmp_path)

    await _fake_origin(session)
    await session.page.goto("http://state.test/")
    await session.page.evaluate(
        "localStorage.setItem('tok','abc'); document.cookie='sid=xyz'")

    r = await state_mod.save_state("login")
    assert r["ok"] is True and (tmp_path / "login.json").exists()

    await session.reset()  # wipe cookies/localStorage
    r2 = await state_mod.load_state("login")
    assert r2["ok"] is True

    await _fake_origin(session)  # fresh context → routes must be re-armed
    await session.page.goto("http://state.test/")
    assert await session.page.evaluate("localStorage.getItem('tok')") == "abc"
    assert "sid=xyz" in await session.page.evaluate("document.cookie")


async def test_state_file_is_owner_only(session, tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "_state_dir", lambda: tmp_path)
    await session.page.goto("about:blank")
    r = await state_mod.save_state("perm")
    assert r["ok"] is True
    if os.name == "posix":
        assert (tmp_path / "perm.json").stat().st_mode & 0o777 == 0o600


async def test_load_state_missing_lists_available(session, tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "_state_dir", lambda: tmp_path)
    await state_mod.save_state("exists")
    r = await state_mod.load_state("ghost")
    assert r["ok"] is False and "exists" in r["available"]


async def test_load_state_refused_in_real_browser_mode(session, tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "_state_dir", lambda: tmp_path)
    await state_mod.save_state("s")
    monkeypatch.setattr(session, "_persistent", True)  # simulate real-browser mode
    r = await state_mod.load_state("s")
    assert r["ok"] is False and "real-browser" in r["error"]


async def test_list_states(session, tmp_path, monkeypatch):
    monkeypatch.setattr(state_mod, "_state_dir", lambda: tmp_path)
    assert await state_mod.list_states() == []
    await state_mod.save_state("a")
    names = [s["name"] for s in await state_mod.list_states()]
    assert names == ["a"]


async def test_runner_state_steps(session, tmp_path, monkeypatch):
    from blackbox_mcp.testing import runner

    monkeypatch.setattr(state_mod, "_state_dir", lambda: tmp_path)
    res = await runner.run(
        [{"action": "save_state", "name": "run1"},
         {"action": "load_state", "name": "run1"}],
        name="state_steps")
    assert res["summary"]["failed"] == 0
    res2 = await runner.run([{"action": "load_state", "name": "nope"}], name="bad")
    assert res2["summary"]["failed"] == 1
