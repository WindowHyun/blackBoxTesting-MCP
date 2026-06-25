# UI Blackbox Tester MCP — ROADMAP

> 실행 계획 문서. *무엇을·왜*는 [PRD v0.6], *어떻게*는 [`DESIGN.md`](./DESIGN.md),
> 이 문서는 ***언제·어떤 순서로·완료 기준은 무엇인지***를 다룬다.
>
> 모든 기술 기반은 **공식 문서로 검증**된 API에 근거한다(§ 검증 출처).
> 스택: Python 3.11+ · Playwright(Chromium) · MCP 공식 SDK(FastMCP) · stdio · Claude Desktop

---

## 마일스톤 개요

| Phase | 목표 | 핵심 요구사항 | 상태 |
|---|---|---|---|
| **0** | 스캐폴드 — 서버·레지스트리·세션 골격 | BR-01, D1, 레지스트리 | ✅ **완료** |
| **1** | 코어 PoC — 실제 브라우저로 탐색/이해 | CT-01, CT-02, BR-02 / Q1 | 🔜 **다음** |
| **2** | 상호작용·검증 (실검증) | CT-03~07, D2 | ☐ |
| **3** | 시나리오 실행·리포트(강화 포함) | SM-01~09, D3 | ☐ |
| **4** | 확장 Tools | CT-08~10, BR-03/04 | ☐ |
| **5** | 시나리오 라이브러리·생성 | SL-01~04 | ☐ |

> 성공지표(설치 <5분 / 탐지율 80% / 허위실패 <5%) 측정은 **Phase 3 이후**
> 내부 베타 10개 페이지 대상으로 수집한다(PRD §7).

---

## Phase 0 — 스캐폴드 ✅ 완료

**산출물**
- FastMCP 서버 부팅(`mcp.run()` stdio), `ensure_chromium()` 자동 설치(D1)
- Tool 레지스트리(`@tool` 데코레이터) — *Tool 추가 = 파일 1개*, server.py 불변
- async `BrowserSession` 싱글톤(BR-01), 콘솔/네트워크 버퍼(BR-02)
- D2 셀렉터 fallback 체인, 리포트/라이브러리/마스킹 스캐폴드
- 16개 Tool 등록(동작 11 + 스텁 5), 단위 테스트 3건

**공식 문서 근거**
- `from mcp.server.fastmcp import FastMCP, Image` / `@mcp.tool()` / `mcp.run()` 기본 stdio — MCP Python SDK
- async Playwright 채택 이유: sync API는 asyncio 루프 내에서 사용 불가 → MCP 비동기 런타임과 충돌

**완료 기준(DoD)** — ✅ 충족
- [x] `pytest` 통과(레지스트리 15툴 수집 / locator / 마스킹)
- [x] FastMCP가 16개 툴 노출 확인
- [x] 전 모듈 컴파일 OK

---

## Phase 1 — 코어 PoC 🔜 다음

**목표** 실제 페이지에서 async 세션·리스너·`aria_snapshot`이 동작함을 입증하고,
미결 **Q1(snapshot 출력 크기)**을 실측으로 닫는다. 모든 후속 Phase의 토대.

**작업**
- venv에 `playwright>=1.60` 설치 + `playwright install chromium` (환경 가능 여부 선확인)
- **FastMCP `lifespan` 배선** — 서버 시작 시 세션 준비, 종료 시 `close()` 정리(릭 방지)
- `bootstrap`의 `executable_path` 시그니처(property/메서드)를 설치 버전으로 재확인
- `tests/fixtures/*.html` 정적 픽스처 → `file://`로 `navigate` 통합 테스트
- `snapshot(mode="a11y")` = `locator.aria_snapshot()`(YAML) 실동작 확인
- **Q1 실측**: 실페이지 aria_snapshot 크기 측정 → 네이티브 `depth`/`mode="ai"` +
  `_MAX_CHARS` 안전장치로 트리밍 규칙 확정 → DESIGN §8 갱신
- `mode="dom"`을 임시 `inner_text`에서 태그/role/text 간략 트리로 정련

**공식 문서 근거**
- `page.accessibility.snapshot()`은 **deprecated** → `locator.aria_snapshot()` 권장(YAML).
  `boxes=True` 옵션은 "AI 소비에 유용" — 셀렉터 매칭 보조로 검토
