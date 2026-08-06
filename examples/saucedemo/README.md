# saucedemo.com 시나리오 스위트

[saucedemo.com](https://www.saucedemo.com/)은 Sauce Labs가 **테스트 자동화 연습용으로
공개한 데모 상점**이다. 계정 목록과 비밀번호가 로그인 페이지에 그대로 적혀 있고,
일부 계정에는 **결함이 의도적으로 심겨 있다**. 그래서 "도구가 실제 결함을 잡아내는가"를
증명하기에 적합하다 — 정답을 이미 아는 상태로 채점할 수 있기 때문이다.

## 실행

```bash
# 비밀번호는 사이트에 공개돼 있지만, 시나리오에는 절대 인라인하지 않는다.
# ${SAUCE_PASSWORD}로 주입되고 리포트에는 ***로 마스킹된다.
export SAUCE_PASSWORD=secret_sauce

ui-blackbox doctor --url https://www.saucedemo.com/     # 먼저 도달 가능 여부

ui-blackbox run examples/saucedemo/happy-path.json
ui-blackbox run examples/saucedemo/login-negative.json     --continue-on-fail
ui-blackbox run examples/saucedemo/problem-user.json       --continue-on-fail
ui-blackbox run examples/saucedemo/performance-glitch.json

# 전부 한 번에 (실패해도 계속 → 리포트 4개 + 통합 JUnit)
ui-blackbox run examples/saucedemo/*.json --continue-on-fail --junit junit.xml
```

리포트는 `~/ui-blackbox/reports/`(또는 `REPORT_DIR`)에 JSON·Markdown·HTML로 저장된다.
브라우저를 눈으로 보려면 `HEADLESS=false`.

## 시나리오별 목적

| 파일 | 계정 | 통과 기대 | 목적 |
|---|---|---|---|
| `happy-path.json` | `standard_user` | **전부 통과** | 기준선(baseline). 여기가 깨지면 시나리오나 사이트 구조가 바뀐 것이다. |
| `login-negative.json` | 3종 | **전부 통과** | 실패 경로의 *올바른 에러*를 단언한다. 빈 입력·오답·잠긴 계정. |
| `problem-user.json` | `problem_user` | **일부 실패해야 정상** | 결함이 심긴 계정. 실패 지점이 곧 탐지 성능이다. |
| `performance-glitch.json` | `performance_glitch_user` | 통과하되 **느림** | 기능 통과 / 성능 이상을 리포트가 분리해 보여주는지. |

`problem-user.json`은 `happy-path.json`과 **같은 단언**을 쓴다. 두 리포트를 나란히 두면
"같은 요구사항, 다른 계정, 다른 결과"가 되어 대조군이 성립한다. 이것이 이 스위트의 핵심이다.

## 왜 `--continue-on-fail`이 필요한가

기본값은 첫 실패에서 멈추고 나머지를 `skipped`로 기록한다(회귀 스위트에선 이게 맞다).
하지만 결함을 **수집**하는 것이 목적일 땐 멈추면 안 된다 — 한 번에 하나씩만 보이면
결함 3건을 찾는 데 3번 실행해야 한다.

## 주의

- 남의 사이트다. Sauce Labs가 연습용으로 공개한 범위 안에서만 쓰고, 부하를 주지 않는다.
- 사이트 구조가 바뀌면 셀렉터가 깨진다. 리포트의 `resolved_by`와 실패 스텝의 스크린샷을
  보면 어디가 바뀌었는지 바로 보인다.
- 사내망에서 실행한다면 외부 도메인이라 프록시 설정이 필요하다 — 루트 README의
  "Closed / corporate networks" 참고.
