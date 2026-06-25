# HARNESS.md — 실행 하네스 (Execution Playbook)

ROADMAP을 **자율 실행 가능한 원자 작업(task)**으로 풀어둔 문서. 에이전트(또는 개발자)는
이 문서만 보고 한 작업씩 집어 구현 → 검증 → 커밋할 수 있다.

- 컨텍스트/불변규칙: [`CLAUDE.md`](./CLAUDE.md)
- 설계 근거: [`DESIGN.md`](./DESIGN.md) · 마일스톤: [`ROADMAP.md`](./ROADMAP.md)

---

## 0. 실행 프로토콜 (매 작업 공통 루프)

각 task는 다음 순서로 처리한다.

1. **PICK** — 미완료 task 중 의존성이 풀린 가장 앞 번호를 고른다.
2. **VERIFY-DOCS** — 새 MCP/Playwright API를 쓰면 공식 문서로 확인하고 `DESIGN §13`에 한 줄 기록.
3. **IMPLEMENT** — `Files`에 적힌 파일만 수정. 불변규칙(CLAUDE.md) 준수.
4. **TEST** — `Verify` 명령을 실행해 green 확인.
5. **DoD** — 체크리스트를 모두 만족하는지 확인.
6. **COMMIT** — 한 task = 한 커밋(권장). 메시지에 task ID 포함.
7. 막히면(blocked) 사유를 적고 다음 독립 task로 넘어가거나 사용자에게 질문.

> **Definition of Done (전역 게이트)** — 모든 task는: ① `pytest -q` green, ② 불변규칙 위반 없음,
> ③ 새 공개 동작은 테스트 1개 이상, ④ 문서(DESIGN/ROADMAP 해당 항목) 상태 갱신.

---

## 1. 환경 부트스트랩 (최초 1회)

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
# 브라우저 연동 task(T1.3+) 전:
.venv/bin/playwright install chromium
```
명령 alias (이 문서에서 `PY`/`PYTEST`로 표기):
- `PY`   = `.venv/bin/python`
- `PYTEST` = `.venv/bin/python -m pytest -q`

> 시스템 pip는 PyJWT 충돌로 실패하므로 **venv 필수**. CI/세션 자동 준비는 `.claude/`의
> SessionStart 훅이 수행(§5).

---

## 2. 작업 분해 (Phase별 task)

표기: `[req]` 요구사항 ID · `Files` 수정 대상 · `Verify` 검증 명령 · `DoD` 완료기준.

### Phase 1 — 코어 PoC  (의존: Phase 0 ✅)

**T1.1 의존성 핀 & 브라우저 가용성** `[D1]` ✅
- Files: `pyproject.toml`, `config.py`, `bootstrap.py`, `browser/session.py`, `.env.example`
- 결과: playwright **1.60** 설치 확인. 브라우저 CDN 차단으로 `playwright install` 불가
  → **사전설치 `/opt/pw-browsers/chromium`을 `executable_path`로 사용**(자동 감지,
  `CHROMIUM_EXECUTABLE`로 override). bootstrap은 다운로드 실패 시 비크래시.
- Verify(통과): `PY -c "import asyncio,blackbox_mcp.browser as b; asyncio.run(b.get_session())"` 류 스모크 + aria_snapshot 동작.
- DoD: ✅ async import / ✅ 사전설치 브라우저 런치 / ✅ pytest green.

**T1.2 lifespan 배선 + 세션 정리** `[BR-01, NFR]`
- Files: `blackbox_mcp/server.py`, `blackbox_mcp/browser/session.py`
- Steps: FastMCP `lifespan`(@asynccontextmanager)에서 세션 준비, `finally`에서 `close()`. `get_session()` 지연초기화와 병행.
- Verify: `PY -c "import asyncio,blackbox_mcp.server as s; ..."` 서버 import + lifespan 진입/종료 스모크.
- DoD: 종료 시 브라우저/PW 프로세스 정리(릭 없음) 확인.

**T1.3 픽스처 + navigate 통합 테스트** `[CT-01, BR-02]`
- Files: `tests/fixtures/basic.html`, `tests/test_navigate.py`
- Steps: 정적 HTML 픽스처 작성 → `file://`로 `navigate` → `{title,url,status}` 검증. 콘솔/네트워크 버퍼 수집 확인.
- Verify: `PYTEST tests/test_navigate.py`
- DoD: navigate 결과 정확 / 콘솔·네트워크 버퍼에 이벤트 적재.

