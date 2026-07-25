"""Release configuration must derive the package version from one source."""

import json
import os
from pathlib import Path
import shutil
import subprocess
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

    unsafe_frontend = deepcopy(config)
    unsafe_frontend["build"]["frontendDist"] = "../web_demo"
    mutations.append(unsafe_frontend)

    for invalid in mutations:
        assert validate_tauri_config(invalid), invalid


def test_desktop_release_workflow_is_preserved_as_a_hidden_path():
    workflow = ROOT / ".github" / "workflows" / "desktop-release.yml"
    assert workflow.is_file()
    assert workflow.stat().st_size > 0
    text = workflow.read_text(encoding="utf-8")
    for contract in (
        "macos-15", "macos-15-intel", "windows-2022",
        "aarch64-apple-darwin", "x86_64-apple-darwin", "--bundles nsis", "--bundles msi",
        "tools/desktop-build-requirements.txt", "tools/optimize_onnx_assets.py",
        "tools/validate_tauri_config.py", "tools/validate_desktop_release.py",
        "tools/validate_release_version.py",
        "cargo test", "npm test", "tauri-apps/tauri-action@v1",
        'TAURI_CLI_VERSION: "2.11.4"',
        '@tauri-apps/cli@2.11.4', 'tauriScript: tauri',
        'tauri --version | grep -F "2.11.4"',
        'node tools/build_web_dist.mjs',
        'Stage dependency-free Tauri frontend',
        'releaseDraft: true', 'actions/github-script@v9',
        'uploadUpdaterJson: false', 'uploadUpdaterSignatures: false',
        'releaseAssetNamePattern: "Dhad_[version]_[platform]_[arch][setup][ext]"',
        'Verify VBSCRIPT support required by WiX MSI',
        'scripts/verify-windows-installer.ps1',
    ):
        assert contract in text


def test_tauri_frontend_dist_is_isolated_from_node_dependencies():
    config = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    build = config["build"]

    assert build["frontendDist"] == "../web_dist"
    assert build["beforeBuildCommand"] == {
        "script": "node tools/build_web_dist.mjs",
        "cwd": "..",
    }
    assert build["beforeDevCommand"] == {
        "script": "node tools/build_web_dist.mjs",
        "cwd": "..",
        "wait": True,
    }
    assert build["additionalWatchFolders"] == ["../web_demo"]
    staging_tool = (ROOT / "tools" / "build_web_dist.mjs").read_text(encoding="utf-8")
    assert '"node_modules"' in staging_tool
    assert '".test.mjs"' in staging_tool
    assert 'models/model_int8.onnx' in staging_tool
    assert 'const runtimeAssets = Object.freeze([' in staging_tool
    assert 'verifyModuleClosure' in staging_tool
    assert 'verifyIntegrityContracts' in staging_tool


