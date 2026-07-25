# Dhad Desktop Ultimate v1.0.18 — Final Validation

## Diagnosed native failures from v1.0.17

- **NSIS:** the installer built, uploaded, and returned a successful silent-install exit code. Verification then crashed under PowerShell `Set-StrictMode` while enumerating unrelated uninstall-registry objects that did not expose a `DisplayName` property.
- **MSI:** Rust compilation and WiX `candle.exe` compilation succeeded on every attempt. WiX `light.exe` failed while producing an `en-US` MSI whose product/bundle identity and output filename contained the Arabic product name. This matches the documented Tauri failure pattern for a non-ASCII `productName` at the `light.exe` stage.

## Corrections

- Added `src-tauri/tauri.windows.conf.json`, merged by Tauri only on Windows, with the ASCII bundle identity `Dhad`, English Windows installer descriptions, `en-US` WiX language, and the existing Arabic application window titles left unchanged.
- Rebuilt the Windows verifier around null-safe optional-property access; uninstall-registry records with missing properties are ignored instead of terminating strict-mode execution.
- Added a native `windows-2022` CI contract job that parses and executes the PowerShell verifier against missing-property and wrong-entry fixtures before any release tag can be created.
- Added the same verifier contract before both NSIS and MSI builds.
- Retained NSIS PE/install/shortcut/uninstall lifecycle checks and MSI compound-file/administrative-extraction/payload checks.
- Added failure-only upload of generated WiX source and inventory for complete future evidence.
- Retained split Windows jobs and draft-first atomic publication.

## Local validation

- Release version contract: **PASS — 1.0.18 / v1.0.18**.
- Tauri compatibility: **PASS — CLI 2.11.4 / crate 2.11.5**.
- JavaScript syntax: **58 files passed**.
- Version-derived JavaScript contracts: **6/6 passed**.
- Dependency-free frontend closure: **44 files / 165,592,508 bytes**.
- Focused release regression suite: **50/50 passed**.
- Desktop release audit: **221/221 passed**.
- Sovereign release audit: **71/71 passed**.
- Repository audit: **0 findings**.

## Native evidence and limit

The v1.0.17 hosted run already passed both macOS native jobs and built/uploaded the NSIS installer before its verifier crashed. The packaging host used for this source archive does not provide native Windows, PowerShell, WiX, NSIS, or the Rust toolchain, so the corrected Windows builds are not represented as locally executed. GitHub Actions remains the final native confirmation.

## Publication gate

The draft release must stay private until all four artifacts are present and verified: Apple Silicon DMG, Intel DMG, Windows NSIS EXE, and Windows MSI.
