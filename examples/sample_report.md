# UI Blackbox Report — login_demo

**5/6 passed** (rate 0.833) · 425 ms · 2026-06-25T06:45:18

_env: Linux · py3.11.15 · playwright 1.60.0 · chromium_

| # | action | resolved | expected | actual | result | sev |
|---|---|---|---|---|---|---|
| 1 | navigate |  | 페이지 도착 | “Imperfect Login” · HTTP 200 | ✅ |  |
| 2 | interact | testid | type ok | typed | ✅ |  |
| 3 | interact | testid | type ok | typed | ✅ |  |
| 4 | interact | testid | click ok | clicked | ✅ |  |
| 5 | assert |  | text_visible | True | ✅ |  |
| 6 | assert |  | text_visible | False | ❌ | assertion |

## 실패 상세
- **step 6 (assert)** — text_visible did not hold. 제안: expected text_visible on '존재하지_않는_텍스트' — verify the target
  - 스크린샷: `screenshots/login_demo_step06.png`

## 회귀 (직전 실행 대비)
_기준: 2026-06-25T06:45:18_
- step 6: absent → **failed**

## 접근성 발견 (3)
- `img-missing-alt` <img> logo.png
- `control-missing-label` <input> 
- `control-missing-label` <input> 