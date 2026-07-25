# Dhad Sovereign Test Matrix

- Passed: **42**
- Failed: **0**
- Blocked by environment/dependency: **10**
- Timed out: **0**

A blocked entry is not counted as a pass. It records missing tooling or dependencies explicitly.

## Results

| Layer | Check | Status | Seconds | Detail |
|---|---|---:|---:|---|
| python | `python-syntax` | **passed** | 0.14 | parsed 110 Python files without generating bytecode |
| release | `desktop-release-validator` | **passed** | 0.68 | Desktop release audit: 201/201 checks passed across 454 files. |
| release | `sovereign-release-validator` | **passed** | 0.53 | Sovereign release audit: 70/70 checks passed. |
| javascript | `javascript-syntax` | **passed** | 0.97 | JavaScript syntax verified: 58 first-party files |
| javascript | `node-test-suite` | **blocked** | 0.00 | node_modules is absent or incomplete; run npm ci first |
| python | `pytest:test_analysis_context.py` | **passed** | 4.18 | .. [100%] 2 passed in 1.48s |
| python | `pytest:test_api.py` | **passed** | 5.31 | ........... [100%] 11 passed in 2.25s |
| python | `pytest:test_api_cli.py` | **passed** | 19.30 | ............. [100%] 13 passed in 16.48s |
| python | `pytest:test_benchmark_seed.py` | **passed** | 3.97 | . [100%] 1 passed in 1.34s |
| python | `pytest:test_build_pipeline_hygiene.py` | **passed** | 2.00 | ..................... [100%] 21 passed in 0.14s |
| python | `pytest:test_checks.py` | **passed** | 3.20 | .............. [100%] 14 passed in 0.89s |
| python | `pytest:test_crdt.py` | **blocked** | 3.22 | ==================================== ERRORS ==================================== _____________________ ERROR collecting tests/test_crdt.py ______________________ ImportError while importing test module '/mnt/data/v16work/dhad/tests/test_crd |
| python | `pytest:test_desktop.py` | **passed** | 3.56 | ..... [100%] 5 passed in 0.91s |
| python | `pytest:test_diacritics.py` | **passed** | 4.22 | ............. [100%] 13 passed in 1.54s |
| python | `pytest:test_dialects.py` | **passed** | 5.57 | ....................................... [100%] 39 passed in 2.81s |
| python | `pytest:test_distillation.py` | **passed** | 3.16 | ............. [100%] 13 passed in 0.89s |
| python | `pytest:test_extension.py` | **passed** | 1.95 | ..... [100%] 5 passed in 0.12s |
| python | `pytest:test_gold_master.py` | **passed** | 6.57 | .......... [100%] 10 passed in 3.50s |
| python | `pytest:test_incremental.py` | **passed** | 4.58 | ............. [100%] 13 passed in 1.72s |
| python | `pytest:test_intelligence.py` | **passed** | 5.16 | ...... [100%] 6 passed in 2.40s |
| python | `pytest:test_lsp.py` | **passed** | 6.99 | .......... [100%] 10 passed in 4.22s |
| python | `pytest:test_macos_bundle_verifier.py` | **passed** | 2.05 | ... [100%] 3 passed in 0.06s |
| python | `pytest:test_morphology.py` | **passed** | 4.70 | ..................... [100%] 21 passed in 1.90s |
| python | `pytest:test_neural.py` | **passed** | 4.94 | ........... [100%] 11 passed in 2.23s |
| python | `pytest:test_onnx_backend.py` | **blocked** | 1.93 | 1 skipped in 0.02s |
| python | `pytest:test_phase1_rules_v2.py` | **passed** | 4.54 | ............ [100%] 12 passed in 1.81s |
| python | `pytest:test_phase1_text.py` | **passed** | 3.87 | ........................................................................ [ 6%] ........................................................................ [ 13%] ........................................................................ [ 20%] . |
| python | `pytest:test_phase2_evaluation.py` | **passed** | 22.79 | ................ [100%] 16 passed in 19.97s |
| python | `pytest:test_privacy.py` | **passed** | 4.87 | .......... [100%] 10 passed in 2.06s |
| python | `pytest:test_rules.py` | **passed** | 3.53 | ........................................................................ [ 25%] ........................................................................ [ 50%] ........................................................................ [ 75%]  |
| python | `pytest:test_rust_parity.py` | **blocked** | 2.03 | 1 skipped in 0.01s |
| python | `pytest:test_security.py` | **passed** | 5.43 | ............ [100%] 12 passed in 2.44s |
| python | `pytest:test_semantics.py` | **passed** | 4.56 | ................ [100%] 16 passed in 1.70s |
| python | `pytest:test_server.py` | **passed** | 4.85 | ..... [100%] 5 passed in 1.74s |
| python | `pytest:test_sovereign_release.py` | **passed** | 2.08 | . [100%] 1 passed in 0.05s |
| python | `pytest:test_spans.py` | **passed** | 3.65 | ......... [100%] 9 passed in 1.05s |
| python | `pytest:test_spellcheck.py` | **passed** | 6.74 | .................... [100%] 20 passed in 3.91s |
| python | `pytest:test_student_distillation.py` | **passed** | 3.44 | .... [100%] 4 passed in 0.91s |
| python | `pytest:test_style.py` | **passed** | 7.49 | .................................................. [100%] 50 passed in 4.63s |
| python | `pytest:test_stylometry.py` | **passed** | 4.45 | ............................... [100%] 31 passed in 1.64s |
| python | `pytest:test_sync.py` | **passed** | 5.06 | ....... [100%] 7 passed in 2.08s |
| python | `pytest:test_syntax.py` | **passed** | 5.21 | ................................................ [100%] 48 passed in 2.62s |
| python | `pytest:test_text.py` | **passed** | 3.02 | ....... [100%] 7 passed in 0.87s |
| python | `pytest:test_vmax_phase4_crdt.py` | **blocked** | 3.05 | ==================================== ERRORS ==================================== _______________ ERROR collecting tests/test_vmax_phase4_crdt.py ________________ ImportError while importing test module '/mnt/data/v16work/dhad/tests/test_vma |
| python | `pytest:test_vmax_phase4_sync_backend.py` | **blocked** | 1.85 | ==================================== ERRORS ==================================== ___________ ERROR collecting tests/test_vmax_phase4_sync_backend.py ____________ ImportError while importing test module '/mnt/data/v16work/dhad/tests/test_vma |
| python | `pytest:test_vmax_phase4_websocket.py` | **passed** | 5.93 | .......... [100%] 10 passed in 2.84s |
| python | `pytest:test_vmax_phase4_yjs_compat.py` | **blocked** | 3.65 | ==================================== ERRORS ==================================== ____________ ERROR collecting tests/test_vmax_phase4_yjs_compat.py _____________ ImportError while importing test module '/mnt/data/v16work/dhad/tests/test_vma |
| python | `pytest:test_web_interfaces.py` | **passed** | 5.56 | ....... [100%] 7 passed in 2.45s |
| rust | `cargo-fmt` | **blocked** | 0.00 | Rust/Cargo is not installed in this execution environment |
| rust | `cargo-check` | **blocked** | 0.00 | Rust/Cargo is not installed in this execution environment |
| rust | `cargo-test` | **blocked** | 0.00 | Rust/Cargo is not installed in this execution environment |
| python | `pytest:test_release_config.py` | **passed** | 2.16 | ............. [100%] 13 passed in 0.10s |
