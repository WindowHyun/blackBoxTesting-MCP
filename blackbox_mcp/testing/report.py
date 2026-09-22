"""Report generation (SM-03, SM-04, SM-08, D3).

Writes JSON / Markdown / HTML reports under REPORT_DIR (absolute; default
~/ui-blackbox/reports — NOT cwd-relative, since the MCP server's cwd is
unpredictable/often unwritable), created if missing, with a home fallback.
Filenames: report_YYYYMMDD_HHMMSS.{json,md,html}. Step
screenshots go under reports/screenshots/ and are embedded into the HTML as
base64 data URIs for single-file portability.
"""
from __future__ import annotations

import base64
import html
import json
import math
import re
from datetime import datetime
from pathlib import Path

from ..config import CONFIG

_SAFE = re.compile(r"[^A-Za-z0-9_\-]")


def _stamp() -> str:
    # Microseconds keep run ids collision-free even when parallel CLI children
    # start in the same wall-clock second.
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def new_run_id() -> str:
    """A per-run id. The SAME id names this run's report files AND its
    screenshots, so retention (which correlates the two by id) keeps or
    deletes them together — see _prune."""
    return _stamp()


def summarize(steps: list[dict]) -> dict:
    """The one summary shape (DESIGN §6.1) — runner and recorder both use this
    so a schema change happens in exactly one place.

    Skipped steps (not run because an earlier step failed) count toward
    ``total`` and ``skipped`` but NOT toward ``failed`` — "6 steps: 2 passed,
    1 failed, 3 skipped" instead of pretending the un-run steps failed.
    ``pass_rate`` is over EXECUTED steps, so what ran is judged honestly;
    the skipped count itself signals how much never ran."""
    total = len(steps)
    skipped = sum(1 for s in steps if s.get("skipped"))
    passed = sum(1 for s in steps if s.get("passed"))
    executed = total - skipped
    return {"total": total, "passed": passed, "failed": executed - passed,
            "skipped": skipped,
            "pass_rate": round(passed / executed, 3) if executed else 0.0}


def classify_failure(action: str, exc: Exception | None,
                     js_error: bool = False) -> str:
    """Severity for a FAILED step — single implementation for runner/recorder.

    ``js_error`` wins over the action-derived value: when a step is failed
    *because* the page threw, "the app crashed" is the finding, not "an
    assertion did not hold". DESIGN §6.1 lists js_error in the severity
    vocabulary and nothing produced it until this path existed.
    """
    if js_error:
        return "js_error"
    if exc is not None:
        return "timeout" if "Timeout" in type(exc).__name__ else "error"
    if action.startswith("assert"):
        return "assertion"
    return "error"  # failed interact/wait/dialog/etc.


def ensure_dirs() -> Path:
    """Return a writable report dir, creating it. Falls back to the user's home
    if the configured dir cannot be created/written (e.g. server cwd is a system
    path with no write permission)."""
    candidates = [CONFIG.report_dir, Path.home() / "ui-blackbox" / "reports"]
    last_err: Exception | None = None
    for report_dir in candidates:
        try:
            (report_dir / "screenshots").mkdir(parents=True, exist_ok=True)
            probe = report_dir / ".write_test"
            probe.write_text("", encoding="utf-8")
            probe.unlink()
            return report_dir
        except Exception as exc:  # PermissionError, OSError, ...
            last_err = exc
            continue
    raise RuntimeError(f"No writable report directory ({last_err})")


