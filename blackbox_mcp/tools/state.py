"""save_state / load_state — reuse a logged-in session without a real profile.

Exports the current context's cookies + localStorage to a named file
(~/ui-blackbox/state/{name}.json) and seeds a fresh context from it later.
Unlike use_real_browser (persistent Chrome profile, headed), storage state
works headless — log in once (even in the real browser), save, then load in
CI or later sessions.

Security: the file contains live session cookies/tokens. It stays under the
user's home (same trust level as the chrome-profile dir), is chmod 0600 on
POSIX, and its contents are never echoed into results or reports — only the
path is.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

from ..browser import get_session
from ._registry import tool

_SAFE = re.compile(r"[^A-Za-z0-9_\-가-힣]")


def _state_dir() -> Path:
    return Path.home() / "ui-blackbox" / "state"


def _state_path(name: str) -> Path:
    return _state_dir() / f"{_SAFE.sub('_', name.strip())}.json"


@tool(description="현재 브라우저 세션의 로그인 상태(쿠키+localStorage)를 이름으로 저장한다. "
                  "실 브라우저(use_real_browser)에서 로그인한 뒤 저장하면, 이후 headless "
                  "번들 브라우저에서 load_state로 재사용할 수 있다(CI 포함). 파일은 "
                  "~/ui-blackbox/state/{name}.json (POSIX에선 0600).")
async def save_state(name: str = "default") -> dict:
    session = await get_session()
    if session._context is None:
        return {"ok": False, "error": "no active browser context"}
    path = _state_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    await session._context.storage_state(path=str(path))
    try:
        os.chmod(path, 0o600)  # session cookies live here — owner-only
    except OSError:
        pass  # Windows/odd filesystems: best-effort
    return {"ok": True, "name": name, "path": str(path),
            "note": "로그인 쿠키가 담긴 파일입니다 — 공유/커밋 금지."}


@tool(description="save_state로 저장한 로그인 상태를 현재 세션에 불러온다(컨텍스트 재생성 — "
                  "열려 있던 페이지/쿠키는 대체됨). 번들/채널 브라우저 전용: CDP·영구 프로필 "
                  "모드는 자체적으로 로그인을 유지하므로 적용되지 않는다. "
                  "참고: localStorage는 http(s) 오리진만 복원된다(file://는 Playwright "
                  "storage_state 범위 밖).")
async def load_state(name: str = "default") -> dict:
    path = _state_path(name)
    if not path.exists():
        saved = [p.stem for p in _state_dir().glob("*.json")] if _state_dir().is_dir() else []
        return {"ok": False, "error": f"state '{name}' not found",
                "available": saved}
    session = await get_session()
    try:
        await session.load_storage_state(str(path))
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "name": name, "path": str(path)}


@tool(description="저장된 로그인 상태 목록(name·저장 시각). load_state로 불러올 수 있다.")
async def list_states() -> list[dict]:
    d = _state_dir()
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        out.append({"name": p.stem,
                    "saved_at": datetime.fromtimestamp(p.stat().st_mtime)
                    .isoformat(timespec="seconds")})
    return out
