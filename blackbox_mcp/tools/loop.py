"""Tools for the autonomous test loop: 기억 조회 · 원인 진단 · 수정 제안.

These are the three pieces the loop needs that ordinary run/report tools do
not provide:

  get_failure_memory  did we see this before, or is it new?
  diagnose_run        WHY did it fail — and is fixing the test even legitimate?
  propose_repair      candidate replacements for a step whose target moved.

``propose_repair`` deliberately does not write anything. It gathers the
current page's real elements and hands back candidates; the host LLM composes
the new step and calls ``save_scenario`` after the user agrees. Keeping the
write on the far side of a human keeps a bad diagnosis from silently rewriting
a suite into a green no-op.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..browser import get_session
from ..testing import diagnose as diag
from ..testing import memory as mem
from ..testing import report as report_mod
from ._registry import tool


@tool(description="이전 실행들에서 기록된 실패 이력을 조회한다. 각 항목의 status는 "
                  "new(처음)·recurring(만성)·regressed(고쳤다가 재발). 같은 실패를 "
                  "매번 처음부터 진단하지 않기 위한 기억. scenario로 좁힐 수 있다.")
async def get_failure_memory(scenario: str | None = None,
                             unresolved_only: bool = True) -> list[dict]:
    entries = mem.summary(scenario)
    if unresolved_only:
        entries = [e for e in entries if not e.get("resolved_at")]
    return entries


def _latest_report() -> dict | None:
    """Most recent report JSON under REPORT_DIR, or None."""
    try:
        base = report_mod.ensure_dirs()
    except Exception:
        return None
    files = sorted(base.glob("report_*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except Exception:
        return None


@tool(description="실행 결과의 실패를 원인별로 분류한다: app_broken(앱 결함 — 테스트를 "
                  "고치면 결함을 덮는다) · environment(접근 불가) · scenario_bug(스텝 "
                  "정의 오류) · ui_changed(대상 이동/개명 — 테스트 갱신이 정당한 유일한 "
                  "경우) · unknown. report_path 생략 시 가장 최근 리포트를 읽는다.")
async def diagnose_run(report_path: str | None = None) -> dict:
    if report_path:
        try:
            result = json.loads(Path(report_path).expanduser().read_text(encoding="utf-8"))
        except Exception as exc:
            return {"error": f"리포트를 읽을 수 없음: {type(exc).__name__}: {exc}"}
    else:
        result = _latest_report()
        if result is None:
            return {"error": "리포트가 없다 — run_scenario를 먼저 실행할 것"}

    # A report saved before diagnosis existed still classifies fine: the
    # classifier reads step fields, not a stored verdict.
    diagnosis = result.get("diagnosis") or diag.diagnose_result(result)
    diagnosis["summary_text"] = diag.summarize_for_prompt(diagnosis)
    return diagnosis


@tool(description="셀렉터가 더 이상 맞지 않는 스텝에 대해 현재 페이지에서 대체 후보를 "
                  "찾는다(D2 우선순위: testid → role+name → text → css). 아무것도 "
                  "저장하지 않는다 — 후보를 받아 새 스텝을 구성한 뒤 사용자 동의를 받고 "
                  "save_scenario로 반영할 것. app_broken/environment로 분류된 실패에는 "
                  "거부한다(결함을 테스트로 덮는 것을 막기 위해).")
async def propose_repair(selector: str, cause: str = "ui_changed",
                         hint: str | None = None, limit: int = 8) -> dict:
    if cause not in diag.AUTOFIXABLE:
        return {
            "allowed": False,
            "cause": cause,
            "error": (f"'{cause}' 분류에는 테스트 수정을 제안하지 않는다. "
                      "앱/환경 문제를 테스트 변경으로 덮으면 결함이 사라진 것처럼 보인다."),
        }

    session = await get_session()
    from .generate import _COLLECT_JS, _suggest_selector

    try:
        elements = await session.root.locator("body").evaluate(_COLLECT_JS)
    except Exception as exc:
        return {"allowed": True, "candidates": [],
                "error": f"현재 페이지를 읽지 못함: {type(exc).__name__}: {exc}"}

    needle = (hint or selector).split("=", 1)[-1].strip().lower()
    scored: list[tuple[int, dict]] = []
    for el in elements:
        suggestion = _suggest_selector(el)
        haystack = " ".join(str(el.get(k) or "") for k in
                            ("testid", "id", "name", "role", "tag")).lower()
        # Cheap lexical affinity: an element whose testid/label still contains
        # the old token is far more likely to be the renamed target than an
        # arbitrary button on the page. Not clever — just ordered.
        score = 0
        if needle and needle in haystack:
            score += 10
        if el.get("testid"):
            score += 3          # D2 prefers a testid replacement
        elif el.get("role") and el.get("name"):
            score += 2
        scored.append((score, {"selector": suggestion, **el}))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    candidates = [c for _, c in scored[:max(1, limit)]]

    return {
        "allowed": True,
        "cause": cause,
        "old_selector": selector,
        "page_url": session.page.url,
        "candidates": candidates,
        "note": ("D2 우선순위 순으로 정렬된 후보다. 하나를 골라 스텝을 고친 뒤 "
                 "사용자 동의를 받아 save_scenario(overwrite=True)로 저장하고, "
                 "run_scenario로 회귀를 확인할 것."),
    }
