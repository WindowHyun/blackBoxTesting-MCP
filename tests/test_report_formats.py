"""report_format validation — an unrecognized value must never look like a save.

Regression guard for the P1 defect: `save()`'s format selection was three
membership tests with no else branch, so a value outside the documented set
(`"markdown"`, `"JSON"`, `"md,html"`) wrote ZERO files and returned an empty
dict — which `save_report` read as success and followed with `recorder.reset()`,
destroying the recorded flow it had just failed to persist.
"""
from __future__ import annotations

import dataclasses

import pytest

from blackbox_mcp.testing import report

_RESULT = {
    "name": "x", "run_id": "20260101_000000_000000",
    "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0,
                "pass_rate": 1.0},
    "meta": {}, "steps": [{"step": 1, "action": "navigate", "passed": True,
                           "duration_ms": 5}],
}


def _report_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(report, "CONFIG",
                        dataclasses.replace(report.CONFIG, report_dir=tmp_path))


# ── resolve_formats ───────────────────────────────────────────────
@pytest.mark.parametrize("value,expected", [
    ("json", {"json"}),
    ("md", {"md"}),
    ("html", {"html"}),
    ("both", {"json", "md"}),
    ("all", {"json", "md", "html"}),
    # case and surrounding whitespace are not a caller error
    ("JSON", {"json"}),
    ("  All  ", {"json", "md", "html"}),
    # the spelling a host LLM plausibly reaches for
    ("markdown", {"md"}),
    ("htm", {"html"}),
    # an explicit combination
    ("json,html", {"json", "html"}),
    ("md + html", {"md", "html"}),
])
def test_resolve_formats_accepts(value, expected):
    assert report.resolve_formats(value) == expected


@pytest.mark.parametrize("value", ["pdf", "", "   ", "json,pdf", "xml", None])
def test_resolve_formats_rejects_unknown(value):
    """Unknown values raise — they must not degrade to "write nothing"."""
    with pytest.raises(ValueError) as excinfo:
        report.resolve_formats(value)
    # the message has to name the valid values; it is what the caller retries on
    assert "json" in str(excinfo.value) and "all" in str(excinfo.value)


def test_cli_rejects_an_unknown_format_too():
    """The CLI guards the same surface via argparse choices (exit 2, no run)."""
    from blackbox_mcp import cli

    with pytest.raises(SystemExit):
        cli.main(["run", "whatever", "--format", "markdown"])


# ── save() ────────────────────────────────────────────────────────
def test_save_raises_and_writes_nothing_on_unknown_format(monkeypatch, tmp_path):
    _report_dir(monkeypatch, tmp_path)
    with pytest.raises(ValueError):
        report.save(dict(_RESULT), formats="markdown!")
    assert list(tmp_path.glob("report_*")) == []


def test_save_writes_a_combination(monkeypatch, tmp_path):
    _report_dir(monkeypatch, tmp_path)
    files = report.save(dict(_RESULT), formats="json,html")
    assert set(files) == {"json", "html"}
    for path in files.values():
        assert open(path, encoding="utf-8").read()


# ── save_report tool: the flow must survive a bad format ──────────
async def test_save_report_rejects_bad_format_and_keeps_the_recording(
        monkeypatch, tmp_path):
    """The whole point of the fix: a bad format is recoverable.

    Before, this returned ok=True with no files AND wiped the recorder, so the
    steps could not be re-saved with a valid format — the flow was gone.
    """
    from blackbox_mcp.testing import recorder
    from blackbox_mcp.tools import savereport
    from blackbox_mcp.tools.savereport import save_report

    _report_dir(monkeypatch, tmp_path)

    # No browser in this lane: save_report already tolerates an unavailable
    # session (env metadata is simply omitted), so make that the path taken.
    async def _no_session():
        raise RuntimeError("no browser in this test")

    monkeypatch.setattr(savereport, "get_session", _no_session)

    recorder.reset()
    recorder._LOG.append({"step": 1, "action": "navigate", "passed": True,
                          "duration_ms": 10, "raw": {"url": "http://x"},
                          "console_errors": [], "network_errors": [],
                          "dialogs": []})
    recorder._COUNTER = 1

    out = await save_report(name="demo", report_format="markdown!")
    assert out["ok"] is False
    assert "markdown!" in out["error"]
    assert out["recorded_steps"] == 1
    # nothing written, nothing lost
    assert list(tmp_path.glob("report_*")) == []
    assert len(recorder.steps()) == 1
    # and no history baseline was recorded for a run that never saved
    assert not (tmp_path / "history").exists() or \
        list((tmp_path / "history").glob("*.json")) == []

    # the retry with a valid format still has the flow to save
    ok = await save_report(name="demo", report_format="md")
    assert ok["ok"] is True and "md" in ok["report_files"]
    assert recorder.steps() == []  # reset only after a real save


async def test_run_scenario_rejects_bad_format_before_running():
    """Validation happens up front, so a typo costs no browser run."""
    from blackbox_mcp.tools.scenario import run_scenario

    out = await run_scenario([{"action": "navigate", "url": "http://unused"}],
                             report_format="pdf")
    assert out["ok"] is False and "pdf" in out["error"]