def compute_regression(result: dict) -> dict:
    """SM-07: compare this run with the previous run of the same scenario.

    Reads/writes reports/history/{name}.json. Sets result['regression'] with the
    previous run timestamp and the list of steps whose pass/fail status changed,
    then records the current run as the new baseline.
    """
    name = result.get("name", "scenario")
    # Use the SAME writable dir save() resolves (home fallback), not the raw
    # CONFIG.report_dir which may be unwritable — else regression crashes the
    # whole report save. Never let regression bookkeeping break reporting.
    try:
        hist_dir = ensure_dirs() / "history"
        hist_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        result["regression"] = {"previous_run": None, "changed": []}
        result["trend"] = {"recent": [], "consecutive_failures": 0}
        return result
    path = hist_dir / f"{_SAFE.sub('_', name)}.json"

    cur = [{"step": s["step"], "action": s.get("action"), "passed": s["passed"]}
           for s in result.get("steps", [])]
    changed = []
    prev_ts = None
    prev_runs: list[dict] = []
    if path.exists():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
            prev_ts = prev.get("ts")
            prev_runs = prev.get("runs") or []
            # key by (step, action) so a changed action at the same index isn't
            # mis-reported as a pass→fail regression of "the same step".
            prev_by_key = {(s["step"], s.get("action")): s["passed"]
                           for s in prev.get("steps", [])}
            # Zero key overlap means the baseline is an unrelated flow that
            # happened to share the report name (ad-hoc flows all default to
            # "session") — comparing would fabricate "absent" diffs. Skip and
            # let this run become the new baseline.
            overlap = any((s["step"], s.get("action")) in prev_by_key for s in cur)
            if overlap:
                for s in cur:
                    was = prev_by_key.get((s["step"], s.get("action")))
                    if was is None:
                        changed.append({"step": s["step"], "from": "absent",
                                        "to": "passed" if s["passed"] else "failed"})
                    elif was != s["passed"]:
                        changed.append({"step": s["step"],
                                        "from": "passed" if was else "failed",
                                        "to": "passed" if s["passed"] else "failed"})
            else:
                prev_ts = None
        except Exception:
            pass

    result["regression"] = {"previous_run": prev_ts, "changed": changed}

    # Trend (PM view): recent same-name runs + current, newest last, capped.
    # Kept even when the step-overlap guard skipped the diff — the pass/fail
    # history of a NAME is meaningful even if individual steps changed.
    s = result.get("summary", {})
    cur_run = {"ts": result.get("meta", {}).get("started_at"),
               "passed": s.get("passed", 0), "failed": s.get("failed", 0),
               "total": s.get("total", 0)}
    runs = (prev_runs + [cur_run])[-10:]
    streak = 0
    for r in reversed(runs):
        if r.get("failed", 0) > 0:
            streak += 1
        else:
            break
    result["trend"] = {"recent": runs, "consecutive_failures": streak}

    try:
        path.write_text(json.dumps(
            {"ts": result.get("meta", {}).get("started_at"), "steps": cur,
             "runs": runs},
            ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return result


async def capture_step_screenshot(session, run_tag: str, idx: int) -> str | None:
    """Capture the current page to reports/screenshots and return a rel path.

    ``run_tag`` is ``{run_id}_{name}`` — the run id leads so _STAMP_RE always
    extracts THIS run's id (not a digit that happens to be in the name), which
    is what lets retention keep a report and its screenshots together."""
    try:
        base = ensure_dirs()
        safe = _SAFE.sub("_", run_tag)
        rel = Path("screenshots") / f"{safe}_step{idx:02d}.png"
        await session.page.screenshot(path=str(base / rel))
        return str(rel)
    except Exception:
        return None


# Run id = date_time_micros. Anchored at the start of a report filename
# (report_<id>) or a screenshot filename (<id>_name_step..), so the match is
# always this run's id. Microseconds included → parallel runs never collide.
_STAMP_RE = re.compile(r"^(?:report_)?(\d{8}_\d{6}_\d{6})")
# Legacy fallback: pre-microsecond files stamped to the second only.
_STAMP_RE_LEGACY = re.compile(r"(\d{8}_\d{6})")


def _run_id_of(name: str) -> str | None:
    m = _STAMP_RE.match(name) or _STAMP_RE_LEGACY.search(name)
    return m.group(1) if m else None


def _run_id_time(run_id: str) -> float | None:
    """A run id as a POSIX timestamp (ids ARE timestamps — see new_run_id)."""
    for fmt in ("%Y%m%d_%H%M%S_%f", "%Y%m%d_%H%M%S"):
        try:
            return datetime.strptime(run_id, fmt).timestamp()
        except ValueError:
            continue
    return None


def _artifact_globs(report_dir: Path) -> list:
    """(directory, glob) pairs holding per-run artifacts, all stamped with a run id."""
    return [(report_dir, "report_*.*"),
            (report_dir / "screenshots", "*.png"),
            (report_dir / "traces", "*.zip")]


def _collect_run_ids(report_dir: Path) -> set[str]:
    """Every run id present on disk, from ANY artifact kind.

    Deriving the id universe from report files alone made retention blind to
    the interactive path: recorder.run_and_record captures a screenshot for
    every failed tool call, while save_report is optional, so a run that never
    wrote a report could not appear in the doomed set — its screenshots stayed
    forever in the exact directory retention exists to bound.
    """
    ids: set[str] = set()
    for directory, pattern in _artifact_globs(report_dir):
        if not directory.is_dir():
            continue
        for p in directory.glob(pattern):
            if (rid := _run_id_of(p.name)):
                ids.add(rid)
    return ids


def prune_now() -> None:
    """Apply retention outside a save. Best-effort: never raises.

    save() prunes after writing, but an interactive flow can capture step
    screenshots for hours and never reach save_report — so retention also has
    to run when a flow BEGINS, or nothing bounds that directory at all.
    """
    try:
        _prune(ensure_dirs())
    except Exception:
        pass


def _prune(report_dir: Path) -> None:
    """Retention: keep the newest CONFIG.report_retention runs, deleting every
    older run's artifacts — report files, screenshots and traces alike. All
    three carry the SAME run id (see new_run_id), so a kept run keeps its
    evidence. Never allowed to break report saving — caller try/excepts."""
    keep = CONFIG.report_retention
    if keep <= 0:
        return
    # Run ids come from all artifact kinds, not just report files: a run that
    # captured screenshots but never saved a report is still a run, and its
    # files must age out with everyone else's.
    ids = sorted(_collect_run_ids(report_dir), reverse=True)
    if len(ids) <= keep:
        return
    doomed = set(ids[keep:])  # everything older than the newest `keep` runs
    for directory, pattern in _artifact_globs(report_dir):
        if not directory.is_dir():
            continue
        for p in directory.glob(pattern):
            # Unstamped legacy files (no id) are left alone.
            if _run_id_of(p.name) in doomed:
                p.unlink(missing_ok=True)
    # Regression baselines are keyed by scenario NAME, not by run id, so they
    # were outside retention entirely: one file per distinct name accumulated
    # forever (ad-hoc flows default to "session", but a renamed scenario leaves
    # its old baseline behind). A baseline whose newest run has been pruned is
    # comparing against runs that no longer exist, so it goes with them.
    history = report_dir / "history"
    cutoff = _run_id_time(ids[keep - 1])   # oldest run we are keeping
    if history.is_dir() and cutoff is not None:
        for p in history.glob("*.json"):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink(missing_ok=True)
            except OSError:
                continue


# What each documented `formats` value writes (DESIGN §6). Single source for
# save(), the MCP tools and the CLI's --format choices.
_FORMAT_SETS: dict[str, frozenset[str]] = {
    "json": frozenset({"json"}),
    "md": frozenset({"md"}),
    "html": frozenset({"html"}),
    "both": frozenset({"json", "md"}),
    "all": frozenset({"json", "md", "html"}),
}
# Spellings a caller plausibly reaches for instead of the documented value —
# the MCP path is driven by a host LLM reading the tool description, and
# "markdown" is a likelier miss than a typo.
_FORMAT_ALIASES = {"markdown": "md", "mkd": "md", "htm": "html", "jsn": "json"}


def resolve_formats(formats: str) -> set[str]:
    """Normalize a ``formats`` argument into the set of files to write.

    Accepts the documented values case-insensitively, the obvious alternate
    spellings above, and a separated list ("json,html").

    Raises ValueError on anything else. That matters more than it looks: the
    old membership tests had no else branch, so an unrecognized value wrote
    NOTHING and still returned success — and in the MCP path save_report read
    that as a successful save and reset the recorder, destroying the very flow
    it had just failed to persist. Refusing loudly keeps the steps recoverable.
    """
    out: set[str] = set()
    unknown: list[str] = []
    for part in re.split(r"[,+|/\s]+", str(formats or "").strip().lower()):
        if not part:
            continue
        part = _FORMAT_ALIASES.get(part, part)
        if part in _FORMAT_SETS:
            out |= _FORMAT_SETS[part]
        else:
            unknown.append(part)
    if not out or unknown:
        raise ValueError(
            f"unknown report format {formats!r} — expected one of "
            f"{sorted(_FORMAT_SETS)} (or a comma-separated combination, "
            f"e.g. 'json,html')")
    return out


def save(result: dict, formats: str = "both") -> dict[str, str]:
    """Persist a scenario result; return written file paths by format."""
    # Validate BEFORE touching the filesystem: a bad format must not create
    # directories or leave a half-written run behind.
    want = resolve_formats(formats)
    report_dir = ensure_dirs()
    # Reuse the run id the screenshots were stamped with, so retention keeps
    # report + screenshots together. Falls back for callers that didn't set it.
    stamp = result.get("run_id") or new_run_id()
    written: dict[str, str] = {}

    want_json = "json" in want
    want_md = "md" in want
    want_html = "html" in want

    if want_json:
        p = report_dir / f"report_{stamp}.json"
        p.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str),
                     encoding="utf-8")
        written["json"] = str(p)
    if want_md:
        p = report_dir / f"report_{stamp}.md"
        p.write_text(_render_markdown(result), encoding="utf-8")
        written["md"] = str(p)
    if want_html:
        p = report_dir / f"report_{stamp}.html"
        p.write_text(_render_html(result, report_dir), encoding="utf-8")
        written["html"] = str(p)

    try:
        _prune(report_dir)
    except Exception:  # retention must never break the save that just succeeded
        pass
    return written


