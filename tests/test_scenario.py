"""Phase 3 — scenario runner + report (SM-01,02,03,04,06,08)."""
from __future__ import annotations

import dataclasses

import pytest
from conftest import fixture_url

from blackbox_mcp.testing import report, runner
from blackbox_mcp.tools.scenario import run_scenario


@pytest.fixture
def report_dir(tmp_path, monkeypatch):
    cfg = dataclasses.replace(report.CONFIG, report_dir=tmp_path)
    monkeypatch.setattr(report, "CONFIG", cfg)
    return tmp_path


def _login_steps():
    return [
        {"action": "navigate", "url": fixture_url("basic.html"), "wait_until": "load"},
        {"action": "interact", "type": "type", "selector": "testid=email", "value": "u@x.com"},
        {"action": "interact", "type": "click", "selector": "testid=submit"},
        {"action": "assert", "kind": "text_visible", "target": "로그인됨"},
    ]


async def test_passing_scenario(session):
    res = await runner.run(_login_steps(), name="login")
    assert res["summary"]["total"] == 4
    assert res["summary"]["failed"] == 0
    assert res["summary"]["pass_rate"] == 1.0
    # resolved_by recorded on interact steps (SM-06)
    click = res["steps"][2]
    assert click["resolved_by"] == "testid"
    # meta present (SM-08)
    assert res["meta"]["playwright"] and res["meta"]["credentials_masked"] is True


async def test_stops_on_failure(session):
    steps = _login_steps() + [{"action": "assert", "kind": "text_visible", "target": "절대없음"}]
    # inject a failing assert in the middle
    steps = [steps[0], {"action": "assert", "kind": "text_visible", "target": "절대없음"}, steps[1]]
    res = await runner.run(steps, name="stop", continue_on_fail=False)
    assert res["summary"]["failed"] == 1
    # Execution stops after the failing step, but the un-run remainder is
    # reported as skipped instead of vanishing (total = whole scenario).
    assert res["summary"]["total"] == 3
    assert res["summary"]["skipped"] == 1
    assert res["steps"][2]["skipped"] is True
    bad = res["steps"][1]
    assert bad["passed"] is False
    assert bad["severity"] == "assertion"
    assert bad["ai_suggestion"]            # failure hint present (SM-05)
    assert bad["screenshot"] is None or bad["screenshot"].startswith("screenshots/")


async def test_continue_on_fail_runs_all(session):
    steps = [
        {"action": "navigate", "url": fixture_url("basic.html"), "wait_until": "load"},
        {"action": "assert", "kind": "text_visible", "target": "절대없음"},
        {"action": "assert", "kind": "text_visible", "target": "로그인"},
    ]
    res = await runner.run(steps, name="cont", continue_on_fail=True)
    assert res["summary"]["total"] == 3
    assert res["summary"]["failed"] == 1


async def test_scenario_supports_extension_actions(session):
    # iframe with an inner button; scenario switches into it and asserts
    await session.page.set_content(
        "<iframe id='f' srcdoc=\"<button data-testid='inner'>안쪽</button>\"></iframe>"
    )
    await session.page.wait_for_timeout(100)
    steps = [
        {"action": "switch_frame", "selector": "#f"},
        {"action": "assert", "kind": "element_visible", "target": "testid=inner"},
        {"action": "screenshot"},
        {"action": "switch_frame", "selector": None},
    ]
    res = await runner.run(steps, name="frames", continue_on_fail=True)
    assert res["summary"]["failed"] == 0
    # the explicit screenshot step captured an image
    shot_step = next(s for s in res["steps"] if s["action"] == "screenshot")
    assert shot_step["screenshot"] is None or shot_step["screenshot"].startswith("screenshots/")


async def test_credentials_masked_in_report(session, report_dir):
    import os
    os.environ["TEST_PW"] = "supersecret"
    steps = [
        {"action": "navigate", "url": fixture_url("basic.html"), "wait_until": "load"},
        {"action": "interact", "type": "type", "selector": "testid=password", "value": "${TEST_PW}"},
    ]
    res = await runner.run(steps, name="mask", continue_on_fail=True)
    raw_dump = str(res["steps"][1]["raw"])
    assert "supersecret" not in raw_dump   # masked / not resolved in report


