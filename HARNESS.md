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

**T1.2 lifespan 배선 + 세션 정리** `[BR-01, NFR]` ✅
- Files: `blackbox_mcp/server.py`, `blackbox_mcp/browser/session.py`
- 결과: `lifespan`(@asynccontextmanager) + `close_session()` → 종료 시 세션 정리.
- DoD: ✅ lifespan 종료 시 세션 None(릭 없음) 스모크 통과.

**T1.3 픽스처 + navigate 통합 테스트** `[CT-01, BR-02]` ✅
- Files: `tests/fixtures/basic.html`, `tests/conftest.py`, `tests/test_navigate.py`
- 결과: `file://` navigate → title/url 검증(file://는 status 200 반환), 콘솔 error·
  네트워크 실패(누락 이미지) 버퍼 적재 확인.
- DoD: ✅ 3 테스트 통과 (browser 미가용 시 자동 skip).

**T1.4 snapshot 실동작 + Q1 실측** `[CT-02, Q1]` ✅
- Files: `blackbox_mcp/tools/snapshot.py`, `tests/test_snapshot.py`, `DESIGN.md §8`
- 결과: a11y(aria_snapshot)/dom 동작. **Q1 발견: `depth`는 `mode="ai"`와 함께만
  유효**(단독 무시) → snapshot이 depth 시 ai모드 사용. §8에 수치 기록.
- DoD: ✅ a11y/dom/depth 트리밍 테스트 통과 / §8 갱신.

**T1.5 dom 모드 정련** `[CT-02]` — (보류) 현재 `inner_text` 유지. 태그/role 트리화는
네트워크 열린 환경에서 실제 페이지로 효용 확인 후 진행.

**T1.6 bootstrap executable_path** `[D1]` ✅ — T1.1에서 `executable_path` +
`os.path.exists` 견고화로 함께 처리(다운로드 실패 비크래시).

### Phase 2 — 상호작용·검증  (의존: T1.2~1.4) ✅

**T2.1 screenshot 통합** `[CT-03]` ✅ — `tests/test_screenshot.py`: 유효 PNG(매직바이트) 확인.

**T2.2 locator 체인 + resolved_by** `[D2]` ✅ — `browser/locator.py`에 async `resolve()`
실제 fallback 체인(testid→text) + `resolved_by` 반환. `test_interact.py`에서 검증.

**T2.3 interact 5동작** `[CT-04]` ✅ — click/type/hover/select/press 통과. 실패는
`{ok:False, error}` 구조화 반환, 값 마스킹, `selector_timeout_ms` 적용.

**T2.4 assert_ 5종** `[CT-05]` ✅ — `tests/test_assert.py`: 5종 + multi-match
strict-mode 회귀 + non-int count 처리.

**T2.5 console/network 통합** `[CT-06, CT-07]` ✅ — `test_navigate.py`에서 콘솔 error·
네트워크 실패 버퍼 적재 검증.

**T2.6 crash-recovery** `[NFR Reliability]` ✅ — `BrowserSession.is_alive()` +
`get_session()`이 죽은 브라우저 감지 시 `restart()`. `test_recovery.py`로 검증.

### Phase 3 — 시나리오 실행·리포트  (의존: Phase 2) ✅ (2차 SM-07/09 보류)

**T3.1 runner 스텝 디스패치** `[SM-01]` ✅ — `testing/runner.py`: navigate/interact/
assert/snapshot/wait 매핑 + `continue_on_fail`. per-step 결과.

**T3.2 실패 자동 캡처 + 스텝 스키마** `[SM-02]` ✅ — 실패 시 스크린샷 저장, 결과가
`DESIGN §6.1` 스키마 준수(`screenshot_each`로 전스텝 캡처 옵션).

**T3.3 리포트 JSON** `[SM-03]` ✅ · **T3.4 Markdown** ✅ · **T3.5 HTML** `[SM-04]` ✅
— `testing/report.py`. HTML은 단일 self-contained(스크린샷 base64). 샘플: `examples/`.

**T3.6 AI 판단근거/제안** `[SM-05]` ✅ — `ai_reason`/`ai_suggestion`(규칙기반 힌트,
호스트 LLM이 보강 가능) 리포트 표시.

**T3.7 셀렉터 투명성 + 에러 스텝귀속** `[SM-06]` ✅ — `resolved_by` 기록 + 콘솔/네트워크
에러를 스텝 버퍼 슬라이스로 귀속.

**T3.8 환경 메타 + 심각도** `[SM-08]` ✅ — meta(OS/Python/PW·브라우저) + severity
(assertion/timeout/error) 분류·색상.

**T3.10 마스킹 연동** `[제약]` ✅ — `secrets.mask_step`로 `${VAR}`/민감값 리포트 마스킹.

**T3.9 (2차) 회귀·a11y** `[SM-07, SM-09]` ✅ — `report.compute_regression()`(히스토리
`reports/history/{name}.json` 대비 step 상태 diff) + runner `_a11y_audit()`(img-alt·
label·accessible-name). MD/HTML에 섹션 렌더. test_backlog.py 4건.

**T1.5 dom 모드 트리화** `[CT-02]` ✅ — `inner_text` → 구조 outline(tag[testid]{role}:text)
JS 워크. test_backlog의 dom outline 검증.

### Phase 4 — 확장 Tools  (의존: Phase 2) ✅

**T4.1 wait** `[CT-08]` ✅ · **T4.2 switch_frame** `[CT-09]` ✅ · **T4.3 expect_dialog**
`[CT-10]` ✅(스텁→구현: `page.once("dialog")` 핸들러로 트리거 클릭 중 처리, accept/
dismiss/텍스트검증, 미노출 시 실패) · **T4.4 reset_session** `[BR-04]` ✅ · **T4.5
HEADLESS 토글** `[BR-03]` ✅
- Tests: `tests/test_extensions.py`(8), `tests/test_config.py`(3).
- DoD: ✅ iframe 스코프 / 다이얼로그 accept·dismiss·텍스트검증 / 시간기반 대기 /
  세션 초기화 버퍼 클리어 / HEADLESS 파싱.

### Phase 5 — 라이브러리·생성  (의존: Phase 3) ✅

**T5.1 save/load/list 통합** `[SL-02~04]` ✅ — `tests/test_library.py`: 저장→로드→list
왕복, overwrite 가드, 로드한 시나리오 run까지.

**T5.2 generate_scenario 작성 키트** `[SL-01]` ✅ — `tools/generate.py`: navigate→
페이지 상호작용 요소 수집(JS) + **D2 suggested_selector**(testid>role+name>text>css)
+ step_schema + example 반환. 키트로 조합한 steps가 실제 실행됨을 검증.

**T5.3 sampling fallback 분기** `[SL-01]` ✅ — `ctx` 있고 sampling 지원 시
`ctx.session.create_message`로 steps 생성(`mode:"generated"`), 미지원 시 키트
(`mode:"kit"`). Desktop은 키트 경로(기본).

### Phase 6 — 운영 보강 (PRD 외, 실사용 대응) ✅
실제 Claude Desktop 사용에서 나온 요구로 추가. DESIGN §3.7 / §5 참조.

- **E1 슬래시 명령**(`_prompts.py`) — `/ui-test·ui-scenario·ui-login·ui-generate`.
  "ui-blackbox 도구만" 지시로 Claude in Chrome 충돌 차단.
- **E2 브라우저 모드** — `BROWSER_CHANNEL`/`STEALTH`(봇오탐 완화), `BROWSER_CDP`
  attach, `use_real_browser`(영구 프로필·idempotent). CDP 실패 시 launch 폴백.
- **E3 출력 경로 견고화** — 기본 `~/ui-blackbox/...` 절대경로 + 쓰기 실패 홈 폴백
  (MCP cwd 불가측 대응).
- **E4 액션 레코더 + save_report** — 임의 도구 흐름도 리포트로 종료. register_all이
  액션 도구를 래핑(스키마 보존), run_scenario는 이중 기록 안 됨.
- **E5 환경 우회** — 브라우저 CDN 차단 시 `CHROMIUM_EXECUTABLE`/사전설치 자동감지.

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
