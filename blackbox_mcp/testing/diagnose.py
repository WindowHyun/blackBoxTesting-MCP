"""Failure classification — is this the app's bug or the test's?

This is the gate that makes an autonomous repair loop safe. A loop that
"fixes" every failing step converges on a green suite that tests nothing:
when the app genuinely broke, rewriting the assertion until it passes is the
worst possible outcome. So before anything proposes a repair, a failure has to
be classified, and only one class is ever eligible for a test-side fix.

    app_broken    the page threw / the server 5xx'd / the app logged a stack
                  trace. NEVER touch the test. Report it.
    environment   the target was unreachable (DNS, TLS, proxy, refused). Not
                  a test defect and not an app defect — fix the environment.
    scenario_bug  the step itself is malformed (missing field, unknown verb).
                  Fixable, and the fix is mechanical.
    ui_changed    the app is healthy but what the step points at moved or was
                  renamed. The ONLY class where updating the selector /
                  expected value is legitimate.
    unknown       not enough signal. Escalate to a human; never auto-fix.

Classification is rule-based and deterministic, from evidence already in the
step record (console/pageerror, network, dialogs, app_log, severity, memory).
The host LLM can enrich the narrative, but the *eligibility* verdict is made
here so it cannot be talked out of by a persuasive-sounding model.
"""
from __future__ import annotations

import re

APP_BROKEN = "app_broken"
ENVIRONMENT = "environment"
SCENARIO_BUG = "scenario_bug"
UI_CHANGED = "ui_changed"
UNKNOWN = "unknown"

# Only this class may ever be auto-repaired on the test side.
AUTOFIXABLE = frozenset({UI_CHANGED, SCENARIO_BUG})

_MALFORMED = re.compile(
    r"missing required field|unknown action|unknown kind|unknown interact type|"
    r"expected not an int|requires a value|provide ms or selector", re.I)

_UNREACHABLE = re.compile(
    r"ERR_NAME_NOT_RESOLVED|ERR_CONNECTION_REFUSED|ERR_TUNNEL_CONNECTION_FAILED|"
    r"ERR_PROXY|ERR_CERT|ERR_SSL|ERR_INTERNET_DISCONNECTED|ERR_ADDRESS_UNREACHABLE|"
    r"net::ERR_", re.I)

_NOT_FOUND = re.compile(
    r"TimeoutError|not visible|element not found|not actionable|"
    r"resolve failed|strict mode violation", re.I)


def _server_errors(step: dict) -> list[dict]:
    return [n for n in step.get("network_errors") or []
            if isinstance(n.get("status"), int) and n["status"] >= 500]


def _page_errors(step: dict) -> list[dict]:
    return [c for c in step.get("console_errors") or []
            if c.get("source") == "pageerror"]


def classify(step: dict) -> dict:
    """Classify one FAILED step. Returns cause, confidence, evidence, eligibility.

    Order is deliberate: app-broken signals win over everything, because a
    failure that coincides with the app throwing must never be re-read as a
    stale selector just because the selector also happened not to match.
    """
    evidence: list[str] = []
    actual = str(step.get("actual") or "")

    page_errors = _page_errors(step)
    server_errors = _server_errors(step)
    app_log = [ln for ln in step.get("app_log") or []]

    # ── app broken ───────────────────────────────────────────────
    if page_errors:
        evidence.append(f"미처리 JS 예외 {len(page_errors)}건: {page_errors[0]['text'][:120]}")
    if server_errors:
        evidence.append(f"서버 5xx {len(server_errors)}건: "
                        f"{server_errors[0].get('status')} {server_errors[0].get('url', '')[:80]}")
    if app_log:
        evidence.append(f"앱 로그 오류 {len(app_log)}줄: {app_log[0][:120]}")
    if step.get("severity") == "js_error":
        evidence.append("severity=js_error")

    if page_errors or server_errors or app_log:
        return _verdict(APP_BROKEN, "high", evidence,
                        "앱이 예외를 던졌거나 서버가 5xx를 반환했다. "
                        "테스트를 고치면 결함을 덮는다 — 개발에 보고할 것.")

    # ── environment ──────────────────────────────────────────────
    failures = [n for n in step.get("network_errors") or [] if n.get("failure")]
    if _UNREACHABLE.search(actual) or any(_UNREACHABLE.search(str(n.get("failure")))
                                          for n in failures):
        evidence.append(f"도달 실패: {actual[:160]}")
        return _verdict(ENVIRONMENT, "high", evidence,
                        "대상에 접근하지 못했다. URL/DNS·프록시(PROXY_SERVER)·"
                        "인증서(IGNORE_HTTPS_ERRORS)·사내망 권한을 확인할 것.")

    # ── scenario bug ─────────────────────────────────────────────
    if _MALFORMED.search(actual):
        evidence.append(f"스텝 정의 오류: {actual[:160]}")
        return _verdict(SCENARIO_BUG, "high", evidence,
                        "스텝 자체가 스키마에 맞지 않는다. 필드를 채우면 된다.")

    # ── ui changed ───────────────────────────────────────────────
    # Reaching here means: the app did not throw, the server did not 5xx, the
    # target was reachable, and the step is well-formed — yet the check did not
    # hold. That is the signature of a UI that moved.
    is_assertion = str(step.get("severity")) == "assertion"
    # Only an explicit locator failure counts as "the element is gone". An
    # assertion simply returning False does NOT: `element_visible → False` is
    # produced both by a renamed element and by one the app failed to render,
    # and treating that as high confidence is how a loop deletes a real defect.
    looks_missing = bool(_NOT_FOUND.search(actual))

    if is_assertion or looks_missing:
        if step.get("selector_input"):
            evidence.append(f"셀렉터 '{step['selector_input']}'가 현재 페이지와 맞지 않음")
        else:
            evidence.append(f"기대와 실제 불일치: {actual[:160]}")
        if step.get("resolved_by"):
            evidence.append(f"직전 매칭 전략: {step['resolved_by']}")
        if looks_missing:
            # The element is genuinely gone from the page — the signature of a
            # rename/move rather than a behavioural bug.
            return _verdict(UI_CHANGED, "high", evidence,
                            "요소가 페이지에서 사라졌다 — 이동/개명으로 보인다. "
                            "셀렉터 갱신이 정당한 경우.")
        # The element exists; the ASSERTION about it is what did not hold. This
        # is the classifier's blind spot and it must say so: "장바구니 배지가
        # 안 뜬다"(기능 결함)와 "배지가 개명됐다"(UI 변경)는 구조적 신호가
        # 동일하다. Guessing here is how a loop deletes a real defect.
        evidence.append("요소는 존재하나 기대가 성립하지 않음 — "
                        "UI 변경인지 기능 결함인지 구조만으로는 구분 불가")
        return _verdict(UI_CHANGED, "medium", evidence,
                        "대상이 사라진 흔적이 없다. **UI 변경이 아니라 기능 결함일 수 "
                        "있으니** 화면/직전 스텝을 사람이 확인한 뒤에만 갱신할 것.")

    evidence.append(f"판단 근거 부족: {actual[:160]}")
    return _verdict(UNKNOWN, "low", evidence,
                    "자동 분류 불가. 사람이 확인할 것 — 자동 수정 금지.")


