# UI Blackbox Tester MCP — 설계 문서 (DESIGN)

> PRD `UI Blackbox MCP v0.6` 기반 구현 설계 + 확장(리포트 강화 SM-04~09).
> 스택: **Python 3.11+ · Playwright(Chromium, async API, ≥1.60) · MCP 공식 SDK(FastMCP) · stdio · Claude Desktop**
> 범위: Phase 0~5 전체 (MUST/SHOULD/COULD 포함). 마일스톤 상태는 ROADMAP 참조.

---

## 1. 목표 요약

Claude Desktop에 브라우저 조작 능력을 부여하여, 자연어 지시만으로 UI를
블랙박스 방식으로 검증하는 MCP 서버. 테스트 코드 없이 Claude가 직접 브라우저를
열고 클릭·입력·검증하고 결과를 리포트로 남긴다.

설계 원칙(PRD NFR Maintainability 반영):
- **Tool 추가 = 파일 1개 추가.** `server.py`는 수정하지 않는다.
- 관심사 분리: `browser/`(브라우저 제어), `testing/`(시나리오·리포트), `tools/`(MCP 노출).
- 모든 외부 영향(파일 쓰기, 네트워크 접근)은 명시적이고 로컬에 한정.

---

## 2. 프로젝트 구조

```
blackbox_mcp/
  __init__.py
  server.py              # FastMCP 인스턴스 생성 + ensure_chromium() + tool 모듈 import
  cli.py                # CI 진입점: `ui-blackbox run/doctor` (MCP 없이 runner/report 직접 호출)
  config.py             # 환경변수 로딩 (HEADLESS, REPORT_DIR, SCENARIO_DIR, REPORT_RETENTION, BROWSER 등)
  bootstrap.py          # ensure_chromium() (D1)

  browser/
    __init__.py
    session.py          # BrowserSession 싱글톤 (BR-01·03·04, 크래시 재시작,
                        #   CDP/persistent/stealth 브라우저 모드 — §3.7)
    listeners.py        # 콘솔/네트워크 버퍼 부착 (BR-02)
    locator.py          # 셀렉터 fallback 체인 해석 (D2: data-testid → role → text → css)

  testing/
    __init__.py
    runner.py           # run_scenario 실행 엔진 (SM-01·02) + _meta·_a11y_audit
    report.py           # 리포트 생성/저장 JSON·MD·HTML + 회귀 (SM-03~09, D3)
    recorder.py         # MCP 호출 액션 자동 기록 → save_report 원천
    library.py          # 시나리오 저장/로드/목록 (SL-02~04)
    secrets.py          # 자격증명 마스킹

  tools/
    __init__.py         # registry: 데코레이터로 등록된 tool 자동 수집
    _registry.py        # @tool/@prompt 데코레이터 + register_all(recorder 래핑)
    _prompts.py         # MCP 프롬프트(슬래시 명령): ui-test/ui-scenario/ui-login/ui-generate
    navigate.py · snapshot.py · screenshot.py · interact.py · assertion.py(assert_)
    console.py · network.py · wait.py · frame.py(switch_frame) · dialog.py(expect_dialog)
    session.py(reset_session) · realbrowser.py(use_real_browser)
    scenario.py(run_scenario) · savereport.py(save_report)
    generate.py(generate_scenario) · library.py(save/load/list_scenario)
    status.py(status)      # 읽기 전용 상태 프로브(버전·모드·생존·버퍼·설정)

# 출력 경로(절대, 기본 ~/ui-blackbox/ — MCP cwd가 불가측·쓰기불가일 수 있어 홈 기준):
~/ui-blackbox/scenarios/   # 저장 시나리오 (SCENARIO_DIR 재정의)
~/ui-blackbox/reports/     # 리포트 출력 (REPORT_DIR 재정의, 쓰기 실패 시 홈 폴백, REPORT_RETENTION개 유지)
~/ui-blackbox/chrome-profile/  # use_real_browser 영구 프로필(로그인 유지)

pyproject.toml
README.md
DESIGN.md
.env.example
claude_desktop_config.example.json
tests/                  # pytest 단위 테스트
```

### Tool 레지스트리 패턴 (NFR: Tool 추가 = 파일 1개)

`tools/_registry.py`:
```python
_PENDING = []                      # (fn, name, description) 누적

def tool(name=None, description=None):
    def deco(fn):
        _PENDING.append((fn, name or fn.__name__, description))
        return fn
    return deco

def register_all(mcp):             # server.py에서 1회 호출
    for fn, name, desc in _PENDING:
        mcp.tool(name=name, description=desc)(fn)
```

`tools/__init__.py`는 모든 tool 모듈을 import → 데코레이터가 `_PENDING`에
누적 → `server.py`가 `register_all(mcp)` 호출. **새 Tool은 파일 추가 +
`tools/__init__.py`에 import 한 줄**로 끝난다. (server.py 불변)

---

## 3. 브라우저 세션 설계

### 3.1 BrowserSession 싱글톤 (BR-01)
- 모듈 전역 단일 인스턴스. `get_session()` 접근자로 lazy 초기화.
- 프로세스 생존 동안 동일 `BrowserContext` 유지 → 쿠키·세션·로컬스토리지 보존.
- 구성: `playwright` → `chromium.launch()` → `browser.new_context()` → `context.new_page()`.
- 동시 세션 1개 (제약). 병렬 미지원.
- **동시 호출 안전(2026-07 감사 반영):** `get_session()`은 모듈 `asyncio.Lock`으로
  직렬화 — 동시 tool 호출이 이중 기동/이중 restart를 일으키지 않는다. 싱글톤은
  `start()` 성공 후에만 공개되고, 실패 시 반쯤 뜬 드라이버를 정리한다.
  `reset`/`switch_to_persistent`/`restart`는 인스턴스 락(`_op_lock`)으로 직렬화
  (본체는 `_impl`로 분리해 재진입 데드락 회피). `close()`는 브라우저가 이미 죽어
  close가 raise해도 Playwright 드라이버를 반드시 stop한다(고아 프로세스 방지).
- **시작/정리는 FastMCP `lifespan`으로 관리(공식 권장):** `@asynccontextmanager`
  로 서버 기동 시 세션을 준비하고 `finally`에서 `close()`로 브라우저를 정리한다.
  지연 초기화(`get_session()`)와 병행하되, 종료 시 리소스 릭이 없도록 lifespan
  `finally`에서 반드시 닫는다. (Phase 1에서 lifespan 배선.)