async def test_report_writes_all_formats(session, report_dir):
    res = await run_scenario(_login_steps(), name="rep", report_format="all")
    files = res["report_files"]
    assert {"json", "md", "html"} <= set(files)
    htmls = list(report_dir.glob("*.html"))
    assert htmls and "PASS" in htmls[0].read_text(encoding="utf-8")


async def test_consent_banner_can_be_dismissed_from_a_saved_scenario(session, report_dir):
    """A banner-clearing step must survive being saved and replayed.

    `dismiss_banners` was registered as an MCP tool and recorded by the
    recorder, but the runner had no branch for it — so the documented workflow
    (build the flow in chat, save it, replay it in CI) answered "unknown action"
    on every real site that gates content behind a consent overlay.
    """
    await session.page.set_content(
        "<div id='cookie-consent'>쿠키 사용에 동의해 주세요"
        "<button onclick=\"document.getElementById('cookie-consent').remove()\">"
        "모두 동의</button></div><button data-testid='go'>계속</button>"
    )
    res = await runner.run([{"action": "dismiss_banners"}], name="consent")
    step = res["steps"][0]
    assert step["passed"] is True, step["actual"]
    assert "unknown action" not in str(step["actual"])
    assert (await runner.assert_("element_visible", "#cookie-consent"))["passed"] is False


async def test_unknown_action_lists_the_supported_verbs(session, report_dir):
    res = await runner.run([{"action": "teleport"}], name="bogus")
    step = res["steps"][0]
    assert step["passed"] is False
    assert "unknown action: teleport" in step["actual"]
    # the hint must enumerate real verbs so the host LLM can self-correct
    assert "dismiss_banners" in step["ai_suggestion"]
    assert "navigate" in step["ai_suggestion"]


async def test_run_scenario_reports_progress_per_step(session, report_dir):
    """A scenario is ONE long tool call; silence is what clients time out on."""
    seen = []

    class _Ctx:
        async def report_progress(self, progress, total=None, message=None):
            seen.append((progress, total, message))

    await run_scenario(_login_steps(), name="prog", save_report=False, ctx=_Ctx())
    assert seen, "no progress reported"
    assert seen[-1][0] == seen[-1][1], f"final progress not complete: {seen[-1]}"
    assert all(a[1] == len(_login_steps()) for a in seen)


async def test_progress_failure_does_not_fail_the_run(session, report_dir):
    """A client that mishandles progress must not break the run it narrates."""
    class _BadCtx:
        async def report_progress(self, progress, total=None, message=None):
            raise RuntimeError("client hung up")

    res = await run_scenario(_login_steps(), name="badprog", save_report=False,
                             ctx=_BadCtx())
    assert res["summary"]["failed"] == 0


async def test_max_duration_truncates_instead_of_overrunning(session, report_dir):
    """Past the budget, remaining steps are reported as skipped rather than
    running on past the caller's timeout."""
    steps = [{"action": "navigate", "url": fixture_url("basic.html")}]
    steps += [{"action": "wait", "ms": 400} for _ in range(10)]
    res = await runner.run(steps, name="budget", max_duration_s=0.5)

    assert res.get("truncated"), "run was not truncated"
    assert res["truncated"]["ran"] < len(steps)
    assert res["summary"]["total"] == len(steps)  # nothing vanishes from the report
    assert res["summary"]["skipped"] > 0
    skipped = [s for s in res["steps"] if s.get("skipped")]
    assert "시간 예산" in skipped[0]["actual"]


async def test_no_budget_runs_every_step(session, report_dir):
    steps = [{"action": "navigate", "url": fixture_url("basic.html")},
             {"action": "wait", "ms": 10}]
    res = await runner.run(steps, name="nobudget")
    assert "truncated" not in res
    assert res["summary"]["skipped"] == 0
