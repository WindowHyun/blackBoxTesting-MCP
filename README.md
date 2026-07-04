# UI Blackbox Tester MCP

**🌐 Language:** **English** · [한국어](./README.ko.md)

> **Test your UI in plain language — an MCP server.** Give Claude Desktop (and other
> MCP clients) the ability to drive a browser. Say *"check that the login flow works"*
> and the agent opens a browser, clicks, types, asserts, and leaves a **QA report
> (HTML/MD/JSON)** behind — no test code required.

<p align="center">
  <img src="examples/sample_report_preview.png" alt="Sample report" width="620">
  <br><em>Auto-generated report — pass rate · per-step screenshots · failure cause · regression · accessibility · credential masking</em>
</p>

Python 3.11+ · Playwright (Chromium, async) · official MCP SDK (FastMCP) · stdio · **78 tests green**

---

## ✨ What's different (vs a generic browser MCP)

Plenty of tools can drive a browser. This one is built around the **QA workflow**.

| | Generic browser MCP | **UI Blackbox MCP** |
|---|---|---|
| Authoring | Write selectors by hand | **Natural language → kit → reusable scenario** (`generate_scenario`) |
| Reuse | Start over each time | **Save & load by name** (scenario library) |
| Output | Text / logs | **QA report**: pass rate · step screenshots · **AI failure cause + fix suggestion** · **regression diff** · **a11y findings** · severity |
| Selector stability | Breaks every build | **D2 priority chain** (data-testid → role+name → text → css) + `resolved_by` transparency |
| Security | — | **Credential masking** (`${VAR}` injected from env, never written to reports) |

→ Not a developer tool, but **regression-test automation that non-developer QA/PMs can drive in natural language**.

---

## 🚀 Quick start

### 1) Install
```bash
git clone https://github.com/WindowHyun/blackBoxTesting-MCP.git
cd blackBoxTesting-MCP

python -m venv .venv
.venv/bin/pip install -e .              # installs deps (mcp, playwright)
.venv/bin/playwright install chromium   # browser (first time). Skipped? the server auto-installs on first run
```
> On networks where the browser CDN is blocked (corp/CI), point at a pre-installed
> binary with `CHROMIUM_EXECUTABLE=/path/to/chrome`.

Wherever a config below uses `<ABS>`, replace it with the **absolute path** of this
repo, e.g. `/home/you/blackBoxTesting-MCP`. On Windows the interpreter is
`<ABS>\.venv\Scripts\python.exe`.

---

## 🔌 Client setup

The server speaks **stdio**, so every MCP client launches it the same way: run the
venv Python with `-m blackbox_mcp.server`. Only the config file/format differs per
client. Pick yours.

<details open>
<summary><b>Claude Desktop</b></summary>

Edit the config file (create it if missing):
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "ui-blackbox": {
      "command": "<ABS>/.venv/bin/python",
      "args": ["-m", "blackbox_mcp.server"],
      "env": {
        "HEADLESS": "true",
        "REPORT_DIR": "<ABS>/reports"
      }
    }
  }
}
```
Restart Claude Desktop. Then in chat: *"Open https://example.com/login, test the login flow and make a report."*
</details>

<details>
<summary><b>Claude Code / Claude CLI</b> (same product — the <code>claude</code> CLI)</summary>

Easiest — one command (user scope, available in every project):
```bash
claude mcp add ui-blackbox \
  --scope user \
  --env HEADLESS=true \
  --env REPORT_DIR=<ABS>/reports \
  -- <ABS>/.venv/bin/python -m blackbox_mcp.server
```
Verify with `claude mcp list` → it should show `ui-blackbox`.

Or, to commit it alongside a repo, drop a project-scoped **`.mcp.json`** at the repo root:
```json
{
  "mcpServers": {
    "ui-blackbox": {
      "command": "<ABS>/.venv/bin/python",
      "args": ["-m", "blackbox_mcp.server"],
      "env": { "HEADLESS": "true", "REPORT_DIR": "<ABS>/reports" }
    }
  }
}
```
</details>

<details>
<summary><b>Codex CLI</b></summary>

One command:
```bash
codex mcp add ui-blackbox \
  --env HEADLESS=true --env REPORT_DIR=<ABS>/reports \
  -- <ABS>/.venv/bin/python -m blackbox_mcp.server
