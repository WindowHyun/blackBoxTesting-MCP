"""MCP Prompts → slash commands in Claude Desktop.

These appear as `/ui-test`, `/ui-scenario`, `/ui-generate` in the input box. Each
returns a primer that scopes the request to the ui-blackbox tools, so a
competing browser tool (e.g. "Claude in Chrome") doesn't intercept the request.

Not MCP tools — registered via the same registry with @prompt (underscore-named
module so the tools package importer doesn't treat it as a tool).
"""
from __future__ import annotations

from ._registry import prompt

_ONLY = ("**ui-blackbox MCP 서버의 도구만** 사용해. 다른 브라우저 도구"
         "(예: Claude in Chrome, 일반 브라우저 커넥터)는 절대 쓰지 마. "
         "사용 가능한 도구: navigate · snapshot · screenshot · interact · assert_ · "
         "get_console_logs · get_network_errors · wait · switch_frame · "
         "expect_dialog · reset_session · use_real_browser · dismiss_banners · "
         "save_state · load_state · list_states · mock_route · unmock_route · "
         "run_scenario · save_report · generate_scenario · save_scenario · "
         "load_scenario · list_scenarios · status.")

# Observation → tool selection matrix (qa-autopilot pattern): tells the host
# LLM which escalation each symptom calls for, instead of trial and error.
# Principle: start with the simple tools; escalate only on the listed signals.
_MATRIX = (
    "\n\n**상황별 도구 선택** (기본 도구로 시작, 아래 신호가 보일 때만 승격):\n"
    "- 클릭이 'intercepts pointer events'로 막힘 → `dismiss_banners`(동의/쿠키 배너)\n"
    "- 로그인/캡차 장벽 → `use_real_browser`(사용자가 그 창에서 직접 로그인) 후 "
    "`save_state`로 저장 — 다음부턴 headless에서 `load_state`로 재사용\n"
    "- 게스트/회원 등 역할 비교 → 역할별 `save_state` 해두고 `reset_session`+"
    "`load_state`로 전환하며 같은 흐름 반복\n"
    "- 요소가 늦게 나타남/타이밍 이슈 → `wait(selector=...)`(고정 ms 지연보다 우선)\n"
    "- 외부 API가 불안정/미구현이라 flaky → `mock_route`로 해당 요청만 로컬 응답 대체 "
    "(reset 후엔 다시 걸 것)\n"
    "- 에러 페이지 자체를 검증 → navigate 스텝에 `expect_status` "
    "(mock_route status=500과 조합하면 오프라인 검증 가능)\n"
    "- 원인 불명 실패 → `status`로 세션 상태 확인 + `get_console_logs`/"
    "`get_network_errors`로 증거 수집\n"
    "- 페이지 구조를 모름 → `snapshot`(트리) 또는 `generate_scenario`(작성 키트)")

# Every test flow must end with a saved report.
_FINISH = ("\n\n**마지막에 반드시 `save_report(report_format='all')`를 호출해 "
           "JSON/MD/HTML 리포트를 저장하고, 저장된 파일 경로를 알려줘.** "
           "(run_scenario를 썼다면 그건 자체적으로 리포트를 저장하므로 생략 가능.)")


@prompt(name="ui-test", description="ui-blackbox 도구로 UI를 테스트하고 리포트를 남긴다")
def ui_test(task: str) -> str:
    return (f"{_ONLY}{_MATRIX}\n\n다음 작업을 수행하고, 각 단계의 결과(통과/실패)와 발견한 "
            f"콘솔/네트워크 에러를 요약해줘.\n\n"
            f"작업: {task}{_FINISH}")


@prompt(name="ui-scenario",
        description="자연어 설명으로 시나리오를 만들어 실행하고 리포트를 남긴다")