# ── Markdown ──────────────────────────────────────────────────────
def _render_markdown(result: dict) -> str:
    s = result.get("summary", {})
    meta = result.get("meta", {})
    skipped = s.get("skipped", 0)
    skip_note = f" · **{skipped} skipped**" if skipped else ""
    lines = [
        f"# UI Blackbox Report — {result.get('name', 'scenario')}",
        "",
        f"**{s.get('passed', 0)}/{s.get('total', 0)} passed** "
        f"(rate {s.get('pass_rate', 0)}){skip_note} · {meta.get('duration_ms', 0)} ms · "
        f"{meta.get('started_at', '')}",
    ]
    if meta.get("target_url"):
        lines += ["", f"_대상: {meta['target_url']}_"]
    trend = result.get("trend") or {}
    recent = trend.get("recent") or []
    if len(recent) > 1:
        icons = "".join("❌" if r.get("failed", 0) > 0 else "✅" for r in recent)
        streak = trend.get("consecutive_failures", 0)
        streak_note = f" · 연속 실패 {streak}회" if streak > 1 else ""
        lines += ["", f"_최근 {len(recent)}회: {icons}{streak_note}_"]
    lines += [
        "",
        f"_env: {meta.get('os')} · py{meta.get('python')} · "
        f"playwright {meta.get('playwright')} · {meta.get('browser')}"
        f"{' ' + str(meta.get('browser_version')) if meta.get('browser_version') else ''}"
        f"{' · ' + str(meta.get('viewport')) if meta.get('viewport') else ''}_",
        "",
        "| # | action | resolved | expected | actual | result | sev |",
        "|---|---|---|---|---|---|---|",
    ]
    for st in result.get("steps", []):
        res = "⏭" if st.get("skipped") else ("✅" if st["passed"] else "❌")
        flaky = " ⚠flaky" if st.get("retries") and st.get("passed") else ""
        tag = f" `{st['tag']}`" if st.get("tag") else ""
        lines.append(
            f"| {st['step']} | {_cell(st.get('action'))}{_cell(tag)} | {_cell(st.get('resolved_by') or '')} "
            f"| {_cell(_short(st.get('expected')))} | {_cell(_short(st.get('actual')))} | {res}{flaky} "
            f"| {_cell(st.get('severity') or st.get('priority') or '')} |"
        )
    # failure details (skipped steps are listed in the table, not as failures)
    fails = [st for st in result.get("steps", [])
             if not st["passed"] and not st.get("skipped")]
    if fails:
        lines += ["", "## 실패 상세"]
        for st in fails:
            tag = f" `{st['tag']}`" if st.get("tag") else ""
            prio = f" [{st['priority']}]" if st.get("priority") else ""
            lines.append(f"- **step {st['step']} ({st.get('action')}){tag}{prio}** — "
                         f"{st.get('ai_reason')}. 제안: {st.get('ai_suggestion') or '—'}")
            if st.get("page_url"):
                lines.append(f"  - 페이지: {st['page_url']}")
            if st.get("screenshot"):
                lines.append(f"  - 스크린샷: `{st['screenshot']}`")
            for ce in st.get("console_errors", []):
                lines.append(f"  - console: {ce.get('text')}")
            for ne in st.get("network_errors", []):
                lines.append(f"  - network: {ne.get('url')} "
                             f"{ne.get('status') or ne.get('failure')}")
            for dl in st.get("dialogs", []):
                mark = "예상치 못한 " if not dl.get("expected") else ""
                lines.append(f"  - {mark}dialog: {dl.get('type')} "
                             f"“{dl.get('message')}” → {dl.get('handled')}")

    reg = result.get("regression") or {}
    if reg.get("changed"):
        lines += ["", "## 회귀 (직전 실행 대비)"]
        lines.append(f"_기준: {reg.get('previous_run')}_")
        for c in reg["changed"]:
            lines.append(f"- step {c['step']}: {c['from']} → **{c['to']}**")

    # Unexpected dialogs deserve their own section: they can land on a step that
    # otherwise PASSED (the page kept going only because the dialog was
    # auto-dismissed), so the 실패 상세 list above would never surface them.
    surprises = [(st, dl) for st in result.get("steps", [])
                 for dl in (st.get("dialogs") or []) if not dl.get("expected")]
    if surprises:
        lines += ["", f"## 예상치 못한 dialog ({len(surprises)})",
                  "_expect_dialog로 대기하지 않은 alert/confirm/prompt — 자동 dismiss "
                  "되어 흐름은 이어졌지만 확인이 필요합니다._"]
        for st, dl in surprises[:20]:
            lines.append(f"- step {st['step']} ({st.get('action')}): "
                         f"`{dl.get('type')}` “{dl.get('message')}”")

    a11y = result.get("a11y_findings") or []
    if a11y:
        lines += ["", f"## 접근성 발견 ({len(a11y)})"]
        for f in a11y[:20]:
            lines.append(f"- `{f.get('type')}` <{f.get('tag')}> {f.get('name') or f.get('info') or ''}")
    lines += ["", "---",
              "_실패 원인·제안은 **규칙 기반 힌트**입니다 — 대화형(Claude) 실행 시 "
              "호스트 LLM이 분석으로 보강합니다._"]
    return "\n".join(lines)


def _dash(v):
    """"—" for a genuinely absent value (a skipped step's expected/actual are
    None) — otherwise str(None) rendered as the literal word "None"."""
    return "—" if v is None else v


def _short(v, n: int = 40) -> str:
    s = str(v).replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def _cell(v) -> str:
    """Escape '|' so page-captured text can't break the Markdown table row."""
    return str(v).replace("|", "\\|")


