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
    assert r["matched"] is True  # a real iframe was found
    # snapshot now scoped to the iframe content
    assert "안쪽" in await snapshot()
    back = await switch_frame(None)
    assert back["context"] == "main"


async def test_switch_frame_flags_missing_selector(session):
    await session.page.set_content("<div>no frames here</div>")
    r = await switch_frame("#nope")
    assert r["ok"] is True and r["matched"] is False  # typo flagged, not silent


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


async def test_expect_dialog_action_case_insensitive(session):
    # "Accept" must accept, not silently fall through to dismiss
    await session.page.set_content(
        "<button data-testid='a' onclick=\"alert('hi')\">go</button>")
    r = await expect_dialog(action="Accept", trigger="testid=a")
    assert r["passed"] is True and r["handled"] == "accept"


async def test_expect_dialog_rejects_bad_action(session):
    await session.page.set_content(
        "<button data-testid='a' onclick=\"alert('hi')\">go</button>")
    r = await expect_dialog(action="approve", trigger="testid=a")
    assert r["passed"] is False and "accept|dismiss" in r["error"]


async def test_expect_dialog_missing_is_failure(session):
    await session.page.set_content("<button data-testid='n'>noop</button>")
    r = await expect_dialog(action="accept", trigger="testid=n")
    assert r["passed"] is False


# ── P2-11: poll cadence ──────────────────────────────────────────────
async def test_wait_backs_off_instead_of_polling_flat(session):
    """A bare-string selector re-runs the whole D2 chain per poll (~12 driver
    round trips). At a flat 100ms that was 208 Locator.count() calls for a 2s
    wait; the ramp keeps a long wait from spending its budget on IPC."""
    from playwright.async_api import Locator

    from blackbox_mcp.tools.wait import wait

    await session.page.set_content("<div>nothing here</div>")
    calls = {"n": 0}
    real = Locator.count

    async def counting(self):
        calls["n"] += 1
        return await real(self)

    Locator.count = counting
    try:
        r = await wait(selector="절대없는텍스트123", timeout_ms=2000)
    finally:
        Locator.count = real
    assert r["ok"] is False
    assert calls["n"] < 150, f"still polling near-flat ({calls['n']} probes)"


async def test_wait_still_finds_a_quickly_appearing_element(session):
    """Backing off must not make the common case sluggish — the first polls
    stay at the original cadence."""
    import time as _time

    from blackbox_mcp.tools.wait import wait

    await session.page.set_content(
        "<div id='d'></div><script>setTimeout(() => {"
        "document.getElementById('d').textContent = '늦게 나타남';}, 120)"
        "</script>")
    t0 = _time.monotonic()
    r = await wait(selector="늦게 나타남", timeout_ms=5000)
    assert r["ok"] is True
    assert _time.monotonic() - t0 < 1.0


async def test_wait_does_not_overshoot_its_deadline(session):
    """The final sleep is clamped to the remaining budget, so a 500ms poll
    cannot push a wait past the timeout the caller asked for."""
    import time as _time

    from blackbox_mcp.tools.wait import wait

    await session.page.set_content("<div>x</div>")
    t0 = _time.monotonic()
    await wait(selector="css=.nope-xyz", timeout_ms=1500)
    elapsed = (_time.monotonic() - t0) * 1000
    assert 1500 <= elapsed < 1900, elapsed
