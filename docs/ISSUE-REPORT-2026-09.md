# 코드 문제점 · 실제 동작 이슈 리포트 (2026-09-01)

대상 커밋 `c38c38e` · Python 3.11.15 · Playwright 1.62.0 · Chromium 141.0.7390.37

## 요약

정적 리뷰만이 아니라 **실제로 서버/CLI/도구를 구동해** 확인한 결과다. 로컬 HTTP 서버와
`file://` 픽스처를 대상으로 MCP 도구 계층(`mcp.call_tool`), `runner.run`, `ui-blackbox run`
세 경로를 모두 태웠다.

기준선: `pytest` **254 passed** (브라우저 포함, 3분 51초), `ruff check` / `mypy` 모두 clean.
**아래 13건은 전부 현재 테스트가 잡지 못하는 것들이다.**

| # | 등급 | 이슈 | 위치 |
|---|---|---|---|
| 1 | **P0** | 실패한 `expect_popup`/`expect_download`가 리포트에 아예 안 남아 **100% 통과로 보고** | `testing/recorder.py:16` |
| 2 | **P0** | `interact type`이 키 이벤트를 안 쏴서 자동완성/키 기반 UI가 **무반응인데 통과** | `tools/interact.py:93` |
| 3 | **P0** | CLI 최종 집계가 **미실행(skip) 스텝을 통과로 계산** | `cli.py:244` |
| 4 | P1 | `${VAR}`가 `navigate.url`·`interact.value`에서만 해석됨 | `testing/runner.py:155` 외 |
| 5 | P1 | 슬래시 명령 도구 허용목록이 5개 도구를 누락 | `tools/_prompts.py:14` |
| 6 | P1 | 대화형 리포트의 `page_url`이 **항상 null** | `testing/recorder.py:152` |
| 7 | P2 | `scrub`에 최소 길이 가드가 없어 **짧은 비밀값이 리포트 본문을 오염** | `testing/secrets.py:93` |
| 8 | P2 | 셀렉터 이름이 안 민감해 보이면 **평문 비밀번호가 리포트에 기록** | `testing/secrets.py:128` |
| 9 | P2 | 대화형 리포트 헤더 소요시간이 항상 `0 ms` | `tools/savereport.py:25` |
| 10 | P2 | `reports/history/`는 리텐션 대상이 아님 (무한 증가) | `testing/report.py:203` |
| 11 | P2 | bare-string `wait`가 폴링당 드라이버 왕복 12회 | `tools/wait.py:31` |
| 12 | P3 | `list_pages()`와 `switch_page()`의 인덱스 기준이 다름 | `browser/session.py:530` |
| 13 | P3 | `expect_popup`이 팝업을 두 번 adopt | `tools/popup.py:59` |

---

## P0 — 결과를 잘못 보고하는 문제

### 1. 실패한 `expect_popup` / `expect_download`가 리포트에서 통째로 사라진다

`recorder.RECORDABLE`(recorder.py:16-20)에 `expect_popup`, `expect_download`, `switch_tab`이
없다. `register_all`은 이 집합에 든 도구만 레코더로 래핑하므로, 대화형 흐름
(`/ui-test` → 도구 호출 → `save_report`)에서 **이 도구들의 호출은 기록되지 않는다.**

재현 — 일부러 실패하는 팝업 검증을 MCP 계층으로 호출한 뒤 `save_report`:

```text
expect_popup 결과 -> {"passed": false, "error": "popup url '.../popup.html'
                      does not contain '/checkout'"}

리포트 steps: [(1, 'navigate', True)]
리포트 summary: {'total': 1, 'passed': 1, 'failed': 0, 'skipped': 0, 'pass_rate': 1.0}
```

**검증이 실패했는데 리포트는 `1/1 passed · 100%`.** 사내 업무 흐름의 최종 산출물 검증
(엑셀/PDF 내려받기 = `expect_download`, 결제/OAuth 팝업 = `expect_popup`)이 정확히 이
구멍에 들어간다.