- `page.goto(url, wait_until=...)` 값: `load`/`domcontentloaded`/`networkidle`/`commit`
- 콘솔/네트워크: `page.on("console"|"response"|"requestfailed")` — **4xx/5xx는
  `response`(status≥400)**, `requestfailed`는 네트워크 실패 한정

**완료 기준(DoD)**
- [ ] 실페이지 navigate→snapshot 통합 테스트 green
- [ ] lifespan으로 브라우저 시작/종료 정리 동작(릭 없음) 확인
- [ ] aria_snapshot 크기 측정값 기록 + 트리밍 정책 확정(Q1 close)
- [ ] 콘솔/네트워크 버퍼가 실제 이벤트를 수집함을 테스트로 확인

---

## Phase 2 — 상호작용·검증

**작업** `screenshot`(CT-03), `interact`(CT-04), `assert_`(CT-05),
`get_console_logs`(CT-06), `get_network_errors`(CT-07)를 픽스처로 실검증.
D2 셀렉터 체인(testid→role→text→css) 동작 확인.

추가: **crash-recovery 배선(NFR)** — 공통 tool 래퍼에서 `TargetClosedError` 등
캡처 → `BrowserSession.restart()` 1회 후 재시도(§DESIGN 3.5).

**공식 문서 근거**
- 이미지 반환: `Image(data=bytes, format="png")` (MCP SDK)
- `page.get_by_role(role, name=, exact=)`, `page.get_by_text(text, exact=)`,
  `locator.fill/click/hover/select_option/press`
- `FrameLocator`도 `get_by_role/get_by_text/get_by_test_id/locator` 지원 → frame root 동일 동작

**DoD**
- [ ] 5종 assert(text_visible/element_visible/url_is/url_contains/count) 테스트 통과
- [ ] interact 5동작 + 셀렉터 체인 fallback 테스트 통과
- [ ] screenshot이 유효 PNG 반환
- [ ] 브라우저 강제 종료 후 자동 재시작 < 5s 확인(R3)

---

## Phase 3 — 시나리오 실행·리포트

**작업** `run_scenario`(SM-01) 실행 엔진 — 스텝 디스패치, `continue_on_fail`,
실패 시 자동 스크린샷(SM-02). 리포트 JSON+MD(SM-03/D3): `./reports/
report_YYYYMMDD_HHMMSS.*`, `REPORT_DIR` 재정의, `${VAR}` 마스킹.
**HTML 리포트(SM-04, SHOULD)** — 단일 self-contained `.html`(스텝 표 + 스크린샷
인라인 + 콘솔/네트워크 에러), `report_format`에 `html`/`all` 추가.
다수 스텝 장기 실행 시 `await ctx.report_progress(i, total)`로 진행률 표시(옵션).

**리포트 강화(우선순위순, DESIGN §5.3·§6)**
- **SM-05** AI 판단 근거(`ai_reason`) + 실패 수정 제안(`ai_suggestion`) — 차별점
- **SM-06** 스텝별 캡처(통과/실패) + 셀렉터 투명성(`resolved_by`) + 콘솔/네트워크 **스텝 귀속**
- **SM-08** 환경 메타(OS/Python/Playwright·브라우저 버전/뷰포트) + 실패 심각도 분류
- **SM-07** 회귀 비교(직전 실행 대비 diff) — 2차
- **SM-09** a11y 발견사항(aria_snapshot 부산물) — 2차

**DoD**
- [ ] 성공/실패 혼합 시나리오가 정확한 per-step 결과·요약 생성
- [ ] 실패 스텝 스크린샷이 리포트에 첨부
- [ ] JSON+MD 리포트 파일 생성 확인
- [ ] HTML 리포트 생성 확인(스크린샷 임베드, 외부 의존성 없음) — SM-04
- [ ] 스텝별 캡처·`resolved_by`·에러 스텝귀속 반영 — SM-06
- [ ] AI 판단근거/수정제안 필드 채워짐 — SM-05
- [ ] 환경 메타·심각도 분류 표시 — SM-08
- [ ] (2차) 회귀 diff·a11y 섹션 — SM-07/09
- [ ] **성공지표 측정 착수** — 내부 베타 10페이지(PRD §7)

---

## Phase 4 — 확장 Tools

