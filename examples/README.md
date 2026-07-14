# 샘플 리포트 (Demo)

`run_scenario`가 생성하는 리포트 예시. `demo_page.html`(로그인+주문 내역 데모 페이지)을
대상으로 실행하되 마지막 단언을 의도적으로 실패시켜, 리포트의 모든 기능을 한 화면에서
보여준다.

- `sample_report.html` — 단일 self-contained HTML (스크린샷 base64 임베드, 외부 의존성 0).
  브라우저로 바로 열면 됨. **이게 메인 산출물.**
- `sample_report.md` — 사람이 읽는 마크다운 요약.
- `sample_report.json` — 기계 판독용 전체 결과(DESIGN §6.1 스키마).
- `demo_page.html` — 샘플 생성용 픽스처(지연 로그인 = flaky 데모, alt 없는 이미지 =
  a11y 데모, 콘솔/네트워크 에러 데모 포함).

시나리오(요약):
```
navigate → assert 제목 → type(email) → type(${DEMO_PASSWORD}=마스킹)
→ click(로그인) → assert 환영(⚠flaky: retry 후 통과) → mock_route(API 모킹)
→ count 주문행=2 → assert "포인트 잔액"(의도적 FAIL) → 이후 2스텝 SKIP
결과: 8/11 passed (rate 0.889) · 1 failed · 2 skipped
```

한 리포트에 담긴 것 (직군별):
- **PM** — 헤더 요약(8/11·88%), PASS/FAIL/SKIP 칩, **최근 실행 트렌드**(✓✗ 칩),
  대상 URL
- **기획/QA** — 스텝별 **`REQ-…` 태그**와 `priority`(실패 상세 `[blocker]`),
  **⚠flaky 마킹**(retry 후 통과), **미실행 스텝 SKIP 표기**(소실 없음)
- **개발** — 실패 스텝의 **페이지 URL**·스크린샷·AI 수정 제안(SM-05), 스텝 귀속
  콘솔/네트워크 에러, 셀렉터 `resolved_by`, chromium 실버전·뷰포트 메타
- **회귀(SM-07)** — 직전 실행 대비 `absent → failed` diff
- **접근성(SM-09)** — img-missing-alt, control-missing-label
- **보안** — `${DEMO_PASSWORD}` 완전 마스킹(`***`) — 세 포맷 모두 평문 부재 검증됨

재생성: 저장소 루트에서 데모 페이지를 대상으로 같은 시나리오를 2회 실행(트렌드/회귀
baseline)한 뒤 최신 리포트를 이 폴더로 복사하고, HTML을 Chromium으로 렌더해
`sample_report_preview.png`(full-page)를 캡처한다.
