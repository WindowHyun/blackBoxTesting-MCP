# CLAUDE.md — Agent Context

Claude Code가 이 저장소에서 작업할 때 먼저 읽는 컨텍스트. 실행 절차의 단일 출처는
[`HARNESS.md`](./HARNESS.md), 설계는 [`DESIGN.md`](./DESIGN.md), 마일스톤은
[`ROADMAP.md`](./ROADMAP.md).

## 프로젝트 한 줄
Claude Desktop에 브라우저 조작 능력을 붙여 자연어로 UI를 블랙박스 테스트하는 MCP 서버.

## 스택
Python 3.11+ · Playwright(Chromium, **async API**, ≥1.60) · MCP 공식 SDK(FastMCP) · stdio

## 자주 쓰는 명령
```bash
# 격리 환경(시스템 pip는 PyJWT 충돌로 막힘 → 반드시 venv 사용)
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/playwright install chromium     # 브라우저 연동 테스트 시

.venv/bin/python -m pytest -q              # 테스트
.venv/bin/python -m blackbox_mcp.server    # 서버 기동(stdio)
```

## 아키텍처 지도 (어디에 뭐가 있나)
- `blackbox_mcp/server.py` — FastMCP 부팅: `ensure_chromium()` → `register_all()` → `mcp.run()`, lifespan으로 세션 정리
- `blackbox_mcp/cli.py` — CI 진입점(`ui-blackbox run/doctor`): MCP 없이 runner/report 직접 호출, exit code+JUnit, `--parallel`은 서브프로세스 격리
- `blackbox_mcp/tools/` — **MCP Tool = 파일 1개**. `_registry.py`의 `@tool`로 등록(`@prompt`=슬래시 명령은 `_prompts.py`). register_all이 액션 도구를 recorder로 래핑
- `blackbox_mcp/browser/` — `session.py`(싱글톤 + 4 모드: 번들/채널·스텔스/영구프로필/CDP — DESIGN §3.7), `listeners.py`(콘솔/네트워크 버퍼), `locator.py`(D2 체인)
- `blackbox_mcp/testing/` — `runner.py`(시나리오), `report.py`(JSON/MD/HTML+회귀), `recorder.py`(액션 자동 기록→save_report), `library.py`, `secrets.py`(마스킹)
- `tests/` — 브라우저 없는 단위 + `file://` 픽스처 통합. 브라우저 필요 테스트는 `browser` 마커(자동 부여) — 고속 레인: `-m "not browser"`

## 불변 규칙 (반드시 지킬 것)
1. **Tool 추가 = `tools/`에 파일 1개 + `tools/__init__.py`에 import 한 줄.** `server.py`는 절대 수정하지 않는다.
2. **async 일관성** — tool/세션은 async. Playwright **async API**만 사용(sync API는 asyncio 루프에서 불가). 단 `bootstrap.ensure_chromium()`은 루프 시작 전이라 sync 허용.
3. **공식 문서 검증** — MCP/Playwright API를 쓰기 전 공식 문서로 확인하고, 새 사실은 `DESIGN.md §13`에 기록. 추측 금지.
4. **자격증명** — 시나리오의 `${VAR}`는 env에서 주입, 리포트엔 완전 마스킹(`***`) + 해석값 scrub(`testing/secrets.py` — 파생 URL/에러 텍스트까지). 평문 저장 금지. 리포트에 닿는 새 텍스트 필드는 `scrub_record` 경유.
5. **셀렉터 우선순위(D2)** — data-testid → role+name → text → css. `browser/locator.py` 경유.
6. **리포트 스키마 단일 출처** — `DESIGN.md §6.1`. 스텝 필드는 거기에 맞춘다.
7. 각 작업 후 `pytest` 통과 + 커밋. PR/병합은 명시 요청 시에만.

## 작업 브랜치
`claude/compassionate-gauss-m0w47k` (메인라인 `main` 존재). 커밋은 작업 브랜치에.