# ── HTML (self-contained instrument-panel theme) ───────────────────
#
# No <link>/@font-face: DESIGN §6.2 requires the HTML report to run with zero
# external dependencies/network (this tool targets closed corporate networks —
# CLAUDE.md "사내망 지원"). Font names are PREFERENCES only, with a universal
# fallback; nothing is fetched. The pass-rate gauge is plain inline SVG with
# its arc math computed in Python (stroke-dasharray/dashoffset), so no
# client-side script is needed to render it. A run with 2+ chapters (Steps
# plus regression and/or a11y findings) gets one inline <script> for sidebar
# tab switching (_chapters_html) — still zero network/external deps, just no
# longer zero script; a single-chapter run (most runs) never emits it.
_CSS = """
:root{
  --paper:#f2efe6;--surface:#fbfaf5;--sunk:#eae4d5;--track:#e3ddc9;
  --ink:#1b1712;--ink2:#56504a;--ink3:#8a8375;--ink4:#a9a294;
  --rule:#ddd5c1;--rule-soft:#e9e3d3;
  --accent:#b8480f;--accent-ink:#8a3308;--accent-soft:#f6e2ce;--accent-bd:#e7c19c;
  --good:#0ca30c;--good-bg:#e2f4df;--good-bd:#bfe3b8;
  --warn:#c8790a;--warn-bg:#fbedd3;--warn-bd:#eecf98;
  --crit:#d03b3b;--crit-bg:#fbe4e1;--crit-bd:#f0bcb6;
  --skip:#726c60;--skip-bg:#eae4d5;--skip-bd:#d8cfba;
}
@media (prefers-color-scheme:dark){:root{
  --paper:#12100b;--surface:#1b170f;--sunk:#211c13;--track:#2a2415;
  --ink:#f3ede0;--ink2:#cbc1ac;--ink3:#928a76;--ink4:#726b5a;
  --rule:#332c1d;--rule-soft:#292213;
  --accent:#e88a3d;--accent-ink:#f3a765;--accent-soft:#2f1d0e;--accent-bd:#4a2c12;
  --good:#3ac23a;--good-bg:#132313;--good-bd:#204a20;
  --warn:#f0a933;--warn-bg:#2a1f0c;--warn-bd:#4a3712;
  --crit:#ec6d6d;--crit-bg:#2c1414;--crit-bd:#4d2222;
  --skip:#9b9484;--skip-bg:#211c13;--skip-bd:#332c1d;
}}
*{box-sizing:border-box}
[hidden]{display:none}
body{font-family:'Pretendard',-apple-system,BlinkMacSystemFont,system-ui,"Malgun Gothic",
"Apple SD Gothic Neo",sans-serif;background:var(--paper);color:var(--ink);
margin:0;padding:28px 18px 60px;font-size:14px;line-height:1.6;-webkit-font-smoothing:antialiased}
.mono{font-family:'JetBrains Mono',ui-monospace,"SF Mono",Consolas,monospace}
.wrap{max-width:1000px;margin:0 auto}
code{font-family:'JetBrains Mono',ui-monospace,"SF Mono",Consolas,monospace;font-size:.86em;
background:var(--sunk);padding:.1em .38em;border-radius:3px}

/* masthead */
.mast{padding-bottom:20px;border-bottom:2px solid var(--ink)}
.eyebrow{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:11px;font-weight:600;
letter-spacing:.14em;text-transform:uppercase;color:var(--accent-ink);margin-bottom:12px}
h1{font-size:24px;font-weight:800;letter-spacing:-.01em;margin:0}
.desc{color:var(--ink2);font-size:14px;margin:10px 0 0;max-width:70ch}
.mmeta{display:flex;flex-wrap:wrap;gap:5px 18px;margin-top:14px;
font-family:'JetBrains Mono',ui-monospace,monospace;font-size:11.5px;color:var(--ink3)}
.mmeta b{color:var(--ink2);font-weight:500}

/* instrument cluster */
.cluster{display:grid;grid-template-columns:180px 1fr;margin-top:22px;
border:1px solid var(--rule);background:var(--surface)}
.gaugebox{padding:16px;display:flex;flex-direction:column;align-items:center;
justify-content:center;gap:6px;border-right:1px solid var(--rule)}
.glabel{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:10px;letter-spacing:.1em;
text-transform:uppercase;color:var(--ink3)}
.gsub{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:10.5px;color:var(--ink3);
text-align:center}
.rightcol{display:flex;flex-direction:column;min-width:0}
.statrow{display:grid;grid-template-columns:repeat(4,1fr);border-bottom:1px solid var(--rule)}
.stat{padding:12px 14px;border-left:1px solid var(--rule)}
.stat:first-child{border-left:none}
.stat .sv{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:20px;font-weight:700;
line-height:1}
.stat .sl{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:9.5px;letter-spacing:.08em;
text-transform:uppercase;color:var(--ink3);margin-top:6px}
.envrow{display:flex;flex-wrap:wrap;gap:6px;padding:11px 14px;border-bottom:1px solid var(--rule)}
.chip{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:10.5px;padding:3px 8px;
border-radius:3px;border:1px solid var(--rule);background:var(--sunk);color:var(--ink2);
white-space:nowrap}
.chip.mask{color:var(--good);border-color:var(--good-bd);background:var(--good-bg)}
.trendrow{padding:11px 14px}
.trendlabel{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:9.5px;letter-spacing:.08em;
text-transform:uppercase;color:var(--ink3);margin-bottom:8px}
.tstreak{color:var(--crit);margin-left:8px;text-transform:none;letter-spacing:0}
.trend-runs{display:flex;gap:14px;overflow-x:auto}
.trun{flex:none;display:flex;flex-direction:column;gap:4px}
.trun.now .tlabel{color:var(--ink)}
.tbar{display:flex;height:8px;gap:1px}
.tseg{display:block;height:100%;border-radius:1px}
.tseg.good{background:var(--good)}.tseg.crit{background:var(--crit)}
.tseg.skip{background:var(--skip)}
.tlabel{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:10px;color:var(--ink3);
display:flex;gap:6px;white-space:nowrap}

/* chapter sidebar — only rendered when a run has 2+ chapters (Steps plus
   regression and/or a11y findings); a single-chapter report skips this
   entirely and stays exactly as before (no sidebar, no script). */
section[id]{scroll-margin-top:16px}
.layout{display:grid;grid-template-columns:168px minmax(0,1fr);gap:0 28px;
align-items:start;margin-top:20px}
.content{min-width:0}
.sidenav{position:sticky;top:14px}
.sidenav .inner{display:flex;flex-direction:column;gap:2px}
.sidenav .brand{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:10px;
font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--ink3);
padding:0 10px 8px;margin-bottom:6px;border-bottom:1px solid var(--rule)}
.tab{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:11.5px;
color:var(--ink3);background:transparent;border:1px solid transparent;border-radius:4px;
cursor:pointer;display:flex;align-items:center;justify-content:space-between;gap:8px;
width:100%;text-align:left;padding:7px 10px}
.tab:hover{color:var(--ink);background:var(--sunk)}
.tab[aria-selected="true"]{color:var(--ink);background:var(--accent-soft);
border-color:var(--accent-bd);font-weight:600}
.tab .cnt{font-size:10px;color:var(--ink4)}
.tab[aria-selected="true"] .cnt{color:var(--accent-ink)}

/* generic panel (regression / a11y) */
.panel{margin-top:20px;border:1px solid var(--rule);background:var(--surface)}
.phead{display:flex;align-items:baseline;justify-content:space-between;gap:10px;
padding:11px 14px;border-bottom:1px solid var(--rule);flex-wrap:wrap}
.phead h2{font-size:13.5px;margin:0;font-weight:700}
.phead .pnote{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:10.5px;color:var(--ink3)}
.pbody{padding:4px 14px}

.regrow{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:7px 0;font-size:13px;
border-bottom:1px solid var(--rule-soft)}
.regrow:last-child{border-bottom:none}
.regstep{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:11px;color:var(--ink3);
width:52px;flex:none}
.regfrom,.regto{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:11px}
.regto.crit{color:var(--crit);font-weight:600}
.regto.good{color:var(--good);font-weight:600}
.regarrow{color:var(--ink4)}
.regnote{color:var(--ink3);font-size:12px}
.regnote.crit{color:var(--crit)}.regnote.good{color:var(--good)}

.a11yrow{display:flex;gap:9px;align-items:baseline;padding:7px 0;font-size:13px;
border-bottom:1px solid var(--rule-soft)}
.a11yrow:last-child{border-bottom:none}
.a11yrow code{color:var(--warn)}
.a11ytag{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:11px;color:var(--ink3)}
.a11yname{color:var(--ink2)}

/* step ledger */
.ledger{display:flex;flex-direction:column}
.step{display:grid;grid-template-columns:44px 1fr 82px;border-bottom:1px solid var(--rule)}
.step:last-child{border-bottom:none}
.step.fail{background:linear-gradient(90deg,var(--crit-bg) 0,transparent 240px)}
.step.skip{opacity:.55}
.rail{padding:13px 0 13px 14px;border-right:1px solid var(--rule)}
.rail .sn{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:14px;font-weight:700;
color:var(--ink3)}
.step.fail .rail .sn{color:var(--crit)}
.body{padding:13px 14px;min-width:0}
.bhead{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.act{font-weight:700;font-size:13px}
.tagchip,.rbchip{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:10px;
padding:2px 6px;border-radius:3px;border:1px solid var(--rule);background:var(--sunk);
color:var(--ink3)}
.rbchip{background:var(--accent-soft);color:var(--accent-ink);border-color:var(--accent-bd)}
.priochip{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:10px;font-weight:700;
padding:2px 6px;border-radius:3px;text-transform:uppercase;letter-spacing:.03em;
background:var(--sunk);color:var(--ink3);border:1px solid var(--rule)}
.priochip.crit{background:var(--crit-bg);color:var(--crit);border-color:var(--crit-bd)}
.priochip.warn{background:var(--warn-bg);color:var(--warn);border-color:var(--warn-bd)}
.retrychip{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:10px;font-weight:700;
padding:2px 6px;border-radius:3px;background:var(--warn-bg);color:var(--warn);
border:1px solid var(--warn-bd)}
.ea{display:flex;gap:16px;margin-top:7px;font-size:12.5px;flex-wrap:wrap}
.ea div{color:var(--ink2);min-width:0}
.ea b{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:9px;letter-spacing:.07em;
text-transform:uppercase;color:var(--ink4);display:block;margin-bottom:2px;font-weight:600}
.purl{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:10.5px;color:var(--ink3);
margin-top:6px;word-break:break-all}
.reason{color:var(--ink2);font-size:12.5px;margin-top:8px}
.sugg{margin-top:8px;padding:7px 10px;background:var(--warn-bg);border:1px solid var(--warn-bd);
border-radius:3px;font-size:12.5px;color:var(--ink);display:flex;gap:7px}
.sugglbl{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:9px;letter-spacing:.07em;
color:var(--warn);font-weight:700;flex:none;padding-top:1px}
.evline{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:11px;padding:4px 8px;
border-radius:3px;margin-top:5px;word-break:break-all}
.evline.crit{background:var(--crit-bg);color:var(--crit)}
.evtag{font-weight:700;letter-spacing:.04em;margin-right:5px}
.evk{color:var(--ink3);margin-right:6px}
.evline.crit .evk{color:inherit;opacity:.7}
.shot{margin-top:9px}
.shot img{max-width:220px;border:1px solid var(--rule);border-radius:3px;display:block}
.shotpath{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:10px;color:var(--ink3);
display:block;margin-top:4px;word-break:break-all}
.right{padding:13px 12px;text-align:right}
.verdict{display:inline-flex;align-items:center;gap:4px;font-family:'JetBrains Mono',
ui-monospace,monospace;font-size:10px;font-weight:700;letter-spacing:.04em;padding:3px 7px;
border-radius:3px;border:1px solid}
.verdict.pass{background:var(--good-bg);color:var(--good);border-color:var(--good-bd)}
.verdict.fail{background:var(--crit-bg);color:var(--crit);border-color:var(--crit-bd)}
.verdict.skip{background:var(--skip-bg);color:var(--skip);border-color:var(--skip-bd)}
.vicon{width:8px;height:8px;flex:none}
.sevtag{display:block;font-family:'JetBrains Mono',ui-monospace,monospace;font-size:9.5px;
color:var(--ink4);margin-top:5px}
.dur{display:block;font-family:'JetBrains Mono',ui-monospace,monospace;font-size:10px;
color:var(--ink4);margin-top:5px}

.foot{margin-top:24px;padding-top:14px;border-top:1px solid var(--rule);
font-family:'JetBrains Mono',ui-monospace,monospace;font-size:10.5px;color:var(--ink3);
line-height:1.8}

@media (max-width:640px){
  .cluster{grid-template-columns:1fr}
  .gaugebox{border-right:none;border-bottom:1px solid var(--rule)}
  .statrow{grid-template-columns:1fr 1fr}
  .stat:nth-child(3){border-left:none}
  .step{grid-template-columns:38px 1fr;grid-template-rows:auto auto}
  .right{grid-column:1/-1;text-align:left;padding:0 14px 12px;display:flex;
  align-items:center;gap:10px;border-top:1px solid var(--rule-soft)}
  .rail{padding-left:10px}
  .layout{grid-template-columns:1fr;gap:0;margin-top:14px}
  .sidenav{position:static;margin-bottom:12px;border-bottom:1px solid var(--rule);
  padding-bottom:8px}
  .sidenav .inner{flex-direction:row;gap:4px;overflow-x:auto;scrollbar-width:none}
  .sidenav .inner::-webkit-scrollbar{display:none}
  .sidenav .brand{display:none}
  .tab{width:auto;white-space:nowrap}
}
@media (prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
"""


