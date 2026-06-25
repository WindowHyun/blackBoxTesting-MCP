#!/usr/bin/env bash
# SessionStart setup for Claude Code web/remote sessions.
#
# Goal: leave the repo ready to run `pytest` without manual steps. Idempotent and
# non-blocking — it must never fail the session, so it always exits 0 and only
# logs problems. Chromium (~150MB) is NOT installed here by default to keep
# session start fast; run `.venv/bin/playwright install chromium` when a
# browser-integration task needs it (see HARNESS.md §1).
set -u

log() { printf '[setup_env] %s\n' "$*"; }

cd "$(dirname "$0")/.." || exit 0

# System pip is blocked by a PyJWT RECORD conflict, so always use a venv.
if [ ! -d .venv ]; then
  log "creating .venv"
  python -m venv .venv || { log "venv creation failed; skipping"; exit 0; }
fi

log "installing project (editable) + dev deps"
.venv/bin/pip install -q --upgrade pip >/dev/null 2>&1 || true
if .venv/bin/pip install -q -e ".[dev]" >/dev/null 2>&1; then
  log "dependencies ready"
else
  log "pip install failed (offline?); tests may not run until deps are installed"
fi

# Optional: uncomment to auto-install the browser (slow, ~150MB).
# .venv/bin/playwright install chromium >/dev/null 2>&1 || log "chromium install skipped"

log "done — run tests with: .venv/bin/python -m pytest -q"
exit 0
