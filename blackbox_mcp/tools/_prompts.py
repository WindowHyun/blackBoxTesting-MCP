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
         "expect_dialog · reset_session · run_scenario · generate_scenario · "
         "save_scenario · load_scenario · list_scenarios.")


@prompt(name="ui-test", description="ui-blackbox 도구로 UI를 테스트한다 (자연어 작업 입력)")
def ui_test(task: str) -> str:
    return (f"{_ONLY}\n\n다음 작업을 수행하고, 각 단계의 결과(통과/실패)와 발견한 "
            f"콘솔/네트워크 에러를 요약해줘.\n\n작업: {task}")


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
    return (f"{_ONLY}\n\n먼저 `use_real_browser`를 호출해 실제 크롬(영구 프로필)으로 "
            f"전환해. 로그인 페이지로 이동한 뒤, **로그인/캡차가 필요하면 사용자가 그 "
            f"창에서 직접 처리하도록 안내하고 잠시 대기**한 다음 작업을 이어가.{target}\n\n"
            f"작업: {task}")


@prompt(name="ui-generate",
        description="페이지를 분석해 재사용 시나리오를 생성하고 이름 붙여 저장한다")
def ui_generate(description: str, url: str, name: str = "") -> str:
    save = f" 완성하면 '{name}'(으)로 저장해줘." if name else " 적당한 이름으로 저장해줘."
    return (f"{_ONLY}\n\n`generate_scenario(description, url)`로 작성 키트를 받아 "
            f"steps를 만든 뒤 `save_scenario`로 저장해.{save}\n\n"
            f"URL: {url}\n설명: {description}")
