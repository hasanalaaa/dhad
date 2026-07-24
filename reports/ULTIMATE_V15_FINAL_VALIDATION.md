# Dhad Desktop Ultimate v1.0.15 — Final Validation

## Result

**Source archive ready for hosted CI and native bundle verification.** No unavailable test is counted as a pass.

## Verified locally

- Release/version contract: **PASS** (`1.0.15`, expected tag `v1.0.15`).
- Tauri configuration: **PASS** (npm CLI `2.11.4`, Rust crate `2.11.5`).
- Dependency-free frontend staging: **PASS** — 44 exact allowlisted files, 165,592,508 bytes.
- Staging closure checks: module imports, HTML/CSS references, PWA precache/manifest, ONNX/tokenizer/vendor hashes: **PASS**.
- Adversarial staging: unexpected files ignored; missing source, bare import, and model tampering rejected: **PASS**.
- JavaScript syntax: **58 first-party files PASS**.
- Available Python suite: **1807 unique tests PASS across 38 test files**.
- Focused release/packaging regressions: **47 PASS**.
- Desktop release audit: **196/196 PASS**.
- Sovereign release audit (cleanliness excluded because generated/local directories are separately excluded): **70/70 PASS**.
- Repository audit: **PASS, 0 findings**.
- JSON, TOML, YAML, plist parsing and shell syntax: **PASS**.
- Workspace lock: **one complete root Cargo.lock**, local versions and Tauri pins validated.
- Release workflow: draft-first; public release requires two DMGs, MSI, and NSIS before atomic publication.

## Explicitly blocked in this execution environment

- Full npm tests: package installation is unavailable in this offline container.
- CRDT/Yjs and sync-backend tests requiring `pycrdt`/`fakeredis`.
- ONNX Runtime test requiring `onnx`/`onnxruntime`.
- Rust fmt/check/test and native Tauri bundles: Rust/Cargo and Linux development headers are not installed here.

These are not reported as passes. The committed GitHub workflows run the locked Python, npm, Rust, macOS, and Windows gates before publishing.

## Final release gate

1. Push the source to `main` and require all CI jobs to pass.
2. Create `v1.0.15` only after CI is green.
3. Accept the release only when both macOS DMGs, Windows MSI and NSIS, and the atomic publish job succeed.
