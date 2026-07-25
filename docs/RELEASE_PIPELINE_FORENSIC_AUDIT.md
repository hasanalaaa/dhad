# Dhad Desktop — Release Pipeline Forensic Audit (v1.0.19)

Independent audit of the repository at commit `8807331` (tag `v1.0.18`), performed
without trusting any previously retained validation report. Every claim below was
re-derived from the repository, from the pinned upstream sources of Tauri 2.11.5 /
tauri-runtime-wry 2.11.4 / tauri-bundler (tag `tauri-cli-v2.11.4`), from
`tauri-apps/tauri-action@v1`'s own source, and from GitHub's REST documentation.

## 1. The symptom, restated correctly

The reported symptom was "local validation passes, Desktop Release keeps failing".
The measurable facts are narrower and more useful:

* `ci.yml` has been green for many consecutive runs.
* The Desktop Release build matrix has been *succeeding* — runs took 28–41 minutes,
  which is a completed multi-platform build, not an early failure.
* No release has ever been published. The `v1.0.18` tag exists; the Releases page
  shows nothing.

So the pipeline was not failing to build. It was failing to *publish*, at the last
job, after every expensive build had already succeeded.

## 2. Root cause of the failed releases (release-blocking)

### 2.1 A draft release cannot be found by tag

`publish` located the release with:

```js
const { data: release } = await github.rest.repos.getReleaseByTag({ owner, repo, tag });
```

GitHub documents that endpoint as "Get **a published release** with the specified
tag". Draft releases are excluded from it entirely. `tauri-action` knows this and
says so in its own source:

```ts
// you can't get a an existing draft by tag
// so we must find one in the list of all releases
```

`tauri-action` therefore uploaded the installers to a draft correctly, and then the
`publish` job 404-ed looking for that same draft. Deterministic, on every tag, after
30–40 minutes of successful building. This is the failure the last eight releases hit.

**Fix.** A new `prepare-release` job creates the draft exactly once, locating any
pre-existing draft through `repos.listReleases` pagination (which does include drafts
for callers with push access), and exports its numeric id. The build matrix passes
`releaseId` to `tauri-action` and no longer passes `tagName`. `publish` reads the
release by id with `repos.getRelease`, verifies the asset set, and flips
`draft: false` on that same id. This is the pattern `tauri-action`'s own
`publish-to-manual-release` example documents.

### 2.2 Four parallel jobs racing to create the same draft

Because every matrix job called `tauri-action` with `tagName`, each job independently
looked up and — on a miss — created its own draft for the tag. Two jobs reaching that
step close together produce duplicate drafts holding a subset of the installers each,
which no publish gate can then satisfy. Passing a single pre-created `releaseId`
removes the race by construction.

### 2.3 Reused drafts accumulated stale assets

Re-running a tag reused the previous attempt's draft with its old assets still
attached. `prepare-release` now deletes existing assets from a reused draft, so a
re-run is idempotent, and `publish` additionally rejects any asset whose
`state !== 'uploaded'`.

## 3. Latent build-integrity defects (CI-only, invisible locally)

### 3.1 A validator that mutated its own inputs

`tools/optimize_onnx_assets.py` rewrote `web_demo/models/model_int8.onnx` **in place**
whenever metadata stripping produced a smaller file. The model's SHA-256 is pinned in
`web_demo/models/student-manifest.json` and `SHA256SUMS.txt`, and
`tools/build_web_dist.mjs` re-verifies it during `beforeBuildCommand` on every
`tauri build`. Any rewrite therefore breaks the build several steps later.

The divergence is precisely local-versus-CI: the rewrite path only runs when the
optional `onnx` package is importable, and CI installs `onnx==1.22.0` from
`tools/desktop-build-requirements.txt`. Measured today the model is already
size-optimal, so the bomb had not gone off — it was one dependency bump away.

Two further hazards in the same function: the 135 MB candidate was written as a
`.tmp` file *inside* the tracked model directory (and `.tmp` is a release blocker in
three separate hygiene validators), and `EXCLUDED_SCAN_DIRS` did not exclude
`web_dist`, so the generated frontend copy was scanned and would have been rewritten
too.

**Fix.** Verification is now the default and rewriting is opt-in behind `--optimize`;
candidates are serialized into a temporary directory outside the repository; and
`web_dist` is excluded from discovery.

### 3.2 A version bump was guaranteed to break Windows CI

