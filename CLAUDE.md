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
- `blackbox_mcp/tools/` — **MCP Tool = 파일 1개**. `_registry.py`의 `@tool`로 등록(`@prompt`=슬래시 명령은 `_prompts.py`). register_all이 액션 도구를 recorder로 래핑
- `blackbox_mcp/browser/` — `session.py`(싱글톤 + 4 모드: 번들/채널·스텔스/영구프로필/CDP — DESIGN §3.7), `listeners.py`(콘솔/네트워크 버퍼), `locator.py`(D2 체인)
- `blackbox_mcp/testing/` — `runner.py`(시나리오), `report.py`(JSON/MD/HTML+회귀), `recorder.py`(액션 자동 기록→save_report), `library.py`, `secrets.py`(마스킹)
- `tests/` — 브라우저 없는 단위 + `file://` 픽스처 통합 (현재 65건)

## 불변 규칙 (반드시 지킬 것)
1. **Tool 추가 = `tools/`에 파일 1개 + `tools/__init__.py`에 import 한 줄.** `server.py`는 절대 수정하지 않는다.
2. **async 일관성** — tool/세션은 async. Playwright **async API**만 사용(sync API는 asyncio 루프에서 불가). 단 `bootstrap.ensure_chromium()`은 루프 시작 전이라 sync 허용.
3. **공식 문서 검증** — MCP/Playwright API를 쓰기 전 공식 문서로 확인하고, 새 사실은 `DESIGN.md §13`에 기록. 추측 금지.
4. **자격증명** — 시나리오의 `${VAR}`는 env에서 주입, 리포트엔 마스킹(`testing/secrets.py`). 평문 저장 금지.
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