### 3.2 헤드리스 토글 (BR-03)
- 기본 `headless=True`. `HEADLESS=false`(env)면 `headless=False`.
- 브라우저 엔진은 `BROWSER`(env, 기본 `chromium`) — firefox/webkit 허용하되 기본·검증 대상은 chromium.

### 3.3 리스너 버퍼 (BR-02)
`navigate` 시점(또는 page 생성 시) page에 부착:
- `page.on("console", ...)` → `console_buffer` 누적 `{level, text, location, ts}`
- `page.on("response", ...)` → **status ≥ 400이면** `network_buffer`에 `{url, status, method}`
- `page.on("requestfailed", ...)` → `network_buffer`에 `{url, failure, method}`
- 버퍼는 세션에 보관, `reset_session`·`navigate`(옵션) 시 클리어 정책은 아래.

> **검증(공식):** HTTP 4xx/5xx는 Playwright상 "성공한 응답"이라 `requestfailed`가
> 아니라 `response` 이벤트로 전달된다. 따라서 4xx/5xx는 반드시 `response`의
> `status >= 400`으로 판별하고, `requestfailed`는 네트워크 자체 실패(타임아웃·
> DNS 등)에만 사용한다. (CT-07 구현이 두 경로를 모두 수집한다.)

> **버퍼 클리어 정책(결정 필요 사항 아님, 기본 채택):** `navigate`는 버퍼를
> 비우지 않고 누적한다. 명시적 초기화는 `reset_session()`. 이유: 한 시나리오가
> 여러 navigate를 거칠 때 콘솔/네트워크 에러를 끝까지 모아 리포트하기 위함.
> **상한(2026-07):** 버퍼당 최근 1000건 캡(`_MAX_EVENTS`, 최신 유지) — 폴링 많은
> SPA의 장시간 세션에서 메모리·MCP 페이로드가 무한 성장하지 않는다.

### 3.4 reset_session (BR-04)
현재 context 종료 → 새 context + page 생성 → 콘솔/네트워크 버퍼 초기화 →
프레임 컨텍스트 메인으로 복귀. 시나리오 시작 전 호출 권장.

### 3.5 크래시 자동 재시작 (NFR Reliability, < 5s)
- 모든 tool 호출은 `BrowserSession.page` 접근 시 살아있는지 확인.
- Playwright 예외(`TargetClosedError` 등) 감지 시 `restart()`:
  context/browser 정리 → 재기동 → 진행 중 시나리오 스텝은 `error`로 마킹.
- 재시작 후 다음 tool 호출 정상 수신.
- **현황:** `BrowserSession.restart()`는 구현되어 있으나, tool 호출부에서
  라이브니스 체크 → `restart()` 자동 호출하는 **래퍼는 미배선**이다. Phase 2에서
  공통 tool 래퍼(예외 캡처 → 1회 재시작 후 재시도)로 배선한다.

### 3.6 프레임 컨텍스트 (CT-09)
- 세션에 `current_frame` 보관(기본 None=메인 page).
- `switch_frame(selector)` → `page.frame_locator(selector)` 기준으로 이후 동작.
- `switch_frame(null/None)` → 메인 복귀.
- actions/assertions는 `current_frame` 또는 page를 대상 root로 사용.
- **검증(공식):** `FrameLocator`는 `get_by_role` / `get_by_text` /
  `get_by_test_id` / `locator`를 모두 노출하므로, root가 frame_locator일 때도
  §4 셀렉터 체인과 모든 tool이 동일하게 동작한다(코드 변경 불필요).

### 3.7 브라우저 모드 (PRD 외 확장)
세션은 4가지 모드로 기동·전환된다. `is_alive()`(browser.is_connected)로 생존을 확인하고,
죽으면 `get_session()`이 `restart()`로 복구하되 **모드를 보존**한다.

| 모드 | 트리거 | 동작 | 종료 시 |
|---|---|---|---|
| 번들(기본) | 기본값 | bundled Chromium launch + new_context | 브라우저 닫음 |
| 채널/스텔스 | `BROWSER_CHANNEL`·`STEALTH` | 실제 Chrome/Edge 채널, AutomationControlled off·UA·webdriver 숨김 | 브라우저 닫음 |
| 영구 프로필 | `use_real_browser` tool | `launch_persistent_context`(실제 Chrome, 프로필 유지) — **idempotent**(살아있으면 재사용) | context만 닫음·프로필 유지 |
| CDP attach | `BROWSER_CDP` | `connect_over_cdp`로 사용자 브라우저에 attach(기존 context/page 재사용) | **detach만**·사용자 브라우저 유지 |

- 영구/ CDP 모드에서 `reset_session`은 로그인 보존을 위해 **버퍼만** 비운다.
- CDP 연결 실패(스테일 포트) 시 경고 후 번들 launch로 폴백(세션 안 막힘).
- **팝업/새 탭 자동 추적:** `context.on("page")`로 새 페이지를 활성 페이지로 채택
  (target=_blank·window.open·OAuth 팝업), 닫히면 남은 페이지로 복귀.
- **실 사이트 견고화:** navigate는 `networkidle` 미도달 시 `NAV_TIMEOUT_MS` 초과하면
  현재 상태로 진행(`settled:false`). `IGNORE_HTTPS_ERRORS`로 스테이징 인증서 수용.
- 검증: §13 connect_over_cdp / launch_persistent_context 실측.

---

## 4. 셀렉터 전략 (D2) — `browser/locator.py`

`interact`/`assert_`의 `selector`/`target`은 단순 CSS가 아니라 **fallback 체인**으로 해석:

우선순위:
1. `data-testid` — 입력이 `testid=foo` 또는 `[data-testid="foo"]` 형태
2. **role + accessible name** — `role=button name=로그인` → `get_by_role`
3. **가시 텍스트** — `text=로그인` → `get_by_text`
4. **CSS** — 최후 수단, 명시적으로 CSS로 보일 때만

