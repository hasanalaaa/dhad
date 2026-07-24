# Dhad Desktop Gold Master — Release Report

## Source baseline

The requested `dhad-v1.0-Desktop-Phase3.zip` was not present in the execution environment. The latest available desktop source, `dhad-v1.0-Desktop-Phase2.zip`, was used as the baseline and advanced directly to this Gold Master release package.

## Release engineering delivered

- Tauri 2 bundle configuration for macOS DMG and Windows NSIS/MSI.
- Custom DMG background and drag-to-Applications layout.
- Native icon set including PNG, ICNS, and multi-resolution ICO assets.
- NSIS desktop shortcut lifecycle hooks and WiX desktop-shortcut fragment.
- One-command macOS and Windows build scripts.
- Isolated, pinned ONNX build tooling (`onnx==1.22.0`).
- GitHub Actions tagged-release pipeline for:
  - macOS Apple Silicon DMG.
  - macOS Intel DMG.
  - Windows x64 NSIS EXE and MSI.
- Premium Arabic release landing page with configurable demo and release links.
- GitHub Pages and Vercel deployment metadata.
- Repeatable release validator and full file/SHA256 inventory generator.

## Local validation results

- Desktop release structural audit: **87/87 passed**.
- Repository files covered by the structural audit before final inventory generation: **417**.
- JavaScript syntax validation: **56 first-party files passed**.
- Dependency-independent Node test suite: **99/99 passed**.
- Python files parsed: **103**.
- HTML files parsed: **6**.
- YAML files parsed: **15**.
- Raster images decoded and verified: **26**.
- JSON, TOML, XML, SVG, and WiX source parsing: passed.
- Broken symlink and case-insensitive path-collision checks: passed.
- Obvious embedded private-key/token marker scan: passed.

## Environment-limited checks

The execution container did not provide Rust/Cargo or native macOS/Windows toolchains, so a local `cargo build`, DMG build, NSIS build, or MSI build was not performed here. The workflow and one-command scripts are configured to run Rust formatting, Clippy, workspace tests, full npm tests, ONNX validation/optimization, and native Tauri bundling on their target operating systems.

The local npm registry could not be resolved during dependency installation. Therefore two dependency-backed test files were deferred locally:

- `web_demo/collaboration/secure-yjs-provider.test.mjs` — 4 declared test cases.
- `web_demo/storage/db.test.mjs` — 9 declared test cases.

Their locked dependencies and integrity hashes are present in `web_demo/package-lock.json`; the GitHub Actions validation job runs `npm ci` followed by the complete `npm test` command before any release bundle is published.

## Release commands

### macOS

```bash
./scripts/build-desktop.sh
```

### Windows

```bat
scripts\build-desktop.bat
```

## Included audit artifacts

- `reports/DESKTOP_GOLDMASTER_VALIDATION.md`
- `reports/DESKTOP_GOLDMASTER_VALIDATION.json`
- `reports/DESKTOP_GOLDMASTER_DEEP_AUDIT.json`
- `reports/DESKTOP_GOLDMASTER_NODE_TESTS.txt`
- `reports/DESKTOP_GOLDMASTER_JS_CHECK.txt`
- `reports/DESKTOP_ONNX_ASSET_MANIFEST.json`
- `reports/DESKTOP_GOLDMASTER_DIRECTORY_INVENTORY.txt`
- `reports/DESKTOP_GOLDMASTER_INVENTORY.json`
- `reports/DESKTOP_GOLDMASTER_FILE_SHA256SUMS.txt`
