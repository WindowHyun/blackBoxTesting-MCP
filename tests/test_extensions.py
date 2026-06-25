"""Phase 4 — wait, switch_frame, reset_session, expect_dialog (CT-08/09/10, BR-04)."""
from __future__ import annotations

from blackbox_mcp.tools.wait import wait
from blackbox_mcp.tools.frame import switch_frame
from blackbox_mcp.tools.session import reset_session
from blackbox_mcp.tools.dialog import expect_dialog
from blackbox_mcp.tools.assertion import assert_
from blackbox_mcp.tools.snapshot import snapshot


# ── CT-08 wait ────────────────────────────────────────────────────
async def test_wait_fixed_ms(session):
    r = await wait(ms=50)
    assert r["ok"] and "50ms" in r["waited"]


async def test_wait_for_selector(session):
    # element appears after a short delay
    await session.page.set_content(
        "<div id='c'></div><script>setTimeout(()=>{"
        "document.getElementById('c').innerHTML='<b data-testid=late>hi</b>'},100)</script>"
    )
    r = await wait(selector="testid=late")
    assert r["ok"]
    assert (await assert_("element_visible", "testid=late"))["passed"]


async def test_wait_noop_without_args(session):
    r = await wait()
    assert r["ok"] is False


# ── CT-09 switch_frame ────────────────────────────────────────────
async def test_switch_frame_scopes_to_iframe(session):
    await session.page.set_content(
        "<iframe id='f' srcdoc=\"<button data-testid='inner'>안쪽</button>\"></iframe>"
    )
    await session.page.wait_for_timeout(100)
    r = await switch_frame("#f")
    assert r["ok"] and r["context"] == "#f"
    # snapshot now scoped to the iframe content
    assert "안쪽" in await snapshot()
    back = await switch_frame(None)
    assert back["context"] == "main"


# ── BR-04 reset_session ───────────────────────────────────────────
async def test_reset_session_clears_buffers(session):
    await session.page.set_content("<script>console.error('boom')</script>")
    await session.page.wait_for_timeout(50)
    assert len(session.buffers.console) >= 1
    r = await reset_session()
    assert r["ok"]
    assert len(session.buffers.console) == 0


# ── CT-10 expect_dialog ───────────────────────────────────────────
async def test_expect_dialog_accept_alert(session):
    await session.page.set_content(
        "<button data-testid='a' onclick=\"alert('안녕하세요')\">go</button>"
    )
    r = await expect_dialog(action="accept", expected_text="안녕", trigger="testid=a")
    assert r["passed"] is True
    assert r["dialog_type"] == "alert"


async def test_expect_dialog_dismiss_confirm(session):
    await session.page.set_content(
        "<button data-testid='c' onclick=\"confirm('삭제할까요?')\">go</button>"
    )
    r = await expect_dialog(action="dismiss", expected_text="삭제", trigger="testid=c")
    assert r["passed"] is True
    assert r["dialog_type"] == "confirm"


async def test_expect_dialog_missing_is_failure(session):
    await session.page.set_content("<button data-testid='n'>noop</button>")
    r = await expect_dialog(action="accept", trigger="testid=n")
    assert r["passed"] is False
