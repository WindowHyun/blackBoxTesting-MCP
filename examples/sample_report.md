# UI Blackbox Report — checkout_login_demo

**8/11 passed** (rate 0.889) · **2 skipped** · 1295 ms · 2026-07-14T02:29:21

_대상: file:///home/user/blackBoxTesting-MCP/examples/demo_page.html_

_최근 2회: ✅❌_

_env: Linux · py3.11.15 · playwright 1.61.0 · chromium 141.0.7390.37 · 1280x720_

| # | action | resolved | expected | actual | result | sev |
|---|---|---|---|---|---|---|
| 1 | navigate `REQ-101` |  | 도착 (2xx/3xx) | “데모 스토어 — UI Blackbox 샘플” · HTTP 200 | ✅ |  |
| 2 | assert `REQ-101` |  | text_visible | True | ✅ | high |
| 3 | interact `REQ-102` | testid | type ok | typed | ✅ |  |
| 4 | interact `REQ-102` | testid | type ok | typed | ✅ | high |
| 5 | interact | testid | click ok | clicked | ✅ |  |
| 6 | assert `REQ-103` |  | text_visible | True | ✅ ⚠flaky |  |
| 7 | mock_route |  | mock armed | **/api/points** | ✅ |  |
| 8 | assert `REQ-104` |  | 2 | 2 | ✅ |  |
| 9 | assert `REQ-105` |  | text_visible | False | ❌ | assertion |
| 10 | interact |  | None | not run (step 9 failed) | ⏭ |  |
| 11 | assert |  | None | not run (step 9 failed) | ⏭ |  |

## 실패 상세
- **step 9 (assert) `REQ-105` [blocker]** — text_visible did not hold. 제안: expected text_visible on '포인트 잔액' — verify the target
  - 페이지: file:///home/user/blackBoxTesting-MCP/examples/demo_page.html
  - 스크린샷: `screenshots/20260714_022921_768085_checkout_login_demo_step09.png`

## 회귀 (직전 실행 대비)
_기준: 2026-07-14T02:29:20_
- step 9: absent → **failed**
- step 10: absent → **failed**
- step 11: absent → **failed**

## 접근성 발견 (2)
- `img-missing-alt` <img> banner.png
- `control-missing-label` <input> 

---
_실패 원인·제안은 **규칙 기반 힌트**입니다 — 대화형(Claude) 실행 시 호스트 LLM이 분석으로 보강합니다._