"""Uncaught JS errors and native dialogs must be visible, not silently eaten."""
from __future__ import annotations

from blackbox_mcp.tools.assertion import assert_
from blackbox_mcp.tools.console import get_console_logs
from blackbox_mcp.tools.dialog import expect_dialog, get_dialogs


async def test_uncaught_exception_is_captured(session):
    """Regression: Playwright does NOT deliver uncaught exceptions as console
    messages, so without a pageerror listener a page that threw reported a
    clean pass — the single most valuable black-box signal was invisible."""
    await session.page.set_content(
        "<div id=x>hi</div><script>setTimeout(()=>{null.foo()},5)</script>")
    await session.page.wait_for_timeout(300)

    errors = await get_console_logs("error")
    assert any(e["source"] == "pageerror" for e in errors), errors
    assert any("Uncaught" in e["text"] for e in errors)


async def test_unhandled_rejection_is_captured(session):
    await session.page.set_content(
        "<script>setTimeout(()=>Promise.reject(new Error('boom-rejection')),5)</script>")
    await session.page.wait_for_timeout(300)

    errors = await get_console_logs("error")
    assert any("boom-rejection" in e["text"] for e in errors), errors


async def test_console_error_still_tagged_as_console(session):
    await session.page.set_content("<script>console.error('plain-console')</script>")
    await session.page.wait_for_timeout(200)
    entry = next(e for e in await get_console_logs("error")
                 if "plain-console" in e["text"])
    assert entry["source"] == "console"


async def test_unexpected_dialog_is_recorded_and_page_continues(session):
    """An alert nobody armed expect_dialog for used to be auto-dismissed by
    Playwright with no trace at all — a silent pass."""
    await session.page.set_content(
        "<script>alert('예상 못한 알럿')</script><div id=y>after</div>")
    await session.page.wait_for_timeout(300)

    dialogs = await get_dialogs()
    assert len(dialogs) == 1
    assert dialogs[0]["type"] == "alert"
    assert dialogs[0]["message"] == "예상 못한 알럿"
    assert dialogs[0]["expected"] is False
    assert dialogs[0]["handled"] == "dismiss"
    # the page kept going (the dialog was dismissed, not left blocking)
    assert (await assert_("element_visible", "css=#y"))["passed"]


async def test_unexpected_only_filter(session):
    await session.page.set_content(
        "<script>alert('surprise')</script>"
        "<button id=b onclick=\"confirm('정말 삭제할까요?')\">del</button>")
    await session.page.wait_for_timeout(200)
    res = await expect_dialog("accept", "삭제", "css=#b")
    assert res["passed"], res

    assert len(await get_dialogs()) == 2
    unexpected = await get_dialogs(unexpected_only=True)
    assert [d["message"] for d in unexpected] == ["surprise"]


async def test_expected_dialog_is_not_stolen_by_the_recorder(session):
    """The always-on recorder is registered first; expect_dialog must override
    it rather than register a second listener, or the recorder's dismiss()
    would beat the accept()."""
    await session.page.set_content(
        "<div id=out></div>"
        "<button id=b onclick=\"document.getElementById('out').textContent ="
        " confirm('진행할까요?') ? 'ACCEPTED' : 'DISMISSED'\">go</button>")

    res = await expect_dialog("accept", "진행", "css=#b")
    assert res["passed"] and res["handled"] == "accept"
    assert await session.page.locator("#out").inner_text() == "ACCEPTED"

    logged = await get_dialogs()
    assert logged[-1]["expected"] is True and logged[-1]["handled"] == "accept"


async def test_dialog_handler_is_released_after_a_failed_trigger(session):
    """A leaked override would swallow every later dialog."""
    await session.page.set_content("<div>nothing to click</div>")
    res = await expect_dialog("accept", None, "css=#missing")
    assert not res["passed"]
    assert session.buffers.dialog_handler is None
