"""Corporate-network (사내망) support: proxy, HTTP auth, SSO, viewport, install
timeout. Unit-level — these assert the options we hand Playwright, which is
what a closed network actually depends on.
"""
from __future__ import annotations

import subprocess

import pytest

from blackbox_mcp import bootstrap, config
from blackbox_mcp.browser import session as session_mod


def _cfg(**overrides):
    base = dict(
        headless=True, browser="chromium", chromium_executable=None,
        browser_channel=None, cdp_url=None, stealth=False,
        report_dir=config.CONFIG.report_dir, scenario_dir=config.CONFIG.scenario_dir,
        selector_timeout_ms=2000, default_wait_until="networkidle",
        nav_timeout_ms=30000, ignore_https_errors=False, report_retention=0,
        proxy_server=None, proxy_username=None, proxy_password=None,
        proxy_bypass=None, http_username=None, http_password=None,
        auth_server_allowlist=None, viewport=None, install_timeout_s=300,
        download_dir=config.CONFIG.download_dir,
    )
    base.update(overrides)
    return config.Config(**base)


# ── proxy ────────────────────────────────────────────────────────
def test_no_proxy_configured_sends_no_proxy_option():
    assert _cfg().proxy_settings() is None


def test_proxy_carries_credentials_and_bypass():
    proxy = _cfg(proxy_server="http://proxy.corp:8080", proxy_username="u",
                 proxy_password="p", proxy_bypass="*.corp,localhost").proxy_settings()
    assert proxy == {"server": "http://proxy.corp:8080", "username": "u",
                     "password": "p", "bypass": "*.corp,localhost"}


def test_proxy_falls_back_to_conventional_env(monkeypatch):
    monkeypatch.delenv("PROXY_SERVER", raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://env-proxy:3128")
    monkeypatch.setenv("NO_PROXY", "localhost")
    cfg = config.Config.from_env()
    assert cfg.proxy_settings() == {"server": "http://env-proxy:3128",
                                    "bypass": "localhost"}


def test_proxy_reaches_launch_kwargs(monkeypatch):
    """Proxy must ride on launch(), not the context: Chromium ignores env proxy
    on some platforms and never picks up its credentials."""
    monkeypatch.setattr(session_mod, "CONFIG",
                        _cfg(proxy_server="http://proxy.corp:8080",
                             proxy_username="u", proxy_password="p"))
    kwargs = session_mod._base_launch_kwargs()
    assert kwargs["proxy"]["server"] == "http://proxy.corp:8080"
    assert kwargs["proxy"]["username"] == "u"


# ── HTTP basic auth / SSO ────────────────────────────────────────
@pytest.mark.parametrize("raw,expected", [
    ("http://id:pw@proxy.corp:8080", "http://***@proxy.corp:8080"),
    ("http://proxy.corp:8080", "http://proxy.corp:8080"),
    (None, None),
])
def test_proxy_url_credentials_are_redacted_for_display(raw, expected):
    """status/doctor both print the proxy — neither may echo its password."""
    assert config.redact_url(raw) == expected


def test_http_credentials_option():
    assert _cfg().http_credentials() is None
    assert _cfg(http_username="svc", http_password="s3cr3t").http_credentials() == {
        "username": "svc", "password": "s3cr3t"}


def test_http_credentials_reach_context_kwargs(monkeypatch):
    monkeypatch.setattr(session_mod, "CONFIG",
                        _cfg(http_username="svc", http_password="s3cr3t"))
    assert session_mod._context_kwargs()["http_credentials"]["username"] == "svc"


def test_sso_allowlist_becomes_chromium_args(monkeypatch):
    monkeypatch.setattr(session_mod, "CONFIG",
                        _cfg(auth_server_allowlist="*.corp.example.com"))
    args = session_mod._launch_args()
    assert "--auth-server-allowlist=*.corp.example.com" in args
    assert "--auth-negotiate-delegate-allowlist=*.corp.example.com" in args


def test_sso_allowlist_independent_of_stealth(monkeypatch):
    """Regression: the args list used to exist only when STEALTH was on, so
    intranet SSO silently did nothing unless stealth happened to be enabled."""
    monkeypatch.setattr(session_mod, "CONFIG",
                        _cfg(auth_server_allowlist="corp", stealth=False))
    assert any("auth-server-allowlist" in a for a in session_mod._launch_args())


# ── viewport ─────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,expected", [
    ("1280x800", {"width": 1280, "height": 800}),
    (" 390 X 844 ", {"width": 390, "height": 844}),
    ("390,844", {"width": 390, "height": 844}),
    ("garbage", None),
    ("", None),
    (None, None),
])
def test_viewport_parsing(raw, expected):
    assert config._as_viewport(raw) == expected


def test_explicit_viewport_wins_over_stealth_default(monkeypatch):
    monkeypatch.setattr(session_mod, "CONFIG",
                        _cfg(stealth=True, viewport={"width": 390, "height": 844}))
    assert session_mod._context_kwargs()["viewport"] == {"width": 390, "height": 844}


# ── context options are shared across launch modes ───────────────
def test_persistent_profile_gets_same_network_options(monkeypatch):
    """A setup that works headless must not silently lose its proxy/certs when
    the user switches to the real-browser profile mode."""
    monkeypatch.setattr(session_mod, "CONFIG",
                        _cfg(proxy_server="http://proxy.corp:8080",
                             ignore_https_errors=True, http_username="svc"))
    merged = {**session_mod._base_launch_kwargs(), **session_mod._context_kwargs()}
    assert merged["proxy"]["server"] == "http://proxy.corp:8080"
    assert merged["ignore_https_errors"] is True
    assert merged["http_credentials"]["username"] == "svc"


# ── bootstrap must not hang the server ───────────────────────────
def test_install_timeout_is_passed(monkeypatch):
    """Unbounded, a blackholed browser CDN hangs before mcp.run() and the client
    only sees a server that never started."""
    seen = {}

    def fake_run(cmd, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(bootstrap, "CONFIG", _cfg(install_timeout_s=42))
    monkeypatch.setattr(bootstrap, "_browser_installed", lambda name: False)
    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
    bootstrap.ensure_chromium()
    assert seen["timeout"] == 42


def test_install_timeout_does_not_crash_startup(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 1))

    monkeypatch.setattr(bootstrap, "CONFIG", _cfg(install_timeout_s=1))
    monkeypatch.setattr(bootstrap, "_browser_installed", lambda name: False)
    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
    bootstrap.ensure_chromium()  # must return, not raise
