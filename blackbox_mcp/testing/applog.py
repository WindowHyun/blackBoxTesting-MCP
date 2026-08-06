"""Application-log correlation — the half of "원인 추적" the browser can't see.

Everything else in this project observes the app from the outside: console,
network, dialogs, screenshots. When a step fails because the *server* threw,
the browser only shows a 500 and the reason lives in a log file the tool never
reads. This module attaches the log lines that were written **while a given
step was running**, so a failed step carries the stack trace that explains it.

Correlation is by wall clock: every step records ``started_at``/``ended_at``
(epoch seconds), and lines whose parsed timestamp falls in that window — plus
their continuation lines, which is where tracebacks actually live — are
attached to that step.

No log shipping, no parsing of app-specific formats beyond the timestamp: the
point is to put the evidence next to the failure, not to become a log tool.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from . import secrets

# Timestamp prefixes seen in ordinary app logs. First match wins.
_TS_PATTERNS = [
    # 2026-08-06 00:12:14,123 / 2026-08-06T00:12:14.123Z / with or without T/Z
    (re.compile(r"^\[?(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:[.,](\d{1,6}))?"),
     "iso"),
    # 06/Aug/2026:00:12:14 (Apache/nginx access log)
    (re.compile(r"\[(\d{2})/([A-Za-z]{3})/(\d{4}):(\d{2}:\d{2}:\d{2})"), "clf"),
]

_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}

# Lines worth surfacing. Anything else is noise next to a failure.
_INTERESTING = re.compile(
    r"\b(ERROR|SEVERE|CRITICAL|FATAL|WARN(?:ING)?|Exception|Traceback|"
    r"panic:|\bat [\w.$]+\(|\b5\d{2}\b)", re.I)

_MAX_LINES_PER_STEP = 40
_MAX_LINE_CHARS = 400
# Read at most this much of the tail: a run correlates against recent activity,
# and an unbounded read of a multi-GB production log would be the bug.
_MAX_TAIL_BYTES = 4 * 1024 * 1024


def _parse_ts(line: str) -> float | None:
    for pattern, kind in _TS_PATTERNS:
        m = pattern.search(line)
        if not m:
            continue
        try:
            if kind == "iso":
                date, clock, frac = m.group(1), m.group(2), m.group(3)
                dt = datetime.strptime(f"{date} {clock}", "%Y-%m-%d %H:%M:%S")
                micro = float(f"0.{frac}") if frac else 0.0
                return dt.timestamp() + micro
            day, mon, year, clock = m.groups()
            dt = datetime.strptime(
                f"{year}-{_MONTHS.get(mon, 1):02d}-{day} {clock}", "%Y-%m-%d %H:%M:%S")
            return dt.timestamp()
        except (ValueError, KeyError):
            return None
    return None


def read_tail(path: str | Path) -> list[tuple[float | None, str]]:
    """Return (timestamp, line) for the tail of a log file.

    Lines with no parseable timestamp inherit the previous line's — that is
    what keeps a Java/Python stack trace attached to the ERROR line that
    introduced it instead of being dropped.
    """
    p = Path(path).expanduser()
    try:
        size = p.stat().st_size
        with p.open("rb") as fh:
            if size > _MAX_TAIL_BYTES:
                fh.seek(size - _MAX_TAIL_BYTES)
                fh.readline()          # discard the partial first line
            raw = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return []

    out: list[tuple[float | None, str]] = []
    last_ts: float | None = None
    for line in raw.splitlines():
        ts = _parse_ts(line)
        if ts is not None:
            last_ts = ts
        out.append((last_ts, line))
    return out


def lines_for_window(entries: list[tuple[float | None, str]],
                     start: float, end: float,
                     grace_s: float = 1.0) -> list[str]:
    """Interesting log lines written during [start, end] (+ a small grace).

    The grace covers the gap between the browser giving up on a request and
    the server finishing the log write that explains why.
    """
    picked: list[str] = []
    for ts, line in entries:
        if ts is None or not (start - grace_s <= ts <= end + grace_s):
            continue
        if not _INTERESTING.search(line):
            continue
        picked.append(secrets.scrub(line)[:_MAX_LINE_CHARS])
        if len(picked) >= _MAX_LINES_PER_STEP:
            picked.append("… (truncated)")
            break
    return picked


def attach(result: dict, log_path: str | Path) -> dict:
    """Attach ``app_log`` to every step of a finished run.

    Failed steps are the point, but passing steps get theirs too: a step that
    passed while the server logged a stack trace is exactly the silent defect
    this project keeps finding.
    """
    entries = read_tail(log_path)
    if not entries:
        for step in result.get("steps", []):
            step.setdefault("app_log", [])
        result.setdefault("meta", {})["app_log"] = f"{log_path} (unreadable/empty)"
        return result

    for step in result.get("steps", []):
        start, end = step.get("started_at"), step.get("ended_at")
        if start is None or end is None:
            step.setdefault("app_log", [])
            continue
        step["app_log"] = lines_for_window(entries, start, end)

    result.setdefault("meta", {})["app_log"] = str(log_path)
    return result