`scripts/test-windows-installer-verifier.ps1` built its fixtures from the literal
`'1.0.18'` and compared them against the version read from `tauri.conf.json`.
Verified empirically: running the previous script against version 1.0.19 fails with
`A matching uninstall entry was rejected.` Any release after 1.0.18 would have broken
the `windows-installer-contracts` job for a reason unrelated to the installer.

**Fix.** The fixtures derive `$productName` and `$productVersion` from the verifier's
own configuration read, and a new negative case asserts that an uninstall entry left
by a *different* version does not match. Executed under PowerShell 7.4.6: PASS.

## 4. Validators that could not fail, and validators that could not catch

This is the mechanism behind "local validators always pass".

| Defect | Evidence | Fix |
| --- | --- | --- |
| `validate_desktop_release.py --strict` was a no-op | literally `if args.strict and warnings: pass` | `--strict` now fails on warnings |
| ~60 checks asserted that the workflow *text* contained certain substrings | `('cargo test', r"\bcargo\s+test\b")` and 50 more | replaced by `tools/validate_workflows.py`, which parses the YAML |
| Repository cleanliness never ran in CI | both workflows passed `--skip-cleanliness` | the check is now git-aware and runs unconditionally |
| Dead branch in the version validator | `expected = distinct[0] if len(distinct) == 1 else None` inside the `len(distinct) != 1` branch | simplified |

`tools/validate_workflows.py` checks properties that can actually break a release:
the job graph and its dependency edges, `prepare-release`'s `release_id` output, the
build matrix covering all four installers, `--bundles`/`--target` agreeing with each
matrix entry, `tauri-action` receiving `releaseId` and *not* `tagName`, the absence of
`getReleaseByTag` anywhere, every third-party action pinned to a tag rather than a
moving branch, every `tools/`/`scripts/` path a step executes existing on disk, every
job carrying a timeout, `actions/checkout` requesting LFS, `--locked` on every cargo
invocation, and pinned versions agreeing with their single source of truth
(`rust-toolchain.toml`, `.nvmrc`, `src-tauri/Cargo.toml`, the validated CLI profile).

Run against the repository as received, that validator reports exactly the four
contracts CI was missing — which is what a validator earning its name should do.

## 5. macOS correctness

### 5.1 The transparent overlay shipped opaque

`app.windows[mini-assistant]` sets `"transparent": true`, with
`"backgroundColor": "#00000000"` and a runtime `Effect::HudWindow` vibrancy effect —
a design that only works on a transparent window. Neither `app.macOSPrivateApi` nor
the `macos-private-api` Cargo feature was enabled. In `tauri-runtime-wry` 2.11.4:

```rust
#[cfg(any(not(target_os = "macos"), feature = "macos-private-api"))]
{ window = window.transparent(config.transparent); }

#[cfg(all(target_os = "macos", not(feature = "macos-private-api"), debug_assertions))]
if config.transparent { eprintln!("The window is set to be transparent but ...") }
```

On macOS without the feature the transparency call is compiled out, and the warning
exists only under `debug_assertions` — so a release build is silently opaque with no
diagnostic. `tauri-cli` does not add the feature for you; grepping 2.11.4 for
`macos-private-api` finds no occurrence in the CLI.

**Fix.** `app.macOSPrivateApi: true` in `tauri.conf.json` *and*
`features = ["macos-private-api", "tray-icon"]` in `src-tauri/Cargo.toml`, plus a new
audit contract asserting the two halves are never present without each other.
Verified that `cargo clippy --locked` still resolves, so `Cargo.lock` is unaffected.

### 5.2 Dictation was denied by the hardened runtime

`web_demo/app.js` uses `window.SpeechRecognition || window.webkitSpeechRecognition`.
The bundle enables `hardenedRuntime: true` with a completely empty
`Entitlements.plist` and an `Info.plist` carrying no microphone usage description.
Under the hardened runtime that combination denies microphone access, and touching a
privacy-sensitive resource with no usage description terminates the process.
`validate_desktop_release.py` actively *required* the entitlements file to be an empty
dictionary, so the correct configuration was forbidden by a wrong contract.

**Fix.** `NSMicrophoneUsageDescription` and `NSSpeechRecognitionUsageDescription`
added to `Info.plist`; `com.apple.security.device.audio-input` added to
`Entitlements.plist`; the audit contract replaced with a least-privilege check that
allows exactly that one entitlement and requires it only while the frontend actually
uses speech recognition.

### 5.3 Retracted finding: Apple signing

`bundle.macOS.signingIdentity: "-"` initially looked like it would dead-letter the
workflow's Apple certificate plumbing. It does not:
`tauri-cli/src/interface/rust.rs` reads `APPLE_SIGNING_IDENTITY` first and falls back
to the config value only when the variable is unset. The configuration is correct as
written and was deliberately left alone.

