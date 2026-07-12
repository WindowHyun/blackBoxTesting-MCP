"""Scenario library persistence (SL-02 / SL-03 / SL-04).

Scenarios are stored as scenarios/{name}.json. Phase 0 provides the storage
primitives; the MCP tools in tools/library.py wrap them.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from ..config import CONFIG

_SAFE_NAME = re.compile(r"[^A-Za-z0-9_\-가-힣]")


def _path(name: str):
    safe = _SAFE_NAME.sub("_", name.strip())
    return CONFIG.scenario_dir / f"{safe}.json"


def _stored_name(path) -> str | None:
    """The original name recorded inside a scenario file (None if unreadable)."""
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("name")
    except Exception:
        return None


def exists(name: str) -> bool:
    return _path(name).exists()


def save(name: str, steps: list[dict], overwrite: bool = False) -> str:
    path = _path(name)
    if path.exists() and not overwrite:
        owner = _stored_name(path)
        if owner and owner != name.strip():
            # Distinct logical names sanitize to the same file (e.g.
            # "checkout/happy" and "checkout happy" → checkout_happy.json).
            # Surface the collision instead of a misleading "already exists"
            # that names the wrong scenario — or, with overwrite, clobbering it.
            raise FileExistsError(
                f"Scenario name '{name}' maps to the same file as existing "
                f"'{owner}' (names are sanitized to [A-Za-z0-9_-가-힣]). Pick a "
                f"distinct name, or pass overwrite=True to replace '{owner}'.")
        raise FileExistsError(f"Scenario '{name}' already exists. Pass overwrite=True.")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"name": name, "steps": steps, "saved_at": datetime.now().isoformat()}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def load(name: str) -> list[dict]:
    path = _path(name)
    if not path.exists():
        raise FileNotFoundError(f"Scenario '{name}' not found.")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("steps", [])


def listing() -> list[dict]:
    out: list[dict] = []
    if not CONFIG.scenario_dir.exists():
        return out
    for path in sorted(CONFIG.scenario_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        out.append(
            {
                "name": data.get("name", path.stem),
                "steps": len(data.get("steps", [])),
                "saved_at": data.get("saved_at"),
            }
        )
    return out