해석 규칙 (구현 반영):
- 접두사 명시(`testid=`, `role=`, `text=`, `css=`)가 있으면 그 방식으로 단일 해석.
- 접두사 없는 **CSS형 문자열**은 CSS로 해석하되, **명확한 구조 신호에서만**
  판단한다(2026-07 수정): `#`·`[`·`]`·`>` 또는 **선행 `.`**(`. btn`). 중간 점이 있는
  단어(`example.com`, `v1.2`)는 **가시 텍스트로 취급** — 과거엔 이런 텍스트가 CSS로
  둔갑해 실사이트에서 오타겟팅됐다. 공백 가드는 유지.
- 접두사 없는 **평문**은 **D2 전체 순서**로 실제 fallback(2026-07 수정: role 티어 복원):
  `[data-testid="s"]` → **role+name**(흔한 인터랙티브 role을 접근성 이름 `s`로 시도:
  button/link/textbox/checkbox/… ) → 가시 텍스트, **count>0 인 첫 전략** 채택(없으면
  텍스트로 귀결해 에러가 자연스럽게). 과거엔 role 티어(D2 우선순위 2위)를 건너뛰었다.
- 액션 timeout은 `CONFIG.selector_timeout_ms`(기본 2000) 적용 → 없는 요소에서
  30초 대기 없이 빠르게 실패.

API:
- `async resolve(root, selector) -> (Locator, resolved_by)` — 위 체인. `resolved_by`
  ∈ {testid, role, text, css}는 **SM-06 리포트 셀렉터 투명성**의 원천. `interact`가 사용.
- `locate(root, selector) -> Locator` — 동기 단일 해석(체인 불필요한 곳에서 사용).
- `interact` 실패는 예외 대신 `{ok:False, resolved_by, error}` 구조화 반환,
  값(value)은 `detail`에서 마스킹.

---

## 5. MCP Tools 명세

> 공통: FastMCP `@mcp.tool()`로 노출. 반환은 구조화 dict(또는 텍스트), screenshot만
> `mcp.server.fastmcp.Image`로 반환(`return Image(data=..., format="png")`).
> 입력 검증은 타입힌트 + Pydantic(FastMCP 자동).
> 모든 tool은 클라이언트가 설정한 요청 타임아웃 내 반환해야 하며(제약), 장기작업은
> 분할한다. ※ MCP는 고정 타임아웃을 강제하지 않는다 — 클라이언트가 정하는 값이다.
> 반환 dict/list에 구체 타입힌트를 주면 FastMCP가 `outputSchema`(구조화 출력)를
> 자동 생성한다.

### 5.1 브라우저 세션 (BR)
| Tool | 시그니처 | 반환 | 우선순위 |
|---|---|---|---|
| `reset_session` | `reset_session()` | `{ok, message}` | SHOULD |
| `use_real_browser` | `use_real_browser(headless=False, channel="chrome")` | `{ok, mode, browser, profile}` | 확장 |
| `status` | `status()` | `{version, config, session:{mode,alive,url,버퍼}}` | 확장(관측) |

> **status (관측성):** 세션을 **새로 만들지 않는** 읽기 전용 프로브(`_SESSION`을 직접
> 조회). 버전·모드(번들/채널/persistent/CDP)·생존·현재 URL·버퍼 크기·유효 설정을
> 반환해, 사용자 환경 디버깅을 Claude Desktop 로그 없이 대화에서 끝낸다.

### 5.2 코어 (CT)
| Tool | 시그니처 | 반환 | 우선순위 |
|---|---|---|---|
| `navigate` | `navigate(url, wait_until="networkidle")` | `{title, url, status}` | MUST |
| `snapshot` | `snapshot(mode="a11y")` | 텍스트(a11y 트리 or 간략 DOM) | MUST |
| `screenshot` | `screenshot(full_page=False)` | image content | MUST |
| `interact` | `interact(action, selector, value=None)` | `{ok, action, selector, detail}` | MUST |
| `assert_` | `assert_(kind, target, expected=None)` | `{passed, kind, target, expected, actual}` | MUST |
| `get_console_logs` | `get_console_logs(level="all")` | `[{level,text,location,ts}]` | MUST |
| `get_network_errors` | `get_network_errors()` | `[{url,status/failure,method}]` | MUST |
| `wait` | `wait(ms=None, selector=None)` | `{ok, waited}` | SHOULD |
| `switch_frame` | `switch_frame(selector=None)` | `{ok, context}` | SHOULD |
| `expect_dialog` | `expect_dialog(action, expected_text=None)` | `{passed, dialog_type, message}` | SHOULD |

세부:
- **navigate (CT-01):** `wait_until` ∈ {load, domcontentloaded, networkidle, commit}.
  리스너 미부착이면 부착. status는 main response status.
  > **판정(2026-07 QA 리뷰 반영):** 시나리오 스텝에서 navigate의 통과 여부는
  > **상태코드 기반**이다 — `status >= 400`이면 **실패**(과거엔 무조건 통과라 500/404가
  > green이 되는 신뢰 구멍이었다). `status is None`(file:// 또는 settle 타임아웃으로
  > response 객체 없음)은 도달로 간주해 통과. 스텝에 `expect_status: <int>`를 주면
  > 그 코드와 정확히 일치할 때만 통과(에러 페이지를 의도적으로 검증하는 용도).
- **snapshot (CT-02):** `a11y`=**`page.locator("body").aria_snapshot()`** 의
  YAML 트리(권장 API). `page.accessibility.snapshot()`는 deprecated이므로
  사용하지 않는다. `dom`=태그/role/text 위주 간략 트리. **Q1 트리밍은 §8 참조.**
  > 검증: Playwright 공식 문서 기준 `accessibility.snapshot()` deprecated,
  > `locator.aria_snapshot()` / `expect().to_match_aria_snapshot()` 권장.
- **interact (CT-04):** action ∈ {click, type, hover, select, press}.
  `type`/`select`/`press`는 value 사용. 셀렉터는 §4 체인.
- **assert_ (CT-05):** kind ∈ {text_visible, element_visible, url_is,
  url_contains, count}. count는 expected=숫자와 일치 검사.
- **wait (CT-08):** ms 주어지면 고정 대기, selector 주어지면 등장/텍스트 변경 대기.
- **expect_dialog (CT-10):** `page.on("dialog", ...)`로 핸들러를 arm 하거나
  `page.expect_event("dialog")` 컨텍스트로 대기 → `dialog.message()`로 텍스트
  검증, `dialog.type()`로 종류 확인, `action`에 따라 `dialog.accept(prompt_text)`
  / `dialog.dismiss()` 호출. 미노출(timeout) 시 `passed=False`. dialog는 반드시
  accept/dismiss 처리하지 않으면 페이지가 멈추므로 핸들러에서 항상 처리.
  (action 트리거 전에 arm 하는 사용 패턴을 README에 명시.)

