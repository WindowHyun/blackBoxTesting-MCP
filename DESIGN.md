# UI Blackbox Tester MCP — 설계 문서 (DESIGN)

> PRD `UI Blackbox MCP v0.6` 기반 구현 설계.
> 스택: **Python 3.11+ · Playwright(Chromium) · MCP 공식 SDK(FastMCP) · stdio · Claude Desktop**
> 범위: Phase 0~5 전체 (MUST/SHOULD/COULD 포함)

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
  config.py             # 환경변수 로딩 (HEADLESS, REPORT_DIR, SCENARIO_DIR, BROWSER 등)
  bootstrap.py          # ensure_chromium() (D1)

  browser/
    __init__.py
    session.py          # BrowserSession 싱글톤 (BR-01, BR-03, BR-04, 크래시 재시작)
    listeners.py        # 콘솔/네트워크 버퍼 부착 (BR-02)
    actions.py          # 셀렉터 fallback 체인 (D2), interact 실제 동작
    locator.py          # 셀렉터 해석 유틸 (data-testid → role → text → css)

  testing/
    __init__.py
    runner.py           # run_scenario 실행 엔진 (SM-01, SM-02)
    report.py           # JSON+MD 리포트 생성/저장 (SM-03, D3)
    library.py          # 시나리오 저장/로드/목록 (SL-02~04)
    secrets.py          # 자격증명 마스킹

  tools/
    __init__.py         # registry: 데코레이터로 등록된 tool 자동 수집
    _registry.py        # @tool 데코레이터 + register_all(mcp)
    navigate.py         # CT-01
    snapshot.py         # CT-02
    screenshot.py       # CT-03
    interact.py         # CT-04
    assertion.py        # CT-05  (assert_)
    console.py          # CT-06
    network.py          # CT-07
    wait.py             # CT-08
    frame.py            # CT-09  (switch_frame)
    dialog.py           # CT-10  (expect_dialog)
    session.py          # BR-04  (reset_session)
    scenario.py         # SM-01  (run_scenario)
    generate.py         # SL-01  (generate_scenario)
    library.py          # SL-02~04 (save/load/list_scenario)

scenarios/              # 저장된 시나리오 JSON (런타임 생성, SCENARIO_DIR 재정의 가능)
reports/                # 리포트 출력 (런타임 생성, REPORT_DIR 재정의 가능)

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

---

## 4. 셀렉터 전략 (D2) — `browser/locator.py`

`interact`/`assert_`의 `selector`/`target`은 단순 CSS가 아니라 **fallback 체인**으로 해석:

우선순위:
1. `data-testid` — 입력이 `testid=foo` 또는 `[data-testid="foo"]` 형태
2. **role + accessible name** — `role=button name=로그인` → `get_by_role`
3. **가시 텍스트** — `text=로그인` → `get_by_text`
4. **CSS** — 최후 수단, 명시적으로 CSS로 보일 때만

해석 규칙:
- 접두사 명시(`testid=`, `role=`, `text=`, `css=`)가 있으면 그 방식 우선.
- 접두사 없으면: CSS 셀렉터로 보이면(`. # [ >` 포함) CSS 시도 후 실패 시
  텍스트로 fallback. 순수 문자열이면 role/text 우선.
- 각 단계 timeout 짧게(예: 2s) 잡아 체인 전체가 클라이언트 요청 타임아웃 내 동작.

`locate(root, selector) -> Locator` 단일 함수로 추상화하여 모든 tool이 공유.

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
| `run_scenario` | `run_scenario(steps, continue_on_fail=False, save_report=True, report_format="both")` | MUST |

- `steps`: JSON 배열, 각 스텝 `{action, ...args}`. action은 위 코어 tool 이름과 동일 어휘.
- 각 스텝 결과: `{step, action, expected, actual, passed, screenshot_path, console_errors}`.
- 실패 시 자동 스크린샷 캡처(SM-02) → 리포트 첨부.
- `continue_on_fail=False`면 첫 실패에서 중단.
- 종료 후 리포트 저장(SM-03) — §6.
- **SM-04 (SHOULD):** `report_format`에 `html`/`all`을 지원해 단일 self-contained
  HTML 리포트(스텝 표 + 스크린샷 인라인 + 콘솔/네트워크 에러)를 추가 생성한다.
  비개발 페르소나(US-03) 가독성 향상. 외부 의존성 없이 CSS 인라인(NFR 로컬 전용).
  Phase 3에서 마크다운 렌더러와 함께 구현.

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

## 6. 리포트 (testing/report.py, D3 / SM-03)

