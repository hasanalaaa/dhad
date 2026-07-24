# Dhad Sovereign Test Matrix

- Passed: **42**
- Failed: **0**
- Blocked by environment/dependency: **10**
- Timed out: **0**

A blocked entry is not counted as a pass. It records missing tooling or dependencies explicitly.

## Results

| Layer | Check | Status | Seconds | Detail |
|---|---|---:|---:|---|
| python | `python-syntax` | **passed** | 0.29 | parsed 110 Python files without generating bytecode |
| release | `desktop-release-validator` | **passed** | 2.01 | Desktop release audit: 196/196 checks passed across 451 files. |
| release | `sovereign-release-validator` | **passed** | 1.45 | Sovereign release audit: 70/70 checks passed. |
| javascript | `javascript-syntax` | **passed** | 5.84 | JavaScript syntax verified: 58 first-party files |
| javascript | `node-test-suite` | **blocked** | 0.00 | node_modules is absent or incomplete; run npm ci first |
| python | `pytest:test_analysis_context.py` | **passed** | 7.44 | .. [100%] 2 passed in 2.96s |
| python | `pytest:test_api.py` | **passed** | 9.23 | ........... [100%] 11 passed in 4.58s |
| python | `pytest:test_api_cli.py` | **passed** | 45.10 | 13 passed in isolated groups; full-file capture can retain CLI child pipes in this container |
| python | `pytest:test_benchmark_seed.py` | **passed** | 7.11 | . [100%] 1 passed in 2.48s |
| python | `pytest:test_build_pipeline_hygiene.py` | **passed** | 0.20 | 20 passed in 0.20s |
| python | `pytest:test_checks.py` | **passed** | 5.78 | .............. [100%] 14 passed in 1.79s |
| python | `pytest:test_crdt.py` | **blocked** | 6.04 | ==================================== ERRORS ==================================== _____________________ ERROR collecting tests/test_crdt.py ______________________ ImportError while importing test module '/mnt/data/v15work/dhad/tests/test_crd |
| python | `pytest:test_desktop.py` | **passed** | 5.47 | ..... [100%] 5 passed in 1.65s |
| python | `pytest:test_diacritics.py` | **passed** | 7.62 | ............. [100%] 13 passed in 3.25s |
| python | `pytest:test_dialects.py` | **passed** | 10.20 | ....................................... [100%] 39 passed in 5.63s |
| python | `pytest:test_distillation.py` | **passed** | 5.54 | ............. [100%] 13 passed in 1.62s |
| python | `pytest:test_extension.py` | **passed** | 3.64 | ..... [100%] 5 passed in 0.49s |
| python | `pytest:test_gold_master.py` | **passed** | 6.67 | 10 passed in 6.67s |
| python | `pytest:test_incremental.py` | **passed** | 7.97 | ............. [100%] 13 passed in 3.52s |
| python | `pytest:test_intelligence.py` | **passed** | 9.85 | ...... [100%] 6 passed in 5.09s |
| python | `pytest:test_lsp.py` | **passed** | 8.60 | 10 passed in 8.60s |
| python | `pytest:test_macos_bundle_verifier.py` | **passed** | 3.45 | ... [100%] 3 passed in 0.07s |
| python | `pytest:test_morphology.py` | **passed** | 7.95 | ..................... [100%] 21 passed in 3.53s |
| python | `pytest:test_neural.py` | **passed** | 9.19 | ........... [100%] 11 passed in 4.74s |
| python | `pytest:test_onnx_backend.py` | **blocked** | 3.31 | 1 skipped in 0.02s |
| python | `pytest:test_phase1_rules_v2.py` | **passed** | 7.94 | ............ [100%] 12 passed in 3.49s |
| python | `pytest:test_phase1_text.py` | **passed** | 7.15 | ........................................................................ [ 6%] ........................................................................ [ 13%] ........................................................................ [ 20%] . |
| python | `pytest:test_phase2_evaluation.py` | **passed** | 39.17 | 16 passed in two groups (15 passed in 28.74s; final case passed in 10.43s) |
| python | `pytest:test_privacy.py` | **passed** | 8.46 | .......... [100%] 10 passed in 4.09s |
| python | `pytest:test_release_config.py` | **passed** | 3.34 | ........... [100%] 11 passed in 0.07s |
| python | `pytest:test_rules.py` | **passed** | 6.15 | ........................................................................ [ 25%] ........................................................................ [ 50%] ........................................................................ [ 75%]  |
| python | `pytest:test_rust_parity.py` | **blocked** | 3.16 | 1 skipped in 0.02s |
| python | `pytest:test_security.py` | **passed** | 9.95 | ............ [100%] 12 passed in 5.21s |
| python | `pytest:test_semantics.py` | **passed** | 7.81 | ................ [100%] 16 passed in 3.45s |
| python | `pytest:test_server.py` | **passed** | 8.21 | ..... [100%] 5 passed in 3.42s |
| python | `pytest:test_sovereign_release.py` | **passed** | 3.46 | . [100%] 1 passed in 0.06s |
| python | `pytest:test_spans.py` | **passed** | 5.80 | ......... [100%] 9 passed in 1.95s |
| python | `pytest:test_spellcheck.py` | **passed** | 7.92 | 20 passed in 7.92s |
| python | `pytest:test_student_distillation.py` | **passed** | 5.70 | .... [100%] 4 passed in 1.69s |
| python | `pytest:test_style.py` | **passed** | 8.89 | 50 passed in 8.89s |
| python | `pytest:test_stylometry.py` | **passed** | 7.73 | ............................... [100%] 31 passed in 3.48s |
| python | `pytest:test_sync.py` | **passed** | 9.13 | ....... [100%] 7 passed in 4.41s |
| python | `pytest:test_syntax.py` | **passed** | 9.55 | ................................................ [100%] 48 passed in 5.12s |
| python | `pytest:test_text.py` | **passed** | 5.55 | ....... [100%] 7 passed in 1.64s |
| python | `pytest:test_vmax_phase4_crdt.py` | **blocked** | 5.71 | ==================================== ERRORS ==================================== _______________ ERROR collecting tests/test_vmax_phase4_crdt.py ________________ ImportError while importing test module '/mnt/data/v15work/dhad/tests/test_vma |
| python | `pytest:test_vmax_phase4_sync_backend.py` | **blocked** | 3.52 | ==================================== ERRORS ==================================== ___________ ERROR collecting tests/test_vmax_phase4_sync_backend.py ____________ ImportError while importing test module '/mnt/data/v15work/dhad/tests/test_vma |
| python | `pytest:test_vmax_phase4_websocket.py` | **passed** | 5.91 | 10 passed in 5.91s |
| python | `pytest:test_vmax_phase4_yjs_compat.py` | **blocked** | 5.88 | ==================================== ERRORS ==================================== ____________ ERROR collecting tests/test_vmax_phase4_yjs_compat.py _____________ ImportError while importing test module '/mnt/data/v15work/dhad/tests/test_vma |
| python | `pytest:test_web_interfaces.py` | **passed** | 9.69 | ....... [100%] 7 passed in 5.07s |
| rust | `cargo-fmt` | **blocked** | 0.00 | Rust/Cargo is not installed in this execution environment |
| rust | `cargo-check` | **blocked** | 0.00 | Rust/Cargo is not installed in this execution environment |
| rust | `cargo-test` | **blocked** | 0.00 | Rust/Cargo is not installed in this execution environment |
