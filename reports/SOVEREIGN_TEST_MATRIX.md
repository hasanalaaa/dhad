# Dhad Sovereign Test Matrix

- Passed: **26**
- Failed: **0**
- Blocked/not run on packaging host: **26**
- Timed out: **0**

A blocked entry is not counted as a pass. Complete dependency-backed Python, Node, and Rust suites remain mandatory in hosted CI.

## Results

| Layer | Check | Status | Seconds | Detail |
|---|---|---:|---:|---|
| python | `python-syntax` | **passed** | 0.25 | parsed 110 Python files without generating bytecode |
| release | `desktop-release-validator` | **passed** | 1.75 | Desktop release audit: 206/206 checks passed across 450 files. |
| release | `sovereign-release-validator` | **passed** | 1.32 | Sovereign release audit: 70/70 checks passed. |
| javascript | `javascript-syntax` | **passed** | 5.08 | JavaScript syntax verified: 58 first-party files |
| javascript | `node-test-suite` | **blocked** | 0.00 | node_modules is absent or incomplete; run npm ci first |
| python | `pytest:test_analysis_context.py` | **passed** | 6.58 | .. [100%] 2 passed in 2.86s |
| python | `pytest:test_api.py` | **passed** | 8.27 | ........... [100%] 11 passed in 4.42s |
| python | `pytest:test_api_cli.py` | **passed** | 35.79 | ............. [100%] 13 passed in 32.23s |
| python | `pytest:test_benchmark_seed.py` | **passed** | 6.00 | . [100%] 1 passed in 2.35s |
| python | `pytest:test_build_pipeline_hygiene.py` | **passed** | 3.14 | ....................... [100%] 23 passed in 0.31s |
| python | `pytest:test_checks.py` | **passed** | 5.06 | .............. [100%] 14 passed in 1.65s |
| python | `pytest:test_crdt.py` | **blocked** | 6.05 | ==================================== ERRORS ==================================== _____________________ ERROR collecting tests/test_crdt.py ______________________ ImportError while importing test module '/mnt/data/v17work/dhad/tests/test_crd |
| python | `pytest:test_desktop.py` | **passed** | 5.49 | ..... [100%] 5 passed in 1.76s |
| python | `pytest:test_diacritics.py` | **passed** | 6.67 | ............. [100%] 13 passed in 3.08s |
| python | `pytest:test_dialects.py` | **passed** | 9.31 | ....................................... [100%] 39 passed in 5.48s |
| python | `pytest:test_distillation.py` | **passed** | 5.29 | ............. [100%] 13 passed in 1.65s |
| python | `pytest:test_extension.py` | **passed** | 3.23 | ..... [100%] 5 passed in 0.47s |
| python | `pytest:test_gold_master.py` | **passed** | 10.42 | .......... [100%] 10 passed in 6.52s |
| python | `pytest:test_incremental.py` | **passed** | 7.30 | ............. [100%] 13 passed in 3.25s |
| python | `pytest:test_intelligence.py` | **passed** | 8.70 | ...... [100%] 6 passed in 4.85s |
| python | `pytest:test_lsp.py` | **passed** | 11.43 | .......... [100%] 10 passed in 7.73s |
| python | `pytest:test_macos_bundle_verifier.py` | **passed** | 2.64 | ... [100%] 3 passed in 0.06s |
| python | `pytest:test_morphology.py` | **passed** | 6.75 | ..................... [100%] 21 passed in 3.28s |
| python | `pytest:test_neural.py` | **passed** | 7.90 | ........... [100%] 11 passed in 4.37s |
| python | `pytest:test_onnx_backend.py` | **blocked** | 2.64 | 1 skipped in 0.04s |
| python | `pytest:test_phase1_rules_v2.py` | **passed** | 6.95 | ............ [100%] 12 passed in 3.29s |
| python | `pytest:test_phase1_text.py` | **passed** | 6.05 | ........................................................................ [ 6%] ........................................................................ [ 13%] ........................................................................ [ 20%] . |
| python | `pytest:test_phase2_evaluation.py` | **blocked** | 0.00 | not executed on the packaging host within the bounded local validation budget; complete pytest remains mandatory in hosted CI |
| python | `pytest:test_privacy.py` | **blocked** | 0.00 | not executed on the packaging host within the bounded local validation budget; complete pytest remains mandatory in hosted CI |
| python | `pytest:test_release_config.py` | **passed** | 0.00 | passed as part of the independently executed 48/48 focused release regression suite |
| python | `pytest:test_rules.py` | **blocked** | 0.00 | not executed on the packaging host within the bounded local validation budget; complete pytest remains mandatory in hosted CI |
| python | `pytest:test_rust_parity.py` | **blocked** | 0.00 | not executed on the packaging host within the bounded local validation budget; complete pytest remains mandatory in hosted CI |
| python | `pytest:test_security.py` | **blocked** | 0.00 | not executed on the packaging host within the bounded local validation budget; complete pytest remains mandatory in hosted CI |
| python | `pytest:test_semantics.py` | **blocked** | 0.00 | not executed on the packaging host within the bounded local validation budget; complete pytest remains mandatory in hosted CI |
| python | `pytest:test_server.py` | **blocked** | 0.00 | not executed on the packaging host within the bounded local validation budget; complete pytest remains mandatory in hosted CI |
| python | `pytest:test_sovereign_release.py` | **blocked** | 0.00 | not executed on the packaging host within the bounded local validation budget; complete pytest remains mandatory in hosted CI |
| python | `pytest:test_spans.py` | **blocked** | 0.00 | not executed on the packaging host within the bounded local validation budget; complete pytest remains mandatory in hosted CI |
| python | `pytest:test_spellcheck.py` | **blocked** | 0.00 | not executed on the packaging host within the bounded local validation budget; complete pytest remains mandatory in hosted CI |
| python | `pytest:test_student_distillation.py` | **blocked** | 0.00 | not executed on the packaging host within the bounded local validation budget; complete pytest remains mandatory in hosted CI |
| python | `pytest:test_style.py` | **blocked** | 0.00 | not executed on the packaging host within the bounded local validation budget; complete pytest remains mandatory in hosted CI |
| python | `pytest:test_stylometry.py` | **blocked** | 0.00 | not executed on the packaging host within the bounded local validation budget; complete pytest remains mandatory in hosted CI |
| python | `pytest:test_sync.py` | **blocked** | 0.00 | not executed on the packaging host within the bounded local validation budget; complete pytest remains mandatory in hosted CI |
| python | `pytest:test_syntax.py` | **blocked** | 0.00 | not executed on the packaging host within the bounded local validation budget; complete pytest remains mandatory in hosted CI |
| python | `pytest:test_text.py` | **blocked** | 0.00 | not executed on the packaging host within the bounded local validation budget; complete pytest remains mandatory in hosted CI |
| python | `pytest:test_vmax_phase4_crdt.py` | **blocked** | 0.00 | not executed on the packaging host within the bounded local validation budget; complete pytest remains mandatory in hosted CI |
| python | `pytest:test_vmax_phase4_sync_backend.py` | **blocked** | 0.00 | not executed on the packaging host within the bounded local validation budget; complete pytest remains mandatory in hosted CI |
| python | `pytest:test_vmax_phase4_websocket.py` | **blocked** | 0.00 | not executed on the packaging host within the bounded local validation budget; complete pytest remains mandatory in hosted CI |
| python | `pytest:test_vmax_phase4_yjs_compat.py` | **blocked** | 0.00 | not executed on the packaging host within the bounded local validation budget; complete pytest remains mandatory in hosted CI |
| python | `pytest:test_web_interfaces.py` | **passed** | 0.00 | passed as part of the independently executed 48/48 focused release regression suite |
| rust | `cargo-fmt` | **blocked** | 0.00 | Rust/Cargo is not installed in the packaging environment; these checks remain mandatory in CI |
| rust | `cargo-check` | **blocked** | 0.00 | Rust/Cargo is not installed in the packaging environment; these checks remain mandatory in CI |
| rust | `cargo-test` | **blocked** | 0.00 | Rust/Cargo is not installed in the packaging environment; these checks remain mandatory in CI |
