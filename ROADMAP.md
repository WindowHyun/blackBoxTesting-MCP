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
| **1** | 코어 PoC — 실제 브라우저로 탐색/이해 | CT-01, CT-02, BR-02 / Q1 | ✅ 핵심 완료 (T1.5 보류) |
| **2** | 상호작용·검증 (실검증) | CT-03~07, D2 | ✅ 완료 |
| **3** | 시나리오 실행·리포트(강화 포함) | SM-01~09, D3 | ✅ 완료 |
| **4** | 확장 Tools | CT-08~10, BR-03/04 | ✅ 완료 |
| **5** | 시나리오 라이브러리·생성 | SL-01~04 | ✅ 완료 |

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

## Phase 1 — 코어 PoC ✅ 핵심 완료 (T1.5도 완료, dom 트리화)

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

## Phase 2 — 상호작용·검증 ✅ 완료

**완료** `screenshot`(CT-03)·`interact`(CT-04)·`assert_`(CT-05)·`get_console_logs`
(CT-06)·`get_network_errors`(CT-07)를 `file://` 픽스처로 실검증.
D2 셀렉터를 **async `resolve()` 실제 fallback 체인 + `resolved_by`**(SM-06 토대)로 구현.
`selector_timeout_ms` 적용, interact 실패 구조화 반환·값 마스킹.

**crash-recovery(NFR)** ✅ — `is_alive()` + `get_session()` 자동 `restart()`.

> 리뷰 발견·수정: assert_ multi-match strict-mode 크래시 → `count>0 && first` 로 수정.

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

## Phase 3 — 시나리오 실행·리포트 ✅ 완료 (SM-01~09)

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
- **SM-07** ✅ 회귀 비교(직전 실행 대비 diff, `reports/history/`)
- **SM-09** ✅ a11y 발견사항(img-alt/label/accessible-name 감사)

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

## Phase 4 — 확장 Tools ✅ 완료

**완료** `wait`(CT-08), `switch_frame`(CT-09), `expect_dialog`(CT-10, 스텁→구현),
`reset_session`(BR-04), `HEADLESS` 토글(BR-03). test_extensions 8 + test_config 3.
expect_dialog는 `expect_event` 데드락을 피해 `page.once("dialog")` 핸들러로 구현.

**공식 문서 근거**
- `page.wait_for_selector` / `page.wait_for_timeout(ms)` / `page.expect_event`
- `page.frame_locator(selector)` — iframe 컨텍스트
- `page.on("dialog")` + `dialog.accept(prompt_text)`/`dismiss()`/`message()`/`type()`
  — dialog는 반드시 accept/dismiss 처리(미처리 시 페이지 freeze)

**DoD**
- [ ] iframe 내부 요소 조작, 다이얼로그 텍스트 검증·처리, 시간기반 대기 테스트 통과

---

## Phase 5 — 시나리오 라이브러리·생성 ✅ 완료

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

## Phase 6 — 실무 하드닝·CI (1.0 이후) ✅ 완료

PRD 범위(Phase 0~5)를 넘어, 전체 코드베이스 감사(동시성·보안·운영)에서 나온
문제를 닫고 팀/CI 실무 요건을 갖춘 단계. **MCP 서버 본체는 무변경** — 대화형
블랙박스 테스트가 핵심 제품이고, 아래는 그 위에 얹은 견고화·진입점이다.

- **감사 수정(치명)** — bootstrap `playwright install`의 stdout DEVNULL(MCP 파이프
  오염 차단), 자격증명 완전 마스킹 + 파생 텍스트 scrub + 한국어/짧은토큰 감지,
  세션 `asyncio.Lock`(이중 기동/restart 경합 제거)·죽은 브라우저에서도 드라이버
  stop, 이벤트 버퍼 1000건 캡, recorder 단조 카운터·실행 스탬프 스크린샷,
  회귀 zero-overlap baseline 가드, env int 관용 파싱, 의존성 메이저 상한.
- **CLI/CI 진입점** (`ui-blackbox run/doctor`, DESIGN §7.1) — exit code + JUnit XML
  + `--parallel`(서브프로세스 격리). CI 파이프라인 편입 가능.
- **관측성** — `status` tool(대화) + `ui-blackbox doctor`(터미널).
- **리포트 보존** — `REPORT_RETENTION`(DESIGN §7.2).
- **후속 견고화(post-merge 리뷰)** — 리포트↔스크린샷 `run_id` 공유(보관 실행의
  스크린샷 유실 방지), CLI 병렬: 시그널사 error 매핑·`--timeout` 워치독·부모 1회
  정리·인터럽트 시 자식 kill, 시나리오 예외 격리, JUnit 제어문자 sanitize,
  `run_scenario` scrub 레지스트리 정리, `register_all` 멱등.