### 5.3 시나리오 모드 (SM)
| Tool | 시그니처 | 우선순위 |
|---|---|---|
| `run_scenario` | `run_scenario(steps, name, description, continue_on_fail=False, save_report=True, report_format="both", screenshot_each=False)` | MUST |
| `save_report` | `save_report(name="session", description="", report_format="all")` | 확장 |

> **save_report (확장):** run_scenario 없이 임의 도구 호출만으로 진행한 흐름도 리포트로
> 끝낼 수 있게 한다. MCP로 호출되는 액션 도구는 `testing/recorder.py`가 자동 기록(§6.1
> 스텝)하며, `save_report`가 그 기록을 JSON/MD/HTML로 저장 후 초기화한다. 슬래시 명령
> `/ui-test`·`/ui-login`이 마지막에 이를 호출하도록 지시한다. 내부적으로 runner는 raw
> 함수를 호출(레지스트리 래핑 대상 아님)하므로 run_scenario는 이중 기록되지 않는다.

- `steps`: JSON 배열, 각 스텝 `{action, ...args}`. action은 위 코어 tool 이름과 동일 어휘.
- 각 스텝 결과 필드의 정식 정의는 **§6.1 리포트 스키마**를 따른다(`screenshot`·
  `resolved_by`·`console_errors`/`network_errors`·`ai_reason`·`severity` 등).
- 실패 시 자동 스크린샷 캡처(SM-02) → 리포트 첨부.
- `continue_on_fail=False`면 첫 실패에서 중단.
- 종료 후 리포트 저장(SM-03) — §6.
- **지원 스텝 action**: `navigate` · `interact` · `assert` · `snapshot` · `wait` ·
  `switch_frame` · `reset_session` · `screenshot` · `expect_dialog`. (runner 디스패치)
- **SM-04 (SHOULD):** `report_format`에 `html`/`all`을 지원해 단일 self-contained
  HTML 리포트(스텝 표 + 스크린샷 인라인 + 콘솔/네트워크 에러)를 추가 생성한다.
  비개발 페르소나(US-03) 가독성 향상. 외부 의존성 없이 CSS 인라인(NFR 로컬 전용).
  Phase 3에서 마크다운 렌더러와 함께 구현.

#### 리포트 강화 요구사항 (SM-05 ~ SM-09)
포트폴리오/실무 가치를 위한 리포트 확장. 우선순위순으로 정리하며 Phase 3에서
SM-01~04와 함께(또는 직후) 구현한다.

| ID | 항목 | 내용 | 우선순위 |
|---|---|---|---|
| **SM-05** | **AI 판단 근거 + 수정 제안** | 각 스텝/실패에 Claude의 판단 사유(`ai_reason`)와 실패 시 가설·수정 제안(`ai_suggestion`)을 기록. 블랙박스 AI 검증의 핵심 차별점(공식 playwright-mcp 대비). | SHOULD |
| **SM-06** | **스텝 캡처 + 셀렉터 투명성 + 에러 귀속** | 스텝마다 캡처(통과/실패 모두), D2 체인 중 **실제 매칭된 셀렉터 전략**(`resolved_by`) 기록, 콘솔/네트워크 에러를 전역이 아닌 **스텝 구간에 귀속**. | SHOULD |
| **SM-07** | **회귀 비교(이전 실행 대비)** | 같은 시나리오의 직전 실행 결과와 diff("어제 통과 → 오늘 실패"). 시나리오 라이브러리의 최종 실행 메타와 연동. | COULD |
| **SM-08** | **환경 메타 + 심각도 분류** | OS·Python·**Playwright/브라우저 버전**·뷰포트·타임스탬프 헤더. 실패를 assertion/JS에러/네트워크/타임아웃으로 분류·색상. | SHOULD |
| **SM-09** | **a11y 발견사항** | `aria_snapshot` 부산물로 role/label 누락 등 접근성 이슈를 부수 리포트. | COULD |

> 범위 관리: SM-05~09는 PRD v0.6 이후 추가되는 **신규 항목**이다. SM-02/03/04는
> 기존 PRD 범위. 구현은 Phase 3에서 우선순위(SM-05·06·08 → 07·09)대로 진행.

### 5.4 시나리오 스텝 스키마
```json
{
  "name": "로그인 흐름",
  "steps": [
    {"action": "navigate", "url": "https://example.com/login"},
    {"action": "interact", "type": "type", "selector": "testid=email", "value": "u@x.com"},
    {"action": "interact", "type": "type", "selector": "testid=password", "value": "${PASSWORD}"},
    {"action": "interact", "type": "click", "selector": "role=button name=로그인"},
    {"action": "assert", "kind": "url_contains", "target": "/dashboard"},
    {"action": "assert", "kind": "text_visible", "target": "환영합니다"}
  ]
}
```
- `${ENV_VAR}` 치환: 자격증명은 env/.env에서 주입, 리포트엔 마스킹(제약).

### 5.5 라이브러리 (SL)
| Tool | 시그니처 | 우선순위 |
|---|---|---|
| `generate_scenario` | `generate_scenario(description, url)` | SHOULD |
| `save_scenario` | `save_scenario(name, steps, overwrite=False)` | SHOULD |
| `load_scenario` | `load_scenario(name)` | SHOULD |
| `list_scenarios` | `list_scenarios()` | COULD |

- **generate_scenario (SL-01):** 이 tool은 navigate→snapshot으로 페이지 구조를
  반환하고, **실제 JSON 스텝 생성은 Claude(LLM)가 수행**하도록 설계.
  즉 tool은 "페이지 구조 + 셀렉터 후보 + 작성 가이드"를 돌려주고, Claude가
  description과 결합해 steps를 만든 뒤 `save_scenario`로 저장하는 흐름.
  (MCP 서버 자체에 LLM이 없으므로 분업. README에 흐름 명시.)