def _gauge_svg(pct: int, ok: bool) -> str:
    """Pass-rate meter as inline SVG — a full ring, arc math done here in Python
    (stroke-dasharray/dashoffset) so the report needs no client-side script.

    ``ok`` (no failures) picks the ring color: even a high rate is not "green"
    if something failed — matches the header's rate-color rule below.
    """
    size, r, sw = 148, 60, 10
    c = size / 2
    circumference = 2 * math.pi * r
    offset = circumference * (1 - max(0, min(100, pct)) / 100)
    color = "var(--good)" if ok else "var(--crit)"
    ticks = []
    for frac in (0, 0.25, 0.5, 0.75):
        a = math.radians(-90 + frac * 360)
        x1, y1 = c + (r - 13) * math.cos(a), c + (r - 13) * math.sin(a)
        x2, y2 = c + (r - 7) * math.cos(a), c + (r - 7) * math.sin(a)
        ticks.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                     f'stroke="var(--ink4)" stroke-width="1.5"/>')
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" role="img" '
        f'aria-label="pass rate {pct}%">'
        f'<circle cx="{c}" cy="{c}" r="{r}" fill="none" stroke="var(--track)" '
        f'stroke-width="{sw}"/>'
        f'<circle cx="{c}" cy="{c}" r="{r}" fill="none" stroke="{color}" stroke-width="{sw}" '
        f'stroke-linecap="round" stroke-dasharray="{circumference:.2f}" '
        f'stroke-dashoffset="{offset:.2f}" transform="rotate(-90 {c} {c})"/>'
        + "".join(ticks) +
        f'<text x="{c}" y="{c - 2}" text-anchor="middle" font-family="\'JetBrains Mono\',ui-monospace,'
        f'monospace" font-size="22" font-weight="700" fill="var(--ink)">{pct}%</text>'
        f'</svg>'
    )


