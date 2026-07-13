"""mock_route / unmock_route — deterministic network mocking (flaky 차단).

Real sites lean on unstable or unimplemented external APIs; mocking them makes
scenarios deterministic. A mock intercepts requests matching a glob pattern on
the CURRENT context and fulfills them locally (no network). Combined with
navigate's status verdict / ``expect_status``, a mocked 500 also lets you test
error-page handling offline.

Lifetime: mocks belong to the current browser context — ``reset_session`` and
``load_state`` recreate the context and silently drop them (re-arm after).
"""
from __future__ import annotations

from ..browser import get_session
from ._registry import tool


def _active(context) -> list[str]:
    return list(getattr(context, "_bbx_mocks", []))


@tool(description="글롭 패턴에 매칭되는 요청을 가로채 로컬 응답으로 대체한다(네트워크 미사용). "
                  "예: mock_route('**/api/items**', body='[]', "
                  "content_type='application/json'). status=500과 expect_status를 "
                  "조합하면 에러 페이지 처리도 오프라인으로 검증 가능. 주의: mock은 현재 "
                  "컨텍스트에만 적용 — reset_session/load_state 후에는 다시 걸어야 한다.")
async def mock_route(pattern: str, body: str = "", status: int = 200,
                     content_type: str = "application/json") -> dict:
    session = await get_session()
    context = session._context
    if context is None:
        return {"ok": False, "error": "no active browser context"}

    async def handler(route) -> None:
        await route.fulfill(status=status, body=body, content_type=content_type)

    await context.route(pattern, handler)
    mocks = _active(context)
    mocks.append(pattern)
    context._bbx_mocks = mocks
    return {"ok": True, "pattern": pattern, "status": status, "active": mocks}


@tool(description="mock_route로 건 모킹을 해제한다. pattern을 주면 그 패턴만, 없으면 전부 "
                  "해제한다. 반환의 active가 남아 있는 모킹 목록.")
async def unmock_route(pattern: str | None = None) -> dict:
    session = await get_session()
    context = session._context
    if context is None:
        return {"ok": False, "error": "no active browser context"}

    if pattern is None:
        await context.unroute_all()
        context._bbx_mocks = []
    else:
        await context.unroute(pattern)
        context._bbx_mocks = [p for p in _active(context) if p != pattern]
    return {"ok": True, "active": _active(context)}
