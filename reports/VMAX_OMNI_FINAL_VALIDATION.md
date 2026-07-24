# Dhad vMAX Omni — Final Validation

تاريخ التحقق: **23 يوليو 2026**

## Results executed locally

| Layer | Result |
|---|---:|
| Python deterministic/API/security/sync suites | **1760 passed** |
| Rust parity Python module | **1 module skipped** — compiled `dhad_core` extension unavailable |
| Web/Node executable suites | **61 passed, 0 failed** |
| JavaScript syntax | **35 first-party files passed** |
| Python `compileall` | **passed** |
| Shell syntax | **passed** |
| Deterministic repository audit | **passed; zero findings** |
| SHA256 asset manifest | **passed** |

## Suites retained but not executable in this environment

| Suite | Reason |
|---|---|
| Python CRDT/Yjs compatibility | `pycrdt` unavailable |
| Redis backend integration | `fakeredis`/`redis` unavailable |
| Browser secure Yjs provider | `yjs` unavailable and registry inaccessible |
| IndexedDB browser unit tests | `fake-indexeddb` unavailable and registry inaccessible |
| Rust `cargo test` / `clippy` | `cargo` and `rustc` unavailable |
| Python ONNX backend | native `onnxruntime` unavailable; no tests collected |
| Container runtime validation | Docker unavailable |

The unavailable suites were not counted as passing. Their source, lockfiles, CI configuration, and regression tests remain included in the release.

## Executed commands

```bash
PYTHONPATH=.:src python -m pytest -q tests/test_phase1_text.py
PYTHONPATH=.:src python -m pytest -q <rules/style/syntax/dialect/morphology groups>
PYTHONPATH=.:src python -m pytest -q <API/security/sync/unit groups>
PYTHONPATH=.:src python -m pytest -q tests/test_checks.py
node --test <all locally executable web test files>
node tools/check_javascript.mjs
PYTHONPATH=.:src python tools/audit_repository.py --write-reports
```

## Release integrity

The final archive is generated from a staging tree that excludes dependency directories, caches, virtual environments, build targets, nested archives, and OS metadata. The archive is tested with `unzip -t`, and a standalone SHA-256 file is generated beside it.
