#!/usr/bin/env python3
"""Validate security, native UX and cleanliness contracts for Dhad Sovereign Edition."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    from .validate_tauri_config import PROFILE as TAURI_SCHEMA_PROFILE, validate_tauri_config
except ImportError:  # Direct script execution from tools/.
    from validate_tauri_config import PROFILE as TAURI_SCHEMA_PROFILE, validate_tauri_config


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def check_contains(name: str, text: str, needle: str) -> Check:
    return Check(name, needle in text, f"requires {needle!r}")


def validate(root: Path, *, include_cleanliness: bool = True) -> list[Check]:
    checks: list[Check] = []
    required = [
        "README.md",
        "docs/assets/dhad-sovereign-hero.svg",
        "docs/MASTER_TRANSFORMATION_SPEC.md",
        "src-tauri/tauri.conf.json",
        "src-tauri/Info.plist",
        "src-tauri/Entitlements.plist",
        "src-tauri/capabilities/default.json",
        "src-tauri/capabilities/mini-assistant.json",
        "src-tauri/src/file_commands.rs",
        "src-tauri/src/native_commands.rs",
        "src-tauri/src/tray.rs",
        "tools/run_sovereign_validation_matrix.py",
        "tools/validate_tauri_config.py",
        "tools/clean_repository.py",
        "tools/package_release.py",
        "tools/verify_macos_bundle.py",
        "scripts/verify-macos-app.sh",
        "scripts/install-macos-app.sh",
        "web_demo/mini-assistant.css",
        "web_demo/mini-assistant.js",
        "web_demo/ui/mini-assistant-runtime.test.mjs",
    ]
    for relative in required:
        checks.append(Check(f"required:{relative}", (root / relative).is_file(), "release file exists"))

    config = read_json(root / "src-tauri/tauri.conf.json")
    security = config.get("app", {}).get("security", {})
    csp = security.get("csp")
    schema_errors = validate_tauri_config(config)
    checks.extend(
        [
            Check("security:csp-enabled", isinstance(csp, dict) and bool(csp), "explicit CSP object"),
            Check("security:freeze-prototype", security.get("freezePrototype") is True, "Object.prototype frozen"),
            Check("security:frame-ancestors", isinstance(csp, dict) and csp.get("frame-ancestors") == "'none'", "frame embedding denied"),
            Check("security:object-src", isinstance(csp, dict) and csp.get("object-src") == "'none'", "plugin/object loading denied"),
            Check("security:wasm", isinstance(csp, dict) and "'wasm-unsafe-eval'" in csp.get("script-src", ""), "WASM allowed explicitly"),
            Check("tauri:schema-2.11-compatible", not schema_errors, "; ".join(schema_errors[:5]) or TAURI_SCHEMA_PROFILE),
            Check("tauri:no-custom-headers", "headers" not in security, "unsupported app.security.headers removed"),
            Check("tauri:no-no-redirection-bitmap", all("noRedirectionBitmap" not in item for item in config.get("app", {}).get("windows", []) if isinstance(item, dict)), "unsupported window key removed"),
            Check("tauri:no-bundle-vc-runtime", "bundleVCRuntime" not in config.get("bundle", {}).get("windows", {}), "unsupported Windows bundle key removed"),
            Check("windows:no-downgrade", config.get("bundle", {}).get("windows", {}).get("allowDowngrades") is False, "installer downgrade protection"),
        ]
    )

    windows = {item.get("label"): item for item in config.get("app", {}).get("windows", [])}
    mini = windows.get("mini-assistant", {})
    configured_effects = mini.get("windowEffects")
    checks.extend(
        [
            Check("mini:transparent", mini.get("transparent") is True, "transparent native window"),
            Check("mini:always-on-top", mini.get("alwaysOnTop") is True, "floating overlay"),
            Check("mini:focusable", mini.get("focusable") is True, "keyboard input"),
            Check("mini:no-cross-platform-static-effects", configured_effects is None, "platform effects are applied in target-guarded Rust code"),
            Check("mini:zoom-disabled", mini.get("zoomHotkeysEnabled") is False, "stable overlay scale"),
        ]
    )

    main_cap = read_json(root / "src-tauri/capabilities/default.json")
    mini_cap = read_json(root / "src-tauri/capabilities/mini-assistant.json")
    checks.extend(
        [
            Check("capabilities:main-only", main_cap.get("windows") == ["main"], "editor capability is isolated"),
            Check("capabilities:mini-only", mini_cap.get("windows") == ["mini-assistant"], "overlay capability is isolated"),
            Check("capabilities:mini-no-dialog", "dialog:default" not in mini_cap.get("permissions", []), "overlay does not receive file-dialog permissions"),
            Check("capabilities:local", main_cap.get("local") is True and mini_cap.get("local") is True, "capabilities reject remote origins"),
        ]
    )

    native = (root / "src-tauri/src/native_commands.rs").read_text(encoding="utf-8")
    files = (root / "src-tauri/src/file_commands.rs").read_text(encoding="utf-8")
    lib = (root / "src-tauri/src/lib.rs").read_text(encoding="utf-8")
    tray = (root / "src-tauri/src/tray.rs").read_text(encoding="utf-8")
    checks.extend(
        [
            check_contains("native:analysis-worker", native, "spawn_blocking(move || analyze_text_native_blocking"),
            check_contains("native:rewrite-worker", native, "spawn_blocking(move || paraphrase_native_blocking"),
            check_contains("files:create-new-temp", files, ".create_new(true)"),
            check_contains("files:sync-before-commit", files, "file.sync_all()"),
            check_contains("files:commit-rename", files, "fs::rename(temp_path, destination)"),
            check_contains("files:windows-rollback", files, "rollback.bak"),
            check_contains("files:windows-restore", files, "fs::rename(backup_path, destination)"),
            check_contains("native:mac-hud-material", lib, "Effect::HudWindow"),
            check_contains("native:windows-mica", lib, "Effect::Mica"),
            check_contains("native:effects-nonfatal", lib, "failed to apply platform window effects"),
            check_contains("shortcut:fallback", lib, "Modifiers::CONTROL | Modifiers::ALT"),
            check_contains("overlay:recenter", tray, "window.center()"),
            check_contains("overlay:restore-topmost", tray, "set_always_on_top(true)"),
        ]
    )

    html = (root / "web_demo/mini-assistant.html").read_text(encoding="utf-8")
    css = (root / "web_demo/mini-assistant.css").read_text(encoding="utf-8")
    js = (root / "web_demo/mini-assistant.js").read_text(encoding="utf-8")
    checks.extend(
        [
            check_contains("ui:character-count", html, 'id="characterCount"'),
            check_contains("ui:performance-status", html, 'id="performanceStatus"'),
            check_contains("ui:reduced-motion", css, "prefers-reduced-motion"),
            check_contains("ui:high-contrast", css, "prefers-contrast: more"),
            check_contains("ui:ime-aware", js, "compositionstart"),
            check_contains("ui:composited-focus", js, "requestAnimationFrame(() => requestAnimationFrame"),
            check_contains("ui:mini-shell-binding", js, 'const miniShell = document.querySelector(".mini-shell")'),
            check_contains("ui:character-count-binding", js, 'const characterCount = $("characterCount")'),
            check_contains("ui:performance-binding", js, 'const performanceStatus = $("performanceStatus")'),
            check_contains("ui:autohide-timer", js, "let autoHideTimer = 0"),
            check_contains("ui:composition-state", js, "let isComposing = false"),
            check_contains("ui:overlay-positioning", css, "position: relative"),
        ]
    )

    readme = (root / "README.md").read_text(encoding="utf-8")
    for marker in ["Product positioning", "Architecture", "Privacy boundary", "Desktop builds", "Verification"]:
        checks.append(check_contains(f"readme:{marker.lower().replace(' ', '-')}", readme, f"## {marker}"))

    if include_cleanliness:
        ignored_transient_names = {
            ".git",
            ".desktop-build",
            ".audit-venv",
            ".ci-venv",
            ".venv",
            "venv",
            "node_modules",
            "target",
            "web_dist",
        }
        forbidden_names = {".pytest_cache", "__pycache__", ".ruff_cache", ".mypy_cache"}
        forbidden_suffixes = {".log", ".tmp", ".temp", ".bak", ".pyc", ".pyo"}
        violations: list[str] = []
        for path in root.rglob("*"):
            relative = path.relative_to(root)
            if any(part in ignored_transient_names for part in relative.parts):
                continue
            if any(part in forbidden_names for part in relative.parts):
                violations.append(relative.as_posix())
                continue
            if path.is_file() and (path.name in {".DS_Store", "Thumbs.db", "Desktop.ini"} or path.name.startswith("._") or path.suffix.lower() in forbidden_suffixes):
                violations.append(relative.as_posix())
        checks.append(Check("clean:generated-artifacts", not violations, ", ".join(violations[:10]) or "clean"))
    return checks


def write_report(root: Path, checks: list[Check]) -> None:
    report_dir = root / "reports"
    report_dir.mkdir(exist_ok=True)
    passed = sum(item.passed for item in checks)
    payload = {
        "release": "Dhad v1.0.0 Sovereign Edition",
        "summary": {"passed": passed, "total": len(checks), "errors": len(checks) - passed},
        "checks": [asdict(item) for item in checks],
    }
    (report_dir / "SOVEREIGN_VALIDATION.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Dhad Sovereign Release Validation",
        "",
        f"- Passed: **{passed}/{len(checks)}**",
        f"- Errors: **{len(checks) - passed}**",
        "",
        "## Checks",
        "",
    ]
    lines.extend(
        f"- {'PASS' if item.passed else 'FAIL'} — `{item.name}`: {item.detail}" for item in checks
    )
    (report_dir / "SOVEREIGN_VALIDATION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--skip-cleanliness", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    checks = validate(root, include_cleanliness=not args.skip_cleanliness)
    if args.write_report:
        write_report(root, checks)
    passed = sum(item.passed for item in checks)
    print(f"Sovereign release audit: {passed}/{len(checks)} checks passed.")
    for item in checks:
        if not item.passed:
            print(f"FAIL {item.name}: {item.detail}", file=sys.stderr)
    return 1 if args.strict and passed != len(checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
