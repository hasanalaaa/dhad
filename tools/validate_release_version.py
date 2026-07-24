#!/usr/bin/env python3
"""Validate that every distributable surface carries one semantic version."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

SEMVER = re.compile(r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)$")


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def python_version(path: Path) -> str:
    pattern = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']\s*$', re.MULTILINE)
    match = pattern.search(path.read_text(encoding="utf-8"))
    if not match:
        raise ValueError(f"missing __version__ assignment: {path}")
    return match.group(1)


def cargo_lock_versions(path: Path) -> dict[str, str]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    packages = data.get("package", [])
    return {
        str(package["name"]): str(package["version"])
        for package in packages
        if package.get("name") in {"dhad-core", "dhad-desktop"}
    }


def collect_versions(root: Path) -> dict[str, str]:
    package_lock = load_json(root / "web_demo" / "package-lock.json")
    lock_root = package_lock.get("packages", {}).get("", {})
    release_manifest = load_json(root / "RELEASE_MANIFEST.json")
    extension = load_json(root / "extension" / "manifest.json")
    return {
        "python": python_version(root / "src" / "dhad" / "__init__.py"),
        "tauri-config": str(load_json(root / "src-tauri" / "tauri.conf.json")["version"]),
        "desktop-crate": str(
            tomllib.loads((root / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8"))["package"][
                "version"
            ]
        ),
        "core-crate": str(
            tomllib.loads(
                (root / "rust" / "dhad-core-rs" / "Cargo.toml").read_text(encoding="utf-8")
            )["package"]["version"]
        ),
        "web-package": str(load_json(root / "web_demo" / "package.json")["version"]),
        "web-lock": str(package_lock["version"]),
        "web-lock-root": str(lock_root["version"]),
        "extension": str(extension["version"]),
        "release-manifest": str(release_manifest["version"]),
        "release-manifest-python": str(release_manifest["python_version"]),
        **{f"cargo-lock:{name}": version for name, version in cargo_lock_versions(root / "Cargo.lock").items()},
    }


def validate(root: Path, tag: str | None = None) -> list[str]:
    errors: list[str] = []
    versions = collect_versions(root)
    distinct = sorted(set(versions.values()))
    if len(distinct) != 1:
        detail = ", ".join(f"{surface}={version}" for surface, version in sorted(versions.items()))
        errors.append(f"release versions diverge: {detail}")
        expected = distinct[0] if len(distinct) == 1 else None
    else:
        expected = distinct[0]

    for surface, version in versions.items():
        if not SEMVER.fullmatch(version):
            errors.append(f"{surface} is not a stable MAJOR.MINOR.PATCH version: {version}")

    if set(cargo_lock_versions(root / "Cargo.lock")) != {"dhad-core", "dhad-desktop"}:
        errors.append("workspace Cargo.lock must contain both dhad-core and dhad-desktop")
    member_lock = root / "rust" / "dhad-core-rs" / "Cargo.lock"
    if member_lock.exists():
        errors.append("remove rust/dhad-core-rs/Cargo.lock; the workspace must have one lockfile")

    if tag is not None:
        normalized_tag = tag[1:] if tag.startswith("v") else tag
        if not SEMVER.fullmatch(normalized_tag):
            errors.append(f"release tag must be vMAJOR.MINOR.PATCH: {tag}")
        elif expected is not None and normalized_tag != expected:
            errors.append(f"release tag {tag} does not match application version {expected}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--tag")
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        versions = collect_versions(root)
        errors = validate(root, args.tag)
    except (OSError, KeyError, TypeError, ValueError, tomllib.TOMLDecodeError, json.JSONDecodeError) as exc:
        print(f"Release version contract: FAIL\n{exc}", file=sys.stderr)
        return 1
    if errors:
        print("Release version contract: FAIL", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    version = next(iter(versions.values()))
    suffix = f", tag={args.tag}" if args.tag else ""
    print(f"Release version contract: PASS (version={version}{suffix})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
