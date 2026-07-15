"""Guards for the MCP-structure audit fixes: non-blocking bootstrap, tool-call
serialization, report_format validation, navigate result shape, bounded log
tools, schema enums."""
from __future__ import annotations

import asyncio

import pytest

from blackbox_mcp.testing import report


# ── HIGH-1: bootstrap no longer blocks the handshake; install is bounded ──
def test_server_main_does_not_install_before_run(monkeypatch):
    """server.main() must register + run without calling ensure_chromium
    (which now happens lazily in session.start)."""
    import blackbox_mcp.server as srv

    calls = {"install": 0, "run": 0}
    monkeypatch.setattr(srv, "register_all", lambda m: 25)
    monkeypatch.setattr(srv.mcp, "run", lambda: calls.__setitem__("run", calls["run"] + 1))
    # ensure_chromium is imported inside session.start now, not server — assert
    # it is not referenced at module scope of server.
    assert not hasattr(srv, "ensure_chromium")
    srv.main()
    assert calls["run"] == 1


def test_install_is_time_bounded():
    import inspect

    from blackbox_mcp import bootstrap
    src = inspect.getsource(bootstrap.ensure_chromium)
    assert "timeout=" in src and "INSTALL_TIMEOUT_S" in src
    assert bootstrap.INSTALL_TIMEOUT_S > 0


def test_cdp_mode_skips_install(monkeypatch):
    import dataclasses

    from blackbox_mcp import bootstrap
    from blackbox_mcp.config import CONFIG
    monkeypatch.setattr(bootstrap, "CONFIG",
                        dataclasses.replace(CONFIG, cdp_url="http://localhost:9222",
                                            chromium_executable=None))
    called = {"install": False}
    monkeypatch.setattr(bootstrap, "_browser_installed",
                        lambda n: called.__setitem__("install", True) or False)
    bootstrap.ensure_chromium()  # must early-return, never probing/installing
    assert called["install"] is False


# ── HIGH-3 / MEDIUM-7: every tool body runs under one serialization lock ──
async def test_tool_calls_are_serialized():
    from mcp.server.fastmcp import FastMCP

    from blackbox_mcp.tools import _registry
    _registry._REGISTERED = False
    m = FastMCP("probe")
    _registry.register_all(m)
    try:
        # The lock exists and wraps tool bodies; prove mutual exclusion with two
        # coroutines that both take it.
        order = []

        async def a():
            async with _registry._TOOL_LOCK:
                order.append("a-start")
                await asyncio.sleep(0.05)
                order.append("a-end")

        async def b():
            async with _registry._TOOL_LOCK:
                order.append("b")

        await asyncio.gather(a(), b())
        # b cannot interleave between a-start and a-end
        assert order == ["a-start", "a-end", "b"]
    finally:
        _registry._REGISTERED = False


def test_registry_wraps_every_tool_in_serializer():
    import inspect

    from blackbox_mcp.tools import _registry
    src = inspect.getsource(_registry.register_all)
    assert "_serialized(fn)" in src


# ── HIGH-2: unknown report_format cannot silently drop the recorder ──
def test_report_save_rejects_unknown_format(tmp_path, monkeypatch):
    import dataclasses
    monkeypatch.setattr(report, "CONFIG",
                        dataclasses.replace(report.CONFIG, report_dir=tmp_path))
    result = {"name": "x", "run_id": "20990101_000000_000001",
              "summary": report.summarize([{"passed": True}]),
              "meta": {}, "steps": []}
    with pytest.raises(ValueError):
        report.save(result, formats="pdf")
    # case-insensitive normalization still accepts canonical values
    assert report.save(result, formats="JSON")


