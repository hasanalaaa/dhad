#!/usr/bin/env python3
"""Structural validation of the GitHub Actions workflows.

Why this exists
---------------
The previous release audit verified the workflows by asserting that dozens of
literal substrings appeared somewhere in ``desktop-release.yml``. That is a
tautology: it proves the file still contains certain spellings, not that the
pipeline is wired correctly, so it passed locally through eight consecutive
releases that failed on GitHub. Worse, it made the validator a mirror of the
workflow, so every workflow edit required an equal edit here purely to keep the
mirror intact.

This module parses the workflows instead and checks the properties that can
actually break a release:

* the job graph and its dependency edges (a draft created once, uploaded to by
  release id, published by id);
* the build matrix covers every shipped installer;
* every ``tools/`` and ``scripts/`` path a step executes really exists;
* every third-party action is pinned to a tag, never a moving branch;
* pinned tool versions agree with their single source of truth
  (``rust-toolchain.toml``, ``.nvmrc``, ``src-tauri/Cargo.toml``);
* the release-publication scripts do not use the by-tag release endpoint, which
  cannot see drafts.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

import yaml

DESKTOP_WORKFLOW = ".github/workflows/desktop-release.yml"
CI_WORKFLOW = ".github/workflows/ci.yml"

REQUIRED_DESKTOP_JOBS = ("validate", "prepare-release", "build", "publish")
REQUIRED_CI_JOBS = ("python", "rust", "web", "windows-installer-contracts")

# Every installer the publish gate insists on must be produced by the matrix.
REQUIRED_BUNDLE_MATRIX = {
    ("macos-15", "aarch64-apple-darwin", "dmg"),
    ("macos-15-intel", "x86_64-apple-darwin", "dmg"),
    ("windows-2022", "x86_64-pc-windows-msvc", "nsis"),
    ("windows-2022", "x86_64-pc-windows-msvc", "msi"),
}

MOVING_REFS = {"main", "master", "dev", "develop", "latest", "HEAD"}

# Paths executed by a `run:` block. Matched against the repository so a renamed or
# deleted tool is caught here rather than 30 minutes into a release build.
REFERENCED_PATH = re.compile(r"(?<![\w./-])((?:tools|scripts|src-tauri|benchmarks)/[\w./@-]+)")
PATH_SUFFIXES = (".py", ".mjs", ".js", ".sh", ".bat", ".ps1", ".json", ".txt", ".toml")


def _load(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path} is not a YAML mapping")
    # PyYAML resolves the bare key `on` to the boolean True (YAML 1.1).
    if True in document and "on" not in document:
        document["on"] = document.pop(True)
    return document


def _jobs(workflow: dict[str, Any]) -> dict[str, dict[str, Any]]:
    jobs = workflow.get("jobs") or {}
    return {name: job for name, job in jobs.items() if isinstance(job, dict)}


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for step in (job.get("steps") or []) if isinstance(step, dict)]


def _needs(job: dict[str, Any]) -> list[str]:
    needs = job.get("needs")
    if needs is None:
        return []
    return [needs] if isinstance(needs, str) else [str(item) for item in needs]


def _all_steps(workflow: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [(name, step) for name, job in _jobs(workflow).items() for step in _steps(job)]


def _run_scripts(workflow: dict[str, Any]) -> list[tuple[str, str]]:
    scripts: list[tuple[str, str]] = []
    for job_name, step in _all_steps(workflow):
        run = step.get("run")
        if isinstance(run, str):
            scripts.append((job_name, run))
        script = (step.get("with") or {}).get("script") if isinstance(step.get("with"), dict) else None
        if isinstance(script, str):
            scripts.append((job_name, script))
    return scripts


def _find_step(workflow: dict[str, Any], job_name: str, *, uses_prefix: str) -> dict[str, Any] | None:
    for step in _steps(_jobs(workflow).get(job_name, {})):
        uses = step.get("uses")
        if isinstance(uses, str) and uses.startswith(uses_prefix):
            return step
    return None


def _check_pinned_actions(workflow: dict[str, Any], label: str, errors: list[str]) -> None:
    for job_name, step in _all_steps(workflow):
        uses = step.get("uses")
        if not isinstance(uses, str) or uses.startswith("./"):
            continue
        if "@" not in uses:
            errors.append(f"{label}:{job_name}: action {uses!r} is not pinned to a ref")
            continue
        ref = uses.rsplit("@", 1)[1]
        if ref in MOVING_REFS:
            errors.append(
                f"{label}:{job_name}: action {uses!r} is pinned to the moving ref {ref!r}"
            )


def _check_referenced_paths(root: Path, workflow: dict[str, Any], label: str, errors: list[str]) -> None:
    for job_name, script in _run_scripts(workflow):
        for candidate in sorted(set(REFERENCED_PATH.findall(script))):
            if not candidate.endswith(PATH_SUFFIXES):
                continue
            if not (root / candidate).is_file():
                errors.append(
                    f"{label}:{job_name}: step executes {candidate!r}, which does not exist"
                )


def _check_timeouts(workflow: dict[str, Any], label: str, errors: list[str]) -> None:
    for job_name, job in _jobs(workflow).items():
        if not isinstance(job.get("timeout-minutes"), int):
            errors.append(f"{label}:{job_name}: job has no integer timeout-minutes")


def _check_checkout_lfs(workflow: dict[str, Any], label: str, errors: list[str]) -> None:
    for job_name, step in _all_steps(workflow):
        uses = step.get("uses")
        if not isinstance(uses, str) or not uses.startswith("actions/checkout@"):
            continue
        with_block = step.get("with") or {}
        if label == "ci" and job_name == "windows-installer-contracts":
            # That job only parses PowerShell; it never touches a model.
            continue
        if with_block.get("lfs") is not True:
            errors.append(
                f"{label}:{job_name}: checkout must set lfs: true so ONNX assets are real files"
            )


def _pinned_versions(root: Path) -> dict[str, str]:
    toolchain = tomllib.loads((root / "rust-toolchain.toml").read_text(encoding="utf-8"))
    desktop_cargo = tomllib.loads((root / "src-tauri/Cargo.toml").read_text(encoding="utf-8"))
    tauri_requirement = str(desktop_cargo["dependencies"]["tauri"]["version"]).lstrip("=")
    profile = (root / "tools/validate_tauri_config.py").read_text(encoding="utf-8")
    profile_match = re.search(r'PROFILE = "tauri-cli ([\d.]+) / tauri ([\d.]+)"', profile)
    return {
        "rust": str(toolchain["toolchain"]["channel"]),
        "node": (root / ".nvmrc").read_text(encoding="utf-8").strip(),
        "tauri-crate": tauri_requirement,
        "cli-profile": profile_match.group(1) if profile_match else "",
        "crate-profile": profile_match.group(2) if profile_match else "",
    }


def _check_version_pins(
    root: Path, workflow: dict[str, Any], label: str, errors: list[str]
) -> None:
    pins = _pinned_versions(root)

    for job_name, step in _all_steps(workflow):
        uses = step.get("uses")
        if isinstance(uses, str) and uses.startswith("dtolnay/rust-toolchain@"):
            ref = uses.rsplit("@", 1)[1]
            if ref != pins["rust"]:
                errors.append(
                    f"{label}:{job_name}: rust-toolchain action pins {ref}, "
                    f"rust-toolchain.toml pins {pins['rust']}"
                )
        if isinstance(uses, str) and uses.startswith("actions/setup-node@"):
            node_version = str((step.get("with") or {}).get("node-version", ""))
            if node_version != pins["node"]:
                errors.append(
                    f"{label}:{job_name}: setup-node requests {node_version!r}, "
                    f".nvmrc pins {pins['node']!r}"
                )

    if pins["crate-profile"] and pins["tauri-crate"] != pins["crate-profile"]:
        errors.append(
            f"src-tauri/Cargo.toml pins tauri {pins['tauri-crate']} but the config profile "
            f"targets tauri {pins['crate-profile']}"
        )

    text = json.dumps(workflow)
    cli_versions = set(re.findall(r"@tauri-apps/cli@([\d.]+)", text))
    if cli_versions:
        env_version = str((workflow.get("env") or {}).get("TAURI_CLI_VERSION", ""))
        if cli_versions != {env_version}:
            errors.append(
                f"{label}: installed Tauri CLI version(s) {sorted(cli_versions)} disagree with "
                f"TAURI_CLI_VERSION {env_version!r}"
            )
        if pins["cli-profile"] and cli_versions != {pins["cli-profile"]}:
            errors.append(
                f"{label}: installed Tauri CLI version(s) {sorted(cli_versions)} disagree with the "
                f"validated CLI profile {pins['cli-profile']}"
            )


def _check_locked_cargo(workflow: dict[str, Any], label: str, errors: list[str]) -> None:
    for job_name, script in _run_scripts(workflow):
        for command in re.findall(r"cargo\s+(clippy|test|build)[^\n]*", script):
            line = next(
                line
                for line in script.splitlines()
                if f"cargo {command}" in line
            )
            if "--locked" not in line:
                errors.append(
                    f"{label}:{job_name}: {line.strip()!r} must pass --locked for a reproducible build"
                )


def _validate_desktop(root: Path, workflow: dict[str, Any], errors: list[str]) -> None:
    label = "desktop-release"
    triggers = workflow.get("on") or {}
    if (triggers.get("push") or {}).get("tags") != ["v*.*.*"]:
        errors.append(f"{label}: must trigger only on v*.*.* tags")
    dispatch_input = ((triggers.get("workflow_dispatch") or {}).get("inputs") or {}).get("tag") or {}
    if dispatch_input.get("required") is not True:
        errors.append(f"{label}: workflow_dispatch must require an explicit tag input")
    if (workflow.get("permissions") or {}).get("contents") != "write":
        errors.append(f"{label}: needs contents: write to publish a release")

    jobs = _jobs(workflow)
    for name in REQUIRED_DESKTOP_JOBS:
        if name not in jobs:
            errors.append(f"{label}: missing required job {name!r}")
    if not all(name in jobs for name in REQUIRED_DESKTOP_JOBS):
        return

    if "validate" not in _needs(jobs["prepare-release"]):
        errors.append(f"{label}: prepare-release must run only after validate")
    if "prepare-release" not in _needs(jobs["build"]):
        errors.append(f"{label}: build must depend on prepare-release for the release id")
    for dependency in ("prepare-release", "build"):
        if dependency not in _needs(jobs["publish"]):
            errors.append(f"{label}: publish must depend on {dependency}")

    outputs = jobs["prepare-release"].get("outputs") or {}
    if "release_id" not in outputs:
        errors.append(f"{label}: prepare-release must export a release_id output")

    strategy = jobs["build"].get("strategy") or {}
    if strategy.get("fail-fast") is not False:
        errors.append(f"{label}: build matrix must set fail-fast: false")
    matrix_entries = (strategy.get("matrix") or {}).get("include") or []
    produced = {
        (str(entry.get("platform")), str(entry.get("target")), str(entry.get("bundle")))
        for entry in matrix_entries
        if isinstance(entry, dict)
    }
    for required in sorted(REQUIRED_BUNDLE_MATRIX - produced):
        errors.append(f"{label}: build matrix does not produce {required}")
    for entry in matrix_entries:
        if not isinstance(entry, dict):
            continue
        args = str(entry.get("args", ""))
        bundle = str(entry.get("bundle", ""))
        target = str(entry.get("target", ""))
        if f"--bundles {bundle}" not in args:
            errors.append(f"{label}: matrix entry {entry.get('label')!r} does not build --bundles {bundle}")
        if f"--target {target}" not in args:
            errors.append(f"{label}: matrix entry {entry.get('label')!r} does not build --target {target}")

    action = _find_step(workflow, "build", uses_prefix="tauri-apps/tauri-action@")
    if action is None:
        errors.append(f"{label}: build job never invokes tauri-apps/tauri-action")
    else:
        with_block = action.get("with") or {}
        if "tagName" in with_block:
            errors.append(
                f"{label}: tauri-action must not receive tagName; a tag lookup lets every matrix "
                "job create its own draft release"
            )
        release_id = str(with_block.get("releaseId", ""))
        if "needs.prepare-release.outputs.release_id" not in release_id:
            errors.append(
                f"{label}: tauri-action must upload to needs.prepare-release.outputs.release_id"
            )
        if with_block.get("projectPath") != "src-tauri":
            errors.append(f"{label}: tauri-action projectPath must be src-tauri")
        if with_block.get("tauriScript") != "tauri":
            errors.append(f"{label}: tauri-action must call the pinned global tauri CLI")
        if with_block.get("uploadUpdaterJson") is not False:
            errors.append(f"{label}: updater artifacts are not part of this release")

    scripts = dict(
        (job_name, script)
        for job_name, script in _run_scripts(workflow)
        if job_name in {"prepare-release", "publish"}
    )
    prepare_script = scripts.get("prepare-release", "")
    publish_script = scripts.get("publish", "")
    if "listReleases" not in prepare_script:
        errors.append(
            f"{label}: prepare-release must locate the draft through listReleases; the by-tag "
            "endpoint only returns published releases"
        )
    for job_name, script in (("prepare-release", prepare_script), ("publish", publish_script)):
        if "getReleaseByTag" in script:
            errors.append(
                f"{label}:{job_name}: getReleaseByTag cannot see draft releases and must not be used"
            )
    for token, message in (
        ("getRelease(", "publish must read the release by id"),
        ("updateRelease", "publish must flip the draft to published"),
        ("draft: false", "publish must clear the draft flag"),
        ("dmgCount < 2", "publish must require both macOS DMGs"),
        ("hasMsi", "publish must require the MSI"),
        ("hasNsis", "publish must require the NSIS setup executable"),
    ):
        if token not in publish_script:
            errors.append(f"{label}:publish: {message}")

    build_steps = _steps(jobs["build"])
    step_text = json.dumps(build_steps)
    for token, message in (
        ("verify-macos-app.sh", "macOS bundles must be verified and launch-smoked"),
        ("verify-windows-installer.ps1", "Windows installers must be verified"),
        ("test-windows-installer-verifier.ps1", "the Windows verifier's own contracts must run"),
        ("VBSCRIPT", "WiX needs the VBSCRIPT optional feature checked before bundling"),
        ("dhad-wix-diagnostics", "MSI failures must upload WiX diagnostics"),
    ):
        if token not in step_text:
            errors.append(f"{label}:build: {message}")
    if not any(str(step.get("if", "")).startswith("failure()") for step in build_steps):
        errors.append(f"{label}:build: no failure() step preserves diagnostics")


def _validate_ci(root: Path, workflow: dict[str, Any], errors: list[str]) -> None:
    label = "ci"
    triggers = workflow.get("on") or {}
    if (triggers.get("push") or {}).get("branches") != ["main"]:
        errors.append(f"{label}: must run on pushes to main")
    if (triggers.get("pull_request") or {}).get("branches") != ["main"]:
        errors.append(f"{label}: must run on pull requests targeting main")
    if "tags" in (triggers.get("push") or {}):
        errors.append(f"{label}: tag pushes belong to the release workflow, not CI")
    if (workflow.get("permissions") or {}).get("contents") != "read":
        errors.append(f"{label}: must stay read-only")
    if (workflow.get("concurrency") or {}).get("cancel-in-progress") is not True:
        errors.append(f"{label}: superseded CI runs must be cancelled")

    jobs = _jobs(workflow)
    for name in REQUIRED_CI_JOBS:
        if name not in jobs:
            errors.append(f"{label}: missing required job {name!r}")

    combined = "\n".join(script for _, script in _run_scripts(workflow))
    for token, message in (
        ("ruff check", "ruff must gate every push"),
        ("pytest", "the Python suite must gate every push"),
        ("cargo fmt --all -- --check", "Rust formatting must gate every push"),
        ("cargo clippy", "clippy must gate every push"),
        ("cargo test", "the Rust suite must gate every push"),
        ("--target wasm32-unknown-unknown", "the browser core must keep building for wasm32"),
        ("npm test", "the JavaScript suite must gate every push"),
        ("tools/audit_repository.py", "the repository audit must gate every push"),
        ("tools/validate_release_version.py", "version divergence must be caught before tagging"),
        ("tools/validate_tauri_config.py", "the Tauri config must be validated before tagging"),
        ("tools/validate_desktop_release.py", "the desktop release contracts must gate every push"),
        ("tools/validate_workflows.py", "the workflows must validate themselves"),
        ("test-windows-installer-verifier.ps1", "the Windows verifier contracts must run on Windows"),
    ):
        if token not in combined:
            errors.append(f"{label}: {message} (missing {token!r})")

    if "--skip-cleanliness" in combined:
        errors.append(
            f"{label}: repository cleanliness must not be skipped; the check is git-aware and is "
            "the only automated guard against committed .DS_Store and build artifacts"
        )


def validate_workflows(root: Path) -> list[str]:
    errors: list[str] = []
    for relative in (DESKTOP_WORKFLOW, CI_WORKFLOW):
        if not (root / relative).is_file():
            errors.append(f"missing workflow: {relative}")
    if errors:
        return errors

    desktop = _load(root / DESKTOP_WORKFLOW)
    ci = _load(root / CI_WORKFLOW)
    for label, workflow in (("desktop-release", desktop), ("ci", ci)):
        _check_pinned_actions(workflow, label, errors)
        _check_referenced_paths(root, workflow, label, errors)
        _check_timeouts(workflow, label, errors)
        _check_checkout_lfs(workflow, label, errors)
        _check_version_pins(root, workflow, label, errors)
        _check_locked_cargo(workflow, label, errors)
    _validate_desktop(root, desktop, errors)
    _validate_ci(root, ci, errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    arguments = parser.parse_args()
    root = arguments.root.resolve()
    try:
        errors = validate_workflows(root)
    except (OSError, ValueError, KeyError, yaml.YAMLError, tomllib.TOMLDecodeError) as exc:
        print(f"Workflow structure: FAIL\n{exc}", file=sys.stderr)
        return 1
    if errors:
        print("Workflow structure: FAIL", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Workflow structure: PASS (job graph, matrix, pins, and release wiring verified)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