**T1.4 snapshot 실동작 + Q1 실측** `[CT-02, Q1]`
- Files: `blackbox_mcp/tools/snapshot.py`, `tests/test_snapshot.py`, `DESIGN.md §8`
- Steps: `aria_snapshot()` YAML 실동작 확인. 대형 페이지로 문자/토큰 크기 측정 → `depth`/`mode="ai"` + `_MAX_CHARS` 규칙 확정 → §8 수치 기입.
- Verify: `PYTEST tests/test_snapshot.py`
- DoD: a11y/dom 모드 동작 / Q1 측정값 §8 기록 / 트리밍 동작.

**T1.5 dom 모드 정련** `[CT-02]`
- Files: `blackbox_mcp/tools/snapshot.py`
- Steps: 임시 `inner_text` → 태그/role/text 간략 트리.
- Verify: `PYTEST tests/test_snapshot.py`
- DoD: dom 모드가 구조적 outline 반환.

**T1.6 bootstrap executable_path 재확인** `[D1]`
- Files: `blackbox_mcp/bootstrap.py`
- Steps: 설치 버전에서 property/메서드 확정, 존재 체크 `os.path.exists` 견고화.
- Verify: `PY -c "from blackbox_mcp.bootstrap import ensure_chromium; ensure_chromium()"`
- DoD: 이미 설치 시 즉시 통과 / 미설치 시 install 호출.

### Phase 2 — 상호작용·검증  (의존: T1.2~1.4)

**T2.1 screenshot 통합** `[CT-03]` — Files: `tests/test_screenshot.py` · Verify: `PYTEST -k screenshot` · DoD: 유효 PNG 바이트 반환.

**T2.2 locator 체인 단위/통합** `[D2]` — Files: `tests/test_locator_live.py` · DoD: testid/role/text/css 각 전략 + fallback 동작.

**T2.3 interact 5동작** `[CT-04]` — Files: `tests/test_interact.py` · DoD: click/type/hover/select/press 모두 통과.

**T2.4 assert_ 5종** `[CT-05]` — Files: `tests/test_assert.py` · DoD: text_visible/element_visible/url_is/url_contains/count 정확.

**T2.5 console/network 통합** `[CT-06, CT-07]` — Files: `tests/test_events.py` · DoD: 의도적 4xx/JS에러를 버퍼에서 확인.

**T2.6 crash-recovery 래퍼** `[NFR Reliability]`
- Files: `blackbox_mcp/browser/session.py`, 공통 tool 래퍼(예: `tools/_registry.py` 또는 `browser/session.py` 헬퍼)
- Steps: tool 실행을 감싸 `TargetClosedError` 등 캡처 → `restart()` 1회 후 재시도.
- DoD: 강제 종료 후 다음 호출 정상, 재시작 < 5s.

### Phase 3 — 시나리오 실행·리포트  (의존: Phase 2)

**T3.1 runner 스텝 디스패치** `[SM-01]` — Files: `blackbox_mcp/testing/runner.py` · Steps: step.action → navigate/interact/assert_/wait/... 매핑, `continue_on_fail` 처리. DoD: 성공/실패 혼합 시나리오 per-step 결과.

**T3.2 실패 자동 캡처 + 스텝 스키마** `[SM-02]` — Files: `runner.py` · DoD: 실패 시 스크린샷 첨부, 결과가 `DESIGN §6.1` 스키마 준수.

