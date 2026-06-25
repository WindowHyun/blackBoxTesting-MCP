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

## 구현 현황 (Phase)
- [x] **Phase 0** 스캐폴드: 레지스트리, 세션 싱글톤, config, 부트스트랩
- [x] 코어 read: `navigate` `snapshot`(aria_snapshot) `screenshot`
      `get_console_logs` `get_network_errors`
- [x] 액션/검증: `interact` `assert_` (D2 셀렉터 체인)
- [x] 확장: `wait` `switch_frame` `reset_session`
- [x] 라이브러리 저장: `save_scenario` `load_scenario` `list_scenarios`
- [ ] **Phase 1** snapshot 크기 실측(Q1) · DOM 모드 정련
- [ ] **Phase 3** `run_scenario` 실행 엔진 · 리포트 JSON/MD/**HTML(SM-04)**
      + 강화: AI 판단근거·수정제안(SM-05) · 스텝캡처/셀렉터투명성/에러귀속(SM-06)
      · 환경메타·심각도(SM-08) · 회귀비교(SM-07) · a11y(SM-09)
- [ ] **Phase 4** `expect_dialog`
- [ ] **Phase 5** `generate_scenario` 작성 키트(+sampling fallback)

## 개발
```bash
pip install -e ".[dev]"
pytest
```
