# Dhad Desktop Ultimate v1.0.17 — Final Validation

## Diagnosed native failures

- **NSIS:** the v1.0.16 installer completed with exit code 0, but the verifier assumed `/D` controlled the destination while Tauri used `installMode = "both"`. The revised verifier discovers the installed application from Add/Remove Programs metadata and bounded standard-root fallbacks.
- **MSI:** Rust compilation and WiX `candle.exe` compilation succeeded. `light.exe` failed after the redundant project-specific desktop-shortcut fragment was added. v1.0.17 removes that fragment and relies on Tauri's native WiX shortcut component.

## Corrections

- Removed the custom WiX shortcut fragment and component reference.
- Removed duplicate NSIS shortcut hooks.
- Added registry-based NSIS install discovery, PE validation, native desktop-shortcut verification, uninstaller discovery, and silent-uninstall cleanup verification.
- Added MSI compound-file and administrative-extraction payload verification.
- Retained split NSIS/MSI jobs and draft-first atomic publication.
- Hardened the local validation matrix so descendant stdout cannot keep a capture pipe open indefinitely.

## Local validation

- Release version contract: **PASS — 1.0.17 / v1.0.17**.
- Tauri compatibility: **PASS — CLI 2.11.4 / crate 2.11.5**.
- JavaScript syntax: **58 files passed**.
- Dependency-free frontend closure: **44 files / 165,592,508 bytes**.
- Focused release regression suite: **48/48 passed**.
- Desktop release audit: **206/206 passed across 452 files** after final validation-report generation.
- Sovereign release audit: **71/71 passed**.
- Repository audit: **449 files, 0 findings**.
- Validation matrix: **26 passed, 0 failed, 26 explicitly blocked/not run, 0 timed out**. Blocked entries are not represented as passes.

## Native evidence and limit

The v1.0.16 hosted release run passed both macOS native jobs, including DMG extraction and application launch for Apple Silicon and Intel. The v1.0.17 Windows changes cannot be built locally because the packaging host lacks Cargo, PowerShell, WiX, NSIS, and a Windows runner. GitHub Actions is therefore the final native confirmation for NSIS and MSI.

## Publication gate

The draft release must stay private until all four artifacts are present and verified: Apple Silicon DMG, Intel DMG, Windows NSIS EXE, and Windows MSI.