같은 뿌리의 2차 위험: `recorder._interpret`(recorder.py:111)의 마지막 fallback은
알 수 없는 도구에 대해 **무조건 `passed=True`** 를 돌려준다. 그래서 `RECORDABLE`에
이름만 추가하면 이번엔 "항상 통과하는 스텝"이 된다 — `_interpret` 분기를 함께 넣어야 한다.

> 제안: `RECORDABLE`에 세 도구를 추가하고 `_interpret`에 `expect_popup`(`passed`),
> `expect_download`(`passed`/`filename`/`size_bytes`), `switch_tab`(`ok`) 분기를 추가.
> fallback은 `passed=True` 대신 `result.get("passed", result.get("ok", True))` 같이
> 결과를 읽도록 바꾸고, "RECORDABLE의 모든 이름은 `_interpret` 분기를 갖는다"를
> 단위 테스트로 고정.

### 2. `interact type`은 키 이벤트를 발생시키지 않는다 (무반응인데 "통과")

`interact.py:93`은 `locator.fill()`을 쓴다. `fill()`은 `input`/`change`만 발생시키고
`keydown`/`keyup`/`keypress`는 발생시키지 않는다.

재현 — `keydown`에만 반응하는 검색창:

```text
interact type: {'ok': True, 'resolved_by': 'css', 'detail': 'typed'}
keydown 카운터 : keydown:0        ← 한 번도 안 올라감
자동완성 결과   : passed=False     ← 드롭다운이 안 뜸
```

`fill()` 덕분에 React/Vue처럼 `input`을 듣는 컨트롤드 인풋은 정상 동작한다. 깨지는 것은
**키 이벤트에 의존하는 UI** — 검색 자동완성, 실시간 추천, 글자수 카운터, 숫자만 허용하는
키 필터, Enter 제출 핸들러. 이 경우 스텝은 `ok: True`로 통과하고, 뒤따르는 단언만 실패해
원인이 "요소를 못 찾음"으로 오진된다.

> 제안: `type_sequentially`(또는 `type` + `mode="keys"`) 액션을 추가해
> `locator.press_sequentially(value, delay=...)`로 매핑. 기존 `type`의 의미(빠른 fill)는
> 유지하되 도구 설명에 "키 이벤트를 발생시키지 않는다"를 명시.

### 3. CLI 최종 집계가 미실행 스텝을 통과로 센다

`cli.py:244`:

```python
failed = sum(r["summary"]["failed"] for r in results)
total  = sum(r["summary"]["total"]  for r in results)
print(f"total: {total - failed}/{total} passed")
```

`summarize`는 skip을 `failed`에 넣지 않으므로(의도된 설계) `total - failed`가
**passed + skipped**가 된다.

실제 CLI 출력 — 4스텝 시나리오, 2번에서 실패해 3·4번이 미실행:

```text
▶ cli-probe (4 steps)
  FAIL 1/4 (pass_rate 50%)      ← 시나리오별 줄은 정확
  ...
total: 3/4 passed               ← 실제로 통과한 것은 1개
```

exit code는 `1`로 정확해서 **CI 게이팅은 정상**이다. 잘못된 것은 사람이 읽는 마지막
집계 줄이며, 스위트가 커질수록(스킵이 많아질수록) 괴리가 벌어진다.

> 제안: `passed = sum(r["summary"]["passed"] ...)`, `skipped = sum(...)`를 따로 집계해
> `total: {passed}/{total} passed ({failed} failed, {skipped} skipped)`로 출력.

---

## P1 — 조용히 동작하지 않는 기능

### 4. `${VAR}` 치환이 두 필드에만 적용된다

`secrets.resolve()`를 호출하는 곳은 `runner.py:108`(`navigate.url`)과
`interact.py:63`(`interact.value`) **둘뿐**이다. 나머지 스텝 필드는 리터럴
`"${VAR}"` 문자열 그대로 도구에 전달된다.

재현:

