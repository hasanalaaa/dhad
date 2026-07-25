# Dhad Desktop Gold Master — v1.0.18 Release Report

## Scope

This source package addresses the two exact Windows-only failures captured by the tagged v1.0.17 release while retaining the macOS path that already passed natively. Publication remains draft-first and atomic.

## Diagnosed Windows failures

- **NSIS verification:** the installer built, uploaded, and completed silent installation. `Set-StrictMode` then terminated the verifier while it enumerated an unrelated Add/Remove Programs registry object without a `DisplayName` property.
- **MSI linking:** application compilation and WiX `candle.exe` succeeded on all attempts. `light.exe` failed while producing the `en-US` MSI with the Arabic `productName` embedded in the Windows bundle identity and filename—the same stage and pattern reported by Tauri for non-ASCII product names.

## Release engineering changes

- Added a platform-specific `src-tauri/tauri.windows.conf.json` with `productName: Dhad`, ASCII installer descriptions, the existing `en-US` WiX language, and `Dhad` Start Menu branding. The base configuration still owns the Arabic application window titles.
- Rebuilt `scripts/verify-windows-installer.ps1` so every optional registry field is read through `PSObject.Properties[...]` and missing fields return null under strict mode.
- Added `scripts/test-windows-installer-verifier.ps1` and a mandatory `windows-2022` CI job exercising missing-property, wrong-entry, matching-entry, and missing-path cases.
- Run that PowerShell contract before each Windows release build.
- Retained native installer lifecycle checks:
  - NSIS PE header, silent installation, registry-discovered executable, desktop shortcut, uninstaller, and silent cleanup.
  - MSI compound-file header, administrative extraction, executable payload size, and PE header.
- Added failure-only upload of generated WiX source and inventory.
- Retained separate NSIS and MSI jobs and atomic publication requiring both DMGs and both Windows installers.

## Local validation

- Release/version contract: **PASS — 1.0.18 / v1.0.18**.
- JavaScript syntax: **58 first-party files passed**.
- Version-derived JavaScript contracts: **6/6 passed**.
- Dependency-free Tauri frontend: **44 allowlisted runtime files verified**.
- Focused release regressions: **50/50 passed**.
- Desktop release structural audit: **221/221 passed**.
- Sovereign release audit: **71/71 passed**.
- Repository audit: **0 findings**.

## Native evidence and remaining gate

The v1.0.17 hosted run successfully built, inspected, and launched both macOS DMGs. It also built and uploaded NSIS before the verifier defect terminated the job. Native Windows packaging is unavailable on this archive-building host, so GitHub Actions is the mandatory final gate for the corrected NSIS verifier and the ASCII-identity MSI build.

The release must not be published unless all four artifacts exist and pass their native checks:

1. macOS Apple Silicon DMG.
2. macOS Intel DMG.
3. Windows x64 NSIS EXE.
4. Windows x64 MSI.