def _short_time(ts) -> str:
    ts = str(ts or "")
    return ts.split("T", 1)[1][:8] if "T" in ts else ts[:16]


def _trend_html(result: dict) -> str:
    """Recent same-name runs as small shared-scale bars (SM-07's trend).

    A fixed px-per-step scale across ALL shown bars (not one width per bar) so
    a run with more steps actually draws a longer bar — an earlier per-bar-
    independent scale silently implied every run had the same step count.
    """
    trend = result.get("trend") or {}
    recent = trend.get("recent") or []
    if len(recent) < 2:
        return ""
    max_total = max((r.get("total", 0) for r in recent), default=0) or 1
    unit = 64 / max_total
    bars = []
    for i, r in enumerate(recent):
        total = r.get("total", 0)
        passed = r.get("passed", 0)
        failed = r.get("failed", 0)
        skipped = max(total - passed - failed, 0)
        segs = "".join(
            f'<span class="tseg {cls}" style="width:{n * unit:.1f}px"></span>'
            for cls, n in (("good", passed), ("crit", failed), ("skip", skipped)) if n
        )
        now = " now" if i == len(recent) - 1 else ""
        bars.append(
            f'<div class="trun{now}"><div class="tbar">{segs}</div>'
            f'<div class="tlabel"><span>{passed}/{total}</span>'
            f'<span>{html.escape(_short_time(r.get("ts")))}</span></div></div>'
        )
    streak = trend.get("consecutive_failures", 0)
    streak_html = f'<span class="tstreak">연속 실패 {streak}회</span>' if streak > 1 else ""
    return (f'<div class="trendrow"><div class="trendlabel">최근 실행{streak_html}</div>'
           f'<div class="trend-runs">{"".join(bars)}</div></div>')


def _render_html(result: dict, report_dir: Path) -> str:
    s = result.get("summary", {})
    meta = result.get("meta", {})
    rate = s.get("pass_rate", 0)
    pct = int(rate * 100)
    failed = s.get("failed", 0)
    total = s.get("total", 0)
    executed = total - s.get("skipped", 0)
    name = html.escape(result.get("name", "scenario"))
    desc = html.escape(result.get("description") or "")

    env_chips = [
        f'<span class="chip">{html.escape(str(meta.get("os")))} · '
        f'py{html.escape(str(meta.get("python")))}</span>',
        f'<span class="chip">playwright {html.escape(str(meta.get("playwright")))}</span>',
        f'<span class="chip">{html.escape(str(meta.get("browser")))}'
        f'{" " + html.escape(str(meta.get("browser_version"))) if meta.get("browser_version") else ""}'
        f' · headless={meta.get("headless")}</span>',
    ]
    if meta.get("viewport"):
        env_chips.append(f'<span class="chip">{html.escape(str(meta["viewport"]))}</span>')
    if meta.get("credentials_masked"):
        env_chips.append(
            '<span class="chip mask"><svg width="10" height="10" viewBox="0 0 10 10" '
            'style="vertical-align:-1px;margin-right:1px"><path d="M3 4.3V3.2a2 2 0 0 1 4 0v1.1" '
            'fill="none" stroke="currentColor" stroke-width="1.1"/><rect x="2.3" y="4.3" '
            'width="5.4" height="4.4" rx=".8" fill="currentColor"/></svg>creds masked</span>')

    target_html = (f'<span><b>대상</b> {html.escape(str(meta["target_url"]))}</span>'
                   if meta.get("target_url") else "")
    run_html = f'<span><b>run</b> {html.escape(str(result["run_id"]))}</span>' if result.get("run_id") else ""

    steps_html = "".join(_step_html(st, report_dir) for st in result.get("steps", []))
    trace_html = (f'trace: {html.escape(str(result["trace"]))} '
                 f'(playwright show-trace로 열기)<br>' if result.get("trace") else "")

    steps_panel = f"""<section class="panel">
  <div class="phead"><h2>Steps</h2><span class="pnote">{total} total</span></div>
  <div class="ledger">{steps_html}</div>
</section>"""
    chapters: list[tuple[str, str, int | None, str]] = [
        ("ch-steps", "Steps", None, steps_panel)]
    reg_panel = _regression_html(result)
    if reg_panel:
        n = len((result.get("regression") or {}).get("changed") or [])
        chapters.append(("ch-regression", "회귀", n, reg_panel))
    a11y_panel = _a11y_html(result)
    if a11y_panel:
        chapters.append(("ch-a11y", "접근성", len(result.get("a11y_findings") or []), a11y_panel))
    # A single chapter (the common case: just Steps, nothing to switch
    # between) renders exactly as before — no sidebar, no script.
    body_html = _chapters_html(chapters) if len(chapters) > 1 else steps_panel

    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>UI Blackbox Report — {name}</title><style>{_CSS}</style></head>