```
Or edit `~/.codex/config.toml` directly (TOML, not JSON):
```toml
[mcp_servers.ui-blackbox]
command = "<ABS>/.venv/bin/python"
args = ["-m", "blackbox_mcp.server"]

[mcp_servers.ui-blackbox.env]
HEADLESS = "true"
REPORT_DIR = "<ABS>/reports"
```
</details>

<details>
<summary><b>Gemini CLI</b></summary>

Edit `~/.gemini/settings.json`:
```json
{
  "mcpServers": {
    "ui-blackbox": {
      "command": "<ABS>/.venv/bin/python",
      "args": ["-m", "blackbox_mcp.server"],
      "env": { "HEADLESS": "true", "REPORT_DIR": "<ABS>/reports" },
      "timeout": 30000
    }
  }
}
```
Values can reference shell env vars as `$VAR` / `${VAR}`. Run `/mcp` inside Gemini CLI to confirm the server connected.
</details>

<details>
<summary><b>Google Antigravity</b> (IDE & CLI)</summary>

Antigravity (IDE + CLI) share one MCP config: `~/.gemini/config/mcp_config.json`.
In the IDE you can open it via the **⋯** menu at the top of the agent panel →
**MCP Servers → Manage MCP Servers → View raw config**.

```json
{
  "mcpServers": {
    "ui-blackbox": {
      "command": "<ABS>/.venv/bin/python",
      "args": ["-m", "blackbox_mcp.server"],
      "env": { "HEADLESS": "true", "REPORT_DIR": "<ABS>/reports" }
    }
  }
}
```
Save the file and Antigravity reloads the server automatically.
</details>

> **Tips that apply to every client.** Use the **venv Python absolute path** for
> `command` (avoids system-Python dependency clashes). The MCP server's cwd may be a
> system path, so **set `REPORT_DIR` to an absolute path** or reports fall back to
> `~/ui-blackbox/reports`. Slash commands (below) are Claude-specific; other clients
> drive the same tools via natural language.

---

## ⌨️ Slash commands (Claude — recommended, avoids clashing with other browser tools)

Type `/` in Claude to see these. Each **instructs the agent to use only the
ui-blackbox tools**, so another browser tool (e.g. "Claude in Chrome") can't hijack
the request.

| Command | Args | Purpose |
|---|---|---|
| `/ui-test` | task | Run a natural-language task with the ui-blackbox tools |
| `/ui-scenario` | description, url | Build → run → report (all formats) |
| `/ui-login` | task, url | **Switch to real Chrome (persistent login)** then test a site that needs auth |
| `/ui-generate` | description, url, name | Analyze a page → generate & save a reusable scenario |

Example: `/ui-test` → `open example.com, click the login button, take a screenshot`

## 💬 Usage examples (natural language)
- *"On this page, check that the signup form shows an error when fields are empty."*
- *"Make a login scenario and save it as 'smoke_login'."* → later: *"run smoke_login."*
- *"Compared to yesterday, what broke in that last test?"* (regression)
- *"Were there any console errors or 4xx responses?"*

---

## 🧰 MCP Tools (19)

| Group | Tools |
|---|---|
| Core | `navigate` · `snapshot` (a11y/dom) · `screenshot` · `interact` · `assert_` · `get_console_logs` · `get_network_errors` |
| Extended | `wait` · `switch_frame` · `expect_dialog` · `reset_session` · `use_real_browser` · `dismiss_banners` |
| Scenario & report | `run_scenario` · `generate_scenario` · `save_report` |
| Library | `save_scenario` · `load_scenario` · `list_scenarios` |

> **Every test flow ends with a report.** Ad-hoc tool calls (navigate/interact/assert…)
> are recorded automatically, and a final `save_report` writes the JSON/MD/HTML report
> (slash commands instruct this automatically). `run_scenario` saves its own report.

> **Adding a tool = 1 file in `tools/` + 1 import line.** `server.py` is never touched.

---

## 🧪 Reports
See [`examples/`](./examples/) for real output (open `sample_report.html` in a browser).
A single self-contained HTML (screenshots inlined as base64, zero external deps) —
per-step results · failure screenshots · AI fix suggestions · **regression (vs the
previous run)** · **a11y findings** · environment metadata · masking badges.

---

## 🏗️ Structure
```
blackbox_mcp/
  server.py        # FastMCP boot + ensure_chromium + lifespan + register_all
  bootstrap.py     # Chromium auto-install (D1)
  config.py        # environment variables
  browser/         # session singleton · event buffers · D2 selector chain
  testing/         # scenario runner · report (JSON/MD/HTML) · library · masking
  tools/           # MCP tool = 1 file (registry auto-registers)