## 6. Verified sound — no change made

Checked against upstream sources rather than assumed:

* **NSIS desktop shortcut.** `verify-windows-installer.ps1` hard-requires
  `$productName.lnk` on the user or common desktop. `installer.nsi` creates it
  unconditionally except in `/UPDATE` or `/NS` mode; a plain `/S` install creates it.
  The contract is correct.
* **MSI code page.** `main.wxs` stamps `SummaryCodepage="!(loc.TauriCodepage)"`
  (1252 for `en-US`), so Arabic strings reaching the MSI would break `light.exe`.
  Everything that reaches it — `product_name`, `manufacturer`, both descriptions — is
  ASCII after the `tauri.windows.conf.json` merge, and the one non-ASCII survivor
  (`©` in `copyright`) is Latin-1 representable and unused by the template.
* **Action refs.** `actions/checkout@v5`, `setup-node@v6`, `setup-python@v7`,
  `github-script@v9`, `upload-artifact@v4`, `Swatinem/rust-cache@v2`,
  `tauri-apps/tauri-action@v1`, `dtolnay/rust-toolchain@1.97.1` all resolve.

## 7. Accepted, documented, not fixed

**The frontend closure embeds 165,592,508 bytes into the executable.**
`build_web_dist.mjs` stages a 135 MB INT8 ONNX model and a 24 MB onnxruntime-web
binary into `web_dist`, and `frontendDist` assets are embedded at compile time by
`generate_context!`. That is the real explanation for 28–41 minute platform builds and
~200 MB installers, and it is the largest remaining production-readiness debt.

It is *not* fixed here, deliberately. The correct fix moves the heavy assets to
`bundle.resources` and loads them over the asset protocol, which touches the JS
loading path, the CSP, `assetProtocol` scope, the closure validator and both
installers — and cannot be verified from a Linux host with no macOS or Windows
runner. Shipping an unverifiable structural change into a release that has failed
eight times in a row is how this pipeline got here. The migration is specified as the
next unit of work.

Lower-priority debt recorded rather than changed:

* `requirements-dev.lock` pins `numpy==2.5.1`, which needs Python ≥ 3.12, while
  `pyproject.toml` advertises `requires-python = ">=3.10"`.
* `reports/` holds ~90 accumulated historical artifacts, four of which CI regenerates
  on every run, so the committed copies are permanently stale. They belong in release
  artifacts, not in version control.
* `script-src` includes `'unsafe-eval'` in addition to `'wasm-unsafe-eval'`.

## 8. Verification performed for v1.0.19

Executed in a Linux container with Python 3.12 (matching CI), Node 22, and the locked
dependency set:

| Check | Result |
| --- | --- |
| `pytest -q` | 1851 passed, 1 skipped |
| `ruff check src tests tools benchmarks gunicorn_conf.py` | clean |
| `python -m compileall -q src tests tools benchmarks` | clean |
| `npm run check --prefix web_demo` | 58 first-party files verified |
| `npm test --prefix web_demo` | 114 passed |
| `cargo fmt --all -- --check` | clean |
| `cargo clippy --workspace --all-targets --locked -- -D warnings` | clean |
| `cargo test --workspace --all-targets --locked` | 23 passed, including `dhad-desktop` with the 165 MB frontend embedded |
| `node tools/build_web_dist.mjs` | 44 allowlisted files, exact closure |
| `tools/validate_release_version.py --tag v1.0.19` | PASS |
| `tools/validate_workflows.py` | PASS |
| `tools/validate_tauri_config.py` | PASS |
| `tools/validate_desktop_release.py --strict` | 186/186 |
| `tools/validate_sovereign_release.py --strict` | 71/71, cleanliness included |
| `tools/audit_repository.py` | PASS |
| `tools/optimize_onnx_assets.py` | verified, tree unmodified |
| `scripts/test-windows-installer-verifier.ps1` (PowerShell 7.4.6) | PASS |
| `sha256sum -c SHA256SUMS.txt` | 6/6 OK |

**Not verifiable off-runner, and stated as such:** the macOS DMG bundles and their
launch smoke test, the Windows NSIS install/shortcut/uninstall lifecycle, the MSI
`light.exe` bundling and administrative extraction, and
`cargo build --target wasm32-unknown-unknown` (the audit host cannot reach
`static.rust-lang.org` to install the target). Those four remain the responsibility of
the `macos-15`, `macos-15-intel`, and `windows-2022` legs.