**T3.3 리포트 JSON** `[SM-03]` — Files: `testing/report.py`, `tests/test_report.py` · DoD: §6.1 JSON 생성.

**T3.4 리포트 Markdown** `[SM-03]` — Files: `report.py` · DoD: 헤더 요약 + 스텝 표 + 에러 섹션.

**T3.5 리포트 HTML** `[SM-04]` — Files: `report.py` · DoD: 단일 self-contained HTML, 스크린샷 base64, 외부 의존성 0.

**T3.6 AI 판단근거/제안 배선** `[SM-05]` — Files: `runner.py`, `report.py` · Steps: 스텝 결과에 `ai_reason`/`ai_suggestion` 필드 수용·렌더. DoD: 필드가 리포트에 표시.

**T3.7 셀렉터 투명성 + 에러 스텝귀속** `[SM-06]` — Files: `browser/locator.py`(resolved_by 반환), `runner.py` · DoD: `resolved_by` 기록, 콘솔/네트워크 에러가 스텝 구간에 귀속.

**T3.8 환경 메타 + 심각도** `[SM-08]` — Files: `report.py` · DoD: meta(OS/Python/PW·브라우저 버전/뷰포트) + severity 분류.

**T3.9 (2차) 회귀·a11y** `[SM-07, SM-09]` — Files: `report.py`, `testing/library.py` · DoD: 직전 실행 diff, a11y 발견 섹션.

**T3.10 마스킹 연동** `[제약]` — Files: `runner.py`/`report.py` + `secrets.py` · DoD: 민감 값이 리포트에 마스킹.

### Phase 4 — 확장 Tools  (의존: Phase 2)

**T4.1 wait** `[CT-08]` · **T4.2 switch_frame** `[CT-09]` · **T4.3 expect_dialog** `[CT-10]`(스텁→구현) · **T4.4 reset_session 검증** `[BR-04]` · **T4.5 HEADLESS 토글** `[BR-03]`
- 각 Files: `tools/*.py` + `tests/test_*.py` · DoD: iframe 조작 / dialog 텍스트검증·accept·dismiss / 시간기반 대기 / 헤드풀 전환.

### Phase 5 — 라이브러리·생성  (의존: Phase 3)

**T5.1 save/load/list 통합** `[SL-02~04]` — Files: `tests/test_library.py` · DoD: 저장→로드→run 왕복.

**T5.2 generate_scenario 작성 키트** `[SL-01]` — Files: `tools/generate.py` · Steps: navigate→snapshot→상호작용 요소+D2 셀렉터+스텝 스키마+few-shot 반환. DoD: 유효 키트 반환.

**T5.3 sampling fallback 분기** `[SL-01]` — Files: `tools/generate.py` · Steps: `ctx: Context` 주입, 지원 시 `ctx.session.create_message`로 생성, 미지원 시 키트. DoD: 분기 동작.

---

## 3. 검증 자산
- 단위(브라우저 불필요): 레지스트리/locator 파싱/마스킹/스키마 → `tests/test_registry.py` 외.
- 통합(`file://` 픽스처): `tests/fixtures/*.html` + `tests/test_*.py`.
- 측정: Q1(snapshot 크기), 성공지표(탐지율·허위실패)는 Phase 3 이후 내부 베타 10페이지.

## 4. 커밋·PR 규약
- 한 task = 한 커밋, 메시지 첫 줄에 `[T1.3]` 식 ID.
- PR/병합은 **사용자 명시 요청 시에만**. 작업 브랜치: `claude/compassionate-gauss-m0w47k`.

## 5. 세션 자동 준비 (.claude SessionStart 훅)
`.claude/settings.json`의 SessionStart 훅이 `scripts/setup_env.sh`를 실행해 venv 생성 +
`pip install -e .[dev]`를 수행한다(Chromium 설치는 비용 때문에 수동/조건부). 자세한 동작은
스크립트 주석 참조.
