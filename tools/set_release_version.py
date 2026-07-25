#!/usr/bin/env python3
"""Set one semantic release version across every distributable surface.

``tools/validate_release_version.py`` proves that the surfaces agree; this tool is
how they are made to agree. Every surface it edits is listed in ``SURFACES`` so the
two tools can be diffed against each other by eye, and every edit is a targeted
replacement rather than a blind search-and-replace, so an unrelated occurrence of
the previous version string is never touched.

Usage::

    python tools/set_release_version.py 1.0.19
    python tools/set_release_version.py 1.0.19 --check
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SEMVER = re.compile(r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$")

SURFACES = (
    "src/dhad/__init__.py",
    "src-tauri/tauri.conf.json",
    "src-tauri/Cargo.toml",
    "rust/dhad-core-rs/Cargo.toml",
    "web_demo/package.json",
    "web_demo/package-lock.json",
    "web_demo/pwa/cache-policy.js",
    "extension/manifest.json",
    "RELEASE_MANIFEST.json",
    "Cargo.lock",
)


class SurfaceError(RuntimeError):
    """A surface could not be rewritten deterministically."""


def _substitute(path: Path, pattern: re.Pattern[str], replacement: str, *, expected: int) -> str:
    original = path.read_text(encoding="utf-8")
    updated, count = pattern.subn(replacement, original)
    if count != expected:
        raise SurfaceError(f"{path}: expected {expected} replacement(s), made {count}")
    return updated


def _python_init(root: Path, version: str) -> tuple[Path, str]:
    path = root / "src/dhad/__init__.py"
    pattern = re.compile(r'(?m)^__version__\s*=\s*"[^"]+"$')
    return path, _substitute(path, pattern, f'__version__ = "{version}"', expected=1)


def _tauri_config(root: Path, version: str) -> tuple[Path, str]:
    path = root / "src-tauri/tauri.conf.json"
    pattern = re.compile(r'(?m)^(\s*"version"\s*:\s*)"[^"]+"')
    return path, _substitute(path, pattern, rf'\g<1>"{version}"', expected=1)


def _cargo_manifest(root: Path, relative: str, version: str) -> tuple[Path, str]:
    path = root / relative
    # Only the [package] version is rewritten: dependency pins live under other
    # tables and must survive untouched.
    pattern = re.compile(r'(?ms)(^\[package\]\n(?:(?!^\[).)*?^version\s*=\s*)"[^"]+"')
    return path, _substitute(path, pattern, rf'\g<1>"{version}"', expected=1)


def _package_json(root: Path, version: str) -> tuple[Path, str]:
    path = root / "web_demo/package.json"
    pattern = re.compile(r'(?m)^(\s*"version"\s*:\s*)"[^"]+"')
    return path, _substitute(path, pattern, rf'\g<1>"{version}"', expected=1)


def _package_lock(root: Path, version: str) -> tuple[Path, str]:
    path = root / "web_demo/package-lock.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["version"] = version
    if "" not in document.get("packages", {}):
        raise SurfaceError(f"{path}: lockfile has no root package entry")
    document["packages"][""]["version"] = version
    return path, json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def _cache_policy(root: Path, version: str) -> tuple[Path, str]:
    path = root / "web_demo/pwa/cache-policy.js"
    pattern = re.compile(r'(?m)^(export const CACHE_VERSION = ")[^"]+(";)$')
    return path, _substitute(path, pattern, rf"\g<1>gold-{version}-desktop-goldmaster\g<2>", expected=1)


def _extension_manifest(root: Path, version: str) -> tuple[Path, str]:
    path = root / "extension/manifest.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["version"] = version
    if "version_name" in document:
        suffix = str(document["version_name"]).split(" ", 1)
        document["version_name"] = f"{version} {suffix[1]}" if len(suffix) == 2 else version
    return path, json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def _release_manifest(root: Path, version: str) -> tuple[Path, str]:
    path = root / "RELEASE_MANIFEST.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    previous = str(document.get("version", ""))
    document["version"] = version
    document["python_version"] = version
    if previous and isinstance(document.get("completed_phase"), str):
        document["completed_phase"] = document["completed_phase"].replace(previous, version)
    return path, json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def _cargo_lock(root: Path, version: str) -> tuple[Path, str]:
    path = root / "Cargo.lock"
    text = path.read_text(encoding="utf-8")
    for name in ("dhad-core", "dhad-desktop"):
        pattern = re.compile(rf'(?ms)(^name = "{re.escape(name)}"\nversion = )"[^"]+"')
        text, count = pattern.subn(rf'\g<1>"{version}"', text)
        if count != 1:
            raise SurfaceError(f"{path}: expected exactly one {name} entry, found {count}")
    return path, text


def rewrite(root: Path, version: str) -> dict[str, bool]:
    edits = [
        _python_init(root, version),
        _tauri_config(root, version),
        _cargo_manifest(root, "src-tauri/Cargo.toml", version),
        _cargo_manifest(root, "rust/dhad-core-rs/Cargo.toml", version),
        _package_json(root, version),
        _package_lock(root, version),
        _cache_policy(root, version),
        _extension_manifest(root, version),
        _release_manifest(root, version),
        _cargo_lock(root, version),
    ]
    changed: dict[str, bool] = {}
    for path, content in edits:
        relative = path.relative_to(root).as_posix()
        changed[relative] = path.read_text(encoding="utf-8") != content
        path.write_text(content, encoding="utf-8")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="target MAJOR.MINOR.PATCH version, for example 1.0.19")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--check",
        action="store_true",
        help="report which surfaces would change without writing them",
    )
    arguments = parser.parse_args()
    if not SEMVER.fullmatch(arguments.version):
        print(f"version must be MAJOR.MINOR.PATCH: {arguments.version}", file=sys.stderr)
        return 2
    root = arguments.root.resolve()
    if arguments.check:
        snapshots = {relative: (root / relative).read_bytes() for relative in SURFACES}
    try:
        changed = rewrite(root, arguments.version)
    except (SurfaceError, OSError, KeyError, json.JSONDecodeError) as error:
        print(f"Release version rewrite failed: {error}", file=sys.stderr)
        return 1
    finally:
        if arguments.check:
            for relative, payload in snapshots.items():
                (root / relative).write_bytes(payload)
    pending = sorted(name for name, dirty in changed.items() if dirty)
    verb = "would update" if arguments.check else "updated"
    if pending:
        print(f"Release version {arguments.version}: {verb} {len(pending)} surface(s)")
        for name in pending:
            print(f"- {name}")
    else:
        print(f"Release version {arguments.version}: every surface already matches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