async def test_save_report_bad_format_keeps_recorder(session, tmp_path, monkeypatch):
    import dataclasses

    from blackbox_mcp.testing import recorder
    from blackbox_mcp.tools.navigate import navigate
    from blackbox_mcp.tools.savereport import save_report
    monkeypatch.setattr(report, "CONFIG",
                        dataclasses.replace(report.CONFIG, report_dir=tmp_path))
    recorder.reset()
    from conftest import fixture_url
    await recorder.run_and_record("navigate", navigate,
                                  (fixture_url("basic.html"),), {})
    assert len(recorder.steps()) == 1
    r = await save_report(report_format="pdf")
    assert r["ok"] is False and "pdf" in r["error"]
    # steps NOT discarded — a retry with a valid format still works
    assert len(recorder.steps()) == 1
    r2 = await save_report(report_format="md")
    assert r2["ok"] is True


# ── MEDIUM-4: navigate returns a consistent {ok,...} shape ──
async def test_navigate_shape_ok_on_load(session):
    from conftest import fixture_url

    from blackbox_mcp.tools.navigate import navigate
    r = await navigate(fixture_url("basic.html"))
    assert r["ok"] is True and r["error"] is None
    assert r["status"] is None or r["status"] < 400


async def test_navigate_dns_error_returns_structured_not_raises(session):
    from blackbox_mcp.tools.navigate import navigate
    r = await navigate("http://no-such-host.invalid.example/")
    assert r["ok"] is False and r["error"] and r["status"] is None


async def test_runner_navigate_error_is_a_failed_step(session):
    from blackbox_mcp.testing import runner
    res = await runner.run(
        [{"action": "navigate", "url": "http://no-such-host.invalid.example/"}],
        name="dns")
    assert res["summary"]["failed"] == 1
    assert res["steps"][0]["ai_reason"] == "navigation failed"


# ── MEDIUM-5: log tools are bounded and signal truncation/overflow ──
async def test_console_logs_bounded_and_signalled(session):
    from blackbox_mcp.browser.listeners import ConsoleEntry
    from blackbox_mcp.tools.console import get_console_logs
    for i in range(50):
        session.buffers.console.append(
            ConsoleEntry(level="error", text=f"e{i}", location="", ts=0.0))
    r = await get_console_logs(level="error", limit=10)
    assert r["returned"] == 10 and r["total"] == 50 and r["truncated"] is True
    assert r["logs"][-1]["text"] == "e49"  # newest kept


def test_buffer_tracks_dropped_overflow():
    from blackbox_mcp.browser.listeners import ConsoleEntry, EventBuffers, _MAX_EVENTS
    b = EventBuffers()
    for i in range(_MAX_EVENTS + 5):
        b.add_console(ConsoleEntry(level="log", text=str(i), location="", ts=0.0))
    assert b.console_dropped == 5 and len(b.console) == _MAX_EVENTS
    b.clear()
    assert b.console_dropped == 0


# ── MEDIUM-6: enum params carry a schema enum ──
async def test_enum_params_have_schema_enums():
    from mcp.server.fastmcp import FastMCP

    import blackbox_mcp.tools as tools_pkg
    from blackbox_mcp.tools import _registry
    # Import every tool module first (the inner _registry.register_all does NOT)
    # so this passes in the fast lane too, not only after a browser test has
    # imported them — order-independent.
    tools_pkg._import_all()
    _registry._REGISTERED = False
    m = FastMCP("probe")
    _registry.register_all(m)
    try:
        tools = {t.name: t for t in await m.list_tools()}
    finally:
        _registry._REGISTERED = False

    def enum_of(tn, p):
        s = tools[tn].inputSchema["properties"][p]
        if "enum" in s:
            return s["enum"]
        for x in s.get("anyOf", []):
            if "enum" in x:
                return x["enum"]
        return None

    assert enum_of("interact", "action") == ["click", "type", "hover", "select", "press"]
    assert set(enum_of("assert_", "kind")) == {
        "text_visible", "element_visible", "url_is", "url_contains", "count"}
    assert enum_of("navigate", "wait_until")
    assert enum_of("snapshot", "mode") == ["a11y", "dom"]
    assert enum_of("save_report", "report_format") == ["json", "md", "html", "both", "all"]
    # assert_.expected accepts int as well as str
    types = {x.get("type")
             for x in tools["assert_"].inputSchema["properties"]["expected"]["anyOf"]}
    assert "integer" in types and "string" in types
