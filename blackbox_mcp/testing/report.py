"""Report generation (SM-03, SM-04, SM-08, D3).

Writes JSON / Markdown / HTML reports under REPORT_DIR (default ./reports),
created if missing. Filenames: report_YYYYMMDD_HHMMSS.{json,md,html}. Step
screenshots go under reports/screenshots/ and are embedded into the HTML as
base64 data URIs for single-file portability.
"""
from __future__ import annotations

import base64
import html
import json
import re
from datetime import datetime
from pathlib import Path

from ..config import CONFIG

_SAFE = re.compile(r"[^A-Za-z0-9_\-]")


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_dirs() -> Path:
    report_dir = CONFIG.report_dir
    (report_dir / "screenshots").mkdir(parents=True, exist_ok=True)
    return report_dir


def compute_regression(result: dict) -> dict:
    """SM-07: compare this run with the previous run of the same scenario.

    Reads/writes reports/history/{name}.json. Sets result['regression'] with the
    previous run timestamp and the list of steps whose pass/fail status changed,
    then records the current run as the new baseline.
    """
    name = result.get("name", "scenario")
    hist_dir = CONFIG.report_dir / "history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    path = hist_dir / f"{_SAFE.sub('_', name)}.json"

    cur = [{"step": s["step"], "action": s.get("action"), "passed": s["passed"]}
           for s in result.get("steps", [])]
    changed = []
    prev_ts = None
    if path.exists():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
            prev_ts = prev.get("ts")
            prev_by_step = {s["step"]: s["passed"] for s in prev.get("steps", [])}
            for s in cur:
                was = prev_by_step.get(s["step"])
                if was is None:
                    changed.append({"step": s["step"], "from": "absent",
                                    "to": "passed" if s["passed"] else "failed"})
                elif was != s["passed"]:
                    changed.append({"step": s["step"],
                                    "from": "passed" if was else "failed",
                                    "to": "passed" if s["passed"] else "failed"})
        except Exception:
            pass

    result["regression"] = {"previous_run": prev_ts, "changed": changed}
    path.write_text(json.dumps(
        {"ts": result.get("meta", {}).get("started_at"), "steps": cur},
        ensure_ascii=False, indent=2), encoding="utf-8")
    return result


async def capture_step_screenshot(session, name: str, idx: int) -> str | None:
    """Capture the current page to reports/screenshots and return a rel path."""
    try:
        ensure_dirs()
        safe = _SAFE.sub("_", name)
        rel = Path("screenshots") / f"{safe}_step{idx:02d}.png"
        await session.page.screenshot(path=str(CONFIG.report_dir / rel))
        return str(rel)
    except Exception:
        return None


def save(result: dict, formats: str = "both") -> dict[str, str]:
    """Persist a scenario result; return written file paths by format."""
    report_dir = ensure_dirs()
    stamp = _stamp()
    written: dict[str, str] = {}

    want_json = formats in ("json", "both", "all")
    want_md = formats in ("md", "both", "all")
    want_html = formats in ("html", "all")

    if want_json:
        p = report_dir / f"report_{stamp}.json"
        p.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        written["json"] = str(p)
    if want_md:
        p = report_dir / f"report_{stamp}.md"
        p.write_text(_render_markdown(result), encoding="utf-8")
        written["md"] = str(p)
    if want_html:
        p = report_dir / f"report_{stamp}.html"
        p.write_text(_render_html(result, report_dir), encoding="utf-8")
        written["html"] = str(p)

    return written


# ── Markdown ──────────────────────────────────────────────────────
def _render_markdown(result: dict) -> str:
    s = result.get("summary", {})
    meta = result.get("meta", {})
    lines = [
        f"# UI Blackbox Report — {result.get('name', 'scenario')}",
        "",
        f"**{s.get('passed', 0)}/{s.get('total', 0)} passed** "
        f"(rate {s.get('pass_rate', 0)}) · {meta.get('duration_ms', 0)} ms · "
        f"{meta.get('started_at', '')}",
        "",
        f"_env: {meta.get('os')} · py{meta.get('python')} · "
        f"playwright {meta.get('playwright')} · {meta.get('browser')}_",
        "",
        "| # | action | resolved | expected | actual | result | sev |",
        "|---|---|---|---|---|---|---|",
    ]
    for st in result.get("steps", []):
        res = "✅" if st["passed"] else "❌"
        lines.append(
            f"| {st['step']} | {st.get('action')} | {st.get('resolved_by') or ''} "
            f"| {_short(st.get('expected'))} | {_short(st.get('actual'))} | {res} "
            f"| {st.get('severity') or ''} |"
        )
    # failure details
    fails = [st for st in result.get("steps", []) if not st["passed"]]
    if fails:
        lines += ["", "## 실패 상세"]
        for st in fails:
            lines.append(f"- **step {st['step']} ({st.get('action')})** — "
                         f"{st.get('ai_reason')}. 제안: {st.get('ai_suggestion') or '—'}")
            if st.get("screenshot"):
                lines.append(f"  - 스크린샷: `{st['screenshot']}`")
            for ce in st.get("console_errors", []):
                lines.append(f"  - console: {ce.get('text')}")
            for ne in st.get("network_errors", []):
                lines.append(f"  - network: {ne.get('url')} "
                             f"{ne.get('status') or ne.get('failure')}")

    reg = result.get("regression") or {}
    if reg.get("changed"):
        lines += ["", "## 회귀 (직전 실행 대비)"]
        lines.append(f"_기준: {reg.get('previous_run')}_")
        for c in reg["changed"]:
            lines.append(f"- step {c['step']}: {c['from']} → **{c['to']}**")

    a11y = result.get("a11y_findings") or []
    if a11y:
        lines += ["", f"## 접근성 발견 ({len(a11y)})"]
        for f in a11y[:20]:
            lines.append(f"- `{f.get('type')}` <{f.get('tag')}> {f.get('name') or f.get('info') or ''}")
    return "\n".join(lines)


