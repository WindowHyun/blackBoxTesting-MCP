"""CI entrypoint — run saved scenarios without any MCP client.

`ui-blackbox run <scenario ...>` executes library scenarios (or step-JSON
files) with the same runner/report engine the MCP tools use, prints a summary,
and exits non-zero on failure so pipelines can gate on it. Unlike the MCP
server, stdout here is ours — printing is fine.

    ui-blackbox run smoke_login                      # library scenario
    ui-blackbox run ./steps.json --format all        # step file
    ui-blackbox run a b c --junit results.xml        # suite + JUnit for CI
    ui-blackbox run a b c --parallel 3               # one subprocess each
    ui-blackbox doctor                               # environment self-check
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

EXIT_OK, EXIT_FAILED, EXIT_ERROR = 0, 1, 2


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("ui-blackbox-mcp")
    except PackageNotFoundError:  # editable/odd installs
        return "unknown"


def _load_steps(ref: str) -> tuple[str, list[dict]]:
    """Resolve a scenario reference: a .json step file path, or a library name."""
    path = Path(ref)
    if path.suffix == ".json" and path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        steps = data.get("steps", data) if isinstance(data, dict) else data
        if not isinstance(steps, list):
            raise ValueError(f"{ref}: expected a steps array or {{'steps': [...]}}")
        name = data.get("name", path.stem) if isinstance(data, dict) else path.stem
        return name, steps
    from .testing import library
    return ref, library.load(ref)


def _errored_result(name: str, exc: Exception) -> dict:
    """A synthetic failed result so one scenario blowing up (browser launch,
    disk-full save…) doesn't discard the whole suite's aggregate/JUnit."""
    return {"name": name, "meta": {},
            "summary": {"total": 1, "passed": 0, "failed": 1, "skipped": 0,
                        "pass_rate": 0.0},
            "steps": [{"step": 1, "action": "run", "passed": False,
                       "actual": f"{type(exc).__name__}: {exc}",
                       "severity": "error", "ai_reason": "scenario raised",
                       "ai_suggestion": str(exc)[:160], "duration_ms": 0}]}


async def _run_all(items: list[tuple[str, list[dict]]], args) -> list[dict]:
    """Run scenarios sequentially in one browser session; always clean up.
    A scenario that raises is recorded as an errored result and the suite
    continues — completed results and JUnit are never lost to one failure."""
    from .browser.session import close_session
    from .testing import report, runner

    results: list[dict] = []
    try:
        for name, steps in items:
            print(f"▶ {name} ({len(steps)} steps)")
            try:
                res = await runner.run(steps, name=name,
                                       continue_on_fail=args.continue_on_fail,
                                       screenshot_each=args.screenshot_each,
                                       trace_on_failure=args.trace_on_failure)
                if res.get("trace"):
                    print(f"  trace: {res['trace']}  (playwright show-trace로 열기)")
                files = report.save(res, formats=args.format)
                s = res["summary"]
                mark = "PASS" if s["failed"] == 0 else "FAIL"
                print(f"  {mark} {s['passed']}/{s['total']} "
                      f"(pass_rate {s['pass_rate']:.0%})")
                for fmt, p in files.items():
                    print(f"  report[{fmt}]: {p}")
                results.append(res)
            except Exception as exc:
                print(f"  ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
                results.append(_errored_result(name, exc))
    finally:
        await close_session()
    return results


# Chars illegal in XML 1.0 text (all C0 controls except tab/LF/CR).
_XML_ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _xml_safe(value) -> str:
    """Strip control chars so page-captured text (ANSI escapes, NUL) can't
    produce XML that strict JUnit parsers reject. (ET already escapes &<>".)"""
    return _XML_ILLEGAL.sub("", str(value))


def _write_junit(results: list[dict], path: str) -> None:
    """JUnit XML (one testsuite per scenario) — natively parsed by CI systems."""
    import xml.etree.ElementTree as ET

    suites = ET.Element("testsuites")
    for res in results:
        s = res["summary"]
        suite = ET.SubElement(
            suites, "testsuite", name=_xml_safe(res.get("name", "scenario")),
            tests=str(s["total"]), failures=str(s["failed"]),
            skipped=str(s.get("skipped", 0)),
            time=f"{res.get('meta', {}).get('duration_ms', 0) / 1000:.3f}")
        for step in res.get("steps", []):
            tag = f" [{step['tag']}]" if step.get("tag") else ""
            case = ET.SubElement(
                suite, "testcase",
                name=_xml_safe(f"step{step['step']} {step.get('action')}{tag}"),
                time=f"{step.get('duration_ms', 0) / 1000:.3f}")
            if step.get("skipped"):
                # Native JUnit skip — CI dashboards show "not run", not "failed".
                ET.SubElement(case, "skipped",
                              message=_xml_safe(step.get("actual") or "not run"))
            elif not step.get("passed"):
                fail = ET.SubElement(case, "failure",
                                     message=_xml_safe(step.get("actual") or "failed"))
                fail.text = _xml_safe(f"severity={step.get('severity')}\n"
                                      f"reason={step.get('ai_reason')}\n"
                                      f"suggestion={step.get('ai_suggestion')}")
    ET.ElementTree(suites).write(path, encoding="unicode", xml_declaration=True)
    print(f"  junit: {path}")


def _norm_exit(code: int) -> int:
    """Map a child process return code to our exit taxonomy. A signal death
    (negative code, e.g. OOM-killed browser = -9) or any unexpected value is an
    ERROR, never a silent PASS."""
    return code if code in (EXIT_OK, EXIT_FAILED, EXIT_ERROR) else EXIT_ERROR


def _run_parallel(refs: list[str], args) -> int:
    """Fan out one subprocess per scenario (each gets its own browser/session
    singleton — no shared-state refactor needed). Concurrency-capped.

    Children run with retention disabled (REPORT_RETENTION=0) so siblings can't
    race-delete each other's reports; the parent prunes once at the end."""
    import os

    child_env = {**os.environ, "REPORT_RETENTION": "0"}
    # A list, not a ref-keyed dict: the same scenario passed twice must not
    # shadow its sibling's process and dodge the kill-on-interrupt cleanup.
    procs: list = []

    async def _go() -> list[int]:
        sem = asyncio.Semaphore(args.parallel)

        async def one(ref: str) -> int:
            async with sem:
                cmd = [sys.executable, "-m", "blackbox_mcp.cli", "run", ref,
                       "--format", args.format]
                if args.continue_on_fail:
                    cmd.append("--continue-on-fail")
                if args.screenshot_each:
                    cmd.append("--screenshot-each")
                if args.trace_on_failure:
                    cmd.append("--trace-on-failure")
                proc = await asyncio.create_subprocess_exec(*cmd, env=child_env)
                procs.append(proc)
                try:
                    return await asyncio.wait_for(proc.wait(), timeout=args.timeout)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
                    print(f"error: '{ref}' exceeded {args.timeout}s — killed",
                          file=sys.stderr)
                    return EXIT_ERROR

        try:
            return list(await asyncio.gather(*(one(r) for r in refs)))
        finally:
            # KeyboardInterrupt/cancel: don't orphan child browsers.
            for p in procs:
                if p.returncode is None:
                    p.kill()

    try:
        codes = [_norm_exit(c) for c in asyncio.run(_go())]
    except KeyboardInterrupt:
        for p in procs:
            if getattr(p, "returncode", 0) is None:
                p.kill()
        print("interrupted", file=sys.stderr)
        return EXIT_ERROR

    _parent_prune()
    passed = codes.count(EXIT_OK)
    print(f"parallel done: {passed}/{len(codes)} passed")
    if any(c == EXIT_ERROR for c in codes):
        return EXIT_ERROR
    return EXIT_OK if passed == len(codes) else EXIT_FAILED


def _parent_prune() -> None:
    """Apply retention once, after all parallel children have finished."""
    try:
        from .testing.report import _prune, ensure_dirs
        _prune(ensure_dirs())
    except Exception:
        pass


def _cmd_run(args) -> int:
    if args.parallel > 1:
        if args.junit:
            print("--junit is not supported with --parallel (each child writes "
                  "its own reports); run sequentially for a merged JUnit file.",
                  file=sys.stderr)
            return EXIT_ERROR
        return _run_parallel(args.scenario, args)

    try:
        items = [_load_steps(ref) for ref in args.scenario]
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    from .bootstrap import ensure_chromium
    ensure_chromium()
    try:
        results = asyncio.run(_run_all(items, args))
    except Exception as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if args.junit:
        _write_junit(results, args.junit)
    failed = sum(r["summary"]["failed"] for r in results)
    total = sum(r["summary"]["total"] for r in results)
    print(f"total: {total - failed}/{total} passed")
    return EXIT_OK if failed == 0 else EXIT_FAILED


def _cmd_doctor(args) -> int:  # noqa: ARG001
    """Self-check: browser resolvable + output dirs writable + config echo."""
    from .bootstrap import _browser_installed
    from .config import CONFIG, effective_browser
    from .testing.report import ensure_dirs

    ok = True
    print(f"ui-blackbox {_version()}")
    print(f"  python: {sys.version.split()[0]}  platform: {sys.platform}")

    if CONFIG.chromium_executable:
        import os
        exists = os.path.exists(CONFIG.chromium_executable)
        ok &= exists
        print(f"  browser: CHROMIUM_EXECUTABLE={CONFIG.chromium_executable} "
              f"{'✓' if exists else '✗ MISSING'}")
    else:
        # Probe the browser the session will actually launch (BROWSER=chrome
        # coerces to chromium) — probing the raw value fails a CI gate that
        # would in fact run fine.
        name = effective_browser(CONFIG.browser)
        installed = _browser_installed(name)
        ok &= installed
        coerced = f" (BROWSER={CONFIG.browser} → {name})" if name != CONFIG.browser else ""
        print(f"  browser: playwright {name}{coerced} "
              f"{'✓ installed' if installed else f'✗ not installed (run: playwright install {name})'}")

    try:
        d = ensure_dirs()
        print(f"  report_dir: {d} ✓ writable")
    except Exception as exc:
        ok = False
        print(f"  report_dir: ✗ {exc}")
    print(f"  scenario_dir: {CONFIG.scenario_dir}")
    print(f"  headless={CONFIG.headless} channel={CONFIG.browser_channel or '-'} "
          f"cdp={CONFIG.cdp_url or '-'} stealth={CONFIG.stealth}")
    print("doctor: OK" if ok else "doctor: PROBLEMS FOUND")
    return EXIT_OK if ok else EXIT_FAILED


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ui-blackbox",
        description="Run ui-blackbox scenarios from the command line (CI-friendly).")
    parser.add_argument("--version", action="version",
                        version=f"ui-blackbox {_version()}")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run scenario(s); exit 1 if any step fails")
    run_p.add_argument("scenario", nargs="+",
                       help="library scenario name or path to a steps .json file")
    run_p.add_argument("--format", default="all",
                       choices=["json", "md", "html", "both", "all"],
                       help="report formats to write (default: all)")
    run_p.add_argument("--continue-on-fail", action="store_true",
                       help="keep executing steps after a failure")
    run_p.add_argument("--screenshot-each", action="store_true",
                       help="screenshot every step, not just failures")
    run_p.add_argument("--trace-on-failure", action="store_true",
                       help="record a Playwright trace; keep the .zip only if "
                            "the scenario fails (open with: playwright show-trace)")
    run_p.add_argument("--junit", metavar="PATH",
                       help="also write a JUnit XML report (sequential runs only)")
    run_p.add_argument("--parallel", type=int, default=1, metavar="N",
                       help="run N scenarios concurrently (one subprocess each)")
    run_p.add_argument("--timeout", type=float, default=600.0, metavar="SEC",
                       help="per-scenario watchdog for --parallel (default 600s)")
    run_p.set_defaults(func=_cmd_run)

    doc_p = sub.add_parser("doctor", help="check browser/dirs/config health")
    doc_p.set_defaults(func=_cmd_doctor)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
