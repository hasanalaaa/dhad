# Dhad v1.0 — Desktop Phase 1 Validation

**Date:** 2026-07-23  
**Scope:** Additive Tauri 2.0 desktop wrapper for macOS and Windows.

## Implemented

- Added `src-tauri/` as a Rust workspace member.
- Configured `com.dhad.app`, a 1280×800 resizable window, 900×600 minimum bounds, and direct `../web_demo` static assets.
- Registered `analyze_text_native`, `paraphrase_native`, and `get_system_info`.
- Bound native analysis to `dhad-core` `RuleSet` and `SyntaxEngine`.
- Added deterministic native rewriting that reuses shared core normalization, tokenization, and sentence segmentation.
- Added `web_demo/js/desktop-adapter.js` with Tauri detection and browser WASM/WebWorker fallback.
- Preserved PWA offline behavior by adding the adapter to the atomic app-shell precache.
- Generated valid `.icns` and `.ico` bundle icons from the existing Dhad PWA icon.

## Validation results

| Gate | Result |
|---|---|
| Tauri JSON and capability JSON parsing | Passed |
| Root and Tauri Cargo TOML parsing | Passed |
| Tauri configuration invariants | Passed |
| Rust lexical delimiter/string/comment structure | Passed |
| Rust command registration ↔ JavaScript invoke parity | Passed |
| JavaScript syntax (`node --check`) | Passed |
| Focused desktop/browser/PWA tests | **26 passed, 0 failed** |
| macOS ICNS and Windows ICO signatures | Passed |
| Archive dependency hygiene (`node_modules`, `target`) | Passed |

## Environment gates

A native `cargo check`/Tauri bundle build was not run because this execution image does not provide `cargo` or `rustc`, and the package gateway did not make a Rust toolchain available. The source was therefore validated structurally and through interface parity checks, but host-native compilation must run on a machine with the official Tauri prerequisites.

The full `npm test` matrix remains dependency-gated locally because `yjs`, `onnxruntime-web`, and `fake-indexeddb` could not be installed from the package gateway. The 26 tests directly covering the modified analysis, rewrite, adapter, PWA, and UI paths all passed.
