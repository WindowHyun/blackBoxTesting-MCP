"""use_real_browser — switch to a real, persistent-profile browser on demand.

When the user wants to test a site that needs login/CAPTCHA, ask Claude to use
the real browser. This launches Chrome with a saved profile (login persists), so
subsequent runs reuse the session. The default flow (bundled headless browser)
stays unchanged unless this tool is called.
"""
from __future__ import annotations

from ..browser import get_session
from ._registry import tool


@tool(description="실제 Chrome을 '영구 프로필'로 띄워 이후 모든 동작을 그 브라우저에서 "
                  "수행하도록 전환한다. 로그인·쿠키가 프로필에 저장돼 다음 실행에도 "
                  "유지되므로 로그인/캡차가 필요한 사이트에 쓴다(처음 한 번만 그 창에서 "
                  "직접 로그인). headless 기본 False(창이 보임). 호출하지 않으면 기본 "
                  "번들 브라우저를 그대로 사용한다.")
async def use_real_browser(headless: bool = False, channel: str = "chrome") -> dict:
    session = await get_session()
    info = await session.switch_to_persistent(headless=headless, channel=channel)
    return {
        "ok": True,
        "mode": "real-persistent",
        "browser": info["used"],
        "profile": info["profile"],
        "note": "이 창에서 직접 로그인해 두면 다음 실행에도 유지됩니다.",
    }