## 함정(Gotchas)
- 시스템 Python `pip install`은 PyJWT RECORD 충돌로 실패 → **venv 필수**.
- Chromium 다운로드 ~150MB. Phase 1 착수 시 환경 가능 여부 먼저 확인.
- `BrowserType.executable_path`는 "설치 여부"가 아니라 "기대 경로" → `os.path.exists()`로 확인.
- 4xx/5xx는 `requestfailed`가 아니라 `response`(status≥400)로 잡힌다.
- 출력 경로는 **홈 기준 절대경로**(`~/ui-blackbox/...`). MCP 서버 cwd가 시스템 경로일 수 있어 상대경로 저장은 막힌다(`ensure_dirs` 홈 폴백).
- recorder 래핑은 **MCP 등록 함수만** 감싼다(모듈 함수는 unwrapped) → `run_scenario` 내부 호출은 이중 기록 안 됨. 래퍼는 반환 어노테이션을 떼서 `Image` 스키마 오류를 피한다.
- 브라우저 CDN(`cdn.playwright.dev`) 차단 환경: `CHROMIUM_EXECUTABLE`/사전설치 자동감지로 우회.
- **stdout은 MCP JSON-RPC 파이프** — 서브프로세스/`print()`가 stdout에 쓰면 프로토콜이 깨진다(bootstrap 설치는 DEVNULL, 로깅은 stderr).
- 세션 수명주기는 락 경유 — `get_session()`·`close_session()`은 모듈 락, `reset/switch_to_persistent/restart/close`는 `_op_lock`(공개 메서드가 락 획득, 본체는 `_impl` — 락 보유 중 공개 메서드 재호출 금지, `restart`는 `_close_impl` 사용). 락 순서는 `_SESSION_LOCK` → `_op_lock`.
- `start()`는 런치 폴백 체인(channel → 존재하는 chromium 실행 파일 → 번들) — stale `CHROMIUM_EXECUTABLE`/미설치 channel이 런치를 영구 실패시키지 않는다. 실행 파일은 `BROWSER=chromium`일 때만 적용.
- 활성 페이지가 될 수 있는 모든 페이지는 `_watch_page` 경유(리스너+close 폴백 핸들러, 페이지당 1회 멱등) — 세션 코드에서 `attach()`를 직접 호출하지 말 것(이중 버퍼링).
- 콘솔/네트워크 버퍼는 1000건 캡, recorder 스텝 번호는 단조 카운터(`len(_LOG)+1` 아님).
- FastMCP Context 주입은 **타입 어노테이션 기반** — `ctx: Context | None = None`처럼 어노테이션 필수, 없으면 스키마에 입력 파라미터로 노출된다(DESIGN §13).
- 리포트↔스크린샷은 **동일 `run_id` 공유**(`result["run_id"]`, `save()`가 파일명에 재사용) → 리테인션이 run 단위로 함께 보관/삭제(DESIGN §7.2). 스크린샷 태그는 `{run_id}_{name}` — id를 앞에 둬 `_STAMP_RE`가 name의 숫자에 오염되지 않는다.
- `register_all`은 멱등(중복 등록 방지 가드). scrub 레지스트리(`secrets._RESOLVED_SECRETS`)는 flow 경계(`recorder.reset`·`runner.run` 종료)에서 clear — 레코드는 append 시점에 이미 스크럽됨.
- CLI `--parallel` 자식은 `REPORT_RETENTION=0`(부모가 1회 정리), 시그널사는 error, `--timeout` 워치독. stdout이 MCP 파이프가 아니라 print 자유(서버와 달리).
- navigate 판정은 **상태코드 기반**(`status>=400` 실패, `None`=file://·타임아웃은 통과, 스텝 `expect_status`로 정확 일치 검증). runner·recorder 양쪽 동일.
- D2 bare-string 체인은 testid→**role+name(흔한 role 순회)**→text — 단, 공백 포함 CSS 신호(`#form input`, `div > a`)는 CSS 프로브가 선행(0건이면 체인 계속 → `Order #123` 같은 텍스트는 텍스트 티어). CSS 즉시 확정은 `# [ ] >` 또는 선행 `.` **이고 공백 없음**일 때만. `locate()`(sync, 프로브 불가)는 보수적 — 공백 있으면 텍스트. assert/wait는 `resolve()` 체인 사용. `resolved_by`는 `role=button`처럼 구체 표기.
- `secrets.scrub`은 긴 값부터 치환(부분문자열 secret 잔여 노출 방지). HTML 리포트 스크린샷 임베드는 report_dir 하위 경로만.
- `ai_reason`/`ai_suggestion`은 러너에선 **규칙 기반**(리포트 각주로 명시) — 대화형(Claude)에선 호스트 LLM이 보강. 필드명은 스키마(DESIGN §6.1)라 유지.
- 서버는 **단일 테넌트**(프로세스당 세션 1개·전역 recorder). 병렬은 CLI 프로세스 분리로만. 공유 서버는 스코프 밖(아키텍처 재작업 필요).
- 린트 게이트: `ruff check blackbox_mcp`는 CI 차단, `mypy`는 비차단(Playwright 옵셔널-init 패턴 미정리).
