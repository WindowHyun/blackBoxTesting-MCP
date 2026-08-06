# Defect Lab — 결함을 심어 둔 테스트 대상

이 도구가 **어떤 결함을 잡고 어떤 결함을 놓치는지** 측정하기 위한 자체 제작 사이트다.
의존성 없는 정적 HTML이라 `python -m http.server`만 있으면 돈다.

핵심 설계: **못 잡을 것으로 예상되는 결함을 일부러 함께 심었다.** 잡히는 결함만 심으면
100% 탐지가 나오고 그건 아무것도 증명하지 않는다.

채점 결과는 [`docs/CASE-STUDY-defect-detection.md`](../../docs/CASE-STUDY-defect-detection.md),
회귀 고정은 [`tests/test_defect_lab.py`](../../tests/test_defect_lab.py).

## 실행

```bash
python -m http.server 8799 --directory examples/defect-lab &
export LAB_URL=http://127.0.0.1:8799 LAB_PASSWORD=secret_sauce

LAB_USER=standard_user ui-blackbox run examples/defect-lab/scenario.json --continue-on-fail
LAB_USER=problem_user  ui-blackbox run examples/defect-lab/scenario.json --continue-on-fail --fail-on-js-error
```

브라우저에서 직접 열어보려면 <http://127.0.0.1:8799/login.html>.
계정과 비밀번호는 로그인 페이지에 적혀 있다.

## 계정별 주입 결함

| 계정 | 결함 | 탐지 여부 |
|---|---|---|
| `standard_user` | 없음 (기준선) | 20/20 통과 |
| `problem_user` | D-1 모든 상품 이미지가 동일한 엉뚱한 그림 | ❌ 미탐지 (시각 회귀 범위 밖) |
| | D-2 체크아웃 성(姓) 입력이 조용히 사라짐 | ✅ 탐지 |
| | D-3 정렬 드롭다운이 아무것도 안 함 | ❌ 미탐지 (순서 어서션 없음) |
| | D-4 담기는 되지만 배지 미갱신 | ✅ 탐지 |
| | D-5 미처리 JS 예외 | ✅ 탐지 (`source="pageerror"`) |
| `performance_glitch_user` | D-6 목록이 1.5초 늦게 렌더 | ⚠️ 관찰만 (임계값 어서션 없음) |
| `locked_out_user` | 없음 — 로그인 차단 (정상 동작) | — |

## 구조

- `login.html` → `inventory.html` → `cart.html` → `checkout.html` → `complete.html`
- 결함 프로파일은 `lab.js`의 `PROFILES`에 모여 있다. 상태는 쿼리스트링으로 넘긴다
  (`file://` 오리진에서 storage가 막히는 것을 피하려고).
- 각 페이지에 `<link rel="icon" href="data:,">` — 이게 없으면 브라우저의 자동
  `/favicon.ico` 요청이 404를 내고, 그 콘솔 에러가 매 실행 리포트에 섞여 신호를 흐린다.

## 결함을 추가하려면

`lab.js`의 `PROFILES.problem`에 플래그를 넣고 해당 페이지에서 분기한 뒤,
`tests/test_defect_lab.py`에 **탐지되든 안 되든** 단언을 추가한다. 미탐지도 고정해야
나중에 조용히 커버리지를 잃거나 부풀리지 않는다.
