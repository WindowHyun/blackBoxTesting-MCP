"""Credential handling (PRD constraint: credentials externalized + masked).

Scenario steps may reference ``${ENV_VAR}``; values are injected from the
environment at run time and never persisted. The same values are masked before
they reach logs or reports, and any *resolved* sensitive value is scrubbed from
derived strings (URLs, error messages) via :func:`scrub`.
"""
from __future__ import annotations

import logging
import os
import re

log = logging.getLogger(__name__)

_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

# Shortest resolved value that may be globally substituted out of derived text.
#
# scrub() replaces the value ANYWHERE it appears, so a short one is not a
# secret, it is a common substring: PIN="1" rewrote "?page=1 · 12 rows" into
# "?page=${PIN} · ${PIN}2 rows", and TOKEN="dev" turned "#dev-banner on
# dev.corp" into "#${TOKEN}-banner on ${TOKEN}.corp". The report stops being
# usable as evidence — which is the same reason masking is targeted rather
# than unconditional (CLAUDE.md). Values below this are still masked by FIELD
# NAME (mask_step / interact._display_value); only the derived-text scrub is
# skipped, and it is logged so the choice is visible rather than silent.
_MIN_SCRUBBABLE = 6
_warned_short: set[str] = set()

# Substring keywords (field names, selectors, env-var names) that mark a value
# as sensitive. Short tokens ("pw", "otp", "pin") are matched as whole words to
# avoid false hits inside ordinary words.
_SENSITIVE_SUBSTR = {"password", "passwd", "pwd", "token", "secret",
                     "credential", "apikey", "api_key", "auth"}
_SENSITIVE_TOKENS = {"pw", "otp", "pin", "pass"}
# Korean field/selector names commonly used for credentials.
_SENSITIVE_KO = ("비밀번호", "패스워드", "암호", "인증번호")
# Back-compat name (tests/other modules may import it).
_SENSITIVE_KEYS = _SENSITIVE_SUBSTR

_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")

# Resolved values of sensitive ${VAR}s substituted during this process —
# value → placeholder, used by scrub() to clean derived text before reporting.
_RESOLVED_SECRETS: dict[str, str] = {}


def is_sensitive_name(name: str) -> bool:
    """True if a field/selector/env-var name looks credential-bearing."""
    if not name:
        return False
    low = str(name).lower()
    if any(k in low for k in _SENSITIVE_SUBSTR):
        return True
    if any(k in str(name) for k in _SENSITIVE_KO):
        return True
    return any(t in _SENSITIVE_TOKENS for t in _TOKEN_SPLIT.split(low))


def resolve(value: str) -> str:
    """Substitute ${VAR} references from the environment.

    Sensitive-named vars have their resolved value remembered so scrub() can
    remove them from any derived string (URL, error text) later.
    """
    if not isinstance(value, str):
        return value

    def _sub(m: re.Match) -> str:
        var = m.group(1)
        val = os.getenv(var)
        if val is None:
            return m.group(0)
        if val and is_sensitive_name(var):
            if len(val) >= _MIN_SCRUBBABLE:
                _RESOLVED_SECRETS[val] = "${" + var + "}"
            elif var not in _warned_short:
                _warned_short.add(var)
                log.warning(
                    "%s resolves to a value shorter than %d chars — it is masked "
                    "by field name but NOT scrubbed from derived report text "
                    "(too short to substitute without corrupting unrelated text).",
                    var, _MIN_SCRUBBABLE)
        return val

    return _VAR.sub(_sub, value)


def unresolved_vars(value: str) -> list[str]:
    """${VAR} references with no matching environment variable."""
    if not isinstance(value, str):
        return []
    return [m.group(1) for m in _VAR.finditer(value)
            if os.getenv(m.group(1)) is None]


def clear_registry() -> None:
    """Drop all remembered resolved-secret values.

    Called when a recording flow ends (recorder.reset) and between tests —
    bounds per-process growth and stops scenario A's placeholders from
    rewriting scenario B's report text. Values re-register on the next
    resolve(), so clearing between flows never weakens scrubbing.
    """
    _RESOLVED_SECRETS.clear()


def scrub(text):
    """Replace resolved secret values embedded in derived text (page URLs,
    exception messages, network entries) with their ${VAR} placeholder."""
    if not isinstance(text, str) or not text:
        return text
    # Longest value first: when one secret is a prefix/substring of another
    # (PW="abc", TOKEN="abcdef"), replacing the short one first would mangle
    # the long one into "${PW}def" and leak its tail.
    for val, placeholder in sorted(_RESOLVED_SECRETS.items(),
                                   key=lambda kv: len(kv[0]), reverse=True):
        if val in text:
            text = text.replace(val, placeholder)
    return text


def mask_value(value: str) -> str:
    return "***" if value else value


def scrub_record(record: dict) -> dict:
    """Scrub a finished step record in place: derived text fields plus the
    console/network entries attributed to the step may embed resolved secrets
    (e.g. a token that was part of a navigated URL)."""
    for key in ("expected", "actual", "ai_reason", "ai_suggestion", "page_url"):
        record[key] = scrub(record.get(key))
    for entry in record.get("console_errors") or []:
        entry["text"] = scrub(entry.get("text"))
        entry["location"] = scrub(entry.get("location"))
    for entry in record.get("network_errors") or []:
        entry["url"] = scrub(entry.get("url"))
    for entry in record.get("dialogs") or []:
        # A prompt's message can echo back a value the flow just typed.
        entry["message"] = scrub(entry.get("message"))
    return record


def mask_step(step: dict, *, sensitive_value: bool = False) -> dict:
    """Return a copy of a step with sensitive values masked for reporting.

    ``sensitive_value`` is the verdict the RUNTIME reached about the target
    field (interact inspects the resolved element). Name matching alone reads
    only the selector text, so an opaque one — "#p" on <input type="password">
    — let the plaintext through into the report.
    """
    out = dict(step)
    for key in list(out.keys()):
        if is_sensitive_name(key) and isinstance(out[key], str):
            out[key] = mask_value(out[key])
    # Mask a 'value' field when the runtime said so, or the target field name
    # looks sensitive.
    if "value" in out and (sensitive_value
                           or is_sensitive_name(str(out.get("selector", "")))):
        out["value"] = mask_value(str(out["value"]))
    return out