```text
step1 navigate  passed=True   ← ${BASE_PAGE} 해석됨
step2 assert    passed=False  ← target="${BASE_PAGE}" 리터럴과 실제 URL 비교
                actual='file:///.../basic.html'
```

치환되지 않는 필드: `assert.target`/`expected`, `interact.selector`, `wait.selector`,
`expect_popup.trigger`/`expect_url`, `expect_download.trigger`/`save_as`/`expect_name`,
`expect_dialog.trigger`/`expected_text`/`accept_text`, `mock_route.pattern`/`body`,
`switch_frame.selector`, `save_state`/`load_state`의 `name`.

`unresolved_vars` 경고도 위 두 필드에서만 호출되므로 **오타 난 `${BAES_URL}`은 경고조차
없이** 그냥 실패한다. DESIGN §822("존재하는 모든 env 변수를 해석한다")와도 어긋난다.

> 제안: `runner._dispatch` 진입점에서 스텝 전체를 한 번 훑어 문자열 값에
> `secrets.resolve`를 적용(`raw`는 원본 유지 — 마스킹은 이미 원본 기준). 동시에
> `unresolved_vars`도 스텝 단위로 수집.

### 5. 슬래시 명령의 도구 허용목록이 실제 레지스트리와 어긋난다

`_prompts.py:14`의 `_ONLY`는 "**ui-blackbox MCP 서버의 도구만** 사용해 … 사용 가능한
도구: …"라며 25개를 열거한다. 실제 등록은 30개다:

```text
등록됐지만 허용목록에 없음: expect_download, expect_popup,
                            get_dialogs, list_tabs, switch_tab
```

즉 `/ui-test`, `/ui-scenario`로 들어온 흐름에서 호스트 LLM은 **팝업·다운로드·탭 도구를
쓰지 말라고 지시받는다.** 이슈 1과 겹쳐서, 이 기능군은 대화형 경로에서 사실상 존재하지
않는 것과 같다.

> 제안: `_ONLY`를 레지스트리에서 생성하거나(권장), 최소한 "허용목록 == 등록 도구 이름"을
> 단위 테스트로 고정. 관찰용 도구를 제외하고 싶다면 명시적 제외 집합으로 표현.

### 6. 대화형 리포트의 `page_url`이 항상 null

`runner`는 스텝마다 `page_url`을 채우지만 `recorder.run_and_record`(recorder.py:152-169)의
레코드 dict에는 `page_url` 키가 없다. `secrets.scrub_record`(secrets.py:108)가
`record["page_url"] = scrub(record.get("page_url"))`로 **키를 None으로 만들어 주기 때문에**
스키마 검사에는 걸리지 않고, 리포트 렌더러의 `if st.get("page_url")` 분기만 조용히 죽는다.

실제 대화형 리포트:

```text
6 assert_ passed=False page_url=None shot=screenshots/..._step06.png

## 실패 상세
- **step 6 (assert_)** — text_visible did not hold. …
  - 스크린샷: `screenshots/..._step06.png`      ← "페이지:" 줄이 없음
```

SPA 라우팅 디버깅용으로 넣은 필드인데, 정작 SPA를 손으로 돌려보는 대화형 경로에서만 빠진다.

> 제안: `run_and_record`에서 `session.page.url`을 try/except로 읽어 넣기(runner와 동일).

---

## P2 — 데이터 품질 · 견고성

### 7. `scrub`에 최소 길이 가드가 없다

`secrets.py:93-97`은 등록된 비밀값을 **길이 제한 없이** 전역 치환한다. 짧은 값이면
리포트 본문이 오염된다:

```text
APP_PIN="1"
before: navigated to https://shop.corp/orders?page=1 (status 200) · 12 rows
after : navigated to https://shop.corp/orders?page=${APP_PIN} (status 200) · ${APP_PIN}2 rows

API_TOKEN="dev"
before: TimeoutError: waiting for locator('#dev-banner') on https://dev.corp/
after : TimeoutError: waiting for locator('#${API_TOKEN}-banner') on https://${API_TOKEN}.corp/
```

