# Dhad 1.0 Gold Master — Final Validation

**Release:** `1.0.0`  
**Validation date:** 2026-07-23

## Measured local results

| Gate | Result |
|---|---|
| Python locally executable suites | **1776 passed, 0 failed** |
| Web/Node locally executable suites | **91 passed, 0 failed** |
| JavaScript syntax | **51 first-party files passed** |
| Python compileall | **passed** |
| Shell syntax | **passed** |
| Structured JSON/TOML/YAML validation | **passed through repository audit** |
| Repository audit | **357 repository files audited; zero findings** |
| ZIP CRC/integrity | **passed; every final archive entry CRC-tested** |

## Python evidence

Pytest collected 1,776 locally executable tests after excluding four modules whose imports require unavailable native or service dependencies. The executable matrix was run in deterministic groups and all 1,776 passed. Async sync tests were run with the installed AnyIO pytest plugin.

Environment-gated Python modules:

- `tests/test_crdt.py` — requires compatible `pycrdt`.
- `tests/test_vmax_phase4_crdt.py` — requires compatible `pycrdt`.
- `tests/test_vmax_phase4_yjs_compat.py` — requires compatible `pycrdt`.
- `tests/test_vmax_phase4_sync_backend.py` — requires `redis` and `fakeredis`.

## Web/Node evidence

Ninety-one tests that do not depend on unavailable npm packages passed in two independent Node test runs:

- **45 passed**: analysis, analytics, documents, Writing Intelligence, PWA, rewrite, templates, themes, capability parity, UI rendering, and packed WASM bridge.
- **46 passed**: E2EE, WebSocket transport, neural client/core/runtime, verified asset streaming, batching, and worker recovery.

Two test files remain dependency-gated locally:

- `web_demo/collaboration/secure-yjs-provider.test.mjs` — requires a complete `yjs` installation.
- `web_demo/storage/db.test.mjs` — requires a complete `fake-indexeddb` installation.

The package lock and CI job retain both suites. The packaging environment could not complete `npm ci` from the package gateway, so these files are not represented as locally passing.

## Additional environment gates

- Rust tests, clippy, and WASM rebuild require `cargo` and `rustc`, which are unavailable in this environment.
- Python ONNX runtime tests require native `onnxruntime`.
- Container runtime validation requires Docker.
- No third-party penetration test, natural-corpus quality certification, or WCAG conformance audit is claimed.

Missing tools are reported as skipped/not-run, never as passing.