<body><div class="wrap">

<header class="mast">
  <div class="eyebrow">UI Blackbox Report</div>
  <h1>{name}</h1>
  {f'<p class="desc">{desc}</p>' if desc else ''}
  <div class="mmeta">{run_html}
    <span><b>시작</b> {html.escape(str(meta.get('started_at', '')))}</span>
    {target_html}</div>
</header>

<div class="cluster">
  <div class="gaugebox">
    <div class="glabel">Pass rate</div>
    {_gauge_svg(pct, failed == 0)}
    <div class="gsub">{s.get('passed', 0)} / {executed} executed</div>
  </div>
  <div class="rightcol">
    <div class="statrow">
      <div class="stat"><div class="sv" style="color:var(--good)">{s.get('passed', 0)}</div>
        <div class="sl">passed</div></div>
      <div class="stat"><div class="sv" style="color:var(--crit)">{failed}</div>
        <div class="sl">failed</div></div>
      <div class="stat"><div class="sv" style="color:var(--skip)">{s.get('skipped', 0)}</div>
        <div class="sl">skipped</div></div>
      <div class="stat"><div class="sv">{meta.get('duration_ms', 0)}<span
        style="font-size:12px;color:var(--ink3)">ms</span></div>
        <div class="sl">전체 소요</div></div>
    </div>
    <div class="envrow">{''.join(env_chips)}</div>
    {_trend_html(result)}
  </div>
</div>

{body_html}

<div class="foot">
  {trace_html}실패 원인·제안은 규칙 기반 힌트입니다 — 대화형(Claude) 실행 시 호스트 LLM이
  분석으로 보강합니다.<br>
  generated by ui-blackbox-mcp
</div>

