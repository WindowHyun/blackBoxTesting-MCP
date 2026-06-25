"""T1.4 — snapshot integration + trimming (CT-02, Q1)."""
from __future__ import annotations

from conftest import fixture_url

from blackbox_mcp.tools.navigate import navigate
from blackbox_mcp.tools.snapshot import snapshot


async def test_a11y_snapshot_lists_roles(session):
    await navigate(fixture_url("basic.html"), wait_until="load")
    snap = await snapshot(mode="a11y")
    # YAML aria tree should mention the heading/button accessible names
    assert "로그인" in snap
    assert "button" in snap


async def test_dom_mode_returns_text(session):
    await navigate(fixture_url("basic.html"), wait_until="load")
    snap = await snapshot(mode="dom")
    assert "로그인" in snap


async def test_depth_trims_large_tree(session):
    big = "<main>" + "".join(
        f"<section><h2>S{i}</h2><ul><li>a{i}</li><li>b{i}</li></ul></section>"
        for i in range(30)
    ) + "</main>"
    await session.page.set_content(big)
    full = await snapshot(mode="a11y")
    shallow = await snapshot(mode="a11y", depth=1)
    # depth (via AI mode) must produce a meaningfully smaller snapshot
    assert len(shallow) < len(full)
