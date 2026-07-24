#!/usr/bin/env python3
"""Create a clean deterministic ZIP while preserving dot-directories such as .github."""

from __future__ import annotations

import argparse
import hashlib
import os
import stat
import sys
import zipfile
from pathlib import Path

EXCLUDED_DIRS = {
    ".git", ".desktop-build", ".audit-venv", ".ci-venv", ".pytest_cache", ".ruff_cache",
    ".mypy_cache", "__pycache__", "node_modules", "target", "venv", ".venv",
}
EXCLUDED_NAMES = {".DS_Store", "Thumbs.db", "Desktop.ini"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp", ".temp", ".bak", ".swp"}
REQUIRED_ARCHIVE_PATHS = {
    "dhad/.github/workflows/desktop-release.yml",
    "dhad/src-tauri/tauri.conf.json",
    "dhad/tools/validate_tauri_config.py",
    "dhad/tools/verify_macos_bundle.py",
    "dhad/src-tauri/Info.plist",
    "dhad/src-tauri/Entitlements.plist",
    "dhad/scripts/build-desktop.sh",
    "dhad/scripts/verify-macos-app.sh",
    "dhad/scripts/build-desktop.bat",
    "dhad/scripts/install-macos-app.sh",
    "dhad/tools/clean_repository.py",
}


def include(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if any(part in EXCLUDED_DIRS for part in relative.parts):
        return False
    if path.name in EXCLUDED_NAMES or path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    return path.is_file()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package(root: Path, output: Path) -> tuple[int, str]:
    root = root.resolve()
    output = output.resolve()
    files = sorted(path for path in root.rglob("*") if include(path, root))
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + ".partial")
    temp.unlink(missing_ok=True)
    with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        for path in files:
            relative = Path("dhad") / path.relative_to(root)
            info = zipfile.ZipInfo(relative.as_posix(), date_time=(2026, 7, 24, 0, 0, 0))
            mode = path.stat().st_mode
            info.create_system = 3  # Unix: preserve executable permission bits on macOS/Linux extraction.
            info.external_attr = (stat.S_IFREG | stat.S_IMODE(mode)) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with path.open("rb") as stream:
                archive.writestr(info, stream.read(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
    with zipfile.ZipFile(temp) as archive:
        names = set(archive.namelist())
        missing = sorted(REQUIRED_ARCHIVE_PATHS - names)
        bad = archive.testzip()
        if missing:
            raise RuntimeError(f"archive is missing required paths: {missing}")
        if bad:
            raise RuntimeError(f"CRC failure in archive entry: {bad}")
        excluded_archive_fragments=("/.git/", "/node_modules/", "/target/", "/.desktop-build/", "/.audit-venv/", "/.ci-venv/", "/__pycache__/")
        if any(any(fragment in f"/{name}" for fragment in excluded_archive_fragments) for name in names):
            raise RuntimeError("archive contains excluded build, cache, or VCS directories")
        forbidden_basenames = {".DS_Store", "Thumbs.db", "Desktop.ini"}
        forbidden_suffixes = {".pyc", ".pyo", ".tmp", ".temp", ".bak", ".swp"}
        dirty = sorted(
            name for name in names
            if Path(name).name in forbidden_basenames
            or Path(name).name.startswith("._")
            or Path(name).suffix.lower() in forbidden_suffixes
        )
        if dirty:
            raise RuntimeError(f"archive contains generated host artifacts: {dirty[:10]}")
        nonempty_required = (
            "dhad/.github/workflows/desktop-release.yml",
            "dhad/src-tauri/Info.plist",
            "dhad/src-tauri/Entitlements.plist",
            "dhad/tools/verify_macos_bundle.py",
            "dhad/tools/clean_repository.py",
            "dhad/scripts/verify-macos-app.sh",
            "dhad/scripts/install-macos-app.sh",
        )
        for required_name in nonempty_required:
            if archive.getinfo(required_name).file_size == 0 or not archive.read(required_name).strip():
                raise RuntimeError(f"required release file is empty: {required_name}")
        for executable_name in (
            "dhad/scripts/build-desktop.sh",
            "dhad/scripts/verify-macos-app.sh",
            "dhad/scripts/install-macos-app.sh",
            "dhad/tools/verify_macos_bundle.py",
            "dhad/tools/clean_repository.py",
        ):
            mode = archive.getinfo(executable_name).external_attr >> 16
            if not mode & 0o111:
                raise RuntimeError(f"archive lost executable permissions: {executable_name}")
    os.replace(temp, output)
    return len(files), sha256(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        count, checksum = package(args.root, args.output)
    except Exception as exc:
        print(f"Release packaging failed: {exc}", file=sys.stderr)
        return 1
    print(f"Packaged {count} files: {args.output}")
    print(f"SHA256 {checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
