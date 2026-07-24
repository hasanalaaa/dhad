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