def _short(v, n: int = 40) -> str:
    s = str(v).replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


# ── HTML (self-contained) ─────────────────────────────────────────
def _render_html(result: dict, report_dir: Path) -> str:
    s = result.get("summary", {})
    meta = result.get("meta", {})
    rate = s.get("pass_rate", 0)
    bar = "#0baa77" if s.get("failed", 0) == 0 else "#c93030"

    rows = []
    for st in result.get("steps", []):
        ok = st["passed"]
        color = "#0baa77" if ok else "#c93030"
        img = ""
        if st.get("screenshot"):
            data = _b64(report_dir / st["screenshot"])
            if data:
                img = (f'<details><summary>screenshot</summary>'
                       f'<img src="data:image/png;base64,{data}" '
                       f'style="max-width:100%;border:1px solid #ddd"></details>')
        errs = ""
        for ce in st.get("console_errors", []):
            errs += f'<div class="err">console: {html.escape(str(ce.get("text")))}</div>'
        for ne in st.get("network_errors", []):
            errs += (f'<div class="err">network: {html.escape(str(ne.get("url")))} '
                     f'{ne.get("status") or ne.get("failure")}</div>')
        sugg = (f'<div class="sugg">제안: {html.escape(str(st["ai_suggestion"]))}</div>'
                if st.get("ai_suggestion") else "")
        rows.append(f"""
        <tr class="{'ok' if ok else 'fail'}">
          <td>{st['step']}</td>
          <td>{html.escape(str(st.get('action')))}</td>
          <td>{html.escape(str(st.get('resolved_by') or ''))}</td>
          <td>{html.escape(_short(st.get('expected'), 60))}</td>
          <td>{html.escape(_short(st.get('actual'), 60))}</td>
          <td style="color:{color};font-weight:600">{'PASS' if ok else 'FAIL'}
            <span class="sev">{html.escape(str(st.get('severity') or ''))}</span></td>
          <td>{st.get('duration_ms')}ms</td>
          <td><div class="reason">{html.escape(str(st.get('ai_reason') or ''))}</div>
              {sugg}{errs}{img}</td>
        </tr>""")

    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<title>UI Blackbox Report — {html.escape(result.get('name', 'scenario'))}</title>
<style>
body{{font-family:system-ui,sans-serif;margin:24px;color:#0d1117;background:#f5f6f8}}
.card{{background:#fff;border:1px solid #e1e4eb;border-radius:8px;padding:20px 24px;margin-bottom:16px}}
h1{{font-size:20px;margin:0 0 8px}}
.rate{{font-size:28px;font-weight:700;color:{bar}}}
.meta{{color:#6a7386;font-size:12px;font-family:monospace}}
table{{width:100%;border-collapse:collapse;background:#fff;font-size:13px}}
th,td{{border-bottom:1px solid #e1e4eb;padding:8px 10px;text-align:left;vertical-align:top}}
th{{font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:#9da6b8}}
tr.fail{{background:#fdf2f2}}
.sev{{font-size:10px;color:#9da6b8;font-family:monospace;margin-left:6px}}
.reason{{color:#353d4f}}.sugg{{color:#c9780a;font-size:12px;margin-top:4px}}
.err{{color:#c93030;font-family:monospace;font-size:12px}}
img{{margin-top:8px}}
</style></head><body>
<div class="card">
  <h1>UI Blackbox Report — {html.escape(result.get('name', 'scenario'))}</h1>
  <div class="rate">{s.get('passed', 0)}/{s.get('total', 0)} passed · {rate}</div>
  <div class="meta">{html.escape(meta.get('started_at', ''))} · {meta.get('duration_ms', 0)}ms ·
    {html.escape(str(meta.get('os')))} · py{html.escape(str(meta.get('python')))} ·
    playwright {html.escape(str(meta.get('playwright')))} ·
    {html.escape(str(meta.get('browser')))} · headless={meta.get('headless')} ·
    creds-masked={meta.get('credentials_masked')}</div>
</div>
<div class="card"><table>
<thead><tr><th>#</th><th>action</th><th>resolved</th><th>expected</th><th>actual</th>
<th>result</th><th>time</th><th>detail</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table></div>
{_extras_html(result)}
</body></html>"""


def _extras_html(result: dict) -> str:
    out = ""
    reg = result.get("regression") or {}
    if reg.get("changed"):
        items = "".join(
            f"<li>step {c['step']}: {html.escape(c['from'])} → "
            f"<b>{html.escape(c['to'])}</b></li>" for c in reg["changed"])
        out += (f'<div class="card"><h1>회귀 (직전 실행 대비)</h1>'
                f'<div class="meta">기준: {html.escape(str(reg.get("previous_run")))}</div>'
                f'<ul>{items}</ul></div>')
    a11y = result.get("a11y_findings") or []
    if a11y:
        items = "".join(
            f"<li><code>{html.escape(str(f.get('type')))}</code> "
            f"&lt;{html.escape(str(f.get('tag')))}&gt; "
            f"{html.escape(str(f.get('name') or f.get('info') or ''))}</li>"
            for f in a11y[:30])
        out += (f'<div class="card"><h1>접근성 발견 ({len(a11y)})</h1><ul>{items}</ul></div>')
    return out


def _b64(path: Path) -> str | None:
    try:
        return base64.b64encode(path.read_bytes()).decode("ascii")
    except Exception:
        return None
