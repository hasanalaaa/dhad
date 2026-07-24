# Dhad vMAX Apex — Final Validation

**Validation date:** 23 July 2026

## Executed successfully

| Layer | Result |
|---|---:|
| Python locally available suite | **1,766 passed** |
| Node/Web dependency-available suite | **73 passed, 0 failed** |
| New Apex Python tests | **6 passed** |
| Apex intelligence/worker/PWA fast suite | **20 passed** |
| Post-refactor API/security/check regression subset | **58 passed** |
| JavaScript syntax | **38 first-party files passed** |
| Python `compileall` | **passed** |
| Shell syntax | **passed** |
| Binary `SHA256SUMS.txt` | **all entries passed** |
| Deterministic repository audit | **passed, zero findings** |

The Python total was collected as 1,766 tests and executed in independent groups to avoid an environment-specific tracing-plugin teardown delay. The final 94-test remainder passed with the tracing plugin disabled; this changes only test-process shutdown, not application behavior.

## Not executable in this packaging environment

| Suite | Constraint |
|---|---|
| Rust `cargo test`, `clippy`, `rustfmt` | `cargo/rustc` unavailable |
| Native CRDT/Yrs Python tests | compatible `pycrdt` unavailable from the configured package index |
| Redis sync backend tests | `redis` and `fakeredis` unavailable |
| Yjs secure provider and IndexedDB tests | npm tarballs for `yjs` and `fake-indexeddb` were not cached and the package gateway was unavailable |
| Docker runtime validation | Docker unavailable |

These are not recorded as successful. Their source tests, lockfiles, and strict CI jobs remain in the release.

## Release integrity gates

- No `node_modules`, virtual environments, Rust `target`, caches, bytecode, editor swap files, OS metadata, or nested release archives are permitted in staging.
- ONNX and WASM assets are retained and verified against `SHA256SUMS.txt`.
- The final ZIP must pass CRC verification and path-policy inspection.
- The archive SHA-256 is generated from the completed deliverable and stored beside it.