def _verdict(cause: str, confidence: str, evidence: list[str],
             recommendation: str) -> dict:
    return {
        "cause": cause,
        "confidence": confidence,
        "evidence": evidence,
        "recommendation": recommendation,
        # The gate. propose_repair refuses to touch anything that is False.
        "test_fix_allowed": cause in AUTOFIXABLE,
        # Eligible, but not on the classifier's word alone. Anything short of
        # high confidence needs a human to look at the screen first — the
        # structural signals cannot separate "renamed" from "broken".
        "requires_human_review": confidence != "high",
    }


def diagnose_result(result: dict) -> dict:
    """Classify every failed step of a finished run.

    Memory (when annotated) is folded into the narrative but never into the
    eligibility decision: a failure being chronic does not make rewriting the
    test any more legitimate.
    """
    findings: list[dict] = []
    for step in result.get("steps", []):
        if step.get("passed") or step.get("skipped"):
            continue
        verdict = classify(step)
        mem = step.get("memory") or {}
        if mem.get("status") == "recurring":
            verdict["evidence"].append(
                f"기억: 같은 실패 {mem.get('seen_before')}회째 (최초 {mem.get('first_seen')})")
        elif mem.get("status") == "regressed":
            verdict["evidence"].append(
                f"기억: 해결됐다가 재발 (최초 {mem.get('first_seen')})")
        findings.append({
            "step": step.get("step"),
            "action": step.get("action"),
            "selector_input": step.get("selector_input"),
            "tag": step.get("tag"),
            "priority": step.get("priority"),
            "severity": step.get("severity"),
            "fingerprint": step.get("fingerprint"),
            "memory_status": mem.get("status"),
            "actual": step.get("actual"),
            "page_url": step.get("page_url"),
            **verdict,
        })

    causes: dict[str, int] = {}
    for f in findings:
        causes[f["cause"]] = causes.get(f["cause"], 0) + 1

    return {
        "scenario": result.get("name"),
        "run_id": result.get("run_id"),
        "failed_steps": len(findings),
        "causes": causes,
        # One line a human (or the loop) can act on without reading everything.
        "verdict": _overall(causes),
        "findings": findings,
    }


def _overall(causes: dict[str, int]) -> str:
    if not causes:
        return "실패 없음"
    if causes.get(APP_BROKEN):
        return (f"앱 결함 {causes[APP_BROKEN]}건 — 테스트를 고치지 말 것. "
                "개발에 보고하고 수정 후 재검증.")
    if causes.get(ENVIRONMENT):
        return f"환경 문제 {causes[ENVIRONMENT]}건 — 접근 설정부터 해결."
    if causes.get(UNKNOWN):
        return f"분류 불가 {causes[UNKNOWN]}건 — 사람 확인 필요."
    total = sum(causes.values())
    return f"테스트 갱신 대상 {total}건 (UI 변경/스텝 정의) — 제안 후 승인받아 반영."


def summarize_for_prompt(diagnosis: dict) -> str:
    """Compact text form for a host LLM to reason over without the full JSON."""
    lines = [f"# 진단: {diagnosis.get('scenario')} ({diagnosis['failed_steps']}건 실패)",
             diagnosis["verdict"], ""]
    for f in diagnosis["findings"]:
        lines.append(f"- step {f['step']} [{f['cause']}/{f['confidence']}] "
                     f"{f['action']} {f.get('selector_input') or ''}")
        for e in f["evidence"]:
            lines.append(f"    · {e}")
        lines.append(f"    → {f['recommendation']}")
    return "\n".join(lines)