- 기본 경로 `./reports/`(서버 실행 위치), `REPORT_DIR` env로 재정의, 없으면 자동 생성.
- 파일명 `report_YYYYMMDD_HHMMSS.json` / `.md`.
- JSON: 시나리오 메타 + 스텝별 결과 배열 + 요약(passed/failed/total, 소요시간).
- Markdown: 사람이 읽는 요약 — 스텝 표, 실패 스텝의 스크린샷 경로 링크,
  콘솔/네트워크 에러 섹션.
- HTML(SM-04, SHOULD): 단일 self-contained `.html` — 스텝 표 + 스크린샷 `<img>`
  인라인 임베드 + 콘솔/네트워크 에러. CSS 인라인, 외부 의존성/네트워크 없음.
- `formats` ∈ {json, md, html, both(json+md), all(json+md+html)}.
- 스크린샷은 `reports/screenshots/`에 저장하고 md/json은 상대경로 참조,
  HTML은 base64 data URI로 임베드(단일 파일 이식성).

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
- Claude Desktop 등록: config 한 줄 (`claude_desktop_config.example.json` 제공).
```json
{
  "mcpServers": {
    "ui-blackbox": { "command": "python", "args": ["-m", "blackbox_mcp.server"] }
  }
}
```

---

## 8. Q1 — snapshot 출력 크기 정책 (미결, Phase 1 실측 후 확정)

대형 SPA aria_snapshot(YAML) 출력이 MCP 컨텍스트 한도를 초과할 수 있음. **잠정 설계**:
- `snapshot(mode, depth=N, focus=selector)` 파라미터 도입.
  (`focus` 주어지면 `page.locator(focus).aria_snapshot()`로 서브트리만.)
- **네이티브 트리밍 옵션 우선 사용(공식):** `aria_snapshot(depth=N)`로 깊이 제한,
  `aria_snapshot(mode="ai")`로 AI 친화 포맷 — 단순 문자 절단보다 의미 보존.
  ※ 버전 게이트: `mode`/`depth`는 **Playwright ≥ 1.59**, `boxes`는 **≥ 1.60**.
  → pyproject 핀을 `playwright>=1.60`으로 상향(이 옵션 사용 전제).
- `aria_snapshot(boxes=True)` 옵션은 각 요소 bounding box를 덧붙여 주며
  공식 문서가 "AI 소비에 유용"하다고 명시 → interact 셀렉터 매칭 보조로 검토.
- 최후 안전장치로 문자수 상한(`_MAX_CHARS`) 절단은 유지.
- Phase 1 PoC에서 실제 토큰/문자 크기를 측정 → depth·상한 규칙 확정.

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

- **Phase 0** — 스캐폴드: pyproject, server.py, FastMCP 부팅, ensure_chromium, registry, config, 예시 config/.env, README 골격.
- **Phase 1** — 코어 PoC(MUST): BrowserSession, listeners, navigate, snapshot. **Q1 실측 → §8 확정.**
- **Phase 2** — 상호작용/검증(MUST): screenshot, locator 체인(D2), interact, assert_, console, network.
- **Phase 3** — 시나리오/리포트(MUST/SHOULD): runner(continue_on_fail, 실패 스크린샷), report(JSON+MD, D3).
- **Phase 4** — 확장(SHOULD): wait, switch_frame, expect_dialog, reset_session, HEADLESS 토글.
- **Phase 5** — 라이브러리(SHOULD/COULD): generate_scenario, save/load/list_scenario.
- 각 Phase: 단위 테스트(pytest) 추가, 커밋. 성공지표 측정은 Phase 3 이후 내부 베타 10페이지.

---

## 11. 테스트 전략

- `tests/`: locator 체인 해석, 스텝 스키마 파싱, 리포트 생성, `${VAR}` 마스킹은
  브라우저 없이 단위 테스트.
- 브라우저 연동은 로컬 정적 HTML 픽스처(`tests/fixtures/*.html`)를 `file://`로 띄워 검증.
- CI 통합은 Out of Scope이나, pytest는 로컬에서 통과 기준으로 유지.

---

## 12. 미해결/확인 필요

1. **Q1 트리밍 수치** — Phase 1 실측 후 확정.
2. **generate_scenario 분업 모델** — 서버가 페이지 구조만 주고 Claude가 steps
   생성하는 방식으로 설계함. PRD 문구("Claude가 ... 생성해 반환")와 합치하나,
   서버 내 LLM이 없다는 현실 반영. 구현 전 합의 확인 권장.
3. **버퍼 클리어 정책** — navigate 누적/유지로 채택(§3.3). 이견 시 조정.

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

> 제약: playwright.dev API 페이지는 직접 fetch가 403으로 막혀, 일부 항목은
> GitHub 원본 마크다운 + 공식 검색 결과로 교차 확인함. 구현 중 실제 버전의
> 시그니처를 코드로 재확인한다.