- **sampling fallback(공식 API):** sampling을 지원하는 클라이언트에서는 tool에
  `ctx: Context`를 주입받아 `await ctx.session.create_message(messages=[...],
  max_tokens=...)`로 서버측에서 steps를 직접 생성할 수 있다. **Claude Desktop은
  sampling 미지원**이므로 이 경로는 옵션이며, 미지원 시 위의 "작성 키트" 반환으로
  graceful fallback 한다.
- 저장: `scenarios/{name}.json`, 동일 이름이면 overwrite 확인.
- `list_scenarios`: 이름·스텝 수·최종 실행 일시(메타 파일 또는 mtime).

---

## 6. 리포트 (testing/report.py, D3 / SM-03~09)

- 기본 경로 **`~/ui-blackbox/reports`(홈 기준 절대경로)**, `REPORT_DIR` env로 재정의, 없으면 자동 생성.
  > cwd 상대(`./reports`)는 MCP 서버 cwd가 예측 불가·쓰기 불가(system32 등)일 수 있어 폐기. 쓰기 실패 시 홈으로 폴백.
- 파일명 `report_YYYYMMDD_HHMMSS.json` / `.md` / `.html`.
- `formats` ∈ {json, md, html, both(json+md), all(json+md+html)}.
- 스크린샷은 `reports/screenshots/`에 저장하고 md/json은 상대경로 참조,
  HTML은 base64 data URI로 임베드(단일 파일 이식성).

### 6.1 리포트 데이터 스키마 (JSON)
```jsonc
{
  "name": "로그인 흐름",
  "description": "이메일/비번 입력 후 대시보드 진입 검증",   // 자연어(②)
  "meta": {                                              // SM-08
    "started_at": "2026-06-24T10:00:00",
    "duration_ms": 4210,
    "target_url": "https://example.com/login",
    "os": "Linux", "python": "3.11.x",
    "playwright": "1.60.x", "browser": "chromium 1.60.x",
    "headless": true, "viewport": "1280x720",
    "credentials_masked": true                           // 보안 배지
  },
  "summary": { "total": 6, "passed": 5, "failed": 1, "pass_rate": 0.83 },
  "steps": [
    {
      "step": 4,
      "action": "interact", "raw": { "type": "click", "selector": "role=button name=로그인" },
      "selector_input": "role=button name=로그인",
      "resolved_by": "role",            // SM-06: D2 체인 중 실제 매칭 전략
      "expected": "클릭 성공", "actual": "클릭됨",
      "passed": true,
      "duration_ms": 320,
      "screenshot": "screenshots/step04.png",   // SM-06: 통과/실패 모두
      "console_errors": [], "network_errors": [], // SM-06: 스텝 구간 귀속
      "severity": null,                  // SM-08: assertion|js_error|network|timeout
      "ai_reason": "버튼이 보이고 활성 상태여서 클릭 성공으로 판단",  // SM-05
      "ai_suggestion": null              // SM-05: 실패 시 가설/수정 제안
    }
  ],
  "a11y_findings": [],                   // SM-09: role/label 누락 등
  "regression": {                        // SM-07: 직전 실행 대비
    "previous_run": "2026-06-23T18:00:00",
    "changed": [{ "step": 4, "from": "passed", "to": "failed" }]
  }
}
```
> **회귀 baseline 가드(2026-07):** 직전 실행과 `(step, action)` 키가 하나도 겹치지
> 않으면(이름만 공유한 무관한 흐름 — ad-hoc 리포트는 기본 이름이 "session") 비교를
> 건너뛰고 이번 실행을 새 baseline으로 기록한다. 가짜 "absent" diff 방지.
> 스텝 번호는 recorder의 **단조 카운터**라 캡(1000) 초과 후에도 키가 충돌하지 않고,
> 스크린샷 파일명에는 실행별 타임스탬프 태그가 붙어 재실행이 이전 이미지를
> 덮어쓰지 않는다.

### 6.2 출력별 표현
- **JSON**: 위 스키마 그대로(기계 판독·CI 연계용).
- **Markdown**: 헤더 요약 + 스텝 표(셀렉터/판단근거 포함) + 실패 상세 + 콘솔/네트워크 + a11y 섹션.
- **HTML(SM-04)**: 단일 self-contained `.html` — 통과율 헤더, 스텝 카드(캡처 인라인),
  실패 강조·심각도 색상, AI 판단근거·수정제안, 회귀 diff, 환경 메타 푸터.
  CSS 인라인, 스크린샷 base64, 외부 의존성/네트워크 없음.

### 6.3 단계적 구현
- 1차(Phase 3): meta(SM-08) · 스텝 캡처/셀렉터/에러귀속(SM-06) · AI 근거/제안(SM-05) · JSON/MD/HTML.
- 2차: 회귀 비교(SM-07) · a11y 발견(SM-09).

---

## 7. 부트스트랩 & 설치 (D1 / NFR Usability)

- `bootstrap.ensure_chromium()`: Chromium 존재 확인(`playwright`의 설치 경로 점검),
  없으면 `subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"])`.
  이미 있으면 즉시 통과. `server.py`의 `main()`에서 `mcp.run()` **이전에** 1회 호출.
  > **확인 필요(Phase 1):** 설치 경로 점검에 쓰는 `browser_type.executable_path`는
  > Playwright 버전에 따라 property/메서드 표기가 다를 수 있고, 반환값은 "설치
  > 여부"가 아니라 "기대 경로"다 → `os.path.exists()`로 실제 존재를 확인한다.
  > 설치된 버전 시그니처는 구현 시 코드로 재확인.
- 설치: `pip install`(또는 `pip install -e .`) 1단계. 별도 명령 불필요.
- **사전 제공 브라우저(`CHROMIUM_EXECUTABLE`):** 브라우저 CDN(`cdn.playwright.dev`)이
  네트워크 정책으로 차단된 환경(예: Claude Code web)에서는 다운로드가 불가하다.
  이때 `CONFIG.chromium_executable`(env `CHROMIUM_EXECUTABLE`, 미설정 시
  `/opt/pw-browsers/chromium` 자동 감지)을 세션 `launch(executable_path=...)`에
  전달해 사전 설치 바이너리를 사용한다. `ensure_chromium()`은 이 경로가 있으면
  다운로드를 건너뛰고, 다운로드 시도가 실패해도 크래시 없이 경고만 남긴다.
  설치 서브프로세스의 stdout/stderr는 `DEVNULL` — stdout은 MCP JSON-RPC 파이프라
  진행률 출력이 프로토콜을 오염시키면 안 된다(§14).
  > 검증(2026-06): preinstalled chromium **build 1194** + Playwright **1.60** 드라이버를
  > `executable_path`로 런치 → `aria_snapshot` 포함 정상 동작 확인(빌드 버전 불일치
  > 무방). R1 해소.
