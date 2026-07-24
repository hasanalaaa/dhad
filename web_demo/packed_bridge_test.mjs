import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { loadEngine } from "./dhad-core.js";

const here = dirname(fileURLToPath(import.meta.url));
const wasmBytes = readFileSync(join(here, "dhad_core.wasm"));
const rulesJson = readFileSync(join(here, "rules.json"), "utf8");
const engine = await loadEngine(wasmBytes, rulesJson);

const baseline = engine.liveDocumentCount();
const document = engine.createDocument("ذهبت الى المدرسه قبل ثلاثة سنوات.");
assert.equal(engine.liveDocumentCount(), baseline + 1);

const view = document.analyzeView();
assert.ok(view.recordsBytes instanceof Uint8Array);
assert.ok(view.stringsBytes instanceof Uint8Array);
assert.equal(view.revision, 1);
const result = view.toObject();
assert.deepEqual(
  result.matches.map((match) => [
    match.rule_id,
    match.offset,
    match.length,
    match.severity,
    match.replacements,
  ]),
  [
    ["HAMZA_ILA", 5, 3, "error", ["إلى"]],
    ["TAA_MADRASA", 9, 7, "error", ["المدرسة"]],
  ],
);
assert.deepEqual(
  result.resolved.map((match) => [match.rule_id, match.offset, match.length]),
  [
    ["HAMZA_ILA", 5, 3],
    ["TAA_MADRASA", 9, 7],
  ],
);

document.update("ذهبت إلى المدرسة قبل ثلاث سنوات.");
assert.throws(() => view.toObject(), /stale packed diagnostics view/);
const corrected = document.analyzeView().toObject();
assert.equal(corrected.matches.length, 0);
assert.equal(corrected.resolved.length, 0);

document.dispose();
assert.equal(engine.liveDocumentCount(), baseline);
assert.throws(() => document.update("نص"), /disposed document/);

// `check` preserves the original UI contract but reuses one persistent scratch
// document and decodes records directly from WASM memory.
assert.equal(engine.check("انا هنا").resolved[0].rule_id, "HAMZA_ANA");
assert.equal(engine.liveDocumentCount(), baseline + 1);
engine.check("لا أخطاء");
assert.equal(engine.liveDocumentCount(), baseline + 1);
engine.dispose();
assert.equal(engine.liveDocumentCount(), 0);

console.log("packed ABI bridge lifecycle + parity: PASS");
