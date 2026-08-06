"""Runtime configuration sourced from environment variables.

All behavior knobs live here so the rest of the code reads typed values
instead of touching os.environ directly.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str | None, default: int) -> int:
    """Tolerant int parsing: a typo like "2000ms" in the client's env block must
    not crash the server at import (the user only sees a dead MCP server)."""
    if value is None:
        return default
    try:
        return int(value.strip())
    except ValueError:
        import sys
        print(f"[blackbox-mcp] invalid int {value!r} — using {default}",
              file=sys.stderr)
        return default


# Well-known location of a pre-provisioned browser in some managed/CI
# environments (e.g. Claude Code web). Used when the matching Playwright build
# cannot be downloaded (network policy) — we launch this binary via
# executable_path instead.
_PREINSTALLED_CHROMIUM = "/opt/pw-browsers/chromium"


def _detect_chromium_executable() -> str | None:
    explicit = os.getenv("CHROMIUM_EXECUTABLE")
    if explicit:
        return explicit
    if os.path.exists(_PREINSTALLED_CHROMIUM):
        return _PREINSTALLED_CHROMIUM
    return None  # let Playwright resolve its bundled browser normally


def _resolve_dir(value: str | None, default_name: str) -> Path:
    """Absolute output dir. When unset, default under the user's home — NOT the
    cwd, which is unpredictable when the server is spawned by Claude Desktop and
    is often not writable (e.g. system32)."""
    if value:
        return Path(value).expanduser().resolve()
    return (Path.home() / "ui-blackbox" / default_name).resolve()


def _as_viewport(value: str | None) -> dict | None:
    """Parse VIEWPORT="1280x800" into Playwright's viewport dict.

    Unparseable values fall back to None (Playwright's default) rather than
    raising: a typo in the client's env block must not kill the server.
    """
    if not value:
        return None
    m = re.fullmatch(r"\s*(\d{2,5})\s*[xX*,]\s*(\d{2,5})\s*", value)
    if not m:
        import sys
        print(f"[blackbox-mcp] invalid VIEWPORT {value!r} — expected e.g. 1280x800",
              file=sys.stderr)
        return None
    return {"width": int(m.group(1)), "height": int(m.group(2))}


@dataclass(frozen=True)
class Config:
    headless: bool
    browser: str          # chromium (default) | firefox | webkit
    # Explicit browser binary path (executable_path). None => Playwright default.
    chromium_executable: str | None
    # Use an installed browser channel (e.g. "chrome", "msedge") instead of the
    # bundled Chromium — real UA reduces anti-bot false positives.
    browser_channel: str | None
    # Attach to an already-running browser via CDP (chrome --remote-debugging-port).
    # When set, we connect to the user's real, logged-in browser instead of
    # launching one. e.g. http://localhost:9222
    cdp_url: str | None
    # Apply light anti-automation-fingerprint hardening for legitimate testing.
    stealth: bool
    report_dir: Path
    scenario_dir: Path
    # Per-step selector resolution budget (ms); the whole fallback chain must
    # finish within the MCP 30s tool timeout. Raise for slow real sites.
    selector_timeout_ms: int
    # Default navigation wait condition.
    default_wait_until: str
    # Navigation timeout (ms). Real sites that never reach networkidle fall back
    # to domcontentloaded rather than hanging.
    nav_timeout_ms: int
    # Accept invalid TLS certs (staging with self-signed/expired certs).
    ignore_https_errors: bool
    # Keep at most N report runs (per format set) in REPORT_DIR; 0 = unlimited.
    # Prevents unbounded growth of ~/ui-blackbox/reports on long-lived setups.
    report_retention: int
    # ── corporate network (사내망) ────────────────────────────────
    # Explicit proxy for the BROWSER's traffic. Chromium only picks up the
    # OS/env proxy on some platforms, and never the credentials — an
    # authenticating corporate proxy pops a native auth dialog that no
    # automation can answer. Passing proxy= to launch() covers both.
    proxy_server: str | None
    proxy_username: str | None
    proxy_password: str | None
    proxy_bypass: str | None
    # HTTP Basic/Digest auth (context-level), common on internal staging.
    http_username: str | None
    http_password: str | None
    # Hosts Chromium may auto-negotiate NTLM/Kerberos SSO with (comma list or
    # "*.corp.example.com"). Without it, intranet SSO shows a login prompt.
    auth_server_allowlist: str | None
    # Fixed viewport ("1280x800") for reproducible/responsive runs.
    viewport: dict | None
    # Seconds to wait for the first-run `playwright install`. A blocked CDN
    # behind a corporate proxy can hang the download forever, and this runs
    # BEFORE mcp.run() — an unbounded wait means the server never starts and
    # the client just shows a dead server.
    install_timeout_s: int
    # Where expect_download saves files.
    download_dir: Path
    # Application/server log to correlate against failing steps. The browser
    # can only see the app from outside; when a step fails because the SERVER
    # threw, the reason lives here and nowhere the tool can otherwise reach.
    app_log: str | None

    @staticmethod
    def from_env() -> "Config":
        return Config(
            headless=_as_bool(os.getenv("HEADLESS"), True),
            browser=os.getenv("BROWSER", "chromium").strip().lower(),
            chromium_executable=_detect_chromium_executable(),
            browser_channel=(os.getenv("BROWSER_CHANNEL") or None),
            cdp_url=(os.getenv("BROWSER_CDP") or None),
            stealth=_as_bool(os.getenv("STEALTH"), False),
            report_dir=_resolve_dir(os.getenv("REPORT_DIR"), "reports"),
            scenario_dir=_resolve_dir(os.getenv("SCENARIO_DIR"), "scenarios"),
            selector_timeout_ms=_as_int(os.getenv("SELECTOR_TIMEOUT_MS"), 2000),
            default_wait_until=os.getenv("DEFAULT_WAIT_UNTIL", "networkidle"),
            nav_timeout_ms=_as_int(os.getenv("NAV_TIMEOUT_MS"), 30000),
            ignore_https_errors=_as_bool(os.getenv("IGNORE_HTTPS_ERRORS"), False),
            report_retention=_as_int(os.getenv("REPORT_RETENTION"), 100),
            # PROXY_SERVER is explicit; fall back to the conventional env vars so
            # a machine already configured for corporate egress works untouched.
            proxy_server=(os.getenv("PROXY_SERVER") or os.getenv("HTTPS_PROXY")
                          or os.getenv("HTTP_PROXY") or None),
            proxy_username=(os.getenv("PROXY_USERNAME") or None),
            proxy_password=(os.getenv("PROXY_PASSWORD") or None),
            proxy_bypass=(os.getenv("PROXY_BYPASS") or os.getenv("NO_PROXY") or None),
            http_username=(os.getenv("HTTP_USERNAME") or None),
            http_password=(os.getenv("HTTP_PASSWORD") or None),
            auth_server_allowlist=(os.getenv("AUTH_SERVER_ALLOWLIST") or None),
            viewport=_as_viewport(os.getenv("VIEWPORT")),
            install_timeout_s=_as_int(os.getenv("BROWSER_INSTALL_TIMEOUT_S"), 300),
            download_dir=_resolve_dir(os.getenv("DOWNLOAD_DIR"), "downloads"),
            app_log=(os.getenv("APP_LOG") or None),
        )

    # ── derived launch/context options ───────────────────────────
    def proxy_settings(self) -> dict | None:
        """Playwright ``proxy=`` option, or None when no proxy is configured."""
        if not self.proxy_server:
            return None
        proxy: dict = {"server": self.proxy_server}
        if self.proxy_username:
            proxy["username"] = self.proxy_username
        if self.proxy_password:
            proxy["password"] = self.proxy_password
        if self.proxy_bypass:
            # Playwright expects a comma-separated list; NO_PROXY already is one.
            proxy["bypass"] = self.proxy_bypass
        return proxy

    def http_credentials(self) -> dict | None:
        """Playwright ``http_credentials=`` context option, or None."""
        if self.http_username is None:
            return None
        return {"username": self.http_username,
                "password": self.http_password or ""}


# Singleton config, loaded once at import.
CONFIG = Config.from_env()

_BROWSER_TYPES = ("chromium", "firefox", "webkit")

_USERINFO = re.compile(r"(?<=://)[^/@]*@")


def redact_url(url: str | None) -> str | None:
    """Strip embedded credentials from a URL before it is displayed.

    A proxy is commonly written http://id:pw@proxy.corp:8080, and both `status`
    and `doctor` print it — neither may echo the password.
    """
    if not url:
        return url
    return _USERINFO.sub("***@", url)


def effective_browser(raw: str | None = None) -> str:
    """The browser name coerced to a real Playwright browser type.

    An unknown value (BROWSER=chrome is a plausible misconfig for "use real
    Chrome") falls back to chromium. Single source for session launch,
    bootstrap install target, doctor, and report metadata — keying different
    layers off the raw value made bootstrap install one thing and start()
    launch another. Callers pass their module-local CONFIG.browser so tests
    that monkeypatch a module's CONFIG see consistent coercion.
    """
    raw = CONFIG.browser if raw is None else raw
    return raw if raw in _BROWSER_TYPES else "chromium"