- Claude Desktop 등록: config 한 줄 (`claude_desktop_config.example.json` 제공).
```json
{
  "mcpServers": {
    "ui-blackbox": { "command": "python", "args": ["-m", "blackbox_mcp.server"] }
  }
}
```

### 7.1 CLI / CI 진입점 (`blackbox_mcp/cli.py`, `ui-blackbox` 스크립트)

대화형 MCP 흐름과 **동일한 runner/report 엔진**을 MCP 없이 직접 호출하는 두 번째
진입점. 서버 코드는 무변경 — runner/report가 tool 함수와 분리된 모듈 함수라 재사용만
한다. stdout이 MCP 파이프가 아니므로 진행 로그 출력이 자유롭다.

- `ui-blackbox run <시나리오명 | steps.json> ...` — 라이브러리 시나리오 또는 스텝
  파일을 실행, 리포트 저장. **exit code**: `0`(전부 통과) / `1`(스텝 실패) /
  `2`(사용법·인프라 오류) → CI 게이팅.
- `--junit PATH` — 시나리오당 `testsuite`, 스텝당 `testcase`의 **JUnit XML**(GitHub
  Actions/Jenkins 네이티브 파싱). `--continue-on-fail`, `--screenshot-each`, `--format`.
- `--parallel N` — 시나리오당 **서브프로세스 1개**로 격리 실행(각자 자기 세션 싱글톤을
  가지므로 공유 상태 리팩토링 불필요). 동시성은 N으로 제한. **견고화(2026-07 리뷰):**
  자식은 `REPORT_RETENTION=0`으로 돌고 부모가 종료 후 1회 정리(형제 간 리포트 삭제
  경쟁 제거), `--timeout SEC`(기본 600) 워치독으로 멈춘 자식은 kill 후 error 처리,
  시그널사(음수 rc, OOM=-9 등)는 **성공 아닌 error**로 매핑, KeyboardInterrupt 시
  자식 서브프로세스를 kill(브라우저 고아 방지). `--junit`은 순차 실행 전용.
- 시나리오 하나가 예외로 죽어도(브라우저 기동 실패·디스크 풀 등) 합성 error 결과로
  기록하고 스위트를 계속 — 완료 결과·JUnit이 유실되지 않는다.
- `ui-blackbox doctor` — 브라우저 해석 가능 여부·출력 디렉토리 쓰기 가능·유효 설정
  자가진단(설치 문제 셀프서비스 디버깅).

### 7.2 리포트 보존 (REPORT_RETENTION)

`REPORT_DIR`이 무한 성장하지 않도록, `save()` 성공 직후 최신 N개(`REPORT_RETENTION`,
기본 100, 0=무제한) 실행을 남기고 초과분을 삭제한다. **한 실행의 리포트 파일과
스크린샷은 동일 `run_id`를 공유**(`report.new_run_id()` → `result["run_id"]` → 리포트
파일명·스크린샷 태그에 동일 사용)하므로, 정리는 두 파일군을 run_id로 상관시켜
**보관하는 실행은 스크린샷도 함께 보관**한다. run_id는 마이크로초까지 포함해 병렬
실행이 같은 초에 겹쳐도 유일하다. 정리 실패는 try/except로 격리 — 방금 성공한
저장을 절대 깨지 않는다.
> 이전 구현은 스크린샷 스탬프(시나리오 시작)와 리포트 스탬프(저장 시점)가 달라
> `REPORT_RETENTION=1`이 방금 저장한 리포트의 스크린샷을 지웠다(2026-07 수정).

---

## 8. Q1 — snapshot 출력 크기 정책 (Phase 1 실측 반영, 메커니즘 확정)

대형 SPA aria_snapshot(YAML) 출력이 MCP 컨텍스트 한도를 초과할 수 있음.

**실측 (Playwright 1.60, 합성 DOM 30 섹션 기준):**
| 호출 | 결과 |
|---|---|
| `aria_snapshot()` (기본) | 2317 chars / 121 lines — 이미 간결 |
| `aria_snapshot(depth=N)` 단독 | **무효** (depth가 무시됨) |
| `aria_snapshot(mode="ai")` | 4502 chars — element ref 포함해 더 김 |
| `aria_snapshot(mode="ai", depth=1)` | **684 chars / 31 lines — 대폭 축소** |

**확정된 메커니즘 (`tools/snapshot.py`):**
- 기본 `mode="a11y"` → 평문 `aria_snapshot()` (간결, Claude 이해용 기본값).
- `depth`가 주어지면 **`mode="ai"`와 함께** 적용해야 효과가 있음 → 내부적으로
  `aria_snapshot(mode="ai", depth=N)` 사용(element ref도 같이 와 후속 interact에 유용).
- `focus=<css>`로 서브트리 한정.
- 최후 안전장치로 문자수 상한 `_MAX_CHARS`(현재 20000) 절단 유지.
- ※ `mode`/`depth`는 Playwright ≥1.59, `boxes`는 ≥1.60 — 핀 `>=1.60` 충족.

**미정(네트워크 필요):** 실제 대형 SPA의 절대 크기·권장 depth 수치는 아웃바운드가
열린 환경에서 추가 측정 후 `_MAX_CHARS`/기본 depth 기본값을 조정한다.

---

## 9. 비기능 / 제약 매핑

| 항목 | 반영 |
|---|---|
| Performance (tool<500ms, snapshot<3s) | 로드 대기 제외 즉시 반환, snapshot 트리밍 |
| Reliability (재시작<5s) | §3.5 자동 재시작 |
| Compatibility (Py≥3.11, 3 OS) | pyproject `requires-python = ">=3.11"`, chromium 기본 |
| Security (로컬 전용) | stdio only, 대상 URL 외 아웃바운드 없음 |
| Usability (설치 1단계) | §7 |
| Maintainability (Tool=파일1개) | §2 레지스트리 |
| 자격증명 외부화 | env/.env 주입, `${VAR}` 치환, 리포트 마스킹 |
| 클라이언트 요청 타임아웃 | 장기작업 분할, 셀렉터 체인 타임아웃 관리 (MCP 고정값 아님·클라이언트 설정) |
| 동시 세션 1개 | 싱글톤 |
| Canvas/WebGL | screenshot 시각 확인만 (한계 명시) |