```
Design: [`DESIGN.md`](./DESIGN.md) · Milestones: [`ROADMAP.md`](./ROADMAP.md) ·
Run playbook: [`HARNESS.md`](./HARNESS.md) · Agent context: [`CLAUDE.md`](./CLAUDE.md)

---

## 🔧 Development
```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q        # 78 tests (unit + file:// integration + E2E)
```

## ⚙️ Environment variables
`HEADLESS` (default true) · `BROWSER` (chromium) · `CHROMIUM_EXECUTABLE` ·
`BROWSER_CHANNEL` (chrome/msedge — real browser) · `BROWSER_CDP` (attach to a running browser) ·
`STEALTH` (reduce bot false-positives) · `REPORT_DIR` (default ~/ui-blackbox/reports) ·
`SCENARIO_DIR` (~/ui-blackbox/scenarios) · `SELECTOR_TIMEOUT_MS` (2000) ·
`DEFAULT_WAIT_UNTIL` (networkidle) · `NAV_TIMEOUT_MS` (30000) ·
`IGNORE_HTTPS_ERRORS` (false). Details in `.env.example`.

> **Testing live/deployed sites.** ① Ad/polling-heavy sites may never reach
> `networkidle` — navigate proceeds on timeout (`settled:false`), and
> `DEFAULT_WAIT_UNTIL=domcontentloaded` is faster. ② For slow-appearing elements,
> raise `SELECTOR_TIMEOUT_MS` to 5000–10000. ③ Filter ad/tracker 4xx noise with
> `get_network_errors(same_origin=True)`. ④ Cookie-consent banners: `dismiss_banners`
> (auto-suggested when a click is blocked). ⑤ Login/bot-walls: `use_real_browser`.
> ⑥ Staging certs: `IGNORE_HTTPS_ERRORS=true`. ⑦ **New tabs/popups are tracked
> automatically** (the session follows a click that opens a new window and returns to
> the original tab when the popup closes — e.g. OAuth popups).

> **About bot detection.** This tool targets **your own UI / staging**. Third-party
> sites may block automation with anti-bot measures, and bypassing those for login
> automation can violate their terms of service. False-positives on legitimate tests
> can be reduced with `BROWSER_CHANNEL=chrome` + `STEALTH=true`.

### 🔗 Sites that require login — real browser (no manual setup)
**Recommended (automatic):** say `/ui-login` or *"log in with a real browser and …"*
and the agent calls the `use_real_browser` tool to **launch real Chrome with a
persistent profile**. Log in **once, by hand**, in that window; the profile is saved
to `~/ui-blackbox/chrome-profile` and reused on later runs. Far less likely to trip
bot detection than the bundled headless browser.
> If real Chrome isn't found, it falls back to the bundled browser automatically. Pin
> a channel with `BROWSER_CHANNEL=msedge`, etc.

**Advanced (manual CDP):** to attach to a Chrome you already have open, launch it with
a debug port and set `BROWSER_CDP`:
```bash
chrome --remote-debugging-port=9222 --user-data-dir="C:\cdp-profile"   # log in there
```
config `env`: `"BROWSER_CDP": "http://localhost:9222"` → attach. Closing the session
**leaves your browser open**.
