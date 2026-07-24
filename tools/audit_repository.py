#!/usr/bin/env python3
"""Deterministic repository inventory and release-readiness audit for Dhad."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib

try:
    import yaml
except ModuleNotFoundError as exc:  # pragma: no cover - startup guidance
    raise SystemExit("PyYAML is required. Run this audit with .desktop-build/venv/bin/python or execute scripts/build-desktop.sh.") from exc

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {
    ".git",
    ".audit-venv",
    ".ci-venv",
    ".desktop-build",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "__pycache__",
    "node_modules",
    "target",
    "venv",
    ".venv",
}
GENERATED_REPORTS = {
    Path("reports/GOLD_MASTER_AUDIT.json"),
    Path("reports/GOLD_MASTER_AUDIT.md"),
    Path("reports/GOLD_MASTER_INVENTORY.json"),
}
FORBIDDEN_NAMES = {".DS_Store", "Thumbs.db", "Desktop.ini"}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".swp", ".tmp", ".temp", ".bak"}
TEXT_SUFFIXES = {
    ".css", ".csv", ".dockerignore", ".gitattributes", ".gitignore", ".html",
    ".ini", ".js", ".json", ".jsonl", ".lock", ".md", ".mjs", ".py",
    ".rs", ".sh", ".svg", ".toml", ".txt", ".yaml", ".yml",
}
BINARY_ASSET_SUFFIXES = {".onnx", ".wasm", ".png", ".zip", ".gz"}
PRIVATE_KEY_RE = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")


@dataclass(frozen=True)
class Finding:
    severity: str
    path: str
    message: str


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repository_files() -> list[Path]:
    files: list[Path] = []
    for directory, names, filenames in os.walk(ROOT):
        names[:] = sorted(name for name in names if name not in EXCLUDED_DIRS)
        base = Path(directory)
        for filename in sorted(filenames):
            path = base / filename
            relative_path = path.relative_to(ROOT)
            if relative_path in GENERATED_REPORTS:
                continue
            files.append(path)
    return files


def category(path: Path) -> str:
    relative_path = path.relative_to(ROOT)
    top = relative_path.parts[0] if relative_path.parts else "root"
    if path.suffix in BINARY_ASSET_SUFFIXES:
        return "binary-asset"
    if top in {"src", "rust", "web_demo", "extension", "tools"}:
        return "source"
    if top == "tests":
        return "test"
    if top in {"docs", "reports"}:
        return "documentation"
    return "configuration"


def parse_text(path: Path, findings: list[Finding]) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        findings.append(Finding("error", str(path.relative_to(ROOT)), f"invalid UTF-8: {error}"))
        return None
    if text and not text.endswith("\n") and path.suffix not in {".csv", ".svg"}:
        findings.append(Finding("warning", str(path.relative_to(ROOT)), "missing final newline"))
    if "\x00" in text:
        findings.append(Finding("error", str(path.relative_to(ROOT)), "NUL byte in text file"))
    if PRIVATE_KEY_RE.search(text):
        findings.append(
            Finding("error", str(path.relative_to(ROOT)), "embedded private key material")
        )
    return text


def validate_structured(path: Path, text: str, findings: list[Finding]) -> None:
    relative_path = str(path.relative_to(ROOT))
    try:
        if path.suffix == ".py":
            ast.parse(text, filename=relative_path)
        elif path.suffix == ".json":
            json.loads(text)
        elif path.suffix == ".toml":
            tomllib.loads(text)
        elif path.suffix in {".yaml", ".yml"}:
            yaml.safe_load(text)
    except (SyntaxError, json.JSONDecodeError, tomllib.TOMLDecodeError, yaml.YAMLError) as error:
        findings.append(Finding("error", relative_path, f"parse failure: {error}"))


def validate_binary_asset(path: Path, findings: list[Finding]) -> None:
    relative_path = str(path.relative_to(ROOT))
    prefix = path.read_bytes()[:128]
    if path.suffix == ".wasm" and not prefix.startswith(b"\x00asm"):
        findings.append(Finding("error", relative_path, "invalid WebAssembly magic header"))
    elif path.suffix == ".png" and not prefix.startswith(b"\x89PNG\r\n\x1a\n"):
        findings.append(Finding("error", relative_path, "invalid PNG signature"))
    elif path.suffix == ".onnx":
        if path.stat().st_size < 16:
            findings.append(Finding("error", relative_path, "ONNX asset is unexpectedly small"))
        if prefix.startswith(b"version https://git-lfs.github.com/spec"):
            findings.append(Finding("error", relative_path, "ONNX asset is an unresolved Git LFS pointer"))


def source_symbols(path: Path, text: str) -> dict[str, int]:
    suffix = path.suffix.lower()
    if suffix == ".py":
        tree = ast.parse(text, filename=str(path.relative_to(ROOT)))
        return {
            "python_classes": sum(isinstance(node, ast.ClassDef) for node in ast.walk(tree)),
            "python_functions": sum(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in ast.walk(tree)
            ),
        }
    if suffix == ".rs":
        return {"rust_functions": len(re.findall(r"\b(?:async\s+)?fn\s+[A-Za-z_][A-Za-z0-9_]*", text))}
    if suffix in {".js", ".mjs"}:
        declarations = re.findall(r"\b(?:async\s+)?function\s+[A-Za-z_$][A-Za-z0-9_$]*", text)
        methods = re.findall(r"^\s*(?:async\s+)?[A-Za-z_$][A-Za-z0-9_$]*\s*\([^)]*\)\s*\{", text, re.MULTILINE)
        arrows = re.findall(r"(?:const|let)\s+[A-Za-z_$][A-Za-z0-9_$]*\s*=.*?=>", text)
        return {"javascript_functions": len(declarations) + len(methods) + len(arrows)}
    return {}


def validate_checksum_manifest(findings: list[Finding]) -> None:
    manifest = ROOT / "SHA256SUMS.txt"
    if not manifest.exists():
        findings.append(Finding("error", "SHA256SUMS.txt", "checksum manifest is missing"))
        return
    for line_number, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            expected, relative_name = line.split(maxsplit=1)
        except ValueError:
            findings.append(Finding("error", "SHA256SUMS.txt", f"invalid line {line_number}"))
            continue
        relative_name = relative_name.lstrip("*")
        target = ROOT / relative_name
        if not target.is_file():
            findings.append(Finding("error", relative_name, "checksummed asset is missing"))
        elif sha256(target) != expected.lower():
            findings.append(Finding("error", relative_name, "SHA-256 does not match manifest"))


def run_external_checks(findings: list[Finding]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    node = subprocess.run(
        ["node", "tools/check_javascript.mjs"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    checks["javascript_syntax"] = {
        "status": "passed" if node.returncode == 0 else "failed",
        "detail": (node.stdout + node.stderr).strip(),
    }
    if node.returncode:
        findings.append(Finding("error", "web_demo", "JavaScript syntax verification failed"))
    shell_scripts = [str(path.relative_to(ROOT)) for path in repository_files() if path.suffix == ".sh"]
    shell = subprocess.run(
        ["bash", "-n", *shell_scripts],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    checks["shell_syntax"] = {
        "status": "passed" if shell.returncode == 0 else "failed",
        "detail": (shell.stdout + shell.stderr).strip() or f"{len(shell_scripts)} script(s) checked",
    }
    if shell.returncode:
        findings.append(Finding("error", "tools", "shell syntax verification failed"))
    with tempfile.TemporaryDirectory(prefix="dhad-compileall-") as cache_dir:
        compile_env = os.environ.copy()
        compile_env["PYTHONPYCACHEPREFIX"] = cache_dir
        compileall = subprocess.run(
            [sys.executable, "-m", "compileall", "-q", "src", "tests", "tools", "benchmarks"],
            cwd=ROOT,
            env=compile_env,
            text=True,
            capture_output=True,
            check=False,
        )
    checks["python_compileall"] = {
        "status": "passed" if compileall.returncode == 0 else "failed",
        "detail": (compileall.stdout + compileall.stderr).strip(),
    }
    if compileall.returncode:
        findings.append(Finding("error", "src", "Python compileall failed"))

    cargo_path = shutil.which("cargo")
    if cargo_path is None:
        checks["rust_workspace"] = {
            "status": "skipped",
            "detail": "cargo is unavailable in this validation environment",
        }
    else:
        cargo = subprocess.run(
            [cargo_path, "metadata", "--no-deps", "--format-version", "1"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        checks["rust_workspace"] = {
            "status": "passed" if cargo.returncode == 0 else "failed",
            "detail": (cargo.stdout + cargo.stderr).strip(),
        }
        if cargo.returncode:
            findings.append(Finding("error", "Cargo.toml", "Rust workspace metadata failed"))
    return checks


def audit() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    findings: list[Finding] = []
    inventory: list[dict[str, Any]] = []
    symbol_counts: dict[str, int] = {}
    files = repository_files()
    for path in files:
        relative_path = path.relative_to(ROOT)
        if path.name in FORBIDDEN_NAMES or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            findings.append(Finding("error", str(relative_path), "forbidden generated artifact"))
        if path.is_symlink():
            findings.append(
                Finding("warning", str(relative_path), "symbolic link requires release review")
            )
        stat = path.stat()
        entry = {
            "path": relative_path.as_posix(),
            "bytes": stat.st_size,
            "sha256": sha256(path),
            "category": category(path),
        }
        inventory.append(entry)
        suffix = path.suffix.lower()
        if suffix in BINARY_ASSET_SUFFIXES:
            validate_binary_asset(path, findings)
        if suffix in TEXT_SUFFIXES or path.name in {"Dockerfile", "Makefile"}:
            text = parse_text(path, findings)
            if text is not None:
                validate_structured(path, text, findings)
                for name, count in source_symbols(path, text).items():
                    symbol_counts[name] = symbol_counts.get(name, 0) + count
    validate_checksum_manifest(findings)
    checks = run_external_checks(findings)
    counts: dict[str, int] = {}
    bytes_by_category: dict[str, int] = {}
    for item in inventory:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
        bytes_by_category[item["category"]] = (
            bytes_by_category.get(item["category"], 0) + item["bytes"]
        )
    report = {
        "schema": "dhad-gold-master-audit-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "root": ROOT.name,
        "files_audited": len(inventory),
        "bytes_audited": sum(item["bytes"] for item in inventory),
        "counts_by_category": counts,
        "bytes_by_category": bytes_by_category,
        "source_symbols": symbol_counts,
        "checks": checks,
        "findings": [asdict(item) for item in findings],
        "status": "failed" if any(item.severity == "error" for item in findings) else "passed",
    }
    return report, inventory


def write_reports(report: dict[str, Any], inventory: list[dict[str, Any]]) -> None:
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "GOLD_MASTER_AUDIT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (reports / "GOLD_MASTER_INVENTORY.json").write_text(
        json.dumps({"schema": "dhad-gold-master-inventory-v1", "files": inventory}, indent=2) + "\n",
        encoding="utf-8",
    )
    findings = report["findings"]
    findings_lines = (
        [
            f"- **{item['severity'].upper()}** `{item['path']}` — {item['message']}"
            for item in findings
        ]
        if findings
        else ["- No audit findings."]
    )
    checks_lines = [
        f"- **{name}**: {data['status']} — {data['detail'] or 'no output'}"
        for name, data in report["checks"].items()
    ]
    markdown = "\n".join(
        [
            "# Dhad 1.0 Gold Master Repository Audit",
            "",
            f"- Status: **{report['status'].upper()}**",
            f"- Files audited: **{report['files_audited']}**",
            f"- Bytes audited: **{report['bytes_audited']}**",
            f"- Generated: `{report['generated_at_utc']}`",
            "",
            "## Source symbols inventoried",
            "",
            *[f"- **{name}**: {count}" for name, count in sorted(report["source_symbols"].items())],
            "",
            "## Automated checks",
            "",
            *checks_lines,
            "",
            "## Findings",
            "",
            *findings_lines,
            "",
            "## Audit scope",
            "",
            "Every repository file outside reproducible dependency/build/cache directories is "
            "inventoried with size and SHA-256. First-party Python, JavaScript, JSON, and "
            "TOML receive syntax/parse validation. Binary models, WASM artifacts, images, "
            "and retained release evidence are integrity-inventoried rather than interpreted "
            "as source.",
            "",
        ]
    )
    (reports / "GOLD_MASTER_AUDIT.md").write_text(markdown, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-reports", action="store_true")
    args = parser.parse_args()
    report, inventory = audit()
    if args.write_reports:
        write_reports(report, inventory)
    print(
        json.dumps(
            {
                "status": report["status"],
                "files": report["files_audited"],
                "findings": len(report["findings"]),
            }
        )
    )
    for finding in report["findings"]:
        print(
            f"{finding['severity'].upper()}: {finding['path']} — {finding['message']}",
            file=sys.stderr,
        )
    for name, result in report["checks"].items():
        if result["status"] == "failed":
            print(f"CHECK FAILED: {name}: {result['detail']}", file=sys.stderr)
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
