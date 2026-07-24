# Dhad Desktop Release Engineering

## Local one-command builds

### macOS

```bash
./scripts/build-desktop.sh
```

The script creates an isolated `.desktop-build/venv`, installs the pinned ONNX tooling, validates and safely optimizes model metadata, runs JavaScript, Clippy, Rust formatting, and workspace tests, stages a dependency-free `web_dist`, installs the pinned npm Tauri CLI when needed, creates a DMG, then verifies the generated `.app` metadata, executable permissions, Mach-O architecture, code signature, dynamic-library linkage, and native launch smoke test.

### Windows

```bat
scripts\build-desktop.bat
```

The Windows script builds both NSIS (`.exe`) and WiX (`.msi`) installers. Both installers include uninstall support; the NSIS hook and WiX fragment create a desktop shortcut.

Environment switches:

- `DHAD_SKIP_WEB_TESTS=1` skips JavaScript tests.
- `DHAD_SKIP_RUST_TESTS=1` skips Cargo formatting/tests.
- `DHAD_SKIP_CLI_INSTALL=1` prevents automatic Tauri CLI installation.
- Local and GitHub release builds use the published npm wrapper `@tauri-apps/cli@2.11.4`, while the Rust application crate remains pinned to `tauri = 2.11.5`; `tools/validate_tauri_config.py` rejects incompatible configuration keys before bundling.
- Preserve the hidden `.github/` directory when copying or extracting the source archive; the build preflight requires `.github/workflows/desktop-release.yml`.
- Tauri embeds only the generated `web_dist/` tree. `tools/build_web_dist.mjs` rebuilds it from `web_demo/` while excluding `node_modules`, tests, package metadata, benchmarks, and fixtures.
- `DHAD_BUNDLES=dmg` or `DHAD_BUNDLES=nsis,msi` overrides bundle targets.
- `DHAD_SKIP_MACOS_LAUNCH_SMOKE=1` skips only the post-build launch smoke test; structural and signing checks still run.
- `DHAD_REQUIRE_NOTARIZED=1` additionally requires Gatekeeper assessment and a valid stapled notarization ticket.

## Automated releases

Pushing a semantic version tag such as `v1.0.0` triggers `.github/workflows/desktop-release.yml`. The workflow validates the complete codebase, then builds:

- macOS Apple Silicon DMG on `macos-15`.
- macOS Intel DMG on `macos-15-intel`.
- Windows x64 NSIS EXE and MSI on `windows-2025`.

The generated bundles are attached to the matching GitHub Release through `tauri-apps/tauri-action@v1`.

## Signing

Local macOS builds use the configured ad-hoc identity when no Apple identity is supplied. This permits executable-integrity checks but does not replace Developer ID signing or notarization for browser-delivered public releases. For public distribution, configure Apple Developer ID/notarization and Windows Authenticode secrets in GitHub before publishing production tags.


## Landing page deployment

- **GitHub Pages:** publish the `docs/` directory and keep `docs/.nojekyll`.
- **Vercel:** import the repository; `vercel.json` serves the landing page and maps `/demo` to the web demo.
- Set the `dhad-release-base` meta value in `docs/index.html` when releases live outside the repository inferred by GitHub Pages.
- Set `dhad-demo-url` when the live demo is hosted at a separate origin.

## Release signing checklist

### macOS

1. Import a Developer ID Application certificate on the build runner.
2. Set a signing identity and Apple notarization credentials.
3. Verify the stapled ticket with `spctl` after the DMG build.

### Windows

1. Configure an Authenticode certificate on the Windows runner.
2. Sign the application executable and both NSIS/MSI installers.
3. Verify signatures with `Get-AuthenticodeSignature` before publishing.

Signing credentials are intentionally not stored in the repository. Unsigned artifacts remain suitable for internal validation but public releases should be signed and notarized.

## macOS local build and installation

Use the repository root, not `src-tauri`, because the Cargo workspace writes native artifacts under the root `target` directory.

Run a development build:

```bash
cd ~/Documents/dhad
cargo tauri dev
```

Create and verify the production DMG:

```bash
cd ~/Documents/dhad
chmod +x scripts/build-desktop.sh scripts/verify-macos-app.sh scripts/install-macos-app.sh
./scripts/build-desktop.sh
```

Install the verified application bundle directly into `/Applications/Dhad.app` and launch it:

```bash
cd ~/Documents/dhad
./scripts/install-macos-app.sh
```

The bundle filename stays ASCII-safe as `Dhad.app`, while `CFBundleDisplayName` presents the Arabic product name «ضاد» in macOS.

The local build environment is isolated under `.desktop-build/venv`. Never install PyYAML or ONNX into Homebrew's managed Python. The build script pins and installs both dependencies automatically.