CLAUDE.md의 "마스킹은 **표적**이어야 한다"가 `mask_value` 쪽에는 적용됐지만 `scrub`에는
적용되지 않았다. PIN·짧은 토큰·`dev`/`test` 같은 값에서 증거 가치가 사라진다.

> 제안: 등록 시점(`resolve`)에 최소 길이(예: 6자) 미만이거나 순수 숫자 4자리 이하인 값은
> `_RESOLVED_SECRETS`에 넣지 않는다. 그런 값은 `mask_step`의 필드명 기반 마스킹으로만 처리.

### 8. 셀렉터 이름이 민감해 보이지 않으면 평문 비밀번호가 리포트에 남는다

`mask_step`(secrets.py:128)은 `value`를 **셀렉터 문자열이 민감해 보일 때만** 마스킹한다.
실행 시점에 알 수 있는 실제 정보(`<input type="password">`)는 보지 않는다.

재현 — `#p`가 `type=password`인 로그인 폼:

```text
report_*.json:72:        "value": "hunter2"
```

`#password`, `#login_pw`, `비밀번호` 같은 이름은 잡히지만 `#p`, `#txtPw2` 같은 불투명한
셀렉터는 통과한다. 시나리오에 `${VAR}`를 쓴 경우엔 `raw`가 원본(`"${PASSWORD}"`)이라
안전하므로, 위험은 "시나리오에 평문을 적은 경우"에 한정된다 — 다만 리포트는 공유되는
산출물이라 방어선이 하나뿐인 건 약하다.

> 제안: `interact`에서 요소의 `type` 속성(또는 `autocomplete=current-password`)을 읽어
> 민감 여부를 판단하고, 그 결과를 결과 dict에 실어 레코드 마스킹에 반영.

### 9. 대화형 리포트 소요시간이 항상 `0 ms`

`save_report`는 `runner._meta(session)`만 붙이는데(savereport.py:25) `_meta`에는
`duration_ms`가 없다(`runner.run`이 나중에 직접 채운다). 렌더러는 `meta.get('duration_ms', 0)`.

```text
**5/6 passed** (rate 0.833) · 0 ms · 2026-09-01T09:53:38
```

스텝별 `duration_ms`는 정상 기록되므로 합산만 하면 된다. `started_at`도 흐름 시작이 아니라
`save_report` 호출 시각이라는 점을 같이 보정하면 좋다.

### 10. `reports/history/`가 리텐션에서 빠져 있다

`report._prune`(report.py:203-231)은 `report_*.*`, `screenshots/*.png`, `traces/*.zip`만
정리한다. 회귀 baseline인 `history/{name}.json`은 제외다.

```text
REPORT_RETENTION=2로 4회 실행 후
report files: 2 runs 분만 남음  ✓
screenshots : 2개              ✓
history     : ret0.json ret1.json ret2.json ret3.json   ← 4개 전부 남음
```

파일 하나당 최근 10회로 캡이 걸려 있어 크기는 작지만, **시나리오 이름 종류만큼 파일이
영구히 쌓인다.** 이름을 자주 바꾸는 애드혹 흐름에서 디렉터리가 지저분해진다.

> 제안: `_prune`에서 오래 손대지 않은(mtime 기준) history 파일도 함께 정리하거나,
> 최소한 문서에 "history는 수동 정리 대상"이라고 명시.

### 11. bare-string `wait`의 폴링 비용

`wait.py:31-58`은 100 ms마다 D2 체인 전체를 재해석한다. `locator.resolve`(locator.py:147-161)의
bare-string 후보는 CSS(조건부) + testid + 흔한 role 10종 + text = 최대 12개이고,
각각 `count()`가 드라이버 왕복 1회다.

측정 (타임아웃 2000 ms):

| 셀렉터 | 경과 | `Locator.count()` 호출 |
|---|---|---|
| `절대없는텍스트123` (bare) | 2069 ms | **208** |
| `css=.nope-xyz` (명시 prefix) | 2087 ms | 21 |