**작업** `wait`(CT-08), `switch_frame`(CT-09), `expect_dialog`(CT-10),
`reset_session`(BR-04, 구현완료·검증), `HEADLESS` 토글(BR-03).

**공식 문서 근거**
- `page.wait_for_selector` / `page.wait_for_timeout(ms)` / `page.expect_event`
- `page.frame_locator(selector)` — iframe 컨텍스트
- `page.on("dialog")` + `dialog.accept(prompt_text)`/`dismiss()`/`message()`/`type()`
  — dialog는 반드시 accept/dismiss 처리(미처리 시 페이지 freeze)

**DoD**
- [ ] iframe 내부 요소 조작, 다이얼로그 텍스트 검증·처리, 시간기반 대기 테스트 통과

---

## Phase 5 — 시나리오 라이브러리·생성

**작업** `save/load/list_scenario`(SL-02~04, 저장 로직 구현완료)에 더해
`generate_scenario`(SL-01) **작성 키트** 구현.

**설계 결정(검증 기반)** — Claude Desktop은 **MCP sampling 미지원**(클라이언트가
`sampling` capability를 선언해야만 동작). 따라서 서버가 LLM을 호출해 JSON을 만드는
방식은 Desktop에서 불가. 대신:
- 서버는 navigate→snapshot 후 **결정론적 작성 키트** 반환
  (상호작용 요소 + D2로 미리 해석된 셀렉터 + 스텝 JSON 스키마 + few-shot)
- **Claude(호스트 LLM)**가 키트로 steps 작성 → `save_scenario` 저장
- 미래 대비: sampling 지원 클라이언트면 tool에 `ctx: Context` 주입 →
  `await ctx.session.create_message(messages=[...], max_tokens=...)`로 서버측 생성,
  미지원 시 키트로 graceful fallback

**DoD**
- [ ] generate_scenario가 유효 키트 반환(요소·셀렉터·스키마)
- [ ] 키트→steps→save→load→run 왕복 동작
- [ ] sampling 분기(있으면 사용, 없으면 fallback) 검증

---

## 미결·리스크

| ID | 내용 | 해소 시점 |
|---|---|---|
| **Q1** | 대형 SPA aria_snapshot이 MCP 컨텍스트 한도 초과 가능 → 트리밍 수치 | Phase 1 실측 |
| R1 | 환경별 Chromium 설치 — CDN 차단 시 다운로드 불가 | ✅ 해소: `CHROMIUM_EXECUTABLE`/사전설치(`/opt/pw-browsers`) `executable_path` 사용 (T1.1) |
| R2 | sampling 미지원 환경에서 generate_scenario UX | Phase 5 (fallback 설계 반영됨) |
| R3 | 브라우저 크래시 자동 재시작 < 5s (NFR) 실측 | Phase 2~3 |

## 범위 외 (PRD Out of Scope)
자동 테스트 탐색(`discover_tests`) · API/백엔드 테스트 · CI/CD 통합 ·
퍼포먼스/로드 테스트 — 본 버전 제외(1.0 이후 검토).

---

## 검증 출처 (Official Docs)

- **MCP Python SDK** — `modelcontextprotocol/python-sdk` README (FastMCP, `@mcp.tool()`,
  `Image`, `mcp.run()` stdio, 타입힌트→`outputSchema`, `Context`(로깅·`report_progress`),
  `ctx.session.create_message` sampling, `lifespan` 시작/정리)
- **MCP Sampling** — MCP 사양/문서 (옵셔널 client capability, 인간 승인 필요, Claude Desktop 미지원)
- **Playwright (Python)** — playwright.dev / `microsoft/playwright` docs
  (`aria_snapshot` 권장·`accessibility.snapshot` deprecated, `aria_snapshot`
  `mode`/`depth`(≥1.59)·`boxes`(≥1.60), `goto` wait_until,
  console/response/requestfailed, dialog, get_by_role/text, frame_locator 및
  FrameLocator의 get_by_*/locator, wait_for_selector/timeout, executable_path)

> 일부 playwright.dev API 페이지는 직접 fetch가 403으로 막혀 GitHub 원본 마크다운 +
> 공식 검색 결과로 교차 확인함. 구현 중 설치된 버전의 시그니처를 코드로 재확인한다.

[PRD v0.6]: 사내 PRD 문서 (UI Blackbox MCP)
