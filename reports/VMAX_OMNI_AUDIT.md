# Dhad vMAX Omni Repository Audit

- Status: **PASSED**
- Files audited: **324**
- Bytes audited: **176690685**
- Generated: `2026-07-23T03:32:37.140242+00:00`

## Source symbols inventoried

- **javascript_functions**: 917
- **python_classes**: 200
- **python_functions**: 1211
- **rust_functions**: 177

## Automated checks

- **javascript_syntax**: passed — JavaScript syntax verified: 35 first-party files
- **shell_syntax**: passed — 1 script(s) checked
- **python_compileall**: passed — no output
- **rust_workspace**: skipped — cargo is unavailable in this validation environment

## Findings

- No audit findings.

## Audit scope

Every repository file outside reproducible dependency/build/cache directories is inventoried with size and SHA-256. First-party Python, JavaScript, JSON, and TOML receive syntax/parse validation. Binary models, WASM artifacts, images, and retained release evidence are integrity-inventoried rather than interpreted as source.