def test_desktop_build_environment_is_ignored_and_never_packaged():
    from tools.package_release import EXCLUDED_DIRS

    assert ".desktop-build" in EXCLUDED_DIRS
    assert ".desktop-build/" in (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".desktop-build/" in (ROOT / ".tauriignore").read_text(encoding="utf-8")
    assert "web_dist" in EXCLUDED_DIRS
    assert "web_dist/" in (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "web_dist/" in (ROOT / ".tauriignore").read_text(encoding="utf-8")


def test_macos_bundle_identity_and_native_launch_contracts_are_pinned():
    import plistlib

    config = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    assert config["identifier"] == "com.dhad.desktop"
    assert config["mainBinaryName"] == "dhad-desktop"
    assert config["bundle"]["macOS"]["bundleName"] == "Dhad"
    assert config["bundle"]["macOS"]["infoPlist"] == "Info.plist"
    assert config["bundle"]["macOS"]["entitlements"] == "Entitlements.plist"
    assert all("windowEffects" not in window for window in config["app"]["windows"])

    with (ROOT / "src-tauri" / "Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    assert info["CFBundleDisplayName"] == "ضاد"
    for generated_key in (
        "CFBundleExecutable",
        "CFBundleIdentifier",
        "CFBundleShortVersionString",
        "CFBundleVersion",
        "LSMinimumSystemVersion",
    ):
        assert generated_key not in info

    library = (ROOT / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
    assert '#[cfg(target_os = "macos")]' in library
    assert "Effect::HudWindow" in library
    assert '#[cfg(target_os = "windows")]' in library
    assert "Effect::Mica" in library
    assert "failed to apply platform window effects" in library


def test_rust_unsafe_operations_are_explicit_for_rust_1_97():
    source = (ROOT / "rust" / "dhad-core-rs" / "src" / "wasm_api.rs").read_text(encoding="utf-8")
    assert "let token = unsafe { read_input(ptr, len) };" in source
    assert "let token = read_input(ptr, len);" not in source

    toolchain = tomllib.loads((ROOT / "rust-toolchain.toml").read_text(encoding="utf-8"))
    assert toolchain["toolchain"]["channel"] == "1.97.1"


def test_macos_bundle_verifier_and_ci_smoke_test_are_mandatory():
    verifier = ROOT / "tools" / "verify_macos_bundle.py"
    shell = ROOT / "scripts" / "verify-macos-app.sh"
    workflow = (ROOT / ".github" / "workflows" / "desktop-release.yml").read_text(encoding="utf-8")
    build_script = (ROOT / "scripts" / "build-desktop.sh").read_text(encoding="utf-8")

    assert verifier.is_file() and verifier.stat().st_size > 0
    assert shell.is_file() and shell.stat().st_mode & 0o111
    assert "Verify signed macOS app bundle and native launch" in workflow
    assert "DHAD_SKIP_MACOS_LAUNCH_SMOKE" in workflow
    assert "verify-macos-app.sh" in build_script
    shell_source = shell.read_text(encoding="utf-8")
    assert "hdiutil attach -readonly -nobrowse" in shell_source
    assert "generated DMG contains no macOS .app bundle" in shell_source
    assert "ditto" in shell_source


def test_windows_installers_are_split_and_use_native_tauri_shortcuts():
    workflow = (ROOT / ".github" / "workflows" / "desktop-release.yml").read_text(encoding="utf-8")
    verifier = (ROOT / "scripts" / "verify-windows-installer.ps1").read_text(encoding="utf-8")
    config = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    windows = config["bundle"]["windows"]

    assert "Windows x64 NSIS" in workflow
    assert "Windows x64 MSI" in workflow
    assert "windows-2022" in workflow
    assert "--bundles nsis" in workflow
    assert "--bundles msi" in workflow
    assert "VBSCRIPT smoke test: PASS" in workflow
    assert "verify-windows-installer.ps1" in workflow
    assert "MSI administrative extraction failed" in verifier
    assert "NSIS silent installation failed" in verifier
    assert "Get-DhadUninstallEntries" in verifier
    assert "CommonDesktopDirectory" in verifier
    assert "NSIS install, desktop shortcut, and uninstall lifecycle: PASS" in verifier
    assert "installerHooks" not in windows["nsis"]
    assert "fragmentPaths" not in windows["wix"]
    assert "componentRefs" not in windows["wix"]
    assert not (ROOT / "src-tauri" / "windows" / "nsis-hooks.nsh").exists()
    assert not (ROOT / "src-tauri" / "windows" / "desktop-shortcut.wxs").exists()



def test_macos_release_wrapper_verifies_the_app_shipped_inside_a_dmg(tmp_path):
    """Regression: Tauri removes bundle/macos/*.app after creating a DMG."""

    bash = shutil.which("bash")
    if not bash:
        return

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    arguments_log = tmp_path / "python-arguments.txt"
    dmg = tmp_path / "Dhad_1.0.17_aarch64.dmg"
    dmg.write_bytes(b"synthetic-dmg")

    scripts = {
        "uname": """#!/usr/bin/env bash
case "${1:-}" in
  -s) printf 'Darwin\\n' ;;
  -m) printf 'arm64\\n' ;;
  *) printf 'Darwin\\n' ;;
esac
""",
        "hdiutil": """#!/usr/bin/env bash
set -e
if [[ "${1:-}" == "attach" ]]; then
  mount=''
  while (($#)); do
    if [[ "$1" == "-mountpoint" ]]; then mount="$2"; shift 2; continue; fi
    shift
  done
  mkdir -p "$mount/ضاد.app/Contents/MacOS"
fi
""",
        "ditto": """#!/usr/bin/env bash
set -e
cp -R "$1" "$2"
""",
        "python3": f"""#!/usr/bin/env bash
printf '%s\\n' "$*" > {arguments_log!s}
""",
    }
    for name, source in scripts.items():
        path = fake_bin / name
        path.write_text(source, encoding="utf-8")
        path.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "DHAD_MACOS_DMG_PATH": str(dmg),
            "DHAD_EXPECTED_MACOS_ARCH": "aarch64",
            "DHAD_SKIP_MACOS_LAUNCH_SMOKE": "1",
        }
    )
    result = subprocess.run(
        [bash, "scripts/verify-macos-app.sh"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert "Mounting generated DMG for verification" in result.stdout
    arguments = arguments_log.read_text(encoding="utf-8")
    assert "tools/verify_macos_bundle.py" in arguments
    assert "--expected-arch aarch64" in arguments
