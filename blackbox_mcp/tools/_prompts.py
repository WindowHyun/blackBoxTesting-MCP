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
         "load_scenario · list_scenarios · status · "
         "expect_popup · list_tabs · switch_tab · expect_download · get_dialogs · "
         "get_failure_memory · diagnose_run · propose_repair.")

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


@prompt(name="ui-loop",
        description="자율 루프: 실행 → 실패 감지/기억 → 원인 추적 → 플로우 덤프 → "
                    "수정 제안(승인 후 반영) → 회귀 검증")
def ui_loop(name: str, app_log: str = "") -> str:
    """The seven stages, wired so the unsafe one cannot fire by accident.

    Stage 6 is the whole reason this prompt is explicit rather than left to
    improvisation: a loop that repairs whatever is red converges on a green
    suite that asserts nothing. The classification gate is stated as a hard
    rule here so the host LLM does not reason its way past it.
    """
    log_arg = f", app_log='{app_log}'" if app_log else ""
    log_note = (f"\n   - 서버 로그 `{app_log}`의 줄이 스텝별로 붙는다(app_log 필드)."
                if app_log else
                "\n   - 서버 로그를 붙이려면 app_log='<경로>'로 다시 호출할 것"
                "(브라우저만으로는 서버가 던진 예외를 볼 수 없다).")
    return (
        f"{_ONLY}\n\n"
        f"시나리오 '{name}'에 대해 **자율 테스트 루프 한 바퀴**를 돌려줘. "
        f"각 단계의 결과를 보고하고, 6단계는 반드시 승인을 받고 진행해.\n\n"

        f"**1~2. 실행**\n"
        f"   `load_scenario('{name}')` → `run_scenario(steps, name='{name}', "
        f"continue_on_fail=True, snapshot_each=True{log_arg})`\n"
        f"   - continue_on_fail: 첫 실패에서 멈추면 결함을 하나씩만 보게 된다.\n"
        f"   - snapshot_each: 스텝별 페이지 개요가 남아 플로우를 읽을 수 있다.{log_note}\n\n"

        f"**3. 실패 감지 / 기억**\n"
        f"   결과의 `summary`와 실패 스텝을 정리하고, `get_failure_memory('{name}')`로 "
        f"이력을 대조해. 각 실패의 `memory.status`를 보고해:\n"
        f"   - `new` — 처음 보는 실패. 원인 추적이 필요하다.\n"
        f"   - `recurring` — 만성. 이미 아는 문제이니 처음부터 다시 진단하지 말고 "
        f"기존 결론을 재확인만 해.\n"
        f"   - `regressed` — 고쳤다가 재발. **이전 수정이 유지되지 않았다는 뜻**이라 "
        f"가장 우선순위가 높다.\n\n"

        f"**4. 원인 추적**\n"
        f"   `diagnose_run()`으로 실패를 원인별로 분류해. 각 실패의 근거"
        f"(console/pageerror · network · dialogs · app_log · 스크린샷 · page_url)를 "
        f"인용해서 설명하고, 분류가 타당한지 검토해. 분류가 틀렸다고 판단하면 "
        f"근거를 들어 반박하고 사람에게 확인을 요청해.\n\n"

        f"**5. 플로우 이해**\n"
        f"   스텝별 `snapshot`과 스크린샷을 순서대로 읽어 **어떤 화면에서 무엇이 "
        f"어긋났는지** 한 문단으로 설명해. 실패 스텝만이 아니라 그 직전 스텝의 화면을 "
        f"같이 봐야 원인이 보인다.\n\n"

        f"**6. 자가 수정 — 여기서 규칙을 지켜**\n"
        f"   `diagnose_run`의 `cause`에 따라 행동이 완전히 다르다:\n"
        f"   - `app_broken` → **테스트를 절대 고치지 마.** 앱이 예외를 던졌거나 서버가 "
        f"5xx를 반환한 것이다. 테스트를 고치면 결함을 덮는다. 재현 절차와 증거를 정리해 "
        f"보고하고 여기서 멈춰.\n"
        f"   - `environment` → 접근 설정 문제(프록시·인증서·DNS). 테스트도 앱도 아니다. "
        f"`doctor --url`로 확인할 것을 안내하고 멈춰.\n"
        f"   - `unknown` → 자동 판단 불가. 사람에게 확인을 요청하고 멈춰.\n"
        f"   - `scenario_bug` → 스텝 정의 오류. 스키마에 맞게 고쳐 제안해.\n"
        f"   - `ui_changed` → **이 경우에만** `propose_repair(selector=..., "
        f"cause='ui_changed')`로 현재 페이지의 대체 후보를 받아, D2 우선순위"
        f"(testid → role+name → text → css)에 맞는 새 스텝을 구성해.\n"
        f"   어느 경우든 **먼저 diff를 보여주고 동의를 받은 뒤에만** "
        f"`save_scenario('{name}', steps, overwrite=True)`로 저장해. "
        f"동의 없이 저장하지 마.\n\n"

        f"**7. 회귀 검증**\n"
        f"   수정했다면 `run_scenario`를 다시 실행해 green을 확인하고, 리포트의 "
        f"`regression`으로 **다른 스텝이 깨지지 않았는지** 확인해. 통과했다면 다음 "
        f"실행에서 해당 실패가 `resolved`로 닫힌다.\n"
        f"   수정하지 않았다면(앱 결함/환경/불명) 그 사실과 근거를 결론으로 남겨.\n\n"

        f"마지막에 **한 줄 결론**을 줘: 무엇이 깨졌고 · 원인이 어느 쪽이며 · "
        f"무엇을 했고 · 사람이 무엇을 해야 하는지.")
