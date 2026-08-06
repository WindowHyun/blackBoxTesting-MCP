"""Failure memory (new/recurring/regressed) and app-log correlation."""
from __future__ import annotations

import dataclasses
import time

import pytest

from blackbox_mcp.testing import applog, memory, report


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Every test gets its own reports dir, so memory can't leak between them."""
    monkeypatch.setattr(report, "CONFIG",
                        dataclasses.replace(report.CONFIG, report_dir=tmp_path))
    yield tmp_path


def _result(name="s", run_id="r1", steps=None):
    return {"name": name, "run_id": run_id, "steps": steps or []}


def _failed(step=1, actual="False", selector="testid=cart", severity="assertion"):
    return {"step": step, "action": "assert", "selector_input": selector,
            "actual": actual, "passed": False, "severity": severity}


# ── fingerprinting ───────────────────────────────────────────────
def test_same_failure_on_a_different_port_is_one_fingerprint():
    """Otherwise every local run looks like a brand-new problem and the memory
    is worthless."""
    a = _failed(actual="expected complete.html, got http://127.0.0.1:5111/checkout.html")
    b = _failed(actual="expected complete.html, got http://127.0.0.1:9873/checkout.html")
    assert memory.fingerprint("s", a) == memory.fingerprint("s", b)


def test_different_selectors_are_different_fingerprints():
    assert memory.fingerprint("s", _failed(selector="#a")) != \
           memory.fingerprint("s", _failed(selector="#b"))


def test_step_number_does_not_affect_the_fingerprint():
    """Inserting a step earlier must not make every later failure look new."""
    assert memory.fingerprint("s", _failed(step=3)) == \
           memory.fingerprint("s", _failed(step=9))


def test_field_boundaries_cannot_collide():
    """With a space separator "a b"+"c" and "a"+"b c" would hash the same."""
    assert memory.fingerprint("s", _failed(selector="a b", actual="c")) != \
           memory.fingerprint("s", _failed(selector="a", actual="b c"))


# ── new → recurring → resolved → regressed ───────────────────────
def test_first_failure_is_new():
    result = _result(steps=[_failed()])
    memory.annotate(result)
    assert result["steps"][0]["memory"]["status"] == "new"
    assert result["steps"][0]["memory"]["seen_before"] == 0


def test_second_occurrence_is_recurring():
    memory.annotate(_result(run_id="r1", steps=[_failed()]))
    second = _result(run_id="r2", steps=[_failed()])
    memory.annotate(second)
    mem = second["steps"][0]["memory"]
    assert mem["status"] == "recurring" and mem["seen_before"] == 1


def test_a_clean_run_resolves_the_known_failure():
    memory.annotate(_result(run_id="r1", steps=[_failed()]))
    memory.annotate(_result(run_id="r2", steps=[{"step": 1, "passed": True}]))

    entries = memory.summary("s")
    assert entries[0]["resolved_at"] is not None
    assert "did not recur" in entries[0]["resolution"]


def test_failing_again_after_a_fix_is_regressed():
    memory.annotate(_result(run_id="r1", steps=[_failed()]))
    memory.annotate(_result(run_id="r2", steps=[{"step": 1, "passed": True}]))
    third = _result(run_id="r3", steps=[_failed()])
    memory.annotate(third)
    assert third["steps"][0]["memory"]["status"] == "regressed"


def test_an_early_stopped_run_never_resolves_anything():
    """A run that bailed at step 1 proves nothing about the steps it skipped —
    closing them would report fixes that never happened."""
    memory.annotate(_result(run_id="r1", steps=[_failed(step=5)]))
    memory.annotate(_result(run_id="r2", steps=[
        _failed(step=1, selector="#other"),
        {"step": 5, "passed": False, "skipped": True},
    ]))
    known = [e for e in memory.summary("s") if e["selector"] == "testid=cart"]
    assert known[0]["resolved_at"] is None


