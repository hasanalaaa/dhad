# Dhad Desktop Ultimate v1.0.16 r3 — Final Validation

## CI diagnostic conclusion

The hosted CI run `30139186762` isolated two release-promotion regressions:

- **JavaScript:** `web_demo/intelligence/apex-ui.test.mjs` still asserted the v1.0.15 PWA cache namespace, while the shipped cache policy correctly contained `gold-1.0.16-desktop-goldmaster`. Hosted CI passed the other 113 JavaScript tests.
- **Rust:** a broad textual version replacement changed the valid lock entry `serde_json 1.0.151` into the nonexistent `1.0.161` without changing its checksum. Cargo therefore rejected the workspace before Clippy.

## r3 corrections

- Derive the Apex PWA cache assertion from `web_demo/package.json`, matching the version-safe Gold Master and extension contracts.
- Restore `serde_json 1.0.151` in the workspace lockfile; the resulting lockfile is identical to the previously green v1.0.15 lock except for the two first-party crate versions changing to `1.0.16`.
- Pin `serde_json = "=1.0.151"` in both Rust manifests.
- Extend the early release-version validator and desktop release audit to enforce the exact registry version and checksum.
- Add mutation coverage proving a corrupted `1.0.161` lock entry is rejected before release.

## Executed checks

- Release/version and lock-integrity contract: **PASS** (`1.0.16`, tag `v1.0.16`, `serde_json 1.0.151`).
- Corrected JavaScript release contracts: **6/6 PASS**.
- Hosted JavaScript evidence before the correction: **113/114 PASS**, with the single failure being the corrected stale assertion.
- Focused Python release regressions: **37/37 PASS**.
- JavaScript syntax: **PASS**, 58 first-party files.
- Frontend runtime closure: **PASS**, 44 allowlisted files and no dependency/test leakage.
- Desktop release audit: **205/205 PASS**.
- Sovereign release audit: **71/71 PASS**.
- Repository audit: **PASS**, 0 findings.
- Cargo lock comparison: **PASS**; only `dhad-core` and `dhad-desktop` versions differ from the previously green v1.0.15 lock.
- Deterministic ZIP packaging and extracted-archive revalidation: **PASS**.

## Honest environment limits

- Cargo and native macOS/Windows runners are unavailable in this container, so the final Clippy and installer builds remain gated by GitHub Actions.
- A fresh `npm ci` could not complete in the network-isolated packaging environment. The corrected affected JavaScript files run without external dependencies; hosted CI had already passed every other JavaScript test in the same run.

## Release gate

1. Install r3 over the current v1.0.16 source using checksum-based synchronization.
2. Run the complete local JavaScript suite on the user Mac.
3. Commit and require all three general CI jobs to pass.
4. Create immutable tag `v1.0.16` only after green CI.
5. Require both DMGs, NSIS, MSI, their native verifiers, and atomic publication to pass.

Keep `v1.0.15` immutable and do not restore the old stash until the native release is complete.
