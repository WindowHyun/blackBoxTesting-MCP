"""Regression guards for the stability/security audit fixes."""
from __future__ import annotations

import asyncio
import json
import subprocess

import pytest

from blackbox_mcp.browser.listeners import ConsoleEntry, EventBuffers, _MAX_EVENTS
from blackbox_mcp.testing import recorder, report, secrets


# ── secrets ──────────────────────────────────────────────────────

def test_mask_value_hides_everything():
    assert secrets.mask_value("hunter2") == "***"
    assert secrets.mask_value("a") == "***"
    assert secrets.mask_value("") == ""


def test_sensitive_name_korean_and_short_tokens():
    assert secrets.is_sensitive_name('role=textbox[name="비밀번호"]')
    assert secrets.is_sensitive_name("css=#user-pw")
    assert secrets.is_sensitive_name("OTP_CODE")
    # short tokens are word-bounded — no false positive inside ordinary words
    assert not secrets.is_sensitive_name("css=#topspin")
    assert not secrets.is_sensitive_name("email")


def test_mask_step_korean_selector():
    step = {"action": "interact", "selector": 'role=textbox[name="비밀번호"]',
            "value": "hunter2"}
    assert secrets.mask_step(step)["value"] == "***"


def test_resolve_registers_secret_and_scrub_removes_it(monkeypatch):
    monkeypatch.setenv("MY_API_TOKEN", "sk-live-abc123")
    resolved = secrets.resolve("https://api.test/login?token=${MY_API_TOKEN}")
    assert "sk-live-abc123" in resolved
    text = f"navigated to {resolved} (status 200)"
    assert "sk-live-abc123" not in secrets.scrub(text)
    assert "${MY_API_TOKEN}" in secrets.scrub(text)


def test_unresolved_vars_detects_missing_env(monkeypatch):
    monkeypatch.delenv("NOPE_VAR", raising=False)
    assert secrets.unresolved_vars("x=${NOPE_VAR}") == ["NOPE_VAR"]
    monkeypatch.setenv("YES_VAR", "1")
    assert secrets.unresolved_vars("x=${YES_VAR}") == []


def test_scrub_record_cleans_network_and_console(monkeypatch):
    monkeypatch.setenv("SCRUB_PW", "topsecret99")
    secrets.resolve("${SCRUB_PW}")  # register
    rec = {"actual": "err topsecret99", "expected": None, "ai_reason": "",
           "ai_suggestion": None,
           "console_errors": [{"text": "leak topsecret99", "location": ""}],
           "network_errors": [{"url": "https://x/?pw=topsecret99"}]}
    out = secrets.scrub_record(rec)
    dumped = json.dumps(out)
    assert "topsecret99" not in dumped
    assert "${SCRUB_PW}" in dumped


# ── bootstrap: install output must not hit the MCP stdout pipe ───

def test_bootstrap_install_redirects_stdout(monkeypatch):
    import dataclasses

    from blackbox_mcp import bootstrap

    calls: list[dict] = []

    def fake_run(*args, **kwargs):
        calls.append(kwargs)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
    monkeypatch.setattr(bootstrap, "_browser_installed", lambda name: False)
    monkeypatch.setattr(bootstrap, "CONFIG",
                        dataclasses.replace(bootstrap.CONFIG, chromium_executable=""))
    bootstrap.ensure_chromium()
    assert calls, "install was not attempted"
    assert calls[0].get("stdout") == subprocess.DEVNULL


# ── listeners: buffers are capped ────────────────────────────────

def test_event_buffers_are_capped():
    buf = EventBuffers()
    for i in range(_MAX_EVENTS + 50):
        buf.add_console(ConsoleEntry(level="log", text=str(i), location="", ts=0.0))
    assert len(buf.console) == _MAX_EVENTS
    assert buf.console[-1].text == str(_MAX_EVENTS + 49)  # newest kept


# ── recorder: monotonic step counter survives the cap ────────────

async def test_recorder_counter_monotonic_past_cap(monkeypatch, session):
    monkeypatch.setattr(recorder, "_MAX_STEPS", 3)
    recorder.reset()

    async def dummy():
        return {"ok": True, "waited": "1ms"}

    for _ in range(5):
        await recorder.run_and_record("wait", dummy, (), {})
    steps = recorder.steps()
    assert len(steps) == 3
    assert [s["step"] for s in steps] == [3, 4, 5]  # unique, monotonic
    recorder.reset()


# ── report: regression skips unrelated baselines ─────────────────

def _result(name, steps):
    return {"name": name, "meta": {"started_at": "t"},
            "steps": [{"step": i + 1, "action": a, "passed": True}
                      for i, a in enumerate(steps)]}


def test_regression_zero_overlap_gives_no_diff(tmp_path, monkeypatch):
    import dataclasses
    monkeypatch.setattr(report, "CONFIG",
                        dataclasses.replace(report.CONFIG, report_dir=tmp_path))
    r1 = _result("session", ["navigate", "interact"])
    report.compute_regression(r1)
    # different flow, same name — actions at every (step, action) key differ
    r2 = _result("session", ["wait", "assert", "screenshot"])
    report.compute_regression(r2)
    assert r2["regression"]["changed"] == []
    assert r2["regression"]["previous_run"] is None
    # same flow re-run still compares normally
    r3 = _result("session", ["wait", "assert", "screenshot"])
    r3["steps"][1]["passed"] = False
    report.compute_regression(r3)
    assert r3["regression"]["previous_run"] == "t"
    assert r3["regression"]["changed"] == [
        {"step": 2, "from": "passed", "to": "failed"}]


# ── session: concurrent get_session yields one browser ───────────

async def test_concurrent_get_session_single_instance(session):
    from blackbox_mcp.browser.session import get_session

    results = await asyncio.gather(*(get_session() for _ in range(5)))
    assert all(r is results[0] for r in results)
