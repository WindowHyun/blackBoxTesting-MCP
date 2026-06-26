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
import re
from datetime import datetime
from pathlib import Path

from ..config import CONFIG

_SAFE = re.compile(r"[^A-Za-z0-9_\-]")


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


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
        return result
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
    try:
        path.write_text(json.dumps(
            {"ts": result.get("meta", {}).get("started_at"), "steps": cur},
            ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return result


async def capture_step_screenshot(session, name: str, idx: int) -> str | None:
    """Capture the current page to reports/screenshots and return a rel path."""
    try:
        base = ensure_dirs()
        safe = _SAFE.sub("_", name)
        rel = Path("screenshots") / f"{safe}_step{idx:02d}.png"
        await session.page.screenshot(path=str(base / rel))
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


# ── HTML (self-contained, mint theme to match the PRD) ────────────
_CSS = """
:root{--bg:#f5f6f8;--surface:#fff;--surface2:#f0f2f5;--border:#e1e4eb;--ink:#0d1117;
--ink2:#353d4f;--ink3:#6a7386;--ink4:#9da6b8;--mint:#0baa77;--mint-dim:#089965;
--mint-bg:#edf9f4;--mint-bd:#b0e6d0;--red:#c93030;--red-bg:#fdf2f2;--red-bd:#f5c0c0;
--amber:#c9780a;--amber-bg:#fff8ed;--amber-bd:#fcd89a;--blue:#1a56e8;--blue-bg:#eff3fd;}
*{box-sizing:border-box}
body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--ink);
margin:0;padding:32px 24px;font-size:14px;line-height:1.6;-webkit-font-smoothing:antialiased}
.wrap{max-width:980px;margin:0 auto}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;
padding:24px 28px;margin-bottom:18px}
.eyebrow{font:500 11px/1 'IBM Plex Mono',monospace;letter-spacing:.14em;
text-transform:uppercase;color:var(--mint-dim);margin-bottom:10px}
h1.title{font-size:26px;font-weight:700;letter-spacing:-.02em;margin:0 0 6px}
.desc{color:var(--ink2);font-size:14px;margin:8px 0 18px;max-width:640px}
.hero{display:flex;align-items:center;gap:22px;flex-wrap:wrap}
.bigrate{font-size:40px;font-weight:700;letter-spacing:-.02em}
.bar{flex:1;min-width:200px;height:12px;background:var(--surface2);border-radius:99px;overflow:hidden}
.bar > span{display:block;height:100%;background:var(--mint)}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}
.chip{font:500 11px/1 'IBM Plex Mono',monospace;padding:5px 9px;border-radius:5px;
border:1px solid var(--border);background:var(--surface2);color:var(--ink3)}
.chip.pass{background:var(--mint-bg);border-color:var(--mint-bd);color:var(--mint-dim)}
.chip.fail{background:var(--red-bg);border-color:var(--red-bd);color:var(--red)}
.sec{font:600 12px/1 'IBM Plex Mono',monospace;letter-spacing:.1em;text-transform:uppercase;
color:var(--ink4);margin:0 0 14px}
.step{display:grid;grid-template-columns:34px 1fr 150px;gap:14px;padding:16px 0;
border-top:1px solid var(--border)}
.step:first-of-type{border-top:none}
.step.fail{background:linear-gradient(90deg,var(--red-bg),transparent);
margin:0 -28px;padding:16px 28px}
.num{font:600 13px/1 'IBM Plex Mono',monospace;color:var(--ink4);padding-top:3px}
.act{font-weight:600;font-size:14px}
.kv{color:var(--ink3);font-size:12.5px;margin-top:3px}
.kv b{color:var(--ink2);font-weight:600}
.rb{font:500 11px/1 'IBM Plex Mono',monospace;background:var(--blue-bg);color:var(--blue);
padding:2px 6px;border-radius:4px;margin-left:6px}
.reason{color:var(--ink2);font-size:12.5px;margin-top:6px}
.sugg{color:var(--amber);background:var(--amber-bg);border:1px solid var(--amber-bd);
border-radius:5px;padding:6px 10px;font-size:12.5px;margin-top:8px}
.err{color:var(--red);font:12px/1.5 'IBM Plex Mono',monospace;margin-top:4px}
.right{text-align:right}
.verdict{font:700 12px/1 'IBM Plex Mono',monospace;padding:5px 10px;border-radius:5px;
display:inline-block}
.verdict.pass{background:var(--mint-bg);color:var(--mint-dim);border:1px solid var(--mint-bd)}
.verdict.fail{background:var(--red-bg);color:var(--red);border:1px solid var(--red-bd)}
.sev{display:block;font:10px/1 'IBM Plex Mono',monospace;color:var(--ink4);margin-top:5px}
.time{display:block;font-size:11px;color:var(--ink4);margin-top:5px}
.thumb{margin-top:10px;border:1px solid var(--border);border-radius:6px;max-height:130px;
display:block}
ul.list{margin:0;padding-left:18px}ul.list li{margin:3px 0;font-size:13px;color:var(--ink2)}
code{font:12px 'IBM Plex Mono',monospace;background:var(--surface2);padding:1px 5px;border-radius:3px}
.foot{color:var(--ink4);font:11px 'IBM Plex Mono',monospace;text-align:center;margin-top:8px}
"""


def _render_html(result: dict, report_dir: Path) -> str:
    s = result.get("summary", {})
    meta = result.get("meta", {})
    rate = s.get("pass_rate", 0)
    pct = int(rate * 100)
    bar_color = "var(--mint)" if s.get("failed", 0) == 0 else "var(--red)"
    rate_color = "var(--mint-dim)" if s.get("failed", 0) == 0 else "var(--red)"
    name = html.escape(result.get("name", "scenario"))
    desc = html.escape(result.get("description") or "")

    steps_html = "".join(_step_html(st, report_dir) for st in result.get("steps", []))

    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>UI Blackbox Report — {name}</title><style>{_CSS}</style></head>
<body><div class="wrap">
  <div class="card">
    <div class="eyebrow">● UI Blackbox Report</div>
    <h1 class="title">{name}</h1>
    {f'<p class="desc">{desc}</p>' if desc else ''}
    <div class="hero">
      <div class="bigrate" style="color:{rate_color}">{s.get('passed',0)}/{s.get('total',0)}</div>
      <div class="bar"><span style="width:{pct}%;background:{bar_color}"></span></div>
      <div style="font:600 14px/1 'IBM Plex Mono',monospace;color:{rate_color}">{pct}%</div>
    </div>
    <div class="chips">
      <span class="chip pass">PASS {s.get('passed',0)}</span>
      <span class="chip fail">FAIL {s.get('failed',0)}</span>
      <span class="chip">{meta.get('duration_ms',0)}ms</span>
      <span class="chip">{html.escape(str(meta.get('os')))} · py{html.escape(str(meta.get('python')))}</span>
      <span class="chip">playwright {html.escape(str(meta.get('playwright')))}</span>
      <span class="chip">{html.escape(str(meta.get('browser')))} · headless={meta.get('headless')}</span>
      <span class="chip pass">🔒 creds masked</span>
    </div>
  </div>
  <div class="card">
    <div class="sec">Steps</div>
    {steps_html}
  </div>
  {_extras_html(result)}
  <div class="foot">{html.escape(meta.get('started_at',''))} · generated by ui-blackbox-mcp</div>
</div></body></html>"""


def _step_html(st: dict, report_dir: Path) -> str:
    ok = st["passed"]
    thumb = ""
    if st.get("screenshot"):
        data = _b64(report_dir / st["screenshot"])
        if data:
            uri = f"data:image/png;base64,{data}"
            thumb = f'<a href="{uri}" target="_blank"><img class="thumb" src="{uri}"></a>'
    sugg = (f'<div class="sugg">💡 {html.escape(str(st["ai_suggestion"]))}</div>'
            if st.get("ai_suggestion") else "")
    errs = ""
    for ce in st.get("console_errors", []):
        errs += f'<div class="err">console: {html.escape(str(ce.get("text")))}</div>'
    for ne in st.get("network_errors", []):
        errs += (f'<div class="err">network: {html.escape(str(ne.get("url")))} '
                 f'{html.escape(str(ne.get("status") or ne.get("failure")))}</div>')
    rb = (f'<span class="rb">{html.escape(str(st["resolved_by"]))}</span>'
          if st.get("resolved_by") else "")
    sev = (f'<span class="sev">{html.escape(str(st.get("severity")))}</span>'
           if not ok and st.get("severity") else "")
    return f"""<div class="step {'fail' if not ok else ''}">
      <div class="num">{st['step']}</div>
      <div>
        <div class="act">{html.escape(str(st.get('action')))}{rb}</div>
        <div class="kv"><b>기대</b> {html.escape(_short(st.get('expected'),70))}
          &nbsp;·&nbsp; <b>실제</b> {html.escape(_short(st.get('actual'),70))}</div>
        <div class="reason">{html.escape(str(st.get('ai_reason') or ''))}</div>
        {sugg}{errs}{thumb}
      </div>
      <div class="right">
        <span class="verdict {'pass' if ok else 'fail'}">{'PASS' if ok else 'FAIL'}</span>
        {sev}<span class="time">{st.get('duration_ms')}ms</span>
      </div>
    </div>"""


def _extras_html(result: dict) -> str:
    out = ""
    reg = result.get("regression") or {}
    if reg.get("changed"):
        items = "".join(
            f"<li>step {c['step']}: {html.escape(c['from'])} → "
            f"<b>{html.escape(c['to'])}</b></li>" for c in reg["changed"])
        out += (f'<div class="card"><div class="sec">회귀 · 직전 실행 대비</div>'
                f'<div class="kv">기준: {html.escape(str(reg.get("previous_run")))}</div>'
                f'<ul class="list">{items}</ul></div>')
    a11y = result.get("a11y_findings") or []
    if a11y:
        items = "".join(
            f"<li><code>{html.escape(str(f.get('type')))}</code> "
            f"&lt;{html.escape(str(f.get('tag')))}&gt; "
            f"{html.escape(str(f.get('name') or f.get('info') or ''))}</li>"
            for f in a11y[:30])
        out += (f'<div class="card"><div class="sec">접근성 발견 · {len(a11y)}</div>'
                f'<ul class="list">{items}</ul></div>')
    return out


def _b64(path: Path) -> str | None:
    try:
        return base64.b64encode(path.read_bytes()).decode("ascii")
    except Exception:
        return None
