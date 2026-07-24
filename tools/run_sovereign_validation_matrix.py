#!/usr/bin/env python3
"""Run Dhad's release validation matrix with explicit environment diagnostics.

The runner never converts a missing tool or dependency into a false pass. Each
entry is recorded as passed, failed, blocked, or timed out, then written to
reports/SOVEREIGN_TEST_MATRIX.{json,md}.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class MatrixResult:
    name: str
    layer: str
    status: str
    seconds: float
    command: list[str]
    detail: str


def run_command(
    name: str,
    layer: str,
    command: Sequence[str],
    *,
    cwd: Path,
    timeout: int,
    env: dict[str, str] | None = None,
) -> MatrixResult:
    """Run one matrix command and terminate its full process tree on timeout."""

    started = time.perf_counter()
    popen_options: dict[str, object] = {}
    if os.name == "posix":
        popen_options["start_new_session"] = True
    elif os.name == "nt":
        popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    process = subprocess.Popen(
        list(command),
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        **popen_options,
    )
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        partial = error.output or ""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", errors="replace")
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            process.kill()
        try:
            remainder, _ = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            remainder, _ = process.communicate()
        output = partial + (remainder or "")
        return MatrixResult(
            name,
            layer,
            "timed_out",
            time.perf_counter() - started,
            list(command),
            output[-4000:].strip() or f"exceeded {timeout}s",
        )

    output = (output or "").strip()
    if process.returncode == 0:
        status = "passed"
    elif "ModuleNotFoundError" in output or "ERR_MODULE_NOT_FOUND" in output:
        status = "blocked"
    elif " skipped" in output and " failed" not in output and "ERROR" not in output:
        status = "blocked"
    else:
        status = "failed"
    return MatrixResult(
        name,
        layer,
        status,
        time.perf_counter() - started,
        list(command),
        output[-4000:] or f"exit code {process.returncode}",
    )


def validate_python_syntax(root: Path) -> MatrixResult:
    started = time.perf_counter()
    files = sorted([*root.glob("src/**/*.py"), *root.glob("tests/**/*.py"), *root.glob("tools/**/*.py")])
    try:
        for path in files:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError) as error:
        return MatrixResult(
            "python-syntax",
            "python",
            "failed",
            time.perf_counter() - started,
            [],
            str(error),
        )
    return MatrixResult(
        "python-syntax",
        "python",
        "passed",
        time.perf_counter() - started,
        [],
        f"parsed {len(files)} Python files without generating bytecode",
    )


def blocked(name: str, layer: str, detail: str, command: Sequence[str] = ()) -> MatrixResult:
    return MatrixResult(name, layer, "blocked", 0.0, list(command), detail)


def write_reports(root: Path, results: list[MatrixResult]) -> None:
    report_dir = root / "reports"
    report_dir.mkdir(exist_ok=True)
    counts = {status: sum(item.status == status for item in results) for status in ("passed", "failed", "blocked", "timed_out")}
    payload = {
        "release": "Dhad v1.0.15 Sovereign Edition",
        "summary": counts | {"total": len(results)},
        "results": [asdict(item) for item in results],
    }
    (report_dir / "SOVEREIGN_TEST_MATRIX.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# Dhad Sovereign Test Matrix",
        "",
        f"- Passed: **{counts['passed']}**",
        f"- Failed: **{counts['failed']}**",
        f"- Blocked by environment/dependency: **{counts['blocked']}**",
        f"- Timed out: **{counts['timed_out']}**",
        "",
        "A blocked entry is not counted as a pass. It records missing tooling or dependencies explicitly.",
        "",
        "## Results",
        "",
        "| Layer | Check | Status | Seconds | Detail |",
        "|---|---|---:|---:|---|",
    ]
    for item in results:
        detail = " ".join(item.detail.split())[:240].replace("|", "\\|")
        lines.append(f"| {item.layer} | `{item.name}` | **{item.status}** | {item.seconds:.2f} | {detail} |")
    (report_dir / "SOVEREIGN_TEST_MATRIX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_results(root: Path) -> list[MatrixResult]:
    report = root / "reports/SOVEREIGN_TEST_MATRIX.json"
    if not report.is_file():
        return []
    try:
        payload = json.loads(report.read_text(encoding="utf-8"))
        return [MatrixResult(**item) for item in payload.get("results", [])]
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--python-file-timeout", type=int, default=90)
    parser.add_argument("--reset", action="store_true", help="discard an existing matrix checkpoint")
    parser.add_argument("--strict", action="store_true", help="fail on failed/timed-out checks")
    args = parser.parse_args()
    root = args.root.resolve()
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(root / "src")

    results: list[MatrixResult] = [] if args.reset else load_results(root)
    positions = {item.name: index for index, item in enumerate(results)}

    def record(item: MatrixResult) -> None:
        index = positions.get(item.name)
        if index is None:
            positions[item.name] = len(results)
            results.append(item)
        else:
            results[index] = item
        write_reports(root, results)
        print(f"{item.status.upper():9} {item.layer:10} {item.name} ({item.seconds:.2f}s)", flush=True)

    def pending(name: str) -> bool:
        return name not in positions

    if pending("python-syntax"):
        record(validate_python_syntax(root))
    if pending("desktop-release-validator"):
        record(
            run_command(
                "desktop-release-validator",
                "release",
                [sys.executable, "tools/validate_desktop_release.py", "--root", ".", "--strict"],
                cwd=root,
                timeout=120,
                env=env,
            )
        )
    if pending("sovereign-release-validator"):
        record(
            run_command(
                "sovereign-release-validator",
                "release",
                [
                    sys.executable,
                    "tools/validate_sovereign_release.py",
                    "--root",
                    ".",
                    "--skip-cleanliness",
                    "--strict",
                ],
                cwd=root,
                timeout=120,
                env=env,
            )
        )

    node = shutil.which("node")
    if pending("javascript-syntax"):
        if node:
            record(
                run_command(
                    "javascript-syntax",
                    "javascript",
                    [node, "../tools/check_javascript.mjs"],
                    cwd=root / "web_demo",
                    timeout=120,
                )
            )
        else:
            record(blocked("javascript-syntax", "javascript", "Node.js is not installed"))

    if pending("node-test-suite"):
        required_modules = [
            root / "web_demo/node_modules/yjs/package.json",
            root / "web_demo/node_modules/fake-indexeddb/package.json",
        ]
        if node and all(path.is_file() for path in required_modules):
            record(
                run_command(
                    "node-test-suite",
                    "javascript",
                    [shutil.which("npm") or "npm", "test"],
                    cwd=root / "web_demo",
                    timeout=300,
                )
            )
        else:
            record(
                blocked(
                    "node-test-suite",
                    "javascript",
                    "node_modules is absent or incomplete; run npm ci first",
                    ["npm", "test"],
                )
            )

    pytest_available = subprocess.run(
        [sys.executable, "-c", "import pytest"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0
    if pytest_available:
        for test_path in sorted((root / "tests").glob("test_*.py")):
            name = f"pytest:{test_path.name}"
            if not pending(name):
                continue
            record(
                run_command(
                    name,
                    "python",
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        "-q",
                        "-p",
                        "no:cacheprovider",
                        str(test_path.relative_to(root)),
                    ],
                    cwd=root,
                    timeout=args.python_file_timeout,
                    env=env,
                )
            )
    elif pending("pytest-suite"):
        record(blocked("pytest-suite", "python", "pytest is not installed"))

    cargo = shutil.which("cargo")
    rust_checks = (
        ("cargo-fmt", [cargo or "cargo", "fmt", "--all", "--", "--check"], 180),
        ("cargo-check", [cargo or "cargo", "check", "--workspace", "--all-targets", "--locked"], 300),
        ("cargo-test", [cargo or "cargo", "test", "--workspace", "--all-targets", "--locked"], 300),
    )
    for name, command, timeout in rust_checks:
        if not pending(name):
            continue
        if cargo:
            record(run_command(name, "rust", command, cwd=root, timeout=timeout))
        else:
            record(
                blocked(
                    name,
                    "rust",
                    "Rust/Cargo is not installed in this execution environment",
                    command,
                )
            )

    counts = {
        status: sum(item.status == status for item in results)
        for status in ("passed", "failed", "blocked", "timed_out")
    }
    print(json.dumps(counts | {"total": len(results)}, ensure_ascii=False), flush=True)
    return 1 if args.strict and (counts["failed"] or counts["timed_out"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