def ui_scenario(description: str, url: str = "") -> str:
    target = f" 대상 URL: {url}." if url else ""
    return (f"{_ONLY}\n\n아래 설명을 바탕으로 시나리오 steps를 구성해 `run_scenario`로 "
            f"실행하고, JSON/MD/HTML 리포트를 저장(report_format='all')해줘. "
            f"필요하면 `generate_scenario`로 페이지 구조를 먼저 파악해.{target}\n\n"
            f"검증할 흐름: {description}")


@prompt(name="ui-login",
        description="실제 크롬(로그인 유지)으로 전환해 로그인이 필요한 사이트를 테스트한다")
def ui_login(task: str, url: str = "") -> str:
    target = f" 대상: {url}." if url else ""
    return (f"{_ONLY}\n\n`use_real_browser`를 **한 번만** 호출해 실제 크롬(영구 프로필)으로 "
            f"전환해(이미 떠 있으면 같은 창을 재사용하니 다시 호출하지 마). 로그인 페이지로 "
            f"이동한 뒤, **로그인/캡차가 필요하면 사용자가 그 창에서 직접 처리하도록 안내하고 "
            f"잠시 대기**한 다음 같은 창에서 작업을 이어가. 절대 새 창을 열거나 재로그인을 "
            f"요구하지 마. 로그인이 확인되면 `save_state`로 상태를 저장해 두면 다음엔 "
            f"headless에서 `load_state`로 재사용할 수 있다고 안내해.{target}\n\n"
            f"작업: {task}{_FINISH}")


@prompt(name="ui-generate",
        description="페이지를 분석해 재사용 시나리오를 생성하고 이름 붙여 저장한다")
def ui_generate(description: str, url: str, name: str = "") -> str:
    save = f" 완성하면 '{name}'(으)로 저장해줘." if name else " 적당한 이름으로 저장해줘."
    return (f"{_ONLY}\n\n`generate_scenario(description, url)`로 작성 키트를 받아 "
            f"steps를 만든 뒤 `save_scenario`로 저장해.{save}\n\n"
            f"URL: {url}\n설명: {description}")


@prompt(name="ui-sync",
        description="저장된 시나리오를 현재 페이지와 대조해 변경점을 찾아 갱신한다(변경 감지)")
def ui_sync(name: str, url: str = "") -> str:
    target = f" 페이지 URL: {url} (없으면 시나리오의 navigate 스텝 URL 사용)." if url \
        else " 페이지 URL은 시나리오의 navigate 스텝에서 가져와."
    return (f"{_ONLY}\n\n저장된 시나리오가 현재 페이지와 여전히 맞는지 **변경 감지**를 "
            f"수행해줘.{target}\n\n"
            f"절차:\n"
            f"1. `load_scenario('{name}')`로 기존 steps를 읽는다.\n"
            f"2. `generate_scenario`로 현재 페이지의 작성 키트(요소 목록+추천 셀렉터)를 "
            f"새로 수집한다.\n"
            f"3. 기존 steps의 셀렉터/URL/기대값을 키트와 대조해 변경을 분류한다:\n"
            f"   - **셀렉터 변경**(testid/텍스트가 바뀜) → 해당 스텝의 selector만 교체\n"
            f"   - **URL 변경** → navigate url과 url_is/url_contains 기대값 갱신\n"
            f"   - **메시지/텍스트 변경** → assert의 target/expected 갱신\n"
            f"   - **기능 추가** → 새 스텝 제안(기존 번호 뒤에 추가)\n"
            f"   - **기능 제거** → 해당 스텝 삭제 제안(먼저 사용자에게 확인)\n"
            f"4. 변경이 없으면 '변경 없음'으로 종료. 변경이 있으면 항목별 diff를 보여주고 "
            f"동의를 받아 `save_scenario(name, steps, overwrite=True)`로 갱신한다.\n"
            f"5. 갱신했다면 `run_scenario`로 재실행해 green을 확인하고 리포트를 남긴다.\n\n"
            f"시나리오 이름: {name}")
