/**
 * Terminal benchmark + parity gate for the WASM engine (Node).
 *
 *   node web_demo/bench.mjs
 *
 * 1. Replays the Python-generated golden corpus through the WASM module and
 *    fails on any divergence (same oracle as `cargo test`).
 * 2. Benchmarks full checks at paragraph and document size, plus the
 *    tokenizer, and prints p50/p95.
 */

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { loadEngine, scalarToUtf16, utf16ToScalar } from "./dhad-core.js";

const here = dirname(fileURLToPath(import.meta.url));
const wasmBytes = readFileSync(join(here, "dhad_core.wasm"));
const rulesJson = readFileSync(join(here, "rules.json"), "utf8");
const goldenPath = join(here, "..", "rust", "dhad-core-rs", "tests", "data", "rules_golden.jsonl");

const engine = await loadEngine(wasmBytes, rulesJson);
console.log(`engine loaded: ${engine.ruleCount} portable rules, wasm ${wasmBytes.length} bytes`);

// ── Parity gate against the Python oracle ──────────────────────────────────
let checked = 0;
for (const line of readFileSync(goldenPath, "utf8").split("\n")) {
  if (!line.trim()) continue;
  const record = JSON.parse(line);
  const result = engine.check(record.text);
  const actual = result.matches.map((m) => [
    m.rule_id,
    m.offset,
    m.length,
    m.replacements[0] ?? "",
  ]);
  const actualResolved = result.resolved.map((m) => [m.rule_id, m.offset, m.length]);
  const same = JSON.stringify(actual) === JSON.stringify(record.matches);
  const sameResolved = JSON.stringify(actualResolved) === JSON.stringify(record.resolved);
  if (!same || !sameResolved) {
    console.error("PARITY FAILURE for:", JSON.stringify(record.text));
    console.error("expected:", JSON.stringify(record.matches));
    console.error("actual:  ", JSON.stringify(actual));
    process.exit(1);
  }
  checked += 1;
}
console.log(`parity vs Python oracle: ${checked}/${checked} texts identical ✔`);

const morphology = engine.analyze("وبالمدرسة", 0.9)[0];
if (
  morphology.lemma !== "مدرسة" ||
  JSON.stringify(morphology.prefixes.map((part) => [part.surface, part.start, part.end])) !==
    JSON.stringify([["و", 0, 1], ["ب", 1, 2], ["ال", 2, 4]])
) {
  throw new Error("morphology WASM contract failure");
}
const unicodeCase = "😀 هذه الكتاب";
if (scalarToUtf16(unicodeCase, 2) !== 3 || utf16ToScalar(unicodeCase, 3) !== 2) {
  throw new Error("Unicode scalar/UTF-16 bridge contract failure");
}
const parsed = engine.parse(unicodeCase);
const syntaxIssues = engine.syntaxCheck(unicodeCase);
if (parsed.sentences[0].tokens[0].start !== 2 || syntaxIssues[0]?.offset !== 2) {
  throw new Error("syntax Unicode-scalar offset contract failure");
}
console.log("morphology + syntax + Unicode offset contracts ✔");

// ── Benchmarks ─────────────────────────────────────────────────────────────
const sentence = "انا ذهبت الى المدرسه قبل ثلاثة سنوات وكان اليوم جميلا. ";
const paragraph = sentence.repeat(8); // ~440 chars
const document = sentence.repeat(180); // ~10k chars

function bench(label, text, iterations) {
  const times = [];
  for (let i = 0; i < iterations; i++) {
    const start = performance.now();
    engine.check(text);
    times.push(performance.now() - start);
  }
  times.sort((a, b) => a - b);
  const p50 = times[Math.floor(times.length * 0.5)];
  const p95 = times[Math.floor(times.length * 0.95)];
  const matches = engine.check(text).resolved.length;
  console.log(
    `${label}: chars=${text.length} resolved=${matches} ` +
      `p50=${p50.toFixed(3)}ms p95=${p95.toFixed(3)}ms (n=${iterations})`
  );
  return p50;
}

console.log("\n— full deterministic check (rules + boundary scan + dedupe) —");
const sentP50 = bench("sentence ", sentence, 400);
bench("paragraph", paragraph, 200);
bench("document ", document, 50);

const tokStart = performance.now();
for (let i = 0; i < 100; i++) engine.tokenize(document);
console.log(
  `\ntokenizer: document p50≈${((performance.now() - tokStart) / 100).toFixed(3)}ms per pass`
);

if (sentP50 > 5) {
  console.error("REGRESSION: sentence check exceeded 5ms budget");
  process.exit(1);
}
console.log("\nWASM engine: ALL GATES PASSED");
