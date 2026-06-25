# UI Blackbox Report — login_demo

**4/5 passed** (rate 0.8) · 237 ms · 2026-06-25T05:56:55

_env: Linux · py3.11.15 · playwright 1.60.0 · chromium_

| # | action | resolved | expected | actual | result | sev |
|---|---|---|---|---|---|---|
| 1 | navigate |  | navigation | {'title': 'Blackbox Fixture', 'url': 'f… | ✅ |  |
| 2 | interact | testid | type ok | typed | ✅ |  |
| 3 | interact | testid | click ok | clicked | ✅ |  |
| 4 | assert |  | text_visible | True | ✅ |  |
| 5 | assert |  | text_visible | False | ❌ | assertion |

## 실패 상세
- **step 5 (assert)** — text_visible did not hold. 제안: expected text_visible on '존재하지_않는_텍스트' — verify the target
  - 스크린샷: `screenshots/login_demo_step05.png`