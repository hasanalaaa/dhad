# Dhad vMAX Apex Repository Audit

- Status: **PASSED**
- Files audited: **334**
- Bytes audited: **176843346**
- Generated: `2026-07-23T18:27:27.975062+00:00`

## Source symbols inventoried

- **javascript_functions**: 953
- **python_classes**: 210
- **python_functions**: 1233
- **rust_functions**: 179

## Automated checks

- **javascript_syntax**: passed — JavaScript syntax verified: 38 first-party files
- **shell_syntax**: passed — 1 script(s) checked
- **python_compileall**: passed — no output
- **rust_workspace**: skipped — cargo is unavailable in this validation environment

## Findings

- No audit findings.

## Audit scope

Every repository file outside reproducible dependency/build/cache directories is inventoried with size and SHA-256. First-party Python, JavaScript, JSON, and TOML receive syntax/parse validation. Binary models, WASM artifacts, images, and retained release evidence are integrity-inventoried rather than interpreted as source.
