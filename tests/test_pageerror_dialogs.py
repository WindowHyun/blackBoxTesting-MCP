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


# ── a dialog raised asynchronously (P-09 regression) ─────────────
#
# expect_dialog used to allow a fixed 50ms grace after the trigger click. A
# dialog opened from a timer or a fetch callback — i.e. any app that confirms
# after a server round trip — arrived later than that and was reported as
# "no dialog appeared", a false failure.

async def test_dialog_raised_after_a_delay_is_still_caught(session):
    await session.page.set_content(
        "<div id=out></div>"
        "<button id=b onclick=\"setTimeout(() => {"
        " document.getElementById('out').textContent ="
        " confirm('정말 삭제할까요?') ? 'ACCEPTED' : 'DISMISSED'; }, 400)\">go</button>")

    res = await expect_dialog("accept", "삭제", "css=#b")

    assert res["passed"] is True, res
    assert res["handled"] == "accept"
    await session.page.wait_for_function(
        "() => document.getElementById('out').textContent === 'ACCEPTED'")


async def test_synchronous_dialog_does_not_wait_out_the_timeout(session):
    """The poll exits on capture, so the common case stays fast."""
    import time

    await session.page.set_content(
        "<button id=b onclick=\"alert('즉시')\">go</button>")

    t0 = time.monotonic()
    res = await expect_dialog("accept", "즉시", "css=#b", timeout_ms=5000)
    elapsed = time.monotonic() - t0

    assert res["passed"] is True
    assert elapsed < 2.0, f"a synchronous dialog waited {elapsed:.2f}s"


async def test_no_dialog_reports_the_window_it_waited(session):
    await session.page.set_content("<button id=b>does nothing</button>")
    res = await expect_dialog("accept", None, "css=#b", timeout_ms=300)
    assert res["passed"] is False
    assert "300ms" in res["error"]


async def test_runner_passes_timeout_ms_to_expect_dialog(session):
    """Dropping the field silently capped every scenario step at the default."""
    from blackbox_mcp.testing import runner

    await session.page.set_content(
        "<button id=b onclick=\"setTimeout(() => confirm('느린 확인'), 600)\">go</button>")

    res = await runner.run([{"action": "expect_dialog", "dialog_action": "accept",
                             "expected_text": "느린", "trigger": "css=#b",
                             "timeout_ms": 4000}], name="slow_dialog")
    assert res["steps"][0]["passed"] is True, res["steps"][0]
