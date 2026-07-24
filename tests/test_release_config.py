"""Release configuration must derive the package version from one source."""

import json
from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_container_install_does_not_pin_a_stale_package_version():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "dhad[server,production]==" not in dockerfile
    assert "image: dhad:local" in (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "version" in project["project"]["dynamic"]
    assert project["tool"]["hatch"]["version"]["path"] == "src/dhad/__init__.py"


def test_release_manifest_tracks_the_single_python_version_source():
    namespace: dict[str, str] = {}
    source = (ROOT / "src" / "dhad" / "__init__.py").read_text(encoding="utf-8")
    version_line = next(line for line in source.splitlines() if line.startswith("__version__ ="))
    exec(version_line, namespace)
    manifest = json.loads((ROOT / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))

    assert manifest["python_version"] == namespace["__version__"]


def test_release_configuration_contains_no_obsolete_version():
    for relative_path in ("Dockerfile", "docker-compose.yml"):
        assert "0.13.0" not in (ROOT / relative_path).read_text(encoding="utf-8")


def test_production_uses_the_supported_standalone_uvicorn_worker():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    production = project["project"]["optional-dependencies"]["production"]
    gunicorn = (ROOT / "gunicorn_conf.py").read_text(encoding="utf-8")

    assert any(item.startswith("uvicorn-worker") for item in production)
    assert 'worker_class = "uvicorn_worker.UvicornWorker"' in gunicorn


def test_tauri_2_11_configuration_is_strict_and_regression_safe():
    from copy import deepcopy

    from tools.validate_tauri_config import validate_tauri_config

    config = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    assert validate_tauri_config(config) == []

    mutations = []
    window_key = deepcopy(config)
    window_key["app"]["windows"][0]["noRedirectionBitmap"] = True
    mutations.append(window_key)

    security_key = deepcopy(config)
    security_key["app"]["security"]["headers"] = {"X-Test": "1"}
    mutations.append(security_key)

    bundle_key = deepcopy(config)
    bundle_key["bundle"]["windows"]["bundleVCRuntime"] = True
    mutations.append(bundle_key)

    for invalid in mutations:
        assert validate_tauri_config(invalid), invalid


def test_desktop_release_workflow_is_preserved_as_a_hidden_path():
    workflow = ROOT / ".github" / "workflows" / "desktop-release.yml"
    assert workflow.is_file()
    assert workflow.stat().st_size > 0
    text = workflow.read_text(encoding="utf-8")
    for contract in (
        "macos-15", "macos-15-intel", "windows-2025",
        "aarch64-apple-darwin", "x86_64-apple-darwin", "nsis,msi",
        "tools/desktop-build-requirements.txt", "tools/optimize_onnx_assets.py",
        "tools/validate_tauri_config.py", "tools/validate_desktop_release.py",
        "cargo test", "npm test", "tauri-apps/tauri-action@v1",
        'TAURI_CLI_VERSION: "2.11.4"',
    ):
        assert contract in text


def test_desktop_build_environment_is_ignored_and_never_packaged():
    from tools.package_release import EXCLUDED_DIRS

    assert ".desktop-build" in EXCLUDED_DIRS
    assert ".desktop-build/" in (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".desktop-build/" in (ROOT / ".tauriignore").read_text(encoding="utf-8")
