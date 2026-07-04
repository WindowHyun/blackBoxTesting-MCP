# 샘플 리포트 (Demo)

`run_scenario`가 생성하는 리포트 예시. "로그인 흐름"을 실행하되 마지막에 의도적으로
실패하는 단언을 넣어 **통과/실패 + 실패 상세 + 스크린샷 + AI 제안 + 환경 메타**를 한
번에 보여준다.

- `sample_report.html` — 단일 self-contained HTML (스크린샷 base64 임베드, 외부 의존성 0).
  브라우저로 바로 열면 됨. **이게 메인 산출물.**
- `sample_report.md` — 사람이 읽는 마크다운 요약.
- `sample_report.json` — 기계 판독용 전체 결과(DESIGN §6.1 스키마).

시나리오(요약):
```
navigate → type(email) → type(password) → click(submit) → assert "로그인됨"(pass) → assert "없는텍스트"(fail)
결과: 5/6 passed (0.833)
```
한 리포트에 담긴 것:
- 스텝 표(셀렉터 `resolved_by`, 소요시간, 심각도)
- 실패 스텝 6: 스크린샷 + AI 수정 제안(SM-05)
- **회귀(SM-07)**: 직전 실행 대비 step 6 `absent → failed`
- **접근성 발견(SM-09)**: img-missing-alt, control-missing-label ×2
- 환경 메타(OS/Python/Playwright)·자격증명 마스킹 배지
