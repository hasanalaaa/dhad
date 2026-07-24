# Dhad 1.0 Gold Master Repository Audit

- Status: **PASSED**
- Files audited: **437**
- Bytes audited: **179993949**
- Generated: `2026-07-24T00:56:02.087385+00:00`

## Source symbols inventoried

- **javascript_functions**: 1167
- **python_classes**: 236
- **python_functions**: 1313
- **rust_functions**: 238

## Automated checks

- **javascript_syntax**: passed — JavaScript syntax verified: 57 first-party files
- **shell_syntax**: passed — 2 script(s) checked
- **python_compileall**: passed — no output
- **rust_workspace**: skipped — cargo is unavailable in this validation environment

## Findings

- No audit findings.

## Audit scope

Every repository file outside reproducible dependency/build/cache directories is inventoried with size and SHA-256. First-party Python, JavaScript, JSON, and TOML receive syntax/parse validation. Binary models, WASM artifacts, images, and retained release evidence are integrity-inventoried rather than interpreted as source.