기능은 정상이고 로컬에선 문제없지만, 원격/느린 대상에서는 왕복 자체가 대기 예산을 잠식한다
(10초 대기 = 1000회 이상). 재해석이 필요한 이유는 주석에 잘 설명돼 있으므로, 비용만 낮추면 된다.

> 제안: 첫 폴에서 어떤 tier가 "존재는 하나 아직 안 보임"인지 확인되면 그 tier로 고정하거나,
> 폴 간격을 점증(100 → 250 → 500 ms)시키는 백오프.

---

## P3 — 잠재 결함

### 12. `list_pages()`와 `switch_page()`의 인덱스 기준 불일치

`session.py:530-543`의 `list_pages()`는 **닫힌 페이지를 포함한** `context.pages` 전체를
`enumerate`한 인덱스를 내보내고, `switch_page()`(session.py:545-557)는 **닫힌 페이지를
걸러낸** 리스트를 인덱싱한다.

현재 Playwright(1.62)는 `Page._on_close`에서 `close` 이벤트를 emit하기 **전에**
`context._pages`에서 제거하므로 두 리스트가 항상 같고, 실제로 재현되지 않는다
(실측: `list_tabs` ↔ `switch_tab` 인덱스 일치 확인). 다만 코드가 스스로 `is_closed()`
필터를 두고 있다는 것은 그 상황을 가정한다는 뜻이고, 그 가정이 참이 되는 순간
"`list_tabs`에서 본 2번 탭이 `switch_tab(2)`에서 range 밖"이 된다.

> 제안: 두 메서드가 같은 헬퍼(`_open_pages()`)를 쓰도록 통일.

### 13. `expect_popup`이 팝업을 두 번 adopt한다

context의 `page` 리스너가 이미 `_adopt_page`를 호출한 뒤 `popup.py:59`에서 한 번 더
명시 호출한다(CDP 모드 대비 — 주석에 근거 있음). 결과적으로 `_page_ready` 태스크가 두 번
생성되고 첫 번째는 await 없이 버려진다.

```text
Adopted new page/popup.
Adopted new page/popup.     ← 같은 팝업
```

동작에는 지장이 없으나(둘 다 같은 페이지), `_adopt_page`에 "이미 활성 페이지면 no-op" 가드를
두면 로그와 태스크가 정리된다.

---

## 참고: 정상 확인된 것

리뷰 중 의심했다가 **실측으로 정상 확인**한 항목 — 회귀 시 참고용.

- 크래시 복구: `browser.close()`로 강제 종료 후 다음 `get_session()`에서 투명 복구, 동일
  싱글턴 유지, 이후 `navigate` 정상.
- 팝업 닫힘 폴백: 활성 팝업을 닫으면 원래 탭으로 복귀.
- 중첩 iframe `>>>` 체인: 2단계 진입, 깊은 testid/텍스트 단언, 잘못된 체인의
  `missing_at{depth,selector}` 보고까지 정확.
- 로드 시점 `alert`: 자동 dismiss되면서 `expected=false`로 기록됨(무흔적 소실 없음).
- `mock_route` 수명: `reset_session` 후 컨텍스트와 함께 정상 폐기, `active` 목록도 초기화.
- 리텐션: 리포트/스크린샷이 run id 단위로 함께 보존·삭제됨.
- `navigate` 상태코드 판정: 404/500 실패, `expect_status: 404` 통과.
- CLI exit code: 실패 시 `1`, JUnit의 `<skipped>` 표기 정확.

## 재현 환경

```bash
.venv/bin/python -m pytest -q                # 254 passed
.venv/bin/ruff check blackbox_mcp            # clean
.venv/bin/mypy blackbox_mcp                  # clean
```

실측은 로컬 `http.server` 픽스처(로그인 폼 · 팝업 · 키 이벤트 검색창 · 로드시 alert ·
2단 중첩 iframe · 404/500 라우트)와 `tests/fixtures/basic.html`을 대상으로,
MCP 도구 계층 / `runner.run` / `ui-blackbox run` 세 경로에서 각각 수행했다.
