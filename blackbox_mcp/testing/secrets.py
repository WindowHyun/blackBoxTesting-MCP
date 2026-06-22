"""Credential handling (PRD constraint: credentials externalized + masked).

Scenario steps may reference ``${ENV_VAR}``; values are injected from the
environment at run time and never persisted. The same values are masked before
they reach logs or reports.
"""
from __future__ import annotations

import os
import re

_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

# Field names whose values should always be masked in reports.
_SENSITIVE_KEYS = {"password", "passwd", "pwd", "token", "secret", "otp", "pin"}


def resolve(value: str) -> str:
    """Substitute ${VAR} references from the environment."""
    if not isinstance(value, str):
        return value
    return _VAR.sub(lambda m: os.getenv(m.group(1), m.group(0)), value)


def mask_value(value: str) -> str:
    if not value:
        return value
    return value[0] + "***" if len(value) > 1 else "***"


def mask_step(step: dict) -> dict:
    """Return a copy of a step with sensitive values masked for reporting."""
    out = dict(step)
    for key in list(out.keys()):
        if key.lower() in _SENSITIVE_KEYS and isinstance(out[key], str):
            out[key] = mask_value(out[key])
    # Mask a 'value' field when the target field name looks sensitive.
    selector = str(out.get("selector", "")).lower()
    if "value" in out and any(k in selector for k in _SENSITIVE_KEYS):
        out["value"] = mask_value(str(out["value"]))
    return out
