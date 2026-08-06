"""Failure memory — does the loop recognise this failure, or is it new?

``report.compute_regression`` answers "did anything change since the PREVIOUS
run", which is one step of history. An autonomous loop needs more: it has to
know whether a failure is brand new (investigate), chronic (already known, do
not re-diagnose from scratch), or a regression of something that was fixed
(the fix did not hold). That distinction is what stops the loop from
re-deriving the same diagnosis every cycle.

Stored at ``reports/memory/failures.json``, keyed by a *fingerprint* that
stays stable across runs even though run ids, timestamps and ports do not.

Security: entries are built from step records that ``secrets.scrub_record``
has already cleaned, so no resolved credential reaches this file. Signatures
are additionally normalised (below), which strips most volatile detail anyway.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

# Volatile parts of a failure message that must NOT make two occurrences of the
# same failure look different: ports, ids, timestamps, run-specific paths.
_VOLATILE = [
    (re.compile(r"https?://[^/\s]+"), "<origin>"),   # host:port
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ][\d:.]+"), "<ts>"),
    (re.compile(r"\b[0-9a-f]{8,}\b", re.I), "<hex>"),
    (re.compile(r"\d+"), "<n>"),
    (re.compile(r"\s+"), " "),
]

_MAX_SIGNATURE = 200
_MAX_RUNS_KEPT = 20      # per fingerprint, newest last
_MAX_ENTRIES = 500       # oldest last_seen evicted first

# NUL, not a space: with a space separator "a b" + "c" and "a" + "b c" hash the
# same, so two different failures could share one fingerprint.
_SEP = "\x00"


def _memory_path() -> Path:
    from .report import ensure_dirs
    base = ensure_dirs() / "memory"
    base.mkdir(parents=True, exist_ok=True)
    return base / "failures.json"


def normalize(text: Any) -> str:
    """Collapse a failure message to its stable shape.

    "expected 6, got 4 at http://127.0.0.1:53211/x" and the same failure on
    another port must produce one fingerprint, or every run looks like a new
    problem and the memory is worthless.
    """
    s = str(text or "")
    for pattern, replacement in _VOLATILE:
        s = pattern.sub(replacement, s)
    return s.strip()[:_MAX_SIGNATURE]


def fingerprint(scenario: str, step: dict) -> str:
    """Stable id for "this particular failure of this particular step".

    Deliberately keyed on WHAT was checked (action + target + severity +
    normalised message), not on the step NUMBER: inserting a step earlier in a
    scenario must not make every later failure look new.
    """
    parts = [
        scenario or "",
        str(step.get("action") or ""),
        str(step.get("selector_input") or ""),
        str(step.get("severity") or ""),
        normalize(step.get("actual")),
    ]
    return hashlib.sha256(_SEP.join(parts).encode("utf-8")).hexdigest()[:16]


def load() -> dict:
    try:
        data = json.loads(_memory_path().read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("failures"), dict):
            return data
    except Exception:
        pass
    return {"version": 1, "failures": {}}


def _save(data: dict) -> None:
    failures = data.get("failures", {})
    if len(failures) > _MAX_ENTRIES:
        # Evict least-recently-seen; the memory is a working set, not an archive.
        keep = sorted(failures.items(), key=lambda kv: kv[1].get("last_seen", ""),
                      reverse=True)[:_MAX_ENTRIES]
        data["failures"] = dict(keep)
    try:
        _memory_path().write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass  # memory is an optimisation; never break a run over it


def annotate(result: dict) -> dict:
    """Attach prior-history to each failed step, then persist this run.

    Order matters: annotation reads the store BEFORE this run is recorded, so
    ``occurrences`` means "times seen before now" and a first failure reads as
    ``new`` rather than ``recurring``.
    """
    data = load()
    failures = data["failures"]
    scenario = result.get("name", "scenario")
    now = datetime.now().isoformat(timespec="seconds")
    run_id = result.get("run_id")

    seen_now: set[str] = set()

    for step in result.get("steps", []):
        if step.get("passed") or step.get("skipped"):
            continue
        fp = fingerprint(scenario, step)
        seen_now.add(fp)
        prior = failures.get(fp)

        if prior is None:
            status, occurrences, first_seen = "new", 0, None
        elif prior.get("resolved_at"):
            status = "regressed"
            occurrences, first_seen = prior.get("occurrences", 0), prior.get("first_seen")
        else:
            status = "recurring"
            occurrences, first_seen = prior.get("occurrences", 0), prior.get("first_seen")

        step["fingerprint"] = fp
        step["memory"] = {
            "status": status,                 # new | recurring | regressed
            "seen_before": occurrences,
            "first_seen": first_seen,
            "last_seen": (prior or {}).get("last_seen"),
        }

        entry = prior or {
            "scenario": scenario,
            "action": step.get("action"),
            "selector": step.get("selector_input"),
            "severity": step.get("severity"),
            "signature": normalize(step.get("actual")),
            "first_seen": now,
            "occurrences": 0,
            "runs": [],
        }
        entry.update(last_seen=now, occurrences=entry.get("occurrences", 0) + 1,
                     severity=step.get("severity"), resolved_at=None, resolution=None)
        runs = [r for r in entry.get("runs", []) if r] + ([run_id] if run_id else [])
        entry["runs"] = runs[-_MAX_RUNS_KEPT:]
        failures[fp] = entry

    _mark_resolved(failures, scenario, result, seen_now, now)
    _save(data)
    return result


def _mark_resolved(failures: dict, scenario: str, result: dict,
                   seen_now: set[str], now: str) -> None:
    """A known failure that did NOT recur in a run of the same scenario counts
    as resolved — that is the signal the loop uses to confirm a fix held.

    Only closes entries for THIS scenario, and only when the run actually
    executed past the point of failure: a run that stopped early (steps
    skipped) proves nothing about the steps it never reached.
    """
    stopped_early = any(s.get("skipped") for s in result.get("steps", []))
    if stopped_early:
        return
    for fp, entry in failures.items():
        if entry.get("scenario") != scenario or fp in seen_now:
            continue
        if entry.get("resolved_at") is None:
            entry["resolved_at"] = now
            entry["resolution"] = f"did not recur in run {result.get('run_id')}"


def summary(scenario: str | None = None) -> list[dict]:
    """Known failures, newest first. Filter to one scenario when given."""
    entries = []
    for fp, entry in load()["failures"].items():
        if scenario and entry.get("scenario") != scenario:
            continue
        entries.append({"fingerprint": fp, **entry})
    entries.sort(key=lambda e: e.get("last_seen", ""), reverse=True)
    return entries


def clear() -> int:
    """Drop the whole memory (test isolation / deliberate reset)."""
    data = load()
    count = len(data["failures"])
    _save({"version": 1, "failures": {}})
    return count