---

## 10. 구현 순서 (Phase)

마일스톤·완료기준(DoD)·상태의 **상세는 [`ROADMAP.md`](./ROADMAP.md)**가 단일
출처(source of truth)다. 여기서는 개요만 둔다.

| Phase | 범위 | 상태 |
|---|---|---|
| 0 | 스캐폴드(서버·레지스트리·세션 골격) | ✅ 완료 |
| 1 | 코어 PoC: BrowserSession·listeners·navigate·snapshot, Q1 실측 | ✅ 완료 |
| 2 | 상호작용/검증: screenshot·locator(D2)·interact·assert_·console·network | ✅ 완료 |
| 3 | 시나리오/리포트: runner + report(JSON/MD/HTML, SM-03~09) | ✅ 완료 |
| 4 | 확장: wait·switch_frame·expect_dialog·reset_session·HEADLESS | ✅ 완료 |
| 5 | 라이브러리: generate_scenario·save/load/list_scenario | ✅ 완료 |
| 6 | 운영 보강(PRD 외): 슬래시명령·브라우저 4모드·레코더+save_report | ✅ 완료 |

각 Phase: 단위 테스트(pytest) 후 커밋(건수는 스위트가 단일 출처 — 문서에 하드코딩하지 않는다). 성공지표 측정은 내부 베타 10페이지(향후).

---

## 11. 테스트 전략

- `tests/`: locator 체인 해석, 스텝 스키마 파싱, 리포트 생성, `${VAR}` 마스킹은
  브라우저 없이 단위 테스트.
- 브라우저 연동은 로컬 정적 HTML 픽스처(`tests/fixtures/*.html`)를 `file://`로 띄워 검증.
- CI 통합은 Out of Scope이나, pytest는 로컬에서 통과 기준으로 유지.

---

## 12. 미해결 / 결정 사항

**미해결 (추가 검토 필요)**
1. **Q1 트리밍 수치** — Phase 1 실측 후 확정. (네이티브 `depth`/`mode="ai"` +
   `_MAX_CHARS` 안전장치 방향은 §8에서 확정, 구체 수치만 미정.)

**결정 완료**
- **generate_scenario 분업 모델** — 서버는 페이지 구조/작성 키트를 반환하고
  Claude가 steps 생성. sampling 지원 클라이언트에선 `ctx.session.create_message`
  로 서버측 생성, 미지원(Claude Desktop) 시 키트 fallback. (§5.5)
- **버퍼 클리어 정책** — navigate는 누적/유지, 명시적 초기화는 `reset_session`. (§3.3)
- **리포트 형식·강화** — JSON/MD/HTML(SM-04) + SM-05~09 항목·스키마 확정. (§5.3·§6)
- **a11y 스냅샷 API / sampling 가용성 / Playwright 핀(≥1.60)** — §13 검증 반영.

---

## 13. 공식 문서 검증 기록 (Verification Log)

이 설계의 외부 API 가정은 아래 공식 소스로 대조 검증함.

**MCP Python SDK (FastMCP)** — `modelcontextprotocol/python-sdk` README
- `from mcp.server.fastmcp import FastMCP` / `@mcp.tool()` 데코레이터 ✅
- 이미지 반환 `from mcp.server.fastmcp import Image` → `Image(data=..., format="png")` ✅
- `mcp.run()` 기본 stdio transport ✅
- **구조화 출력:** 타입힌트(`dict[str, T]`/TypedDict/dataclass/Pydantic)에서
  `outputSchema` 자동 생성 ✅ → 반환 타입힌트 구체화 권장
- **Context 주입:** tool에 `ctx: Context` 파라미터 → 로깅(`ctx.info/...`),
  진행률 `await ctx.report_progress(progress, total, message)` ✅
  > 검증(2026-07, SDK 소스 `utilities/context_injection.py`): 주입 감지는 **타입
  > 어노테이션 기반**(`find_context_parameter`) — `ctx=None`처럼 어노테이션이 없으면
  > 주입되지 않고 일반 입력 파라미터로 스키마에 노출된다. `Context | None` 유니언도
  > 인식됨(get_args 순회). generate_scenario를 이 방식으로 수정.
- **Sampling:** `await ctx.session.create_message(messages=[...], max_tokens=...)`
  로 서버가 클라이언트 LLM에 생성 요청 ✅ (단 Claude Desktop 미지원)
- **Lifespan:** `@asynccontextmanager` lifespan으로 시작/정리 — 브라우저 기동·종료
  관리에 사용, `finally`에서 cleanup ✅

**MCP Sampling 가용성** — MCP 사양/지원 현황
- sampling은 **옵셔널 client capability**(클라이언트가 선언해야 동작), 인간 승인 권장,
  **Claude Desktop 미지원** ✅ → generate_scenario는 키트 fallback이 기본 경로

**Playwright (Python)** — playwright.dev / microsoft/playwright docs
- `page.accessibility.snapshot()` **deprecated** → `locator.aria_snapshot()`(YAML) ✅ (정정)
- `aria_snapshot` 옵션: `mode("ai"/"default")`·`depth`(**≥1.59**), `boxes`(**≥1.60**),
  `timeout`(≥1.49) — Q1 트리밍에 활용, pyproject 핀 `>=1.60` 전제 ✅
- `page.goto(url, wait_until=...)` 값: `load`/`domcontentloaded`/`networkidle`/`commit` ✅
- `page.on("console")`, `page.on("response")`, `page.on("requestfailed")` ✅
  — 4xx/5xx는 `response`(status≥400)로 전달, `requestfailed`는 네트워크 실패 한정 ✅
- `page.on("dialog")` / `page.expect_event("dialog")`,
  `dialog.accept(prompt_text)` · `dismiss()` · `message()` · `type()` ✅
- `page.get_by_role(role, name=, exact=)`, `page.get_by_text(text, exact=)` ✅
- `page.frame_locator(selector)` (snake_case) — `FrameLocator`는 `get_by_role`/
  `get_by_text`/`get_by_test_id`/`locator` 노출, frame root에서 셀렉터 체인 동작 ✅
