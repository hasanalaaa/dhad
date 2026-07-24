import assert from "node:assert/strict";
import test from "node:test";

import {
  WordPieceTokenizer,
  collectMorphologyRequests,
  cosineSimilarity,
  meanPool,
  rankCandidateEmbeddings,
  selectConstrainedCandidate,
  stableSoftmax,
  validateRankRequest,
} from "./neural-core.js";

const CANDIDATES = Object.freeze([
  Object.freeze({ id: "كتب|verb|كتب", value: "كتب", lemma: "كتب", pos: "verb", root: "كتب" }),
  Object.freeze({ id: "كتاب|noun|كتب", value: "كتب", lemma: "كتاب", pos: "noun", root: "كتب" }),
]);

test("stableSoftmax remains normalized for extreme logits", () => {
  const probabilities = stableSoftmax([10_000, 9_998, -10_000], 0.5);
  assert.equal(probabilities.length, 3);
  assert.ok(probabilities.every(Number.isFinite));
  assert.ok(Math.abs(probabilities.reduce((sum, value) => sum + value, 0) - 1) < 1e-12);
  assert.ok(probabilities[0] > probabilities[1]);
});

test("candidate selection can only return an exact Rust candidate", () => {
  const decision = selectConstrainedCandidate(CANDIDATES, [12, 0], {
    confidenceThreshold: 0.999,
    marginThreshold: 0.99,
    temperature: 1,
  });
  assert.equal(decision.abstained, false);
  assert.equal(decision.selectedIndex, 0);
  assert.strictEqual(decision.selected, CANDIDATES[0]);
  assert.ok(decision.confidence >= 0.999);
});

test("candidate selection abstains below the 99.9 percent gate", () => {
  const decision = selectConstrainedCandidate(CANDIDATES, [1.0, 0.9], {
    confidenceThreshold: 0.999,
    marginThreshold: 0.5,
    temperature: 1,
  });
  assert.deepEqual(decision, {
    abstained: true,
    reason: "low_confidence",
    confidence: decision.confidence,
    margin: decision.margin,
  });
  assert.ok(decision.confidence < 0.999);
});

test("rank request validation rejects malformed or duplicate candidate identities", () => {
  const base = {
    requestId: "r1",
    sentence: "كتب الطالب الدرس",
    sentenceStart: 0,
    tokenIndex: 0,
    tokens: ["كتب", "الطالب", "الدرس"],
    targetStart: 0,
    targetEnd: 3,
    candidates: CANDIDATES,
  };
  assert.equal(validateRankRequest(base).requestId, "r1");
  assert.throws(
    () => validateRankRequest({ ...base, candidates: [CANDIDATES[0], CANDIDATES[0]] }),
    /duplicate candidate id/,
  );
  assert.throws(() => validateRankRequest({ ...base, tokenIndex: 9 }), /tokenIndex/);
  assert.throws(() => validateRankRequest({ ...base, sentence: "" }), /sentence/);
});

test("WordPiece maps Arabic text to padded model tensors without inventing ids", () => {
  const vocab = [
    "[PAD]",
    "[UNK]",
    "[CLS]",
    "[SEP]",
    "كتب",
    "الطالب",
    "الدرس",
    "كتاب",
    "noun",
    "verb",
    ".",
  ].join("\n");
  const tokenizer = WordPieceTokenizer.fromVocabText(vocab, {
    maxLength: 12,
    lowercase: false,
  });
  const encoded = tokenizer.encodePair("كتب الطالب الدرس", "كتاب noun");
  assert.deepEqual(encoded.inputIds, [2, 4, 5, 6, 3, 7, 8, 3, 0, 0, 0, 0]);
  assert.deepEqual(encoded.attentionMask, [1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0]);
  assert.deepEqual(encoded.tokenTypeIds, [0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0, 0]);
  assert.ok(encoded.inputIds.every((id) => Number.isInteger(id) && id >= 0 && id < 11));
});

test("WordPiece uses greedy continuation pieces and bounded unknown handling", () => {
  const tokenizer = WordPieceTokenizer.fromVocabText(
    ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "مدر", "##سة"].join("\n"),
    { maxLength: 8 },
  );
  assert.deepEqual(tokenizer.tokenize("مدرسة"), ["مدر", "##سة"]);
  assert.deepEqual(tokenizer.tokenize("كلمةغيرمعروفة"), ["[UNK]"]);
});

test("Rust parse alternatives become immutable, source-anchored ranking requests", () => {
  const analysis = {
    token: "كتب",
    lemma: "كتب",
    root: "كتب",
    pos: "verb",
    confidence: 0.81,
  };
  const duplicate = { ...analysis, confidence: 0.70 };
  const noun = { ...analysis, lemma: "كتاب", pos: "noun", confidence: 0.79 };
  const parsed = {
    sentences: [
      {
        text: "كتب الطالب الدرس",
        start: 5,
        tokens: [
          { text: "كتب", start: 5, end: 8, analysis, alternatives: [duplicate, noun] },
          { text: "الطالب", start: 9, end: 15, analysis: { ...analysis, lemma: "طالب", pos: "noun" }, alternatives: [] },
        ],
      },
    ],
  };
  const requests = collectMorphologyRequests(parsed);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].sentence, "كتب الطالب الدرس");
  assert.equal(requests[0].sentenceStart, 5);
  assert.equal(requests[0].targetStart, 5);
  assert.deepEqual(requests[0].candidates.map((candidate) => candidate.id), [
    "كتب|verb|كتب",
    "كتاب|noun|كتب",
  ]);
  assert.ok(Object.isFrozen(requests[0]));
  assert.ok(Object.isFrozen(requests[0].candidates));
});

test("mean pooling and cosine logits rank only the supplied embedding rows", () => {
  // Batch rows: original context, candidate 0, candidate 1. Shape [3, 2, 2].
  const hidden = new Float32Array([
    1, 0, 1, 0,
    0.99, 0.01, 1, 0,
    0, 1, 0, 1,
  ]);
  const mask = new BigInt64Array([1n, 1n, 1n, 1n, 1n, 1n]);
  const pooled = meanPool(hidden, [3, 2, 2], mask);
  assert.ok(cosineSimilarity(pooled[0], pooled[1]) > cosineSimilarity(pooled[0], pooled[2]));
  const ranked = rankCandidateEmbeddings(CANDIDATES, pooled, {
    confidenceThreshold: 0.999,
    marginThreshold: 0.99,
    temperature: 0.01,
  });
  assert.equal(ranked.abstained, false);
  assert.strictEqual(ranked.selected, CANDIDATES[0]);
});
