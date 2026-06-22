"""Report generation (SM-03, D3).

Default output dir is ./reports (REPORT_DIR overrides); created if missing.
Filenames: report_YYYYMMDD_HHMMSS.{json,md}. Screenshots go under
reports/screenshots/ and are referenced relatively from the markdown.

Phase 0: paths + skeleton writers are in place; full markdown formatting lands
in Phase 3.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..config import CONFIG


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_dirs() -> Path:
    report_dir = CONFIG.report_dir
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "screenshots").mkdir(parents=True, exist_ok=True)
    return report_dir


def save(result: dict, formats: str = "both") -> dict[str, str]:
    """Persist a scenario result. Returns the written file paths.

    TODO(Phase 3): rich markdown (step table, failure screenshots, console /
    network error sections).
    """
    report_dir = ensure_dirs()
    stamp = _stamp()
    written: dict[str, str] = {}

    if formats in ("json", "both"):
        path = report_dir / f"report_{stamp}.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        written["json"] = str(path)

    if formats in ("md", "both"):
        path = report_dir / f"report_{stamp}.md"
        path.write_text(_render_markdown(result), encoding="utf-8")
        written["md"] = str(path)

    return written


def _render_markdown(result: dict) -> str:
    name = result.get("name", "scenario")
    summary = result.get("summary", {})
    lines = [
        f"# UI Blackbox Report — {name}",
        "",
        f"- total: {summary.get('total', 0)}",
        f"- passed: {summary.get('passed', 0)}",
        f"- failed: {summary.get('failed', 0)}",
        "",
        "_Full step table & screenshots: Phase 3._",
    ]
    return "\n".join(lines)
