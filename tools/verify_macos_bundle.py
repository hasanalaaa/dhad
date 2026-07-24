#!/usr/bin/env python3
"""Verify a generated Dhad macOS .app bundle and optionally smoke-launch it."""

from __future__ import annotations

import argparse
import os
import plistlib
import platform
import subprocess
import sys
import time
from pathlib import Path

EXPECTED_IDENTIFIER = "com.dhad.desktop"
EXPECTED_EXECUTABLE = "dhad-desktop"
EXPECTED_DISPLAY_NAME = "ضاد"
SYSTEM_DYLIB_PREFIXES = (
    "/System/Library/",
    "/usr/lib/",
    "@executable_path/",
    "@loader_path/",
    "@rpath/",
)


class VerificationError(RuntimeError):
    pass


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, text=True, capture_output=True)
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise VerificationError(f"command failed ({result.returncode}): {' '.join(command)}\n{detail}")
    return result


def verify_static_bundle(app: Path, expected_arch: str | None = None) -> tuple[Path, dict[str, object]]:
    app = app.resolve()
    if not app.is_dir() or app.suffix != ".app":
        raise VerificationError(f"not a macOS application bundle: {app}")

    contents = app / "Contents"
    plist_path = contents / "Info.plist"
    if not plist_path.is_file():
        raise VerificationError(f"missing Info.plist: {plist_path}")

    try:
        with plist_path.open("rb") as stream:
            plist = plistlib.load(stream)
    except Exception as exc:  # noqa: BLE001 - report malformed bundle metadata.
        raise VerificationError(f"invalid Info.plist: {exc}") from exc

    required_values = {
        "CFBundleIdentifier": EXPECTED_IDENTIFIER,
        "CFBundleExecutable": EXPECTED_EXECUTABLE,
        "CFBundlePackageType": "APPL",
        "CFBundleName": "Dhad",
    }
    for key, expected in required_values.items():
        actual = plist.get(key)
        if actual != expected:
            raise VerificationError(f"{key} must be {expected!r}, got {actual!r}")

    if plist.get("CFBundleDisplayName") != EXPECTED_DISPLAY_NAME:
        raise VerificationError(
            f"CFBundleDisplayName must be {EXPECTED_DISPLAY_NAME!r}, got {plist.get('CFBundleDisplayName')!r}"
        )
    if not plist.get("CFBundleShortVersionString") or not plist.get("CFBundleVersion"):
        raise VerificationError("Info.plist is missing bundle version metadata")
    if not plist.get("LSMinimumSystemVersion"):
        raise VerificationError("Info.plist is missing LSMinimumSystemVersion")

    executable = contents / "MacOS" / EXPECTED_EXECUTABLE
    if not executable.is_file():
        raise VerificationError(f"missing application executable: {executable}")
    if not os.access(executable, os.X_OK):
        raise VerificationError(f"application executable is not executable: {executable}")

    resources = contents / "Resources"
    if not resources.is_dir():
        raise VerificationError(f"missing Resources directory: {resources}")
    if not any(resources.glob("*.icns")):
        raise VerificationError("bundle does not contain an .icns application icon")

    if expected_arch and expected_arch not in {"aarch64", "x86_64"}:
        raise VerificationError(f"unsupported expected architecture: {expected_arch}")
    return executable, plist


def verify_native_macos(app: Path, executable: Path, expected_arch: str | None, require_notarized: bool) -> None:
    run(["plutil", "-lint", str(app / "Contents" / "Info.plist")])

    file_output = run(["file", str(executable)]).stdout
    if "Mach-O" not in file_output:
        raise VerificationError(f"application executable is not Mach-O: {file_output.strip()}")

    if expected_arch:
        arch_output = run(["lipo", "-archs", str(executable)]).stdout.split()
        aliases = {"aarch64": "arm64", "x86_64": "x86_64"}
        if aliases[expected_arch] not in arch_output:
            raise VerificationError(
                f"expected {aliases[expected_arch]} executable, found architectures: {arch_output}"
            )

    run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)])
    signature = run(["codesign", "--display", "--verbose=4", str(app)]).stderr
    if f"Identifier={EXPECTED_IDENTIFIER}" not in signature:
        raise VerificationError("code signature identifier does not match the Tauri bundle identifier")

    dependencies = run(["otool", "-L", str(executable)]).stdout.splitlines()[1:]
    invalid_dependencies: list[str] = []
    for line in dependencies:
        dependency = line.strip().split(" (", 1)[0]
        if dependency and not dependency.startswith(SYSTEM_DYLIB_PREFIXES):
            invalid_dependencies.append(dependency)
    if invalid_dependencies:
        raise VerificationError(f"unbundled absolute dynamic-library dependencies: {invalid_dependencies}")

    if require_notarized:
        run(["spctl", "--assess", "--type", "execute", "--verbose=4", str(app)])
        staple = run(["xcrun", "stapler", "validate", str(app)], check=False)
        if staple.returncode != 0:
            raise VerificationError(f"notarization ticket validation failed: {(staple.stderr or staple.stdout).strip()}")


def smoke_launch(app: Path, executable: Path, seconds: float) -> None:
    """Launch through LaunchServices, matching a Finder double-click as closely as CI permits."""
    process = subprocess.Popen(
        ["open", "-n", "-W", str(app)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            return_code = process.poll()
            if return_code is not None:
                stdout, stderr = process.communicate(timeout=2)
                raise VerificationError(
                    f"LaunchServices exited during smoke test with code {return_code}\n"
                    f"stdout:\n{stdout[-4000:]}\nstderr:\n{stderr[-4000:]}"
                )
            time.sleep(0.2)

        running = run(["pgrep", "-f", str(executable)], check=False)
        if running.returncode != 0:
            raise VerificationError(
                "LaunchServices remained active, but the Dhad executable process was not found"
            )
    finally:
        run(
            ["osascript", "-e", f'tell application id "{EXPECTED_IDENTIFIER}" to quit'],
            check=False,
        )
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            run(["pkill", "-TERM", "-f", str(executable)], check=False)
            try:
                process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)


def find_latest_app(root: Path) -> Path:
    candidates = [path for path in root.rglob("*.app") if path.is_dir()]
    if not candidates:
        raise VerificationError(f"no .app bundle found under {root}")
    candidates.sort(key=lambda path: path.stat().st_mtime_ns, reverse=True)
    return candidates[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, help="Path to the generated .app bundle")
    parser.add_argument("--search-root", type=Path, default=Path("target"))
    parser.add_argument("--expected-arch", choices=("aarch64", "x86_64"))
    parser.add_argument("--launch", action="store_true", help="Require the process to remain alive after startup")
    parser.add_argument("--launch-seconds", type=float, default=5.0)
    parser.add_argument("--require-notarized", action="store_true")
    args = parser.parse_args()

    try:
        app = args.app.resolve() if args.app else find_latest_app(args.search_root.resolve())
        executable, plist = verify_static_bundle(app, args.expected_arch)
        if platform.system() == "Darwin":
            verify_native_macos(app, executable, args.expected_arch, args.require_notarized)
            if args.launch:
                smoke_launch(app, executable, max(1.0, args.launch_seconds))
        elif args.launch or args.require_notarized:
            raise VerificationError("native signing and launch verification requires macOS")
    except VerificationError as exc:
        print(f"macOS bundle verification: FAIL\n{exc}", file=sys.stderr)
        return 1

    print(
        "macOS bundle verification: PASS "
        f"(app={app.name}, executable={plist['CFBundleExecutable']}, identifier={plist['CFBundleIdentifier']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