</div></body></html>"""


# Without JS the sidebar cannot switch anything, so it hides itself and the
# chapters simply stack — i.e. exactly the pre-sidebar layout, fully readable,
# printable and Ctrl+F-able. The document ships every panel VISIBLE; collapsing
# to one is what the script adds.
_CHAPTERS_NOSCRIPT = ("<noscript><style>.sidenav{display:none}"
                      ".layout{grid-template-columns:1fr;gap:0}</style></noscript>")

_CHAPTERS_SCRIPT = """<script>
(function(){
  var tabs = Array.prototype.slice.call(document.querySelectorAll('.tab[role="tab"]'));
  if (!tabs.length) return;
  var panelOf = {};
  tabs.forEach(function(t){ panelOf[t.id] = document.getElementById(t.getAttribute('aria-controls')); });
  function show(t){
    tabs.forEach(function(o){
      var on = o === t;
      o.setAttribute('aria-selected', on ? 'true' : 'false');
      o.setAttribute('tabindex', on ? '0' : '-1');
      if (panelOf[o.id]) panelOf[o.id].hidden = !on;
    });
  }
  // Progressive enhancement: the served HTML has no `hidden` anywhere, so a
  // viewer without JS reads every chapter. This first call is what collapses
  // the stack into tabs.
  show(tabs[0]);
  tabs.forEach(function(t, i){
    t.addEventListener('click', function(){
      show(t);
      panelOf[t.id].scrollIntoView({block: 'start'});
    });
    // Arrow keys are part of the tab pattern this markup claims (role=tab);
    // without them the widget is mouse-only.
    t.addEventListener('keydown', function(e){
      var d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
      if (!d) return;
      e.preventDefault();
      var next = tabs[(i + d + tabs.length) % tabs.length];
      show(next);
      next.focus();
    });
  });
})();
</script>"""


def _chapters_html(chapters: list[tuple[str, str, int | None, str]]) -> str:
    """Left-sidebar tab-panel switching across a run's chapters (Steps plus
    whichever of regression/a11y have data). Called only when there are 2+
    chapters — a single chapter has nothing to switch between, so
    ``_render_html`` skips this and emits that chapter's panel bare (no
    sidebar, no inline script; DESIGN §6.2 stays satisfied trivially since
    most runs never reach this path at all).

    The one inline ``<script>`` this emits is local, non-network tab
    switching — DESIGN §6.2 rules out *external* dependencies/network, not
    inline behavior; the earlier no-JS design simply never needed a script
    until multi-chapter navigation did.

    That script is an ENHANCEMENT, never a gate on content. Panels ship with
    no ``hidden`` attribute, so a viewer that does not run scripts (print
    preview, a corporate document viewer, a mail client) still reads every
    chapter — the 회귀 diff, the most actionable signal in the report, was
    otherwise sealed behind a click that could never happen. The script hides
    the inactive panels on load; a <noscript> rule drops the then-useless
    sidebar so the chapters simply stack, exactly as they did before tabs.
    """
    tabs, panels = [], []
    for i, (cid, label, count, body) in enumerate(chapters):
        active = i == 0
        cnt_html = f'<span class="cnt">{count}</span>' if count else ""
        tabs.append(
            f'<button class="tab" role="tab" id="tabbtn-{cid}" aria-controls="{cid}" '
            f'aria-selected="{"true" if active else "false"}" '
            f'tabindex="{"0" if active else "-1"}">'
            f'{html.escape(label)}{cnt_html}</button>')
        panels.append(
            f'<section id="{cid}" role="tabpanel" aria-labelledby="tabbtn-{cid}" '
            f'tabindex="0">{body}</section>')
    return (
        _CHAPTERS_NOSCRIPT + '\n'
        '<div class="layout">\n<nav class="sidenav" aria-label="리포트 챕터">\n'
        '  <div class="inner" role="tablist" aria-label="챕터">\n'
        '    <span class="brand">CHAPTERS</span>\n    '
        + "\n    ".join(tabs) + "\n  </div>\n</nav>\n"
        '<div class="content">\n' + "\n".join(panels) + "\n</div>\n</div>\n"
        + _CHAPTERS_SCRIPT
    )


def _priority_class(priority) -> str:
    p = str(priority or "").strip().lower()
    if p == "blocker":
        return "crit"
    if p == "high":
        return "warn"
    return ""


_VERDICT_PATH = {
    "pass": '<path d="M1 5.5 4 8.5 9 2" stroke="currentColor" stroke-width="1.6" fill="none" '
           'stroke-linecap="round" stroke-linejoin="round"/>',
    "fail": '<path d="M2 2 8 8M8 2 2 8" stroke="currentColor" stroke-width="1.6" '
           'stroke-linecap="round"/>',
    "skip": '<path d="M2 5h6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
}


def _step_html(st: dict, report_dir: Path) -> str:
    ok = bool(st.get("passed"))
    skipped = bool(st.get("skipped"))
    verdict = "skip" if skipped else ("pass" if ok else "fail")

    thumb = ""
    if st.get("screenshot"):
        data = _b64(report_dir / st["screenshot"], report_dir)
        if data:
            uri = f"data:image/png;base64,{data}"
            thumb = (f'<div class="shot"><a href="{uri}" target="_blank">'
                     f'<img src="{uri}" alt="step {html.escape(str(st.get("step")))} '
                     f'screenshot"></a><span class="shotpath">'
                     f'{html.escape(str(st["screenshot"]))}</span></div>')

    evidence = ""
    for ce in st.get("console_errors") or []:
        # source="pageerror" is an UNCAUGHT exception (an app bug), not a
        # deliberate console.error call — worth flagging distinctly (§13).
        etag = '<span class="evtag">UNCAUGHT</span>' if ce.get("source") == "pageerror" else ""
        evidence += (f'<div class="evline crit">{etag}<span class="evk">console</span>'
                    f'{html.escape(str(ce.get("text")))}</div>')
    for ne in st.get("network_errors") or []:
        status = ne.get("status") or ne.get("failure")
        evidence += (f'<div class="evline crit"><span class="evk">network</span>'
                    f'{html.escape(str(ne.get("url")))} — {html.escape(str(status))}</div>')
    for dl in st.get("dialogs") or []:
        unexpected = not dl.get("expected")
        cls = "evline crit" if unexpected else "evline"
        label = "예상치 못한 dialog" if unexpected else "dialog"
        evidence += (f'<div class="{cls}"><span class="evk">{label}</span>'
                    f'{html.escape(str(dl.get("type")))} '
                    f'“{html.escape(_short(dl.get("message"), 120))}” → '
                    f'{html.escape(str(dl.get("handled")))}</div>')

    tag_chip = (f'<span class="tagchip">{html.escape(str(st["tag"]))}</span>'
               if st.get("tag") else "")
    prio_chip = (f'<span class="priochip {_priority_class(st.get("priority"))}">'
                f'{html.escape(str(st["priority"]))}</span>' if st.get("priority") else "")
    rb_chip = (f'<span class="rbchip">{html.escape(str(st["resolved_by"]))}</span>'
              if st.get("resolved_by") else "")
    retry_chip = (f'<span class="retrychip">&#8635; &times;{st.get("retries")} retry</span>'
                 if ok and st.get("retries") else "")

    purl = (f'<div class="purl">페이지 {html.escape(_short(st.get("page_url"), 100))}</div>'
           if not ok and not skipped and st.get("page_url") else "")
    reason = (f'<div class="reason">{html.escape(str(st["ai_reason"]))}</div>'
             if st.get("ai_reason") else "")
    sugg = (f'<div class="sugg"><span class="sugglbl">SUGGEST</span>'
           f'{html.escape(str(st["ai_suggestion"]))}</div>' if st.get("ai_suggestion") else "")
    sev_html = (f'<span class="sevtag">{html.escape(str(st["severity"]))}</span>'
               if not ok and not skipped and st.get("severity") else "")

    dur = st.get("duration_ms")
    dur_html = f'{dur}ms' if dur is not None else "—"

    return f"""<div class="step {verdict}">
      <div class="rail"><span class="sn">{html.escape(str(st.get('step', '')))}</span></div>
      <div class="body">
        <div class="bhead"><span class="act">{html.escape(str(st.get('action') or ''))}</span>
          {rb_chip}{tag_chip}{prio_chip}{retry_chip}</div>
        <div class="ea">
          <div><b>expect</b>{html.escape(_short(_dash(st.get('expected')), 90))}</div>
          <div><b>actual</b>{html.escape(_short(_dash(st.get('actual')), 90))}</div>
        </div>
        {purl}{reason}{sugg}{evidence}{thumb}
      </div>
      <div class="right">
        <span class="verdict {verdict}"><svg class="vicon" viewBox="0 0 10 10">
        {_VERDICT_PATH[verdict]}</svg>{verdict.upper()}</span>
        {sev_html}<span class="dur">{dur_html}</span>
      </div>
    </div>"""


def _regression_html(result: dict) -> str:
    reg = result.get("regression") or {}
    changed = reg.get("changed") or []
    if not changed:
        return ""
    rows = []
    for c in changed:
        frm, to = c.get("from"), c.get("to")
        note = ""
        if frm == "absent":
            note = '<span class="regnote">이전 실행엔 없던 스텝 — 새로 추가되며 결과가 기록됨</span>'
        elif frm == "passed" and to == "failed":
            note = '<span class="regnote crit">이전엔 통과했으나 이번에 실패</span>'
        elif frm == "failed" and to == "passed":
            note = '<span class="regnote good">이전 실패가 이번에 해결됨</span>'
        to_cls = "crit" if to == "failed" else ("good" if to == "passed" else "")
        rows.append(
            f'<div class="regrow"><span class="regstep">step {html.escape(str(c.get("step")))}</span>'
            f'<span class="regfrom">{html.escape(str(frm))}</span><span class="regarrow">→</span>'
            f'<span class="regto {to_cls}">{html.escape(str(to))}</span>{note}</div>')
    prev = html.escape(str(reg.get("previous_run") or ""))
    return (f'<section class="panel"><div class="phead"><h2>회귀 · 직전 실행 대비</h2>'
           f'<span class="pnote">기준: {prev}</span></div>'
           f'<div class="pbody">{"".join(rows)}</div></section>')


def _a11y_html(result: dict) -> str:
    a11y = result.get("a11y_findings") or []
    if not a11y:
        return ""
    items = "".join(
        f'<div class="a11yrow"><code>{html.escape(str(f.get("type")))}</code>'
        f'<span class="a11ytag">&lt;{html.escape(str(f.get("tag")))}&gt;</span>'
        f'<span class="a11yname">{html.escape(str(f.get("name") or f.get("info") or ""))}'
        f'</span></div>' for f in a11y[:30])
    return (f'<section class="panel"><div class="phead"><h2>접근성 발견</h2>'
           f'<span class="pnote">{len(a11y)}건</span></div>'
           f'<div class="pbody">{items}</div></section>')


def _b64(path: Path, base: Path) -> str | None:
    """Embed only files under the report dir — a step record's screenshot field
    is data, not a license to inline arbitrary local files into the HTML."""
    try:
        if not path.resolve().is_relative_to(base.resolve()):
            return None
        return base64.b64encode(path.read_bytes()).decode("ascii")
    except Exception:
        return None
