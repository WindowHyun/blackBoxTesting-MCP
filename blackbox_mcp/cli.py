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


async def _run_all(items: list[tuple[str, list[dict]]], args) -> list[dict]:
    """Run scenarios sequentially in one browser session; always clean up."""
    from .browser.session import close_session
    from .testing import report, runner

    results: list[dict] = []
    try:
        for name, steps in items:
            print(f"▶ {name} ({len(steps)} steps)")
            res = await runner.run(steps, name=name,
                                   continue_on_fail=args.continue_on_fail,
                                   screenshot_each=args.screenshot_each)
            files = report.save(res, formats=args.format)
            s = res["summary"]
            mark = "PASS" if s["failed"] == 0 else "FAIL"
            print(f"  {mark} {s['passed']}/{s['total']} "
                  f"(pass_rate {s['pass_rate']:.0%})")
            for fmt, p in files.items():
                print(f"  report[{fmt}]: {p}")
            results.append(res)
    finally:
        await close_session()
    return results


def _write_junit(results: list[dict], path: str) -> None:
    """JUnit XML (one testsuite per scenario) — natively parsed by CI systems."""
    import xml.etree.ElementTree as ET

    suites = ET.Element("testsuites")
    for res in results:
        s = res["summary"]
        suite = ET.SubElement(
            suites, "testsuite", name=res.get("name", "scenario"),
            tests=str(s["total"]), failures=str(s["failed"]),
            time=f"{res.get('meta', {}).get('duration_ms', 0) / 1000:.3f}")
        for step in res.get("steps", []):
            case = ET.SubElement(
                suite, "testcase",
                name=f"step{step['step']} {step.get('action')}",
                time=f"{step.get('duration_ms', 0) / 1000:.3f}")
            if not step.get("passed"):
                fail = ET.SubElement(case, "failure",
                                     message=str(step.get("actual") or "failed"))
                fail.text = (f"severity={step.get('severity')}\n"
                             f"reason={step.get('ai_reason')}\n"
                             f"suggestion={step.get('ai_suggestion')}")
    ET.ElementTree(suites).write(path, encoding="unicode", xml_declaration=True)
    print(f"  junit: {path}")


def _run_parallel(refs: list[str], args) -> int:
    """Fan out one subprocess per scenario (each gets its own browser/session
    singleton — no shared-state refactor needed). Concurrency-capped."""
    import subprocess

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
                proc = await asyncio.create_subprocess_exec(*cmd)
                return await proc.wait()

        return list(await asyncio.gather(*(one(r) for r in refs)))

    codes = asyncio.run(_go())
    worst = max(codes, default=EXIT_OK)
    print(f"parallel done: {codes.count(EXIT_OK)}/{len(codes)} passed")
    return worst


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
    from .config import CONFIG
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
        installed = _browser_installed(CONFIG.browser)
        ok &= installed
        print(f"  browser: playwright {CONFIG.browser} "
              f"{'✓ installed' if installed else '✗ not installed (run: playwright install chromium)'}")

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
    run_p.add_argument("--junit", metavar="PATH",
                       help="also write a JUnit XML report (sequential runs only)")
    run_p.add_argument("--parallel", type=int, default=1, metavar="N",
                       help="run N scenarios concurrently (one subprocess each)")
    run_p.set_defaults(func=_cmd_run)

    doc_p = sub.add_parser("doctor", help="check browser/dirs/config health")
    doc_p.set_defaults(func=_cmd_doctor)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
