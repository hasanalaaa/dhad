# Dhad v1.0.0 Sovereign Edition — Final Validation Report

**Release date:** 2026-07-24  
**Deliverable:** `dhad-v1.0-Desktop-Ultimate.zip`  
**Source tree:** clean, 438 files, 180,045,597 bytes before ZIP container overhead

## Executive result

The Gold Master codebase was evolved into the Sovereign Edition with native desktop hardening, least-privilege Tauri capabilities, non-blocking Rust command execution, resilient document writes, a refined floating assistant, a replacement showcase README, a high-resolution SVG hero, and reproducible release gates.

No executable test completed by the packaging host failed. Tests that could not run are listed as **blocked**, never converted into passes.

## Principal transformations

- Enabled an explicit restrictive Tauri CSP, prototype freezing, cross-origin isolation, no-referrer/nosniff headers, and a constrained permissions policy.
- Split native capabilities between the main editor and floating assistant; the assistant has no native file-dialog permission and both capabilities are local-origin only.
- Moved native analysis, paraphrasing, and document I/O into blocking worker tasks to protect WebView responsiveness.
- Added staged, synced file writes, POSIX atomic replacement, and Windows backup/rollback recovery.
- Refined tray recovery, primary/fallback hotkeys, topmost restoration, display recentering, IME input, reduced-motion/high-contrast support, focus reliability, and measured latency reporting.
- Replaced `README.md`, added `docs/assets/dhad-sovereign-hero.svg`, and documented the target architecture in `docs/MASTER_TRANSFORMATION_SPEC.md`.
- Added a runtime boot regression test and a resumable cross-language validation matrix.

## Verification evidence

| Gate | Result |
|---|---:|
| Desktop Gold Master structural audit | **87/87 passed** |
| Sovereign contract + cleanliness audit | **59/59 passed** |
| JavaScript syntax | **57/57 first-party files passed** |
| Mini-assistant runtime boot regression | **1/1 passed** |
| Dependency-available Node/Web/PWA/E2EE suite | **101 passed, 0 failed** |
| Locally executable Python tests | **1,777 passed, 0 failed** |
| Resumable release matrix | **41 passed, 0 failed, 10 blocked, 0 timed out** |
| Structured-file parsing | **67 JSON, 5 TOML, 15 YAML, 2 SVG parsed** |
| Shell build-script syntax | **passed** |
| Generated-cache/temp-artifact scan | **clean** |

Detailed machine-readable evidence is retained in:

- `reports/SOVEREIGN_VALIDATION.json`
- `reports/SOVEREIGN_TEST_MATRIX.json`
- `reports/DESKTOP_GOLDMASTER_VALIDATION.json`
- `reports/SOVEREIGN_NODE_TESTS_AVAILABLE.txt`
- `reports/SOVEREIGN_PHASE2_EVALUATION.txt`

## Explicitly blocked validation

- `cargo fmt`, `cargo check`, and `cargo test`: Cargo/rustc were not installed on the packaging host and could not be fetched through the unavailable external package gateways.
- Native macOS DMG and Windows NSIS/MSI builds: those operating-system runners were unavailable on the Linux packaging host.
- Full Node suite: two files require `yjs` and `fake-indexeddb`; the package registry returned HTTP 503. All remaining dependency-available tests passed.
- Python native/dependency suites: `pycrdt`, `fakeredis`, and native ONNX runtime-dependent checks were unavailable or skipped and remain mandatory in CI.

## Claims boundary

- The `0.09ms` objective is not represented as a measured SLA. The UI now reports observed latency, and actual performance depends on hardware, input size, and backend path.
- “Offline-first” means core writing flows and bundled inference assets are designed to execute locally. It is not a substitute for an independent privacy or penetration audit.
- Native visual materials are best-effort platform effects and degrade gracefully when the operating system does not support them.

## Release disposition

**Approved for source release and platform CI packaging.** Native installer publication should occur only after the macOS and Windows workflow jobs complete their build and smoke-test gates.
