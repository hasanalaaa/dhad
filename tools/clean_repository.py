#!/usr/bin/env python3
"""Remove host-generated artifacts without touching dependencies or build outputs.

macOS Finder recreates ``.DS_Store`` files after extraction. Python and test tools
may also leave bytecode/cache directories. Release validation should be strict,
but the local build entrypoint should normalize these harmless host artifacts
before auditing the source tree.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

PRUNED_DIRS = {".git", ".desktop-build", ".audit-venv", ".ci-venv", ".venv", "venv", "node_modules", "target", "web_dist"}
REMOVABLE_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".pyright", ".nox", ".tox"}
REMOVABLE_NAMES = {".DS_Store", "Thumbs.db", "Desktop.ini", ".coverage"}
REMOVABLE_SUFFIXES = {".pyc", ".pyo", ".swp", ".tmp", ".temp", ".bak"}


def generated_artifacts(root: Path) -> list[Path]:
    root = root.resolve()
    found: list[Path] = []
    for directory, dirnames, filenames in os.walk(root, topdown=True):
        base = Path(directory)
        kept: list[str] = []
        for name in sorted(dirnames):
            path = base / name
            if name in PRUNED_DIRS:
                continue
            if name in REMOVABLE_DIRS:
                found.append(path)
                continue
            kept.append(name)
        dirnames[:] = kept
        for name in sorted(filenames):
            path = base / name
            if name in REMOVABLE_NAMES or name.startswith("._") or path.suffix.lower() in REMOVABLE_SUFFIXES:
                found.append(path)
    return sorted(set(found), key=lambda item: (len(item.parts), item.as_posix()), reverse=True)


def clean(root: Path, *, check_only: bool = False) -> list[Path]:
    artifacts = generated_artifacts(root)
    if check_only:
        return artifacts
    for path in artifacts:
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
        except FileNotFoundError:
            pass
    return artifacts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true", help="Report artifacts without deleting them.")
    args = parser.parse_args()
    root = args.root.resolve()
    artifacts = clean(root, check_only=args.check)
    if args.check and artifacts:
        for path in reversed(artifacts):
            print(path.relative_to(root).as_posix(), file=sys.stderr)
        print(f"Repository hygiene: FAIL ({len(artifacts)} generated artifact(s))", file=sys.stderr)
        return 1
    action = "Found" if args.check else "Removed"
    print(f"Repository hygiene: {action} {len(artifacts)} generated artifact(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
