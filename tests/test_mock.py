"""mock_route / unmock_route — offline deterministic network mocking."""
from __future__ import annotations

from blackbox_mcp.tools.assertion import assert_
from blackbox_mcp.tools.mock import mock_route, unmock_route
from blackbox_mcp.tools.navigate import navigate


async def test_mock_serves_document_offline(session):
    r = await mock_route("**/mock.test/**", body="<h1>MOCKED</h1>",
                         content_type="text/html")
    assert r["ok"] is True and "**/mock.test/**" in r["active"]

    nav = await navigate("http://mock.test/page")
    assert nav["status"] == 200
    assert (await assert_("text_visible", "MOCKED"))["passed"] is True


async def test_mock_500_with_expect_status(session):
    """A mocked 500 exercises the navigate status verdict offline."""
    from blackbox_mcp.testing import runner

    res = await runner.run(
        [{"action": "mock_route", "pattern": "**/down.test/**",
          "body": "oops", "status": 500, "content_type": "text/html"},
         {"action": "navigate", "url": "http://down.test/", "expect_status": 500}],
        name="mock500")
    assert res["summary"]["failed"] == 0  # expect_status matches the mock


async def test_unmock_specific_pattern(session):
    await mock_route("**/a.test/**", body="A", content_type="text/plain")
    await mock_route("**/b.test/**", body="B", content_type="text/plain")
    r = await unmock_route("**/a.test/**")
    assert r["ok"] is True and r["active"] == ["**/b.test/**"]
    # b still mocked
    nav = await navigate("http://b.test/")
    assert nav["status"] == 200


async def test_unmock_all(session):
    await mock_route("**/x.test/**", body="X", content_type="text/plain")
    r = await unmock_route()
    assert r["ok"] is True and r["active"] == []
    # fetch from the (no longer mocked) origin now fails at network level
    await mock_route("**/page.test/**", body="<div>p</div>", content_type="text/html")
    await navigate("http://page.test/")
    out = await session.page.evaluate(
        "fetch('http://x.test/data').then(r => r.text()).catch(() => 'ERR')")
    assert out == "ERR"


async def test_mocks_dropped_on_reset(session):
    await mock_route("**/gone.test/**", body="G", content_type="text/plain")
    await session.reset()
    from blackbox_mcp.tools.mock import _active
    assert _active(session._context) == []  # fresh context → mocks gone


async def test_runner_mock_steps(session):
    from blackbox_mcp.testing import runner

    res = await runner.run(
        [{"action": "mock_route", "pattern": "**/api.test/**",
          "body": "<p>hello api</p>", "content_type": "text/html"},
         {"action": "navigate", "url": "http://api.test/v1"},
         {"action": "assert", "kind": "text_visible", "target": "hello api"},
         {"action": "unmock_route"}],
        name="mock_steps")
    assert res["summary"]["failed"] == 0
    res2 = await runner.run([{"action": "mock_route"}], name="malformed")
    assert res2["summary"]["failed"] == 1  # missing pattern → clear error
