# UI Blackbox Tester MCP

자연어 지시만으로 UI를 검증하는 MCP 서버. Claude Desktop에 브라우저 조작 능력을
붙여, 테스트 코드 없이 "로그인 흐름이 되는지 확인해줘"라고 말하면 Claude가 직접
브라우저를 열고 클릭·입력·검증한 뒤 리포트를 남긴다. (블랙박스 방식)

> 설계 근거는 [`DESIGN.md`](./DESIGN.md), 마일스톤은 [`ROADMAP.md`](./ROADMAP.md),
> 실행 플레이북은 [`HARNESS.md`](./HARNESS.md), 에이전트 컨텍스트는
> [`CLAUDE.md`](./CLAUDE.md). 요구사항은 PRD v0.6 기준.

## 스택
Python 3.11+ · Playwright(Chromium) · MCP 공식 SDK(FastMCP) · stdio · Claude Desktop

## 설치
```bash
pip install -e .
```
Chromium은 서버 **최초 실행 시 자동 설치**된다(D1). 별도 명령 불필요.

## Claude Desktop 등록
`claude_desktop_config.json`에 한 블록 추가 (예시: `claude_desktop_config.example.json`):
```json
{
  "mcpServers": {
    "ui-blackbox": { "command": "python", "args": ["-m", "blackbox_mcp.server"] }
  }
}
```

## 환경변수
`.env.example` 참고. 주요 항목: `HEADLESS`, `BROWSER`, `REPORT_DIR`,
`SCENARIO_DIR`, `DEFAULT_WAIT_UNTIL`.

## 구조
```
blackbox_mcp/
  server.py        # FastMCP 부팅 + ensure_chromium + register_all
  bootstrap.py     # Chromium 자동 설치 (D1)
  config.py        # 환경변수
  browser/         # 세션 싱글톤 · 이벤트 버퍼 · 셀렉터 체인(D2)
  testing/         # 시나리오 실행 · 리포트(D3) · 라이브러리 · 마스킹
  tools/           # MCP Tool = 파일 1개 (레지스트리 자동 등록)
```
**Tool 추가 = `tools/`에 파일 1개 + `tools/__init__.py`에 import 한 줄.**
`server.py`는 수정하지 않는다.

## 구현 현황 (Phase) — 상세는 [`ROADMAP.md`](./ROADMAP.md)
- [x] **Phase 0** 스캐폴드: 레지스트리(Tool=파일1개), 세션 싱글톤, config, 부트스트랩
- [x] **Phase 1** 코어 PoC: `navigate` · `snapshot`(aria_snapshot, Q1 실측) · lifespan 정리
- [x] **Phase 2** 상호작용·검증: `interact` · `assert_`(5종) · `screenshot` · 콘솔/네트워크
      · D2 셀렉터 체인(`resolved_by`) · crash-recovery
- [x] **Phase 3** `run_scenario` + 리포트 JSON/MD/**HTML(SM-04)** + AI 근거·제안(SM-05)
      · 셀렉터투명성/에러귀속(SM-06) · 환경메타·심각도(SM-08) · 마스킹. 샘플: [`examples/`](./examples/)
- [x] **Phase 4** `wait` · `switch_frame` · `expect_dialog` · `reset_session` · `HEADLESS`
- [x] **Phase 5** `generate_scenario`(작성 키트 + sampling fallback) · `save/load/list_scenario`
- [ ] 백로그: 회귀비교(SM-07) · a11y(SM-09) · dom 모드 트리화(T1.5)

테스트 47건 green (단위 + `file://` 통합 + E2E).

## 개발
```bash
pip install -e ".[dev]"
pytest
```
