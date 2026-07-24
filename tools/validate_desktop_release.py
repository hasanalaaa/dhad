#!/usr/bin/env python3
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import plistlib
import re
import struct
import sys
import tomllib
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

try:
    from .validate_tauri_config import PROFILE as TAURI_SCHEMA_PROFILE, validate_tauri_config
except ImportError:
    from validate_tauri_config import PROFILE as TAURI_SCHEMA_PROFILE, validate_tauri_config


def _has_ignore_rule(text: str, directory: str) -> bool:
    expected = {directory, directory.rstrip('/') + '/', '/' + directory.rstrip('/') + '/'}
    rules = {line.strip() for line in text.splitlines() if line.strip() and (not line.lstrip().startswith('#'))}
    return bool(expected & rules)


def _read_literal_string_set(path: Path, variable: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any((isinstance(target, ast.Name) and target.id == variable for target in targets)):
                value = ast.literal_eval(node.value)
                if isinstance(value, (set, list, tuple)) and all((isinstance(item, str) for item in value)):
                    return set(value)
    return set()


def _workflow_contract(text: str, pattern: str) -> bool:
    return re.search(pattern, text, flags=re.MULTILINE) is not None


def image_size(path: Path):
    data = path.read_bytes()
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return struct.unpack('>II', data[16:24])
    if data.startswith(b'BM'):
        return struct.unpack('<ii', data[18:26])
    if data[:4] == b'\x00\x00\x01\x00':
        count = struct.unpack('<H', data[4:6])[0]
        sizes = []
        for i in range(count):
            w, h = (data[6 + i * 16], data[7 + i * 16])
            sizes.append((256 if w == 0 else w, 256 if h == 0 else h))
        return sorted(set(sizes))
    return None


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='.')
    ap.add_argument('--strict', action='store_true')
    ap.add_argument('--write-reports', action='store_true')
    args = ap.parse_args()
    root = Path(args.root).resolve()
    errors = []
    warnings = []
    checks = []

    def ok(name, cond, detail=''):
        checks.append({'name': name, 'ok': bool(cond), 'detail': detail})
        if not cond:
            errors.append(f'{name}: {detail}')
    required = ['src-tauri/tauri.conf.json', 'src-tauri/icons/128x128.png', 'src-tauri/icons/128x128@2x.png', 'src-tauri/icons/icon.icns', 'src-tauri/icons/icon.ico', 'src-tauri/dmg/background.png', 'src-tauri/windows/nsis-hooks.nsh', 'src-tauri/windows/desktop-shortcut.wxs', 'src-tauri/windows/nsis-header.bmp', 'src-tauri/windows/nsis-sidebar.bmp', 'src-tauri/windows/wix-banner.bmp', 'src-tauri/windows/wix-dialog.bmp', 'scripts/build-desktop.sh', 'scripts/build-desktop.bat', '.github/workflows/desktop-release.yml', '.github/workflows/ci.yml', '.nvmrc', 'docs/index.html', 'tools/optimize_onnx_assets.py', 'tools/validate_desktop_release.py', 'tools/validate_tauri_config.py', 'tools/validate_release_version.py', 'tools/package_release.py', 'tools/desktop-build-requirements.txt', 'tools/generate_release_inventory.py', 'tools/verify_macos_bundle.py', 'scripts/verify-macos-app.sh', 'scripts/install-macos-app.sh', 'tools/clean_repository.py', 'tools/build_web_dist.mjs', 'src-tauri/Info.plist', 'src-tauri/Entitlements.plist', 'vercel.json', 'docs/.nojekyll']
    for rel in required:
        path = root / rel
        present = path.is_file() and (rel != '.github/workflows/desktop-release.yml' or path.stat().st_size > 0)
        ok(f'required:{rel}', present, 'missing or empty required release file')
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    cfg = json.loads((root / 'src-tauri/tauri.conf.json').read_text(encoding='utf-8'))
    ok('identifier', cfg.get('identifier') == 'com.dhad.desktop', str(cfg.get('identifier')))
    ok('identifier-no-app-suffix', not str(cfg.get('identifier', '')).lower().endswith('.app'), str(cfg.get('identifier')))
    ok('main-binary-name', cfg.get('mainBinaryName') == 'dhad-desktop', str(cfg.get('mainBinaryName')))
    build = cfg.get('build', {})
    ok('frontend-dist-isolated', build.get('frontendDist') == '../web_dist', str(build.get('frontendDist')))
    ok('frontend-dist-build-hook', build.get('beforeBuildCommand') == {'script': 'node tools/build_web_dist.mjs', 'cwd': '..'}, str(build.get('beforeBuildCommand')))
    ok('frontend-dist-dev-hook', build.get('beforeDevCommand') == {'script': 'node tools/build_web_dist.mjs', 'cwd': '..', 'wait': True}, str(build.get('beforeDevCommand')))
    ok('frontend-source-watch-folder', build.get('additionalWatchFolders') == ['../web_demo'], str(build.get('additionalWatchFolders')))
    schema_errors = validate_tauri_config(cfg)
    ok('tauri-schema-2.11-compatible', not schema_errors, '; '.join(schema_errors[:10]) or TAURI_SCHEMA_PROFILE)
    security = cfg.get('app', {}).get('security', {})
    app_windows = cfg.get('app', {}).get('windows', [])
    ok('tauri-no-security-headers', 'headers' not in security, 'app.security.headers is unsupported by the pinned CLI')
    ok('tauri-no-no-redirection-bitmap', all(('noRedirectionBitmap' not in item for item in app_windows if isinstance(item, dict))), 'unsupported app.windows key')
    ok('tauri-no-bundle-vc-runtime', 'bundleVCRuntime' not in cfg.get('bundle', {}).get('windows', {}), 'unsupported bundle.windows key')
    bundle = cfg.get('bundle', {})
    mac = bundle.get('macOS', {})
    windows = bundle.get('windows', {})
    dmg = mac.get('dmg', {})
    nsis = windows.get('nsis', {})
    wix = windows.get('wix', {})
    ok('macos-bundle-name-ascii-safe', mac.get('bundleName') == 'Dhad', str(mac.get('bundleName')))
    ok('macos-info-plist-configured', mac.get('infoPlist') == 'Info.plist', str(mac.get('infoPlist')))
    ok('macos-entitlements-configured', mac.get('entitlements') == 'Entitlements.plist', str(mac.get('entitlements')))
    ok('macos-hardened-runtime', mac.get('hardenedRuntime') is True, str(mac.get('hardenedRuntime')))
    ok('dmg-background-configured', dmg.get('background') == 'dmg/background.png', str(dmg))
    ok('dmg-drag-layout', dmg.get('appPosition') and dmg.get('applicationFolderPosition'), str(dmg))
    ok('nsis-hooks-configured', nsis.get('installerHooks') == 'windows/nsis-hooks.nsh', str(nsis))
    ok('nsis-installer-icon', nsis.get('installerIcon') == 'icons/icon.ico', str(nsis.get('installerIcon')))
    ok('nsis-uninstaller-icon', nsis.get('uninstallerIcon') == 'icons/icon.ico', str(nsis.get('uninstallerIcon')))
    ok('wix-fragment-configured', 'windows/desktop-shortcut.wxs' in wix.get('fragmentPaths', []), str(wix))
    ok('wix-upgrade-code-pinned', bool(wix.get('upgradeCode')), str(wix.get('upgradeCode')))
    expected = {'src-tauri/icons/128x128.png': (128, 128), 'src-tauri/icons/128x128@2x.png': (256, 256), 'src-tauri/dmg/background.png': (660, 400), 'src-tauri/windows/nsis-header.bmp': (150, 57), 'src-tauri/windows/nsis-sidebar.bmp': (164, 314), 'src-tauri/windows/wix-banner.bmp': (493, 58), 'src-tauri/windows/wix-dialog.bmp': (493, 312)}
    for rel, size in expected.items():
        ok(f'dimensions:{rel}', image_size(root / rel) == size, f'expected {size}, got {image_size(root / rel)}')
    ico_sizes = image_size(root / 'src-tauri/icons/icon.ico')
    ok('ico-multi-resolution', isinstance(ico_sizes, list) and {(16, 16), (32, 32), (48, 48), (256, 256)}.issubset(set(ico_sizes)), str(ico_sizes))
    with (root / 'src-tauri/Info.plist').open('rb') as stream:
        info_plist = plistlib.load(stream)
    with (root / 'src-tauri/Entitlements.plist').open('rb') as stream:
        entitlements = plistlib.load(stream)
    ok('info-plist-display-name', info_plist.get('CFBundleDisplayName') == 'ضاد', str(info_plist.get('CFBundleDisplayName')))
    generated_keys = {'CFBundleExecutable', 'CFBundleIdentifier', 'CFBundleShortVersionString', 'CFBundleVersion', 'LSMinimumSystemVersion'}
    ok('info-plist-does-not-override-generated-identity', not generated_keys.intersection(info_plist), str(sorted(generated_keys.intersection(info_plist))))
    ok('entitlements-minimal-dictionary', isinstance(entitlements, dict) and (not entitlements), str(entitlements))
    ET.parse(root / 'src-tauri/windows/desktop-shortcut.wxs')
    hooks = (root / 'src-tauri/windows/nsis-hooks.nsh').read_text(encoding='utf-8')
    ok('nsis-create-shortcut', 'CreateShortCut' in hooks and '$DESKTOP' in hooks, '')
    ok('nsis-delete-shortcut', 'Delete "$DESKTOP' in hooks, '')
    workflow = (root / '.github/workflows/desktop-release.yml').read_text(encoding='utf-8')
    for token in ['macos-15', 'macos-15-intel', 'windows-2025', 'aarch64-apple-darwin', 'x86_64-apple-darwin', 'nsis,msi', 'tauri-apps/tauri-action@v1']:
        ok(f'workflow:{token}', token in workflow, 'missing workflow contract')
    workflow_contracts = [
        ("v*.*.*", r'["\']v\*\.\*\.\*["\']'),
        ("libwebkit2gtk-4.1-dev", r"\blibwebkit2gtk-4\.1-dev\b"),
        ("libayatana-appindicator3-dev", r"\blibayatana-appindicator3-dev\b"),
        ("build-essential", r"\bbuild-essential\b"),
        ("libxdo-dev", r"\blibxdo-dev\b"),
        ("libssl-dev", r"\blibssl-dev\b"),
        ("tools/desktop-build-requirements.txt", r"tools/desktop-build-requirements\.txt"),
        ("tools/optimize_onnx_assets.py", r"tools/optimize_onnx_assets\.py"),
        ("tools/validate_tauri_config.py", r"tools/validate_tauri_config\.py"),
        ("tools/validate_desktop_release.py", r"tools/validate_desktop_release\.py"),
        ("tools/validate_release_version.py", r"tools/validate_release_version\.py"),
        ("tools/build_web_dist.mjs", r"tools/build_web_dist\.mjs"),
        ("Stage dependency-free Tauri frontend", r"Stage dependency-free Tauri frontend"),
        (
            'TAURI_CLI_VERSION: "2.11.4"',
            r'^\s*TAURI_CLI_VERSION\s*:\s*["\']?2\.11\.4["\']?\s*$',
        ),
        ("@tauri-apps/cli@2.11.4", r"@tauri-apps/cli@2\.11\.4"),
        ("tauriScript: tauri", r"^\s*tauriScript\s*:\s*tauri\s*$"),
        ("dtolnay/rust-toolchain@1.97.1", r"uses\s*:\s*dtolnay/rust-toolchain@1\.97\.1\b"),
        ("cargo test", r"\bcargo\s+test\b"),
        ("npm test", r"\bnpm\s+test\b"),
        ("verify-macos-app.sh", r"(?:^|[\s./])verify-macos-app\.sh\b"),
        ("APPLE_SIGNING_IDENTITY", r"\bAPPLE_SIGNING_IDENTITY\b"),
        ("actions/setup-node@v6", r"actions/setup-node@v6\b"),
        ("actions/github-script@v9", r"actions/github-script@v9\b"),
        ("releaseDraft: true", r"^\s*releaseDraft\s*:\s*true\s*$"),
        ("uploadUpdaterJson: false", r"^\s*uploadUpdaterJson\s*:\s*false\s*$"),
        ("uploadUpdaterSignatures: false", r"^\s*uploadUpdaterSignatures\s*:\s*false\s*$"),
        ("uploadWorkflowArtifacts: true", r"^\s*uploadWorkflowArtifacts\s*:\s*true\s*$"),
        ("atomic publish job", r"Verify assets and publish release atomically"),
        ("updateRelease", r"github\.rest\.repos\.updateRelease"),
        ("locked Rust release checks", r"cargo\s+(?:clippy|test|build)[^\n]*--locked"),
    ]
    for label, pattern in workflow_contracts:
        ok(f'workflow-validation:{label}', _workflow_contract(workflow, pattern), f'missing workflow contract matching {pattern}')
    ci_workflow = (root / '.github/workflows/ci.yml').read_text(encoding='utf-8')
    ci_contracts = {
        'rust-toolchain-pinned': 'dtolnay/rust-toolchain@1.97.1',
        'pythonpath-root-and-src': 'PYTHONPATH: ".:src"',
        'node-22': 'node-version: "22"',
        'ruff-check': 'ruff check src tests tools benchmarks gunicorn_conf.py',
        'pytest': 'pytest -q',
        'npm-test': 'npm test',
        'repository-audit-pyyaml': 'PyYAML==6.0.3',
        'rust-frontend-staging': 'Stage dependency-free Tauri frontend for Rust build scripts',
        'web-staging-root': 'working-directory: .',
        'setup-node-v6': 'actions/setup-node@v6',
        'release-version-validator': 'python tools/validate_release_version.py --root .',
        'locked-rust-checks': '--all-targets --locked',
    }
    for label, token in ci_contracts.items():
        ok(f'ci:{label}', token in ci_workflow, f'missing CI contract: {token}')
    ok('node-version-file', (root / '.nvmrc').read_text(encoding='utf-8').strip() == '22', 'local Node must match CI Node 22')
    landing = (root / 'docs/index.html').read_text(encoding='utf-8')
    for token in ['id="downloads"', 'الخصوصية', 'data-download', 'data-live-demo', 'dhad-demo-url', 'web_demo', 'privacy-diagram']:
        ok(f'landing:{token}', token in landing, 'missing landing-page section')
    sh = (root / 'scripts/build-desktop.sh').read_text(encoding='utf-8')
    bat = (root / 'scripts/build-desktop.bat').read_text(encoding='utf-8')
    for label, text in [('sh', sh), ('bat', bat)]:
        for token in ['desktop-release.yml', 'validate_tauri_config.py', 'desktop-build-requirements.txt', 'optimize_onnx_assets.py', 'validate_desktop_release.py', 'validate_release_version.py', 'build_web_dist.mjs', '2.11.4', 'cargo clippy', '--locked', 'tauri build']:
            ok(f'build-{label}:{token}', token in text, 'missing build stage')
    ok('build-sh:macos-bundle-verification', 'verify-macos-app.sh' in sh, 'macOS build must verify and launch-smoke the generated app')
    excluded_scan_parts = {'.git', 'target', 'node_modules', '.desktop-build', '.audit-venv', '.ci-venv', '.venv', 'venv', '__pycache__', '.pytest_cache', '.ruff_cache', '.mypy_cache', 'web_dist'}
    files = [p for p in root.rglob('*') if p.is_file() and (not any((part in excluded_scan_parts for part in p.relative_to(root).parts)))]
    intentional_zero = {'docs/.nojekyll', 'tools/__init__.py', 'src/dhad/py.typed'}
    zero = [p.relative_to(root).as_posix() for p in files if p.stat().st_size == 0 and p.relative_to(root).as_posix() not in intentional_zero]
    if zero:
        warnings.append(f'unexpected zero-byte files: {zero}')
    broken = [p.relative_to(root).as_posix() for p in root.rglob('*') if not any((part in excluded_scan_parts for part in p.relative_to(root).parts)) and p.is_symlink() and (not p.exists())]
    ok('no-broken-symlinks', not broken, str(broken))
    folded = {}
    collisions = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        key = rel.casefold()
        if key in folded and folded[key] != rel:
            collisions.append((folded[key], rel))
        folded[key] = rel
    ok('no-case-insensitive-path-collisions', not collisions, str(collisions))
    gitignore = (root / '.gitignore').read_text(encoding='utf-8')
    tauriignore = (root / '.tauriignore').read_text(encoding='utf-8') if (root / '.tauriignore').is_file() else ''
    package_excluded_dirs = _read_literal_string_set(root / 'tools/package_release.py', 'EXCLUDED_DIRS')
    node_modules_contracts = {
        'package_release.py': 'node_modules' in package_excluded_dirs,
        '.gitignore': _has_ignore_rule(gitignore, 'node_modules'),
        '.tauriignore': _has_ignore_rule(tauriignore, 'node_modules'),
    }
    target_contracts = {
        'package_release.py': 'target' in package_excluded_dirs,
        '.gitignore': _has_ignore_rule(gitignore, 'target'),
        '.tauriignore': _has_ignore_rule(tauriignore, 'target'),
    }
    web_dist_contracts = {
        'package_release.py': 'web_dist' in package_excluded_dirs,
        '.gitignore': _has_ignore_rule(gitignore, 'web_dist'),
        '.tauriignore': _has_ignore_rule(tauriignore, 'web_dist'),
    }
    missing_node_modules_contracts = [name for name, present in node_modules_contracts.items() if not present]
    missing_target_contracts = [name for name, present in target_contracts.items() if not present]
    missing_web_dist_contracts = [name for name, present in web_dist_contracts.items() if not present]
    ok(
        'no-packaged-node-modules',
        not missing_node_modules_contracts,
        'missing node_modules exclusion in: ' + ', '.join(missing_node_modules_contracts)
        if missing_node_modules_contracts
        else 'excluded by Git, Tauri, and release packaging',
    )
    ok(
        'no-packaged-target',
        not missing_target_contracts,
        'missing target exclusion in: ' + ', '.join(missing_target_contracts)
        if missing_target_contracts
        else 'excluded by Git, Tauri, and release packaging',
    )
    ok(
        'no-packaged-web-dist',
        not missing_web_dist_contracts,
        'missing web_dist exclusion in: ' + ', '.join(missing_web_dist_contracts)
        if missing_web_dist_contracts
        else 'generated on demand and excluded from source release packaging',
    )
    build_venv_contracts = {'package_release.py': '.desktop-build' in package_excluded_dirs, '.gitignore': _has_ignore_rule(gitignore, '.desktop-build'), '.tauriignore': _has_ignore_rule(tauriignore, '.desktop-build')}
    missing_build_venv_contracts = [name for name, present in build_venv_contracts.items() if not present]
    ok('no-packaged-build-venv', not missing_build_venv_contracts, 'missing .desktop-build exclusion in: ' + ', '.join(missing_build_venv_contracts) if missing_build_venv_contracts else 'excluded by Git, Tauri, and release packaging')
    ok('shell-build-script-executable', bool((root / 'scripts/build-desktop.sh').stat().st_mode & 73), '')
    ok('macos-verifier-script-executable', bool((root / 'scripts/verify-macos-app.sh').stat().st_mode & 73), '')
    invalid_json = []
    for path in (p for p in files if p.suffix.lower() == '.json'):
        try:
            json.loads(path.read_text(encoding='utf-8'))
        except Exception as exc:
            invalid_json.append(f'{path.relative_to(root)}: {exc}')
    ok('all-json-parses', not invalid_json, str(invalid_json[:10]))
    invalid_toml = []
    for path in (p for p in files if p.suffix.lower() == '.toml' or p.name == 'Cargo.lock'):
        try:
            with path.open('rb') as stream:
                tomllib.load(stream)
        except Exception as exc:
            invalid_toml.append(f'{path.relative_to(root)}: {exc}')
    ok('all-toml-parses', not invalid_toml, str(invalid_toml[:10]))
    invalid_xml = []
    for path in (p for p in files if p.suffix.lower() in {'.xml', '.svg', '.wxs'}):
        try:
            ET.parse(path)
        except Exception as exc:
            invalid_xml.append(f'{path.relative_to(root)}: {exc}')
    ok('all-xml-svg-wxs-parses', not invalid_xml, str(invalid_xml[:10]))
    wasm_api = (root / 'rust/dhad-core-rs/src/wasm_api.rs').read_text(encoding='utf-8')
    unsafe_calls = re.findall('(?m)^\\s*let\\s+\\w+\\s*=\\s*read_input\\(', wasm_api)
    ok('rust-explicit-unsafe-read-input', not unsafe_calls and 'unsafe { read_input(ptr, len) }' in wasm_api, str(unsafe_calls))
    tauri_lib = (root / 'src-tauri/src/lib.rs').read_text(encoding='utf-8')
    ok('macos-hud-effect-target-guarded', '#[cfg(target_os = "macos")]' in tauri_lib and 'Effect::HudWindow' in tauri_lib, '')
    ok('windows-mica-effect-target-guarded', '#[cfg(target_os = "windows")]' in tauri_lib and 'Effect::Mica' in tauri_lib, '')
    ok('window-effects-nonfatal', 'failed to apply platform window effects' in tauri_lib, '')
    rust_toolchain = tomllib.loads((root / 'rust-toolchain.toml').read_text(encoding='utf-8'))
    ok('rust-toolchain-1.97.1', rust_toolchain.get('toolchain', {}).get('channel') == '1.97.1', str(rust_toolchain))
    tauri_cargo = tomllib.loads((root / 'src-tauri/Cargo.toml').read_text(encoding='utf-8'))
    deps = tauri_cargo.get('dependencies', {})
    ok('tauri-crate-pinned-2.11.5', deps.get('tauri', {}).get('version') == '=2.11.5', str(deps.get('tauri')))
    package_lock = json.loads((root / 'web_demo/package-lock.json').read_text(encoding='utf-8'))
    ok('npm-lockfile-v3', package_lock.get('lockfileVersion') == 3, str(package_lock.get('lockfileVersion')))
    locked_packages = package_lock.get('packages', {})
    missing_integrity = []
    for name in ('node_modules/onnxruntime-web', 'node_modules/yjs', 'node_modules/fake-indexeddb'):
        item = locked_packages.get(name, {})
        if not item.get('version') or not item.get('integrity'):
            missing_integrity.append(name)
    ok('critical-npm-dependencies-pinned', not missing_integrity, str(missing_integrity))
    requirements = (root / 'tools/desktop-build-requirements.txt').read_text(encoding='utf-8').splitlines()
    ok('desktop-build-tools-pinned', requirements == ['onnx==1.22.0', 'PyYAML==6.0.3'], str(requirements))
    version_validator = (root / 'tools/validate_release_version.py').read_text(encoding='utf-8')
    ok('release-version-validator-semver', 'SEMVER = re.compile' in version_validator and 'release tag' in version_validator, '')
    ok('single-workspace-cargo-lock', not (root / 'rust/dhad-core-rs/Cargo.lock').exists(), 'member lockfile must not exist')
    cargo_lock = tomllib.loads((root / 'Cargo.lock').read_text(encoding='utf-8'))
    cargo_packages = cargo_lock.get('package', [])
    cargo_versions = {str(item.get('name')): str(item.get('version')) for item in cargo_packages}
    ok('cargo-lock-desktop-member', cargo_versions.get('dhad-desktop') == cfg.get('version'), str(cargo_versions.get('dhad-desktop')))
    ok('cargo-lock-core-member', cargo_versions.get('dhad-core') == cfg.get('version'), str(cargo_versions.get('dhad-core')))
    ok('cargo-lock-tauri-pinned', cargo_versions.get('tauri') == '2.11.5', str(cargo_versions.get('tauri')))
    ok('cargo-lock-tauri-build-pinned', cargo_versions.get('tauri-build') == '2.6.3', str(cargo_versions.get('tauri-build')))
    staging_tool = (root / 'tools/build_web_dist.mjs').read_text(encoding='utf-8')
    for token in ['const runtimeAssets = Object.freeze([', 'verifyModuleClosure', 'verifyDocumentClosure', 'verifyPwaClosure', 'verifyIntegrityContracts', 'staged frontend differs from its exact allowlist']:
        ok(f'frontend-staging:{token}', token in staging_tool, 'missing exact-closure staging contract')
    collaboration_provider = (root / 'web_demo/collaboration/secure-yjs-provider.js').read_text(encoding='utf-8')
    bare_yjs_pattern = re.compile(r"(?:from\s+|import\s*\()\s*['\"]yjs['\"]")
    ok('frontend-no-bare-yjs-import', not bare_yjs_pattern.search(collaboration_provider), 'packaged provider must not import node_modules')
    ok('frontend-explicit-yjs-runtime', 'yjs,' in collaboration_provider and 'this.yjs = yjs' in collaboration_provider and 'requires an explicit Yjs runtime' in collaboration_provider, '')
    for label, build_text in [('sh', sh), ('bat', bat)]:
        ok(f'build-{label}:locked-clippy', 'cargo clippy --workspace --all-targets --locked -- -D warnings' in build_text, '')
        ok(f'build-{label}:locked-tests', 'cargo test --workspace --all-targets --locked' in build_text, '')
        ok(f'build-{label}:version-contract', 'validate_release_version.py --root .' in build_text, '')
    ok('release-draft-before-matrix-complete', 'releaseDraft: true' in workflow and 'needs: build' in workflow, '')
    ok('release-requires-two-dmgs', 'dmgCount < 2' in workflow, '')
    ok('release-requires-msi-and-nsis', '!hasMsi || !hasNsis' in workflow, '')
    ok('release-publishes-after-asset-verification', 'github.rest.repos.updateRelease' in workflow and 'draft: false' in workflow, '')
    private_markers = []
    markers = ('-----BEGIN ' + 'PRIVATE KEY-----', '-----BEGIN RSA ' + 'PRIVATE KEY-----', 'ghp_', 'AKIA')
    for path in files:
        relpath = path.relative_to(root).as_posix()
        if relpath == 'tools/validate_desktop_release.py' or relpath.startswith('reports/DESKTOP_GOLDMASTER_VALIDATION.'):
            continue
        if path.stat().st_size > 2000000 or path.suffix.lower() in {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.icns', '.onnx', '.wasm', '.zip'}:
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except Exception:
            continue
        for marker in markers:
            if marker in text:
                private_markers.append(f'{path.relative_to(root)}:{marker}')
    ok('no-obvious-embedded-private-keys', not private_markers, str(private_markers[:10]))
    models = [p for p in files if p.suffix.lower() == '.onnx']
    ok('onnx-assets-present', bool(models), 'no ONNX models found')
    ok('repository-file-count', len(files) >= 350, f'only {len(files)} files')
    report = {'generated_at_utc': datetime.now(timezone.utc).isoformat(), 'file_count': len(files), 'total_bytes': sum((p.stat().st_size for p in files)), 'checks_total': len(checks), 'checks_passed': sum((1 for c in checks if c['ok'])), 'errors': errors, 'warnings': warnings, 'checks': checks, 'key_assets': {rel: sha256(root / rel) for rel in required if (root / rel).is_file()}}
    reports = root / 'reports'
    reports.mkdir(exist_ok=True)
    if args.write_reports:
        (reports / 'DESKTOP_GOLDMASTER_VALIDATION.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        md = ['# Dhad Desktop Gold Master Validation', '', f'- Files audited: **{len(files)}**', f"- Checks passed: **{report['checks_passed']}/{report['checks_total']}**", f'- Errors: **{len(errors)}**', f'- Warnings: **{len(warnings)}**', '', '## Results', '']
        md += [f"- {('PASS' if c['ok'] else 'FAIL')} — `{c['name']}`{(': ' + c['detail'] if c['detail'] else '')}" for c in checks]
        if warnings:
            md += ['', '## Warnings', ''] + [f'- {w}' for w in warnings]
        (reports / 'DESKTOP_GOLDMASTER_VALIDATION.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
    print(f"Desktop release audit: {report['checks_passed']}/{report['checks_total']} checks passed across {len(files)} files.")
    for w in warnings:
        print('WARNING:', w)
    if errors:
        for e in errors:
            print('ERROR:', e, file=sys.stderr)
        return 1
    if args.strict and warnings:
        pass
    return 0
if __name__ == '__main__':
    raise SystemExit(main())
