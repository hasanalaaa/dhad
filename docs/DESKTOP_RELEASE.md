# Dhad Desktop Release Engineering

## Local one-command builds

### macOS

```bash
./scripts/build-desktop.sh
```

The script creates an isolated `.desktop-build/venv`, installs the pinned ONNX tooling, validates and safely optimizes model metadata, runs JavaScript, Clippy, Rust formatting, and workspace tests, installs the Tauri 2 CLI when needed, and creates a DMG.

### Windows

```bat
scripts\build-desktop.bat
```

The Windows script builds both NSIS (`.exe`) and WiX (`.msi`) installers. Both installers include uninstall support; the NSIS hook and WiX fragment create a desktop shortcut.

Environment switches:

- `DHAD_SKIP_WEB_TESTS=1` skips JavaScript tests.
- `DHAD_SKIP_RUST_TESTS=1` skips Cargo formatting/tests.
- `DHAD_SKIP_CLI_INSTALL=1` prevents automatic Tauri CLI installation.
- Native release scripts and CI pin `tauri-cli` to `2.11.4`; `tools/validate_tauri_config.py` rejects incompatible configuration keys before dependency installation or bundling.
- Preserve the hidden `.github/` directory when copying or extracting the source archive; the build preflight requires `.github/workflows/desktop-release.yml`.
- `DHAD_BUNDLES=dmg` or `DHAD_BUNDLES=nsis,msi` overrides bundle targets.

## Automated releases

Pushing a semantic version tag such as `v1.0.0` triggers `.github/workflows/desktop-release.yml`. The workflow validates the complete codebase, then builds:

- macOS Apple Silicon DMG on `macos-15`.
- macOS Intel DMG on `macos-15-intel`.
- Windows x64 NSIS EXE and MSI on `windows-2025`.

The generated bundles are attached to the matching GitHub Release through `tauri-apps/tauri-action@v1`.

## Signing

Unsigned development bundles build without secrets. For public distribution, configure Apple Developer ID/notarization and Windows Authenticode secrets in GitHub before publishing production tags.


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
