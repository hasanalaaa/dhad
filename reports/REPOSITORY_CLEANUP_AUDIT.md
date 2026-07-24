# Dhad Repository Cleanup Audit

**Prepared for:** GitHub source release  
**Archive target:** `dhad-production-ready.zip`

## Scope

The source archive was extracted and audited before creating a separate clean repository tree. Source code, tests, documentation, Rust/WASM assets, and ONNX models were preserved. Development environments, dependency caches, generated distributions, nested archives, Git history, and operating-system metadata were excluded from the release package.

## Preservation result

- Original Git-tracked files inspected: **303**
- Missing original tracked files in the clean tree: **0**
- Preserved production ONNX model: `web_demo/models/model_int8.onnx`
- Preserved ONNX test fixture: `web_demo/neural/fixtures/student-fixture.onnx`
- Preserved Rust source, Cargo metadata, WASM binaries, vendored ONNX Runtime WASM, reports, documentation, and tests.

## Removed release clutter

| Category | Approximate logical size | Action |
|---|---:|---|
| Python virtual environment | 229.0 MB | Removed |
| `web_demo/node_modules` | 149.4 MB | Removed; reproducible with `npm ci` |
| Nested `dhad-vMAX.zip` | 63.0 MB | Removed |
| `.git` history | 11.1 MB | Removed from distributable source archive |
| Generated `dist/` packages | 2.1 MB | Removed; reproducible build output |
| pytest / Ruff caches | 0.2 MB | Removed |
| macOS `__MACOSX`, `.DS_Store`, AppleDouble metadata | 3.3 MB logical / many filesystem entries | Removed |

The repository tree was reduced from approximately **631.3 MB** logical size to approximately **176.5 MB** while retaining required runtime binaries. Most of the remaining size is the intentionally preserved quantized ONNX model.

## Repository improvements

- Replaced `README.md` with an Arabic-first, bilingual, developer-oriented release README.
- Added Rust/WebAssembly/WebGPU/PWA/E2EE badges, architecture diagram, quickstarts, directory map, privacy, security, and licensing sections.
- Added root `Cargo.toml` workspace and root `Cargo.lock` for reproducible Cargo commands from the repository root.
- Added `.gitattributes` with Git LFS tracking for `*.onnx` because the production model exceeds GitHub's ordinary 100 MiB object limit.
- Rebuilt `.gitignore` for Python, Rust, Node, browser tooling, OS metadata, local secrets, build artifacts, and archives.
- Added `.dockerignore` to prevent large browser assets and development files from inflating the Python container build context.
- Expanded GitHub Actions into independent Python, Rust, and JavaScript jobs with concurrency cancellation and timeouts.
- Regenerated `SHA256SUMS.txt` for retained ONNX and WASM production assets.
- Preserved the original vMAX release checksums under `reports/release-archives/` and marked the old nested archive metadata as historical.
- Updated the release manifest to describe the clean source-release profile and retained large assets.

## Validation performed

| Check | Result |
|---|---|
| Original tracked-file preservation | Passed — 303/303 present |
| Junk/cache scan | Passed — no matching artifacts |
| TOML / JSON / YAML parsing | Passed |
| Python `compileall` | Passed |
| JavaScript `node --check` | Passed |
| Shell `bash -n` | Passed |
| ONNX/WASM SHA-256 verification | Passed |
| Web/JavaScript test suite | Passed — **53/53** |
| ZIP integrity | Performed after packaging |

## Environment-limited checks

The full Python test suite could not be reinstalled in the packaging environment because its package index did not provide required build/development packages (`hatchling`, `annotated-doc`, and `pycrdt`), and outbound PyPI access was unavailable. The Rust suite could not be rerun because `rustc`/`cargo` were not installed. Docker runtime validation was also unavailable.

These limitations concern this packaging environment only. CI remains configured to run the full Python, Rust, and JavaScript gates on GitHub Actions.