- `page.wait_for_selector(...)`, `page.wait_for_timeout(ms)`, `page.expect_console_message(...)` ✅
- `BrowserType.executable_path`(기대 경로 반환, 설치 여부 ≠) — property/메서드 표기는
  버전별 상이 가능 → 구현 시 재확인 ⚠️
- `BrowserType.connect_over_cdp(endpoint_url)` — **Chromium 전용**. `http://localhost:9222/`
  또는 `ws://...` 허용. `Browser` 반환. 기존 컨텍스트/페이지는 `browser.contexts()[0]` ·
  `defaultContext.pages()[0]`로 접근(구현이 이 패턴 사용). 공식 주의: "Playwright
  프로토콜보다 fidelity 낮음", 브라우저가 Playwright 권장 인자 없이 떠 있으면 일부
  기능이 깨질 수 있음. close()가 실제 브라우저를 닫는지는 문서 미명시 → 실측 결과
  **disconnect만 되고 사용자 브라우저는 유지**됨(CDP 경로에서 context/browser 안 닫음).
- `BrowserType.launch_persistent_context(user_data_dir, channel=, executable_path=,
  headless=)` → `BrowserContext` 반환. 공식: "이 context를 닫으면 브라우저가 자동
  종료"(우리 persistent close()와 일치) ✅. `BrowserType.launch(channel=, executable_path=,
  args=, headless=)` ✅
- `BrowserContext.browser()` — context가 **normal browser 밖(Android/Electron)**에서
  생성됐을 때 None 반환(영속 컨텍스트는 Browser 반환). → `is_alive()`는 `page.is_closed()`
  우선으로 견고화 ✅
- `BrowserContext.add_init_script(...)` ✅ (stealth webdriver 숨김)
- `Browser.new_context(user_agent=, locale=, timezone_id=, viewport=)` — stealth 컨텍스트
  옵션, 실측(UA 적용)으로 확인 ✅
- `page.once(event, handler)` · `page.remove_listener(event, handler)` · `page.is_closed()` ✅
  (expect_dialog는 once 핸들러로 데드락 회피)
- `page.evaluate(expr, arg)` · `locator.evaluate(expr, arg)` — arg가 JS 2번째 인자 ✅
- `locator.click/fill/hover/select_option/press(timeout=)` · `count()` · `first` ·
  `is_visible()` · `wait_for(state=)` ✅
- `request.failure`(property, 실패 텍스트/None) · `request.method`(property) ✅
- `ConsoleMessage.type`/`text`/`location`(property) — location 키는 `url`/`line`/`column`
  (`lineNumber`/`columnNumber`는 deprecated) → `line` 우선 사용으로 정정 ✅
- `page.screenshot(path=, full_page=)` ✅

**MCP Prompts** — `@mcp.prompt(name=, description=)` 데코레이터, 문자열 인자 → 문자열
반환이 user 메시지로 직렬화, 인자는 클라이언트에 `PromptArgument`로 노출 ✅
(슬래시 명령 ui-test/ui-scenario/ui-login/ui-generate)

> 제약: playwright.dev API 페이지는 직접 fetch가 403으로 막혀, 일부 항목은
> GitHub 원본 마크다운 + 공식 검색 결과 + **로컬 실측**으로 교차 확인함.

---

## 14. 보안 모델 (Security Review)

PRD 보안 제약(로컬 전용·자격증명 마스킹·외부 전송 없음) 기준 점검 결과.

**확인된 방어**
- **로컬 전용:** stdio transport, 대상 URL 접근 외 아웃바운드 없음. 텔레메트리/phone-home
  없음. sampling은 클라이언트(로컬 LLM)로만 향함.
- **HTML 리포트 XSS 안전:** 페이지 유래 콘텐츠(콘솔/네트워크/타이틀/actual/a11y/메타)는
  전부 `html.escape` 처리 — 악성 페이지의 `<script>`가 리포트 열람 시 실행되지 않음
  (test_security로 회귀 고정).
- **자격증명 마스킹(2026-07 강화):** `${VAR}`는 리포트에 **미해석 상태로 저장**되고
  민감 필드는 `mask_step`으로 **완전 마스킹**(`***` — 첫 글자도 비노출). 민감 필드
  감지는 영어 키워드 + **한국어**(비밀번호/패스워드/암호/인증번호) + 짧은 토큰
  (pw/otp/pin/pass — 단어 단위 매칭, 오탐 방지). 추가로 **scrub 레지스트리**:
  민감한 이름의 `${VAR}`가 해석되면 그 값을 기억해 두었다가 파생 문자열(navigate된
  URL이 담기는 `ai_reason`, 예외 메시지, 콘솔/네트워크 항목)에서 `${VAR}`
  플레이스홀더로 치환한다(`scrub`/`scrub_record`, runner·recorder·interact 적용).
  미설정 `${VAR}`는 조용히 리터럴 입력되지 않고 `ai_suggestion` 경고를 남긴다.
- **명령 주입 없음:** `subprocess.run`은 리스트 인자, `shell=True` 미사용, 사용자 입력
  미포함(브라우저 설치만).
- **MCP stdout 보호(2026-07):** 첫 실행 자동설치(`playwright install`)의 서브프로세스
  출력을 `DEVNULL`로 차단 — stdout은 MCP JSON-RPC 파이프이므로 다운로드 진행률이
  프로토콜 스트림을 오염시키지 않는다. 패키지 내 `print()` 없음, 로깅은 stderr.
- **경로 traversal 차단:** 시나리오/리포트/스크린샷 파일명은 정규식 sanitize(`_SAFE`).

**수용된 위험(로컬 도구 전제, 문서화)**
- `${VAR}`는 **존재하는 모든 env 변수**를 해석한다(미존재 시 리터럴 유지). 신뢰할 수
  없는 출처의 시나리오는 임의 env 시크릿을 페이지 폼에 주입할 수 있으므로,
  **시나리오는 신뢰 가능한 것만 실행**한다.
- `use_real_browser` 영구 프로필(`~/ui-blackbox/chrome-profile`)에 **로그인 쿠키가
  디스크 저장**된다 — 공유 머신에서 주의.
- `navigate`는 `file://`로 로컬 파일을 열 수 있다(로컬 테스트 도구 특성).
- `BROWSER_CDP`는 localhost 디버그 포트(무인증)에 attach — 로컬 한정.
