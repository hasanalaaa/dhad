from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_optimizer(root: Path):
    path = root / "tools" / "optimize_onnx_assets.py"
    spec = importlib.util.spec_from_file_location("dhad_optimize_onnx_assets", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_onnx_discovery_excludes_build_venv(tmp_path: Path) -> None:
    project_model = tmp_path / "web_demo" / "models" / "model.onnx"
    venv_model = tmp_path / ".desktop-build" / "venv" / "lib" / "site-packages" / "onnx" / "fixture.onnx"
    node_model = tmp_path / "web_demo" / "node_modules" / "pkg" / "fixture.onnx"
    for path in (project_model, venv_model, node_model):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"onnx")

    repository_root = Path(__file__).resolve().parents[1]
    optimizer = _load_optimizer(repository_root)
    discovered = optimizer.discover_models(tmp_path.resolve())

    assert discovered == [project_model.resolve()]


def test_release_pipeline_declares_desktop_build_exclusions() -> None:
    root = Path(__file__).resolve().parents[1]
    assert '".desktop-build"' in (root / "tools" / "package_release.py").read_text(encoding="utf-8")
    assert ".desktop-build/" in (root / ".gitignore").read_text(encoding="utf-8")
    assert ".desktop-build/" in (root / ".tauriignore").read_text(encoding="utf-8")


def test_workflow_contains_pinned_release_contracts() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "desktop-release.yml").read_text(encoding="utf-8")
    for token in (
        'TAURI_CLI_VERSION: "2.11.5"',
        "dtolnay/rust-toolchain@1.97.1",
        "verify-macos-app.sh",
        "APPLE_SIGNING_IDENTITY",
    ):
        assert token in workflow


def test_repository_cleaner_removes_macos_and_python_artifacts(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    cleaner_path = root / "tools" / "clean_repository.py"
    spec = importlib.util.spec_from_file_location("dhad_clean_repository", cleaner_path)
    assert spec and spec.loader
    cleaner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cleaner)

    artifacts = [
        tmp_path / ".DS_Store",
        tmp_path / "docs" / "._README.md",
        tmp_path / "tools" / "__pycache__" / "module.pyc",
        tmp_path / ".pytest_cache" / "CACHEDIR.TAG",
    ]
    for path in artifacts:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"generated")

    protected = tmp_path / ".desktop-build" / "venv" / ".DS_Store"
    protected.parent.mkdir(parents=True, exist_ok=True)
    protected.write_bytes(b"venv")

    removed = cleaner.clean(tmp_path)
    assert removed
    assert all(not path.exists() for path in artifacts)
    assert protected.exists(), "the isolated build environment must not be traversed or damaged"


def test_desktop_build_environment_pins_yaml_and_runs_full_audit() -> None:
    root = Path(__file__).resolve().parents[1]
    requirements = (root / "tools" / "desktop-build-requirements.txt").read_text(encoding="utf-8").splitlines()
    build_script = (root / "scripts" / "build-desktop.sh").read_text(encoding="utf-8")
    validator = (root / "tools" / "validate_desktop_release.py").read_text(encoding="utf-8")

    assert requirements == ["onnx==1.22.0", "PyYAML==6.0.3"]
    assert "tools/clean_repository.py" in build_script
    assert "tools/audit_repository.py" in build_script
    assert "if args.write_reports or True" not in validator


def test_macos_installer_uses_supported_bundle_verifier_cli() -> None:
    root = Path(__file__).resolve().parents[1]
    installer = root / "scripts" / "install-macos-app.sh"
    text = installer.read_text(encoding="utf-8")

    assert installer.stat().st_mode & 0o111
    assert 'tools/verify_macos_bundle.py --app "$APP_PATH"' in text
    assert "--skip-launch" not in text
    assert "/Applications/Dhad.app" in text


def test_release_packager_preserves_new_release_tools() -> None:
    root = Path(__file__).resolve().parents[1]
    packager = (root / "tools" / "package_release.py").read_text(encoding="utf-8")
    for path in (
        "dhad/scripts/install-macos-app.sh",
        "dhad/tools/clean_repository.py",
    ):
        assert path in packager

def test_sovereign_cleanliness_ignores_git_metadata(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    validator_path = root / "tools" / "validate_sovereign_release.py"
    spec = importlib.util.spec_from_file_location("dhad_validate_sovereign_release", validator_path)
    assert spec and spec.loader
    validator = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = validator
    tools_path = str(root / "tools")
    sys.path.insert(0, tools_path)
    try:
        spec.loader.exec_module(validator)
    finally:
        sys.path.remove(tools_path)

    # Minimal required project files are copied from the repository so only cleanliness is under test.
    for relative in (
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
        "src-tauri/src/lib.rs",
        "tools/run_sovereign_validation_matrix.py",
        "tools/validate_tauri_config.py",
        "tools/clean_repository.py",
        "tools/package_release.py",
        "tools/verify_macos_bundle.py",
        "scripts/verify-macos-app.sh",
        "scripts/install-macos-app.sh",
        "web_demo/mini-assistant.css",
        "web_demo/mini-assistant.js",
        "web_demo/mini-assistant.html",
        "web_demo/ui/mini-assistant-runtime.test.mjs",
    ):
        source = root / relative
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())

    git_ds_store = tmp_path / ".git" / ".DS_Store"
    git_ds_store.parent.mkdir(parents=True, exist_ok=True)
    git_ds_store.write_bytes(b"finder metadata")

    checks = validator.validate(tmp_path, include_cleanliness=True)
    cleanliness = next(item for item in checks if item.name == "clean:generated-artifacts")
    assert cleanliness.passed, cleanliness.detail