def test_memory_is_scoped_per_scenario():
    memory.annotate(_result(name="login", run_id="r1", steps=[_failed()]))
    memory.annotate(_result(name="checkout", run_id="r2",
                            steps=[{"step": 1, "passed": True}]))
    login = memory.summary("login")
    assert login[0]["resolved_at"] is None, "다른 시나리오의 통과가 이 실패를 닫으면 안 된다"


def test_summary_filter_and_clear():
    memory.annotate(_result(name="a", steps=[_failed()]))
    memory.annotate(_result(name="b", steps=[_failed()]))
    assert len(memory.summary()) == 2
    assert len(memory.summary("a")) == 1
    assert memory.clear() == 2
    assert memory.summary() == []


# ── app log correlation ──────────────────────────────────────────
def _log(tmp_path, lines):
    p = tmp_path / "app.log"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def _ts(offset=0.0):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + offset))


def test_lines_are_attached_to_the_step_that_was_running(tmp_path):
    now = time.time()
    path = _log(tmp_path, [
        f"{_ts(-60)} INFO  starting up",
        f"{_ts(0)} ERROR NullPointerException in checkout",
        "\tat com.corp.Checkout.submit(Checkout.java:88)",
        f"{_ts(+60)} INFO  later, unrelated",
    ])
    result = {"steps": [
        {"step": 1, "started_at": now - 1, "ended_at": now + 1},
        {"step": 2, "started_at": now + 120, "ended_at": now + 121},
    ]}
    applog.attach(result, path)

    assert any("NullPointerException" in ln for ln in result["steps"][0]["app_log"])
    # the stack frame inherits the ERROR line's timestamp, so it stays attached
    assert any("Checkout.java:88" in ln for ln in result["steps"][0]["app_log"])
    assert result["steps"][1]["app_log"] == []


def test_only_interesting_lines_are_kept(tmp_path):
    now = time.time()
    path = _log(tmp_path, [f"{_ts(0)} INFO handled request 200 OK",
                           f"{_ts(0)} WARN slow query 1200ms"])
    result = {"steps": [{"step": 1, "started_at": now - 2, "ended_at": now + 2}]}
    applog.attach(result, path)
    lines = result["steps"][0]["app_log"]
    assert any("WARN" in ln for ln in lines)
    assert not any("200 OK" in ln for ln in lines)


def test_secrets_are_scrubbed_from_log_lines(tmp_path, monkeypatch):
    from blackbox_mcp.testing import secrets
    monkeypatch.setenv("DB_PASSWORD", "hunter2")
    secrets.resolve("${DB_PASSWORD}")          # registers the resolved value
    now = time.time()
    path = _log(tmp_path, [f"{_ts(0)} ERROR auth failed for password=hunter2"])
    result = {"steps": [{"step": 1, "started_at": now - 2, "ended_at": now + 2}]}
    applog.attach(result, path)

    joined = " ".join(result["steps"][0]["app_log"])
    assert "hunter2" not in joined
    assert "${DB_PASSWORD}" in joined


def test_missing_log_file_is_not_fatal(tmp_path):
    result = {"steps": [{"step": 1, "started_at": 0, "ended_at": 1}]}
    applog.attach(result, tmp_path / "nope.log")
    assert result["steps"][0]["app_log"] == []
    assert "unreadable" in result["meta"]["app_log"]


def test_steps_without_timestamps_get_an_empty_list(tmp_path):
    path = _log(tmp_path, [f"{_ts(0)} ERROR boom"])
    result = {"steps": [{"step": 1}]}
    applog.attach(result, path)
    assert result["steps"][0]["app_log"] == []


def test_clf_access_log_timestamps_parse(tmp_path):
    now = time.time()
    stamp = time.strftime("%d/%b/%Y:%H:%M:%S", time.localtime(now))
    path = _log(tmp_path, [f'127.0.0.1 - - [{stamp} +0000] "GET /x" 500 12'])
    result = {"steps": [{"step": 1, "started_at": now - 2, "ended_at": now + 2}]}
    applog.attach(result, path)
    assert result["steps"][0]["app_log"], "nginx/apache 형식도 상관돼야 한다"
