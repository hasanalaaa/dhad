#!/usr/bin/env bash
set -euo pipefail

task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
workspace_manifest="$task_root/Cargo.toml"
target_directory="${CARGO_TARGET_DIR:-$task_root/target}"
target_root="$target_directory/wasm32-unknown-unknown"
demo_root="$task_root/web_demo"
wasm_optimizer="${WASM_OPT:-$(command -v wasm-opt || true)}"
python_runtime="${DHAD_PYTHON:-$task_root/venv/bin/python}"

if [[ -z "$wasm_optimizer" ]]; then
  echo "error: wasm-opt (Binaryen) is required; set WASM_OPT or install binaryen" >&2
  exit 2
fi
if [[ ! -x "$python_runtime" ]]; then
  python_runtime="$(command -v python3)"
fi

cd "$task_root"
"$python_runtime" tools/export_wasm_morphology.py
"$python_runtime" tools/export_wasm_rules.py
cargo fmt --all --manifest-path "$workspace_manifest" --check
cargo test --workspace --all-targets --locked --manifest-path "$workspace_manifest"
cargo clippy --workspace --all-targets --locked --manifest-path "$workspace_manifest" -- -D warnings

CARGO_TARGET_DIR="$target_directory" RUSTFLAGS="${RUSTFLAGS:-} -C target-feature=+simd128,+bulk-memory,+mutable-globals" \
  cargo build --locked --manifest-path "$workspace_manifest" -p dhad-core --profile wasm-fast --target wasm32-unknown-unknown
CARGO_TARGET_DIR="$target_directory" \
  cargo build --locked --manifest-path "$workspace_manifest" -p dhad-core --profile wasm-small --target wasm32-unknown-unknown

fast_input="$target_root/wasm-fast/dhad_core.wasm"
small_input="$target_root/wasm-small/dhad_core.wasm"
fast_output="$demo_root/dhad_core.fast.wasm"
small_output="$demo_root/dhad_core.small.wasm"

"$wasm_optimizer" -O3 --enable-simd --enable-bulk-memory --enable-bulk-memory-opt \
  --strip-debug --strip-producers "$fast_input" -o "$fast_output"
"$wasm_optimizer" -Oz --enable-bulk-memory --enable-bulk-memory-opt \
  --strip-debug --strip-producers "$small_input" -o "$small_output"
node --input-type=module - "$fast_output" "$small_output" <<'JS'
import { readFileSync } from "node:fs";
for (const path of process.argv.slice(2)) {
  if (!WebAssembly.validate(readFileSync(path))) {
    throw new Error(`WebAssembly validation failed: ${path}`);
  }
}
JS

fast_size="$(wc -c < "$fast_output" | tr -d ' ')"
small_size="$(wc -c < "$small_output" | tr -d ' ')"
if (( fast_size >= 2000000 )); then
  echo "error: fast WASM size gate failed: ${fast_size} bytes" >&2
  exit 3
fi
if (( small_size >= fast_size )); then
  echo "error: small WASM is not smaller than fast WASM" >&2
  exit 3
fi

cp "$fast_output" "$demo_root/dhad_core.wasm"
node web_demo/packed_bridge_test.mjs
node web_demo/bench.mjs
node web_demo/abi_benchmark.mjs

"$python_runtime" - "$fast_input" "$fast_output" "$small_input" "$small_output" <<'PY'
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

fast_raw, fast, small_raw, small = map(Path, sys.argv[1:])

def metrics(raw: Path, optimized: Path, optimization: str) -> dict[str, int | str]:
    payload = optimized.read_bytes()
    return {
        "optimization": optimization,
        "pre_wasm_opt_bytes": raw.stat().st_size,
        "wasm_bytes": len(payload),
        "gzip_bytes": len(gzip.compress(payload, compresslevel=9, mtime=0)),
    }

report = {
    "abi": "dhad-packed-diagnostics-v1",
    "fast": metrics(fast_raw, fast, "wasm-opt -O3"),
    "small": metrics(small_raw, small, "wasm-opt -Oz"),
}
destination = Path("web_demo/wasm-build-metrics.json")
destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(destination.read_text(encoding="utf-8"), end="")
PY
