# Dhad Desktop Ultimate v1.0.16 — Final Validation

## Diagnostic conclusion

- **macOS:** both native applications and DMGs were built and uploaded in v1.0.15. Tauri then cleaned the intermediate `bundle/macos/*.app`; the old verifier treated that expected cleanup as a failure.
- **Windows:** the executable and NSIS setup were built. WiX `candle.exe` compiled both source fragments, but `light.exe` failed while linking the MSI in the combined `windows-2025` job.

## v1.0.16 corrections

- Mount the generated DMG read-only and verify the exact `.app` shipped inside it, with architecture, signing, dylib, and LaunchServices smoke checks.
- Split NSIS and MSI into independent `windows-2022` jobs.
- Verify VBSCRIPT before WiX MSI linking and emit a direct diagnostic if unavailable.
- Smoke-install NSIS and administratively extract MSI after generation.
- Harden the WiX desktop shortcut fragment and use deterministic ASCII asset names.
- Keep the release private as a draft until two DMGs, one MSI, and one NSIS EXE are all present.

## Executed checks

- Release/version contract: **PASS** (`1.0.16`, expected tag `v1.0.16`).
- Tauri configuration: **PASS** (`tauri-cli 2.11.4`, Rust crate `2.11.5`).
- Frontend closure: **PASS**, 44 allowlisted runtime files, 165,592,508 bytes, no `node_modules` or test files.
- JavaScript syntax: **PASS**, 58 first-party files.
- Focused release regressions: **47/47 PASS**.
- Synthetic DMG fallback harness: **PASS**.
- Desktop release audit: **201/201 PASS**.
- Sovereign release audit: **71/71 PASS**.
- Repository audit: **PASS**, 0 findings.
- Structured parsing: **PASS** for JSON, TOML, YAML, plist, and WiX XML.
- Shell syntax: **PASS** for all first-party `.sh` files.
- Sovereign matrix: **42 passed, 0 failed, 10 environment-blocked, 0 timed out**.
- Deterministic source packaging: **PASS**; two independently generated ZIP files were byte-for-byte identical.
- Extracted-ZIP revalidation: **PASS**; 47 focused tests, 201/201 desktop checks, 71/71 sovereign checks, and 0 repository findings.
- Installer script sandbox run: **PASS**; SHA verification, extraction, `rsync`, staging, and validators completed end to end.

## Honest environment limits

- This container has no Cargo, macOS runner, Windows runner, or PowerShell. Native installers were therefore not claimed as locally built.
- Network isolation prevented a fresh `npm ci`; the complete JavaScript runtime suite had already passed **114/114** on the user Mac and hosted CI before these native-release-only changes.
- Missing `pycrdt` and `fakeredis` block several local Python files; the matrix records them as blocked, not passed.

## Release gate

1. Commit and push v1.0.16 source.
2. Require general CI to pass.
3. Create immutable tag `v1.0.16`.
4. Require both DMGs, NSIS, MSI, their post-build verifiers, and atomic publication to pass.

Keep `v1.0.15` unchanged. It is diagnostic history, not the corrected public native release.
