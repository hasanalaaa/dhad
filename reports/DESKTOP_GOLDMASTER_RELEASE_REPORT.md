# Dhad Desktop Gold Master — v1.0.17 Release Report

## Scope

This source package finalizes the native Windows installer path after the tagged v1.0.16 release run proved both macOS targets and exposed two Windows-only defects. The release remains draft-first and is published only after both DMGs, NSIS, and MSI are present and verified.

## Diagnosed Windows failures

- **NSIS verification:** the installer exited successfully, but the old verifier assumed `/D=<temporary path>` controlled the destination while Tauri was configured with `installMode = "both"`. The verifier now discovers the authoritative installation through Add/Remove Programs registry metadata and standard installation roots.
- **MSI linking:** application compilation and WiX `candle.exe` succeeded; `light.exe` failed only after the redundant project-specific desktop-shortcut fragment was added. Tauri already authors the desktop shortcut in its native WiX template, so the duplicate fragment and component reference were removed.

## Release engineering changes

- Removed `src-tauri/windows/desktop-shortcut.wxs` and all WiX fragment/component references.
- Removed `src-tauri/windows/nsis-hooks.nsh` and the duplicate NSIS hook configuration.
- Kept the native Tauri Windows configuration for install mode, branding, Start Menu folder, desktop shortcut lifecycle, and stable WiX upgrade code.
- Rebuilt `scripts/verify-windows-installer.ps1` to verify the actual installer lifecycle:
  - NSIS PE header, silent installation, registry-discovered executable, native desktop shortcut, and silent uninstall cleanup.
  - MSI compound-file header, administrative extraction, executable payload size, and PE header.
  - Optional Authenticode enforcement through `DHAD_REQUIRE_WINDOWS_SIGNED=1`.
- Retained separate Windows NSIS and MSI jobs so one bundle does not hide the result of the other.
- Retained draft-first atomic publication requiring two DMGs, one MSI, and one NSIS EXE.

## Local validation

- Release/version contract: **PASS — 1.0.17 / v1.0.17**.
- JavaScript syntax: **58 first-party files passed**.
- Dependency-free Tauri frontend: **44 allowlisted runtime files verified**.
- Focused release regressions: **48/48 passed**.
- Desktop release structural audit: **206/206 passed** across 452 files after final report generation.
- Sovereign release audit: **71/71 passed**.
- Repository audit: **449 files audited; 0 findings**.
- Shell, JSON, TOML, YAML, plist, and XML structure checks: **passed through the release validators/auditor**.

## Native evidence and remaining gate

The v1.0.16 hosted release run successfully built, mounted, inspected, and launched both Apple Silicon and Intel DMGs. The packaging host used for v1.0.17 does not provide Cargo, PowerShell, WiX, NSIS, or native Windows runners, so the revised Windows installer build and smoke tests cannot be represented as locally executed. GitHub Actions remains the final native gate.

The release must not be published unless all four artifacts exist and pass their native checks:

1. macOS Apple Silicon DMG.
2. macOS Intel DMG.
3. Windows x64 NSIS EXE.
4. Windows x64 MSI.

## Commands

```bash
./scripts/build-desktop.sh
```

```bat
scripts\build-desktop.bat
```
