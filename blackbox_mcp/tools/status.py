"""status — one-call observability for support/debugging.

Lets a user (or Claude) ask "what state is the server in?" instead of digging
through Claude Desktop logs: version, browser mode, liveness, current page,
buffer sizes, and the effective config.
"""
from __future__ import annotations

import sys
from importlib.metadata import PackageNotFoundError, version

from ..browser import session as session_mod
from ..config import CONFIG
from ._registry import tool


@tool(description="서버 상태 요약: 버전·브라우저 모드(번들/채널/영구프로필/CDP)·생존 여부·"
                  "현재 페이지·이벤트 버퍼 크기·유효 설정. 문제 진단 시 먼저 호출한다.")
async def status() -> dict:
    try:
        ver = version("ui-blackbox-mcp")
    except PackageNotFoundError:
        ver = "unknown"

    out: dict = {
        "version": ver,
        "python": sys.version.split()[0],
        "config": {
            "browser": CONFIG.browser,
            "headless": CONFIG.headless,
            "channel": CONFIG.browser_channel,
            "cdp_url": CONFIG.cdp_url,
            "stealth": CONFIG.stealth,
            "executable": CONFIG.chromium_executable or "bundled",
            "report_dir": str(CONFIG.report_dir),
            "scenario_dir": str(CONFIG.scenario_dir),
            "selector_timeout_ms": CONFIG.selector_timeout_ms,
            "nav_timeout_ms": CONFIG.nav_timeout_ms,
        },
    }

    # Inspect the existing session WITHOUT creating one — status must stay a
    # read-only probe (calling get_session() here would launch a browser).
    s = session_mod._SESSION
    if s is None:
        out["session"] = {"started": False}
        return out

    mode = ("cdp" if s._cdp else
            "persistent" if s._persistent else
            "channel" if CONFIG.browser_channel else "bundled")
    info: dict = {"started": True, "mode": mode, "alive": s.is_alive(),
                  "console_buffered": len(s.buffers.console),
                  "network_buffered": len(s.buffers.network)}
    try:
        if s.is_alive():
            info["url"] = s.page.url
            info["title"] = await s.page.title()
    except Exception:
        pass
    out["session"] = info
    return out
