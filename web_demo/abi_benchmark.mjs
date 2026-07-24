import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { loadEngine } from "./dhad-core.js";

const here = dirname(fileURLToPath(import.meta.url));
const wasmBytes = readFileSync(join(here, "dhad_core.wasm"));
const rulesJson = readFileSync(join(here, "rules.json"), "utf8");
const packedEngine = await loadEngine(wasmBytes, rulesJson);

// Reconstruct the pre-Phase-2 bridge against the same optimized binary. This
// deliberately measures TextEncoder allocation + dc_alloc/free + JSON output.
const { instance } = await WebAssembly.instantiate(wasmBytes, {});
const legacy = instance.exports;
const encoder = new TextEncoder();
const decoder = new TextDecoder();

function legacyInput(text, call) {
  const bytes = encoder.encode(text);
  const ptr = Number(legacy.dc_alloc(bytes.length || 1)) >>> 0;
  new Uint8Array(legacy.memory.buffer, ptr, bytes.length).set(bytes);
  try {
    return call(ptr, bytes.length);
  } finally {
    legacy.dc_free(ptr, bytes.length || 1);
  }
}

function legacyUnpack(packed) {
  const ptr = Number(packed >> 32n) >>> 0;
  const length = Number(packed & 0xffffffffn);
  const bytes = new Uint8Array(legacy.memory.buffer, ptr, length).slice();
  legacy.dc_free(ptr, length || 1);
  return JSON.parse(decoder.decode(bytes));
}

const loaded = legacyInput(rulesJson, (ptr, length) => legacy.dc_load_rules(ptr, length));
if (loaded < 0n) throw new Error("legacy benchmark rejected the rule pack");
legacy.dc_warmup();

function legacyCheck(text) {
  return legacyInput(text, (ptr, length) => legacyUnpack(legacy.dc_check(ptr, length)));
}

function percentile(values, quantile) {
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.floor(sorted.length * quantile)];
}

function compare(label, text, iterations) {
  const packedResult = packedEngine.check(text);
  const legacyResult = legacyCheck(text);
  assert.deepEqual(packedResult, legacyResult, `packed/JSON parity failure in ${label}`);
  for (let index = 0; index < 20; index += 1) {
    packedEngine.check(text);
    legacyCheck(text);
  }

  const packedTimes = [];
  const legacyTimes = [];
  const measurePacked = () => {
    const start = performance.now();
    packedEngine.check(text);
    packedTimes.push(performance.now() - start);
  };
  const measureLegacy = () => {
    const start = performance.now();
    legacyCheck(text);
    legacyTimes.push(performance.now() - start);
  };
  for (let index = 0; index < iterations; index += 1) {
    if (index % 2 === 0) {
      measurePacked();
      measureLegacy();
    } else {
      measureLegacy();
      measurePacked();
    }
  }

  const packedP50 = percentile(packedTimes, 0.5);
  const legacyP50 = percentile(legacyTimes, 0.5);
  return {
    label,
    unicode_scalars: [...text].length,
    iterations,
    packed_p50_ms: packedP50,
    packed_p95_ms: percentile(packedTimes, 0.95),
    json_p50_ms: legacyP50,
    json_p95_ms: percentile(legacyTimes, 0.95),
    p50_speedup_percent: ((legacyP50 - packedP50) / legacyP50) * 100,
  };
}

const sentence = "انا ذهبت الى المدرسه قبل ثلاثة سنوات وكان اليوم جميلا. ";
const report = {
  methodology: "interleaved same-binary packed ABI vs pre-Phase-2 JSON bridge",
  cases: [
    compare("sentence", sentence, 500),
    compare("paragraph", sentence.repeat(8), 250),
    compare("document", sentence.repeat(180), 60),
  ],
};
packedEngine.dispose();
writeFileSync(join(here, "abi-benchmark.json"), `${JSON.stringify(report, null, 2)}\n`);
console.log(JSON.stringify(report, null, 2));
