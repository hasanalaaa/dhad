# Dhad 1.0 Gold Master Repository Audit

- Status: **PASSED**
- Files audited: **451**
- Bytes audited: **180253296**
- Generated: `2026-07-25T02:11:50.996467+00:00`

## Source symbols inventoried

- **javascript_functions**: 1197
- **python_classes**: 237
- **python_functions**: 1368
- **rust_functions**: 241

## Automated checks

- **javascript_syntax**: passed — JavaScript syntax verified: 58 first-party files
- **shell_syntax**: passed — 4 script(s) checked
- **python_compileall**: passed — no output
- **rust_workspace**: skipped — cargo is unavailable in this validation environment

## Findings

- No audit findings.

## Audit scope

Every repository file outside reproducible dependency/build/cache directories is inventoried with size and SHA-256. First-party Python, JavaScript, JSON, and TOML receive syntax/parse validation. Binary models, WASM artifacts, images, and retained release evidence are integrity-inventoried rather than interpreted as source.
