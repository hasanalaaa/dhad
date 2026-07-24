# Dhad Sovereign Test Matrix

- Passed: **41**
- Failed: **0**
- Blocked by environment/dependency: **10**
- Timed out: **0**

A blocked entry is not counted as a pass. It records missing tooling or dependencies explicitly.

## Results

| Layer | Check | Status | Seconds | Detail |
|---|---|---:|---:|---|
| python | `python-syntax` | **passed** | 0.13 | parsed 103 Python files without generating bytecode |
| release | `desktop-release-validator` | **passed** | 0.60 | Desktop release audit: 87/87 checks passed across 438 clean release files. |
| release | `sovereign-release-validator` | **passed** | 0.51 | Sovereign release audit: 59/59 checks passed, including the final cleanliness gate. |
| javascript | `javascript-syntax` | **passed** | 0.94 | JavaScript syntax verified: 57 first-party files |
| javascript | `node-test-suite` | **blocked** | 0.00 | node_modules is absent or incomplete; run npm ci first |
| python | `pytest:test_analysis_context.py` | **passed** | 4.08 | .. [100%] 2 passed in 1.45s |
| python | `pytest:test_api.py` | **passed** | 4.96 | ........... [100%] 11 passed in 2.04s |
| python | `pytest:test_api_cli.py` | **passed** | 18.16 | ............. [100%] 13 passed in 15.52s |
| python | `pytest:test_benchmark_seed.py` | **passed** | 3.97 | . [100%] 1 passed in 1.30s |
| python | `pytest:test_checks.py` | **passed** | 3.40 | .............. [100%] 14 passed in 0.90s |
| python | `pytest:test_crdt.py` | **blocked** | 3.65 | ==================================== ERRORS ==================================== _____________________ ERROR collecting tests/test_crdt.py ______________________ ImportError while importing test module '/mnt/data/dhad-gm-work/tests/test_crd |
| python | `pytest:test_desktop.py` | **passed** | 3.47 | ..... [100%] 5 passed in 0.89s |
| python | `pytest:test_diacritics.py` | **passed** | 4.38 | ............. [100%] 13 passed in 1.54s |
| python | `pytest:test_dialects.py` | **passed** | 6.00 | ....................................... [100%] 39 passed in 3.02s |
| python | `pytest:test_distillation.py` | **passed** | 3.29 | ............. [100%] 13 passed in 0.88s |
| python | `pytest:test_extension.py` | **passed** | 2.04 | ..... [100%] 5 passed in 0.13s |
| python | `pytest:test_gold_master.py` | **passed** | 6.10 | .......... [100%] 10 passed in 3.28s |
| python | `pytest:test_incremental.py` | **passed** | 4.36 | ............. [100%] 13 passed in 1.58s |
| python | `pytest:test_intelligence.py` | **passed** | 5.42 | ...... [100%] 6 passed in 2.38s |
| python | `pytest:test_lsp.py` | **passed** | 6.63 | .......... [100%] 10 passed in 3.99s |
| python | `pytest:test_morphology.py` | **passed** | 4.46 | ..................... [100%] 21 passed in 1.78s |
| python | `pytest:test_neural.py` | **passed** | 4.75 | ........... [100%] 11 passed in 2.11s |
| python | `pytest:test_phase1_rules_v2.py` | **passed** | 4.35 | ............ [100%] 12 passed in 1.72s |
| python | `pytest:test_onnx_backend.py` | **blocked** | 1.91 | 1 skipped in 0.02s |
| python | `pytest:test_phase1_text.py` | **passed** | 3.77 | ........................................................................ [ 6%] ........................................................................ [ 13%] ........................................................................ [ 20%] . |
| python | `pytest:test_phase2_evaluation.py` | **passed** | 20.10 | 16 passed in 20.10s (rerun with extended timeout) |
| python | `pytest:test_privacy.py` | **passed** | 4.61 | .......... [100%] 10 passed in 1.92s |
| python | `pytest:test_release_config.py` | **passed** | 1.99 | .... [100%] 4 passed in 0.04s |
| python | `pytest:test_rules.py` | **passed** | 3.63 | ........................................................................ [ 25%] ........................................................................ [ 50%] ........................................................................ [ 75%]  |
| python | `pytest:test_rust_parity.py` | **blocked** | 1.91 | 1 skipped in 0.01s |
| python | `pytest:test_security.py` | **passed** | 5.18 | ............ [100%] 12 passed in 2.36s |
| python | `pytest:test_semantics.py` | **passed** | 4.42 | ................ [100%] 16 passed in 1.60s |
| python | `pytest:test_server.py` | **passed** | 4.64 | ..... [100%] 5 passed in 1.61s |
| python | `pytest:test_sovereign_release.py` | **passed** | 1.91 | . [100%] 1 passed in 0.04s |
| python | `pytest:test_spans.py` | **passed** | 3.36 | ......... [100%] 9 passed in 0.97s |
| python | `pytest:test_spellcheck.py` | **passed** | 6.38 | .................... [100%] 20 passed in 3.59s |
| python | `pytest:test_student_distillation.py` | **passed** | 3.51 | .... [100%] 4 passed in 0.89s |
| python | `pytest:test_style.py` | **passed** | 7.78 | .................................................. [100%] 50 passed in 4.70s |
| python | `pytest:test_stylometry.py` | **passed** | 4.35 | ............................... [100%] 31 passed in 1.65s |
| python | `pytest:test_sync.py` | **passed** | 4.98 | ....... [100%] 7 passed in 2.03s |
| python | `pytest:test_syntax.py` | **passed** | 5.24 | ................................................ [100%] 48 passed in 2.58s |
| python | `pytest:test_text.py` | **passed** | 3.27 | ....... [100%] 7 passed in 0.86s |
| python | `pytest:test_vmax_phase4_crdt.py` | **blocked** | 3.60 | ==================================== ERRORS ==================================== _______________ ERROR collecting tests/test_vmax_phase4_crdt.py ________________ ImportError while importing test module '/mnt/data/dhad-gm-work/tests/test_vma |
| python | `pytest:test_vmax_phase4_sync_backend.py` | **blocked** | 1.95 | ==================================== ERRORS ==================================== ___________ ERROR collecting tests/test_vmax_phase4_sync_backend.py ____________ ImportError while importing test module '/mnt/data/dhad-gm-work/tests/test_vma |
| python | `pytest:test_vmax_phase4_websocket.py` | **passed** | 5.79 | .......... [100%] 10 passed in 2.93s |
| python | `pytest:test_vmax_phase4_yjs_compat.py` | **blocked** | 3.29 | ==================================== ERRORS ==================================== ____________ ERROR collecting tests/test_vmax_phase4_yjs_compat.py _____________ ImportError while importing test module '/mnt/data/dhad-gm-work/tests/test_vma |
| python | `pytest:test_web_interfaces.py` | **passed** | 5.08 | ....... [100%] 7 passed in 2.21s |
| rust | `cargo-fmt` | **blocked** | 0.00 | Rust/Cargo is not installed in this execution environment |
| rust | `cargo-check` | **blocked** | 0.00 | Rust/Cargo is not installed in this execution environment |
| rust | `cargo-test` | **blocked** | 0.00 | Rust/Cargo is not installed in this execution environment |
| javascript | `node-test-suite-available-without-external-packages` | **passed** | 0.48 | 101 passed, 0 failed; two dependency-backed files remain represented by the blocked full npm suite entry |
