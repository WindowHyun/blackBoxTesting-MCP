"""switch_page — list the open tabs/popups and choose the active one.

The session follows every new page the context opens (``_adopt_page``) because
real flows need it: OAuth popups, ``target=_blank`` links, ``window.open``. The
cost is that an ad/tracker popunder is adopted just as eagerly, and until now
there was **no way back** — every later step ran against the ad page and the run
was unrecoverable without a full ``reset_session`` (which also throws away the
login you were testing).

This tool makes adoption reversible:

    switch_page()          -> list the open pages (no switch)
    switch_page(index=0)   -> make page 0 (the original tab) active again

Available as a scenario step too, so a saved flow can pin itself back to the
tab it cares about::

    {"action": "switch_page", "index": 0}
"""
from __future__ import annotations

from ..browser import get_session
from ._registry import tool


def _describe(pages) -> list[dict]:
    out: list[dict] = []
    for i, p in enumerate(pages):
        try:
            out.append({"index": i, "url": p.url, "closed": p.is_closed()})
        except Exception:
            out.append({"index": i, "url": None, "closed": True})
    return out


@tool(description="열려 있는 탭/팝업 목록을 보거나 활성 페이지를 바꾼다. index 없이 "
                  "호출하면 목록만 반환하고, index를 주면 그 페이지를 활성으로 만든다. "
                  "클릭으로 열린 팝업(광고 팝언더 포함)은 자동으로 활성이 되므로, "
                  "원래 탭으로 돌아올 때 index=0으로 호출한다.")
async def switch_page(index: int | None = None) -> dict:
    session = await get_session()
    context = session._context
    if context is None:
        return {"ok": False, "error": "no active browser context"}

    pages = [p for p in context.pages if not p.is_closed()]
    if not pages:
        return {"ok": False, "error": "no open pages"}

    current = next((i for i, p in enumerate(pages) if p is session._page), None)
    if index is None:
        return {"ok": True, "count": len(pages), "index": current,
                "pages": _describe(pages)}

    if not isinstance(index, int) or not 0 <= index < len(pages):
        return {"ok": False, "error": f"index {index} out of range (0..{len(pages) - 1})",
                "count": len(pages), "index": current, "pages": _describe(pages)}

    target = pages[index]
    # Same bookkeeping _adopt_page does: listeners attached exactly once, and a
    # page switch invalidates whatever iframe we had entered.
    session._page = target
    session._frame_selector = None
    session._watch_page(target)
    await target.bring_to_front()
    return {"ok": True, "count": len(pages), "index": index, "url": target.url,
            "title": await target.title()}