**DoD** — ✅ pytest green(CDP/persistent/bootstrap 실패/동시성/CLI 경로 포함),
tools 20, 서버 부팅·`doctor` 정상, GitHub Actions CI(유닛+브라우저 레인) green.

---

## Phase 7 — 확장 도구·배포 (2026-07, PR #15) ✅ 완료

qa-autopilot(playwright-cli) 사례 분석에서 이식한 실무 패턴 + 배포 파이프라인.

- **로그인 상태 재사용** — `save_state`/`load_state`/`list_states`: 쿠키+localStorage를
  파일(0600)로 저장·시드. 영구 프로필과 달리 headless/CI 동작, 역할 전환은 state 스왑.
- **네트워크 모킹** — `mock_route`/`unmock_route`: 글롭 요청을 로컬 fulfill로 결정화,
  `status=500`+`expect_status`로 에러 페이지 오프라인 검증. 컨텍스트 수명.
- **실패 증거 강화** — `--trace-on-failure`/`run_scenario(trace_on_failure=)`:
  실패한 실행만 trace.zip 보존(run_id 공유로 리테인션 연동).
- **프롬프트 강화** — 증상→도구 선택 매트릭스 내장, `/ui-sync`(저장 시나리오 변경 감지).
- **배포** — PyPI `ui-blackbox-mcp` 게시(✅ v0.1.0 라이브): `uvx ui-blackbox-mcp` /
  `pip install ui-blackbox-mcp` 원라인 설치. `release.yml`(trusted publishing,
  빌드→twine check→휠 부팅 검증→OIDC 게시), 절차는 `RELEASING.md`.

**DoD** — ✅ 테스트 160+ green, tools 25·prompts 5, mypy 차단 게이트 clean,
실PyPI 설치→`doctor` OK 실측.

---

## 미결·리스크

| ID | 내용 | 해소 시점 |
|---|---|---|
| **Q1** | 대형 SPA aria_snapshot이 MCP 컨텍스트 한도 초과 가능 → 트리밍 수치 | Phase 1 실측 |
| R1 | 환경별 Chromium 설치 — CDN 차단 시 다운로드 불가 | ✅ 해소: `CHROMIUM_EXECUTABLE`/사전설치(`/opt/pw-browsers`) `executable_path` 사용 (T1.1) |
| R2 | sampling 미지원 환경에서 generate_scenario UX | Phase 5 (fallback 설계 반영됨) |
| R3 | 브라우저 크래시 자동 재시작 < 5s (NFR) 실측 | ✅ 해소: `is_alive()`+`restart()` 모드보존, `test_recovery`·`test_modes`로 고정 |

## Phase 8 — 리포트 실무화 (2026-07) ✅ 완료

PM/개발/기획/QA/디자이너 관점 리포트 격차 분석에서 나온 우선순위 P1~P5.

- **P1 미실행 스텝**: 조기 중단 시 남은 스텝을 `skipped`로 기록(소실 방지),
  summary에 `skipped`(failed 미포함, pass_rate는 실행분 기준), JUnit `<skipped/>`.
- **P2 리포트 정체성**: meta `target_url`(raw url — 스키마-코드 불일치 해소)·
  `viewport`·`browser_version`(실엔진 빌드), 스텝별 `page_url`(scrub 경유).
- **P3 트렌드**: history에 최근 10회 요약 축적 → `trend.recent`+연속 실패 횟수,
  MD/HTML에 추이 표기.
- **P4 태그/우선순위**: 스텝 `tag`/`priority` passthrough — JUnit 이름·실패 상세 노출.
- **P5 flaky 재시도**: 스텝 `retry: N`(250ms 백오프) — 재시도 후 통과는 ⚠flaky 마킹.

**보류(P6, 별도 마일스톤)** — **시각적 회귀**(baseline 스크린샷 diff): 이미지 비교
의존성·baseline 관리 UX 설계가 필요해 단독 페이즈로 분리. 뷰포트 매트릭스·a11y
확장(대비/터치 타겟)도 함께 검토.

## 범위 외 (PRD Out of Scope)
자동 테스트 탐색(`discover_tests`) · API/백엔드 테스트 · 퍼포먼스/로드 테스트 —
본 버전 제외(1.0 이후 검토).
> **CI/CD 통합**은 PRD 원안에서 범위 외였으나, Phase 6에서 대화형 산출물을 재사용하는
> **CLI 러너(`ui-blackbox run`, exit code+JUnit)**로 편입했다(서버 본체 무변경).
> 진정한 멀티세션 병렬(대화별 격리 브라우저)은 여전히 프로세스 분리로 커버.

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
