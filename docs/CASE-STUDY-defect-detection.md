# 케이스 스터디 — 결함 탐지 채점

> **무엇을 측정했나:** 결함 6종을 심은 사이트에 이 도구를 돌려, **몇 개를 잡고 몇 개를
> 놓치는지** 셌다. 못 잡을 것으로 예상한 결함을 일부러 함께 심었다 — 잡히는 것만 심으면
> 아무것도 증명되지 않기 때문이다.
>
> **대상:** [`examples/defect-lab/`](../examples/defect-lab/) (자체 제작).
> saucedemo.com을 겨냥한 시나리오도 [준비돼 있으나](../examples/saucedemo/) 라이브 실행은
> 못 했다 — 작업 환경의 egress 정책이 `www.saucedemo.com:443` CONNECT를 403으로 거부한다.
> 아래 숫자는 **전부 defect-lab에서 실측한 값**이며 saucedemo 결과가 아니다.

## 방법

계정별로 결함을 주입하는 구조(saucedemo의 방식)를 그대로 따랐다. 핵심은 **네 계정에
같은 시나리오 파일을 쓴다**는 점이다. 결함마다 전용 시나리오를 쓰면 답을 알고 그것만
확인하는 셈이라 탐지력이 아니라 시나리오를 시험하게 된다.

```bash
python -m http.server 8799 --directory examples/defect-lab &
export LAB_URL=http://127.0.0.1:8799 LAB_PASSWORD=secret_sauce

LAB_USER=standard_user ui-blackbox run examples/defect-lab/scenario.json --continue-on-fail
LAB_USER=problem_user  ui-blackbox run examples/defect-lab/scenario.json --continue-on-fail --fail-on-js-error
```

## 결과

| 계정 | 통과 | exit | 판정 |
|---|---|---|---|
| `standard_user` | **20/20** | 0 | 기준선 성립 (콘솔도 깨끗) |
| `problem_user` | **16/20** | 1 | 결함 4스텝 검출 |
| `performance_glitch_user` | 20/20 | 0 | 기능 정상, **2,471ms vs 1,191ms** |

### 결함별 채점

| # | 심은 결함 | 예측 | **실제** | 근거 |
|---|---|---|---|---|
| D-1 | 상품 이미지가 전부 동일한 엉뚱한 이미지 | 미탐지 | ❌ **미탐지** | `<img>`가 존재·로드·alt 정상. 구조적 단언으로는 볼 수 없다 |
| D-2 | 체크아웃 성(姓) 입력이 조용히 사라짐 | 탐지 | ✅ **탐지** | step19/20 실패 (`url_contains`, `text_visible`) |
| D-3 | 정렬 드롭다운이 아무것도 안 함 | 부분 | ❌ **미탐지** | 예측이 낙관적이었다 (아래 참조) |
| D-4 | 담기는 되지만 배지가 갱신 안 됨 | 탐지 | ✅ **탐지** | step11 실패 (`element_visible`) |
| D-5 | 미처리 JS 예외 | 탐지 | ✅ **탐지** | `source="pageerror"`로 기록 |
| D-6 | 목록이 늦게 뜸 | 관찰만 | ⚠️ **관찰만** | 통과하되 2.1배 느림이 `duration_ms`에 남음 |

**예측 6건 중 5건 적중.** 빗나간 D-3은 낙관 방향이었다 — "부분 탐지"로 적었지만 실제로는
전혀 못 잡는다. `select` 액션은 성공하고 change 이벤트도 뜨므로 도구 입장에선 정상이며,
"N번째 항목이 X인가"를 물을 어서션 종류가 없어서 순서를 검증할 방법 자체가 없다.

산출물: [`examples/defect-lab/reports/`](../examples/defect-lab/reports/)
(`standard_user.html` / `problem_user.html` — 스크린샷 임베드된 자기완결 HTML)

## 실행 중에 발견해 고친 것

측정만 한 게 아니라, 이 과정에서 도구 자체의 결함이 세 건 나왔다.

1. **JS 예외가 판정에 반영되지 않았다.** D-5는 `pageerror`로 **기록은 됐지만 해당 스텝은
   PASS**였다 — 앱이 터져도 CI 게이트는 초록이었다는 뜻이다. `--fail-on-js-error`
   (opt-in)를 추가해 17/20 → 16/20으로 바뀌는 것을 확인했다.
2. **`severity`에 `js_error`가 정의만 되고 한 번도 나오지 않았다.** DESIGN §6.1의 severity
   어휘에 `js_error`가 있는데 `classify_failure`가 그 값을 반환하는 경로가 없었다.
   스키마-구현 불일치.
3. **`wait` 스텝이 `timeout_ms`를 버렸다.** 러너가 필드를 전달하지 않아 모든 대기가 기본
   10초에 묶여 있었다. 느린 계정 시나리오를 쓰다가 드러났다.

3번은 픽스처만으로는 나오지 않는 종류다 — 실제 대상을 겨냥해 시나리오를 쓰는 행위 자체가
결함을 드러냈다.

## 확정된 한계

측정으로 확인된 공백. 각각 회귀 테스트로 고정해 뒀다([`tests/test_defect_lab.py`](../tests/test_defect_lab.py)) —
나중에 조용히 "더 잡는다"고 주장하거나, 되는 걸 잃지 못하게.

| 한계 | 결과 | 필요한 것 |
|---|---|---|
| 시각 회귀 없음 | D-1 미탐지 | baseline 스크린샷 diff (ROADMAP P6) |
| 순서/정렬 어서션 없음 | D-3 미탐지 | `assert kind="nth_text"` 류 |
| 성능 임계값 어서션 없음 | D-6 관찰만 | 스텝 `max_duration_ms` |
| 원인이 아닌 **결과**를 잡는다 | D-2가 step16이 아닌 step19에서 실패 | `fill` 후 값 검증(read-back) |
| 비동기 JS 예외의 스텝 귀속이 근사값 | 타이밍에 따라 붙는 스텝이 달라짐 | 버퍼 슬라이스 방식의 구조적 한계 |

4번째 항목이 실무에서 가장 성가시다: 성 입력 스텝은 **통과**하고 두 스텝 뒤에 실패가
드러나므로, 리포트만 보면 원인 지점을 한 번에 짚지 못한다.

## 이 결과를 어떻게 읽어야 하나

이 도구는 **구조적·상태적 결함**(요소 유무, URL 전이, 개수, JS 예외)에 강하고
**지각적·시간적 결함**(무엇이 그려졌나, 순서가 맞나, 얼마나 빠른가)에 약하다.
6종 중 3종 탐지는 낮아 보이지만, 못 잡는 3종은 전부 **의도적으로 범위 밖**이거나
어서션 어휘의 공백이며 — 어느 것도 오탐이 아니다. 잡은 것은 정확히 잡았고,
기준선은 20/20으로 깨끗했다(오탐 0).
