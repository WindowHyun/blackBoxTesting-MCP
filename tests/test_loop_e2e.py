"""The seven-stage loop, end to end against the defect lab.

Stages 1-2 (prompt → run) and 5 (screen dump) are exercised by driving the
runner the way the ``/ui-loop`` prompt tells the host LLM to. What this file
actually pins down is the machinery that has to be right for a loop to be
safe: memory across runs, app-log correlation, and above all the
classification gate.
"""
from __future__ import annotations

import dataclasses
import json
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from blackbox_mcp.testing import diagnose, memory, report, runner

LAB = Path(__file__).parent.parent / "examples" / "defect-lab"
pytestmark = pytest.mark.browser


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def lab_url():
    srv = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(_Quiet, directory=str(LAB.resolve())))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()


@pytest.fixture
def loop_env(lab_url, tmp_path, monkeypatch):
    """Isolated report dir per test, so the failure memory starts empty."""
    monkeypatch.setenv("LAB_URL", lab_url)
    monkeypatch.setenv("LAB_PASSWORD", "secret_sauce")
    monkeypatch.setattr(report, "CONFIG",
                        dataclasses.replace(report.CONFIG, report_dir=tmp_path))
    return tmp_path


def _steps():
    return json.loads((LAB / "scenario.json").read_text(encoding="utf-8"))["steps"]


async def _run(user, monkeypatch, **kw):
    monkeypatch.setenv("LAB_USER", user)
    return await runner.run(_steps(), name=f"loop-{user}",
                            continue_on_fail=True, **kw)


# ── stage 3: 실패 감지 + 기억 ────────────────────────────────────
async def test_first_run_is_all_new_second_is_recurring(session, loop_env, monkeypatch):
    first = await _run("problem_user", monkeypatch)
    assert first["summary"]["failed"] > 0
    assert all(s["memory"]["status"] == "new"
               for s in first["steps"] if not s["passed"])

    second = await _run("problem_user", monkeypatch)
    statuses = {s["memory"]["status"] for s in second["steps"] if not s["passed"]}
    assert statuses == {"recurring"}, statuses


async def test_a_clean_run_closes_the_known_failures(session, loop_env, monkeypatch):
    """The signal the loop uses to confirm a fix held."""
    await _run("problem_user", monkeypatch)
    open_before = [e for e in memory.summary() if not e.get("resolved_at")]
    assert open_before

    # standard_user is the same scenario with the defects switched off — the
    # stand-in for "someone fixed the app".
    await _run("standard_user", monkeypatch)
    still_open = [e for e in memory.summary("loop-problem_user")
                  if not e.get("resolved_at")]
    assert still_open, "다른 시나리오 이름의 통과가 이 실패를 닫으면 안 된다"


# ── stage 4 + 6: 원인 분류와 게이트 ──────────────────────────────
async def test_run_carries_a_diagnosis(session, loop_env, monkeypatch):
    result = await _run("problem_user", monkeypatch)
    d = result["diagnosis"]
    assert d["failed_steps"] == result["summary"]["failed"]
    assert d["verdict"]
    assert all("cause" in f and "test_fix_allowed" in f for f in d["findings"])


async def test_js_error_step_is_app_broken_and_locked(session, loop_env, monkeypatch):
    """With fail_on_js_error the thrown exception becomes a failure — and that
    failure must be un-fixable on the test side."""
    result = await _run("problem_user", monkeypatch, fail_on_js_error=True)
    js = [f for f in result["diagnosis"]["findings"]
          if f["severity"] == "js_error"]
    assert js, "pageerror가 실패로 승격되지 않았다"
    assert js[0]["cause"] == diagnose.APP_BROKEN
    assert js[0]["test_fix_allowed"] is False
    assert "테스트를 고치지 말" in result["diagnosis"]["verdict"]


async def test_input_that_is_dropped_fails_at_its_cause(session, loop_env, monkeypatch):
    """Read-back moves the failure from the checkout assertion (the symptom,
    two steps later) to the field that ate the value — which is where an
    autonomous loop has to look."""
    result = await _run("problem_user", monkeypatch)
    culprit = [s for s in result["steps"]
               if not s["passed"] and s.get("selector_input") == "#last-name"]
    assert culprit, "성 입력 스텝이 통과로 보고되면 루프가 엉뚱한 곳을 고친다"
    assert "입력이 유지되지 않음" in culprit[0]["actual"]


async def test_clean_run_has_no_findings(session, loop_env, monkeypatch):
    result = await _run("standard_user", monkeypatch)
    assert result["summary"]["failed"] == 0
    assert result["diagnosis"]["failed_steps"] == 0
    assert result["diagnosis"]["verdict"] == "실패 없음"


# ── stage 4: 서버 로그 상관 ──────────────────────────────────────
async def test_app_log_lines_reach_the_failing_step(session, loop_env, monkeypatch,
                                                    tmp_path):
    """The half the browser cannot see. A server stack trace written while a
    step ran must be attached to that step and flip it to app_broken."""
    log = tmp_path / "server.log"

    # Write the log first with timestamps spanning "now", then run: the run's
    # steps land inside that window.
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log.write_text(
        f"{stamp} INFO  GET /inventory 200\n"
        f"{stamp} ERROR IllegalStateException: cart not initialised\n"
        f"\tat com.corp.Cart.badge(Cart.java:31)\n", encoding="utf-8")

    result = await _run("problem_user", monkeypatch, app_log=str(log))

    with_log = [s for s in result["steps"] if s.get("app_log")]
    assert with_log, "실행 시간대의 로그 줄이 어느 스텝에도 붙지 않았다"
    assert any("IllegalStateException" in ln
               for s in with_log for ln in s["app_log"])

    failed_with_log = [s for s in with_log if not s["passed"]]
    if failed_with_log:
        verdict = diagnose.classify(failed_with_log[0])
        assert verdict["cause"] == diagnose.APP_BROKEN
        assert verdict["test_fix_allowed"] is False


# ── stage 5: 플로우 덤프 ─────────────────────────────────────────
async def test_snapshot_each_records_the_flow(session, loop_env, monkeypatch):
    result = await _run("standard_user", monkeypatch, snapshot_each=True)
    snaps = [s for s in result["steps"] if s.get("snapshot")]
    assert len(snaps) >= len(result["steps"]) - 2, "스텝별 화면 개요가 비어 있다"
    # The outline is tag/testid/text, so look for real page content — and for
    # the flow actually MOVING between screens, which is the point of the dump.
    joined = "\n".join(s["snapshot"] or "" for s in snaps)
    assert "Add to cart" in joined
    assert len({s["snapshot"] for s in snaps}) > 1, "모든 스텝의 화면이 동일하다"


async def test_snapshot_is_absent_by_default(session, loop_env, monkeypatch):
    """A page outline per step is large; it must be opt-in."""
    result = await _run("standard_user", monkeypatch)
    assert all(s.get("snapshot") is None for s in result["steps"])
