import assert from "node:assert/strict";
import test from "node:test";

import { WordPieceTokenizer } from "./neural-core.js";
import {
  buildCandidateBatch,
  buildCandidateSuperBatch,
  createFeeds,
  createSessionWithFallback,
  fetchVerifiedAsset,
  NeuralInferenceRuntime,
  sha256Hex,
  validateModelManifest,
} from "./neural-runtime.js";

const request = {
  requestId: "r1",
  sentence: "كتب الطالب الدرس",
  sentenceStart: 0,
  tokenIndex: 0,
  tokens: ["كتب", "الطالب", "الدرس"],
  targetStart: 0,
  targetEnd: 3,
  candidates: [
    { id: "كتب|verb|كتب", value: "كتب", lemma: "كتب", pos: "verb", root: "كتب", prior: 0 },
    { id: "كتاب|noun|كتب", value: "كتب", lemma: "كتاب", pos: "noun", root: "كتب", prior: 0 },
  ],
};

const manifest = {
  format: 1,
  id: "student-test",
  contract: "dhad-context-embedding-ranker-v1",
  model: { url: "model.onnx", sha256: "a".repeat(64), quantization: "int8" },
  tokenizer: {
    type: "wordpiece",
    url: "vocab.txt",
    sha256: "b".repeat(64),
    lowercase: false,
  },
  inputs: { inputIds: "input_ids", attentionMask: "attention_mask" },
  output: { name: "last_hidden_state" },
  maxLength: 16,
  thresholds: { confidence: 0.999, margin: 0.5, temperature: 0.05 },
};

test("model manifest requires a pinned INT8 model and a 99.9 percent gate", () => {
  const validated = validateModelManifest(manifest, new URL("https://example.test/models/manifest.json"));
  assert.equal(validated.model.url.href, "https://example.test/models/model.onnx");
  assert.equal(validated.tokenizer.url.href, "https://example.test/models/vocab.txt");
  assert.equal(validated.thresholds.confidence, 0.999);
  assert.throws(
    () => validateModelManifest({ ...manifest, thresholds: { ...manifest.thresholds, confidence: 0.998 } }),
    /at least 0.999/,
  );
  assert.throws(
    () => validateModelManifest({ ...manifest, model: { ...manifest.model, quantization: "fp32" } }),
    /INT8 or UINT8/,
  );
  assert.throws(
    () => validateModelManifest({ ...manifest, model: { ...manifest.model, expectedBytes: -1 } }),
    /expectedBytes/,
  );
});

test("session creation attempts WebGPU first and falls back to WASM SIMD", async () => {
  const calls = [];
  const wasmSession = { inputNames: ["input_ids", "attention_mask"] };
  const ort = {
    InferenceSession: {
      async create(_bytes, options) {
        calls.push(options.executionProviders);
        if (options.executionProviders[0] === "webgpu") throw new Error("adapter rejected");
        return wasmSession;
      },
    },
  };
  const result = await createSessionWithFallback(ort, new Uint8Array([1]), {
    webgpuAvailable: true,
  });
  assert.strictEqual(result.session, wasmSession);
  assert.equal(result.provider, "wasm-simd");
  assert.deepEqual(calls, [["webgpu", "wasm"], ["wasm"]]);
  assert.match(result.webgpuError, /adapter rejected/);
});

test("session creation skips WebGPU when the browser exposes no adapter", async () => {
  const calls = [];
  const sessionOptions = [];
  const ort = {
    InferenceSession: {
      async create(_bytes, options) {
        calls.push(options.executionProviders);
        sessionOptions.push(options);
        return {};
      },
    },
  };
  const result = await createSessionWithFallback(ort, new Uint8Array([1]), {
    webgpuAvailable: false,
  });
  assert.equal(result.provider, "wasm-simd");
  assert.deepEqual(calls, [["wasm"]]);
  assert.equal(sessionOptions[0].logSeverityLevel, 3);
});

test("candidate batch is one context row plus only candidate-derived rows", () => {
  const tokenizer = WordPieceTokenizer.fromVocabText(
    [
      "[PAD]", "[UNK]", "[CLS]", "[SEP]", "كتب", "الطالب", "الدرس",
      "فعل", "اسم", "كتاب", "الجذر", "؛",
    ].join("\n"),
    { maxLength: 16 },
  );
  const batch = buildCandidateBatch(tokenizer, request);
  assert.equal(batch.rows, 3);
  assert.equal(batch.sequenceLength, 16);
  assert.equal(batch.inputIds.length, 48);
  assert.equal(batch.attentionMask.length, 48);
  assert.ok(batch.inputIds instanceof BigInt64Array);
  assert.ok(batch.attentionMask instanceof BigInt64Array);
});

test("multiple morphology decisions are coalesced into one contiguous inference batch", () => {
  const tokenizer = WordPieceTokenizer.fromVocabText(
    [
      "[PAD]", "[UNK]", "[CLS]", "[SEP]", "كتب", "الطالب", "الدرس",
      "فعل", "اسم", "كتاب", "الجذر", "؛",
    ].join("\n"),
    { maxLength: 16 },
  );
  const second = { ...request, requestId: "r2", targetStart: 4, targetEnd: 10 };
  const batch = buildCandidateSuperBatch(tokenizer, [request, second]);
  assert.equal(batch.rows, 6);
  assert.equal(batch.items.length, 2);
  assert.deepEqual(batch.items.map(({ rowStart, rowEnd }) => [rowStart, rowEnd]), [[0, 3], [3, 6]]);
  assert.equal(batch.inputIds.length, 96);
  assert.throws(() => buildCandidateSuperBatch(tokenizer, []), /between 1 and 64/);
});

test("feed construction follows manifest names and declared integer dtypes", () => {
  class Tensor {
    constructor(type, data, dimensions) {
      this.type = type;
      this.data = data;
      this.dims = dimensions;
    }
  }
  const ort = { Tensor };
  const batch = {
    rows: 2,
    sequenceLength: 4,
    inputIds: new BigInt64Array(8),
    attentionMask: new BigInt64Array(8).fill(1n),
    tokenTypeIds: new BigInt64Array(8),
  };
  const feeds = createFeeds(ort, batch, {
    inputIds: "ids",
    attentionMask: "mask",
    tokenTypeIds: "segments",
  });
  assert.deepEqual(Object.keys(feeds), ["ids", "mask", "segments"]);
  assert.equal(feeds.ids.type, "int64");
  assert.deepEqual(feeds.ids.dims, [2, 4]);
  assert.strictEqual(feeds.mask.data, batch.attentionMask);
});

test("verified asset loading rejects oversized payloads before buffering them", async () => {
  const previousFetch = globalThis.fetch;
  let bodyRead = false;
  globalThis.fetch = async () => ({
    ok: true,
    status: 200,
    headers: new Headers({ "content-length": "999" }),
    body: {
      getReader() {
        bodyRead = true;
        throw new Error("body must not be read");
      },
    },
  });
  try {
    await assert.rejects(
      fetchVerifiedAsset(new URL("https://example.test/model.onnx"), "a".repeat(64), 10),
      /length mismatch/,
    );
    assert.equal(bodyRead, false);
  } finally {
    globalThis.fetch = previousFetch;
  }
});


test("verified asset streaming accepts an exact pre-sized payload", async () => {
  const previousFetch = globalThis.fetch;
  const payload = new TextEncoder().encode("[PAD]\n[UNK]\n[CLS]\n[SEP]\n");
  const digest = await sha256Hex(payload);
  globalThis.fetch = async () => new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(payload.subarray(0, 7));
        controller.enqueue(payload.subarray(7));
        controller.close();
      },
    }),
    { headers: { "content-length": String(payload.byteLength) } },
  );
  try {
    const loaded = await fetchVerifiedAsset(
      new URL("https://example.test/vocab.txt"),
      digest,
      payload.byteLength,
    );
    assert.deepEqual(loaded, payload);
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test("concurrent runtime initialization coalesces into one model session", async () => {
  const previousFetch = globalThis.fetch;
  const vocab = new TextEncoder().encode("[PAD]\n[UNK]\n[CLS]\n[SEP]\nكتب\n");
  const model = new Uint8Array([1, 2, 3, 4]);
  const runtimeManifest = {
    ...manifest,
    model: {
      ...manifest.model,
      sha256: await sha256Hex(model),
      expectedBytes: model.byteLength,
    },
    tokenizer: { ...manifest.tokenizer, sha256: await sha256Hex(vocab) },
  };
  let manifestFetches = 0;
  let sessionCreations = 0;
  let releases = 0;
  globalThis.fetch = async (target) => {
    const pathname = new URL(target).pathname;
    if (pathname.endsWith("manifest.json")) {
      manifestFetches += 1;
      return Response.json(runtimeManifest);
    }
    if (pathname.endsWith("model.onnx")) return new Response(model);
    if (pathname.endsWith("vocab.txt")) return new Response(vocab);
    throw new Error(`unexpected fetch: ${target}`);
  };
  const ort = {
    InferenceSession: {
      async create() {
        sessionCreations += 1;
        await Promise.resolve();
        return {
          inputNames: ["input_ids", "attention_mask"],
          outputNames: ["last_hidden_state"],
          async release() { releases += 1; },
        };
      },
    },
  };
  try {
    const runtime = new NeuralInferenceRuntime(ort);
    const [first, second] = await Promise.all([
      runtime.initialize("https://example.test/models/manifest.json"),
      runtime.initialize("https://example.test/models/manifest.json"),
    ]);
    assert.deepEqual(first, second);
    assert.equal(first.ready, true);
    assert.equal(manifestFetches, 1);
    assert.equal(sessionCreations, 1);
    await runtime.dispose();
    assert.equal(releases, 1);
    assert.equal(runtime.status().ready, false);
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test("disposing during initialization aborts in-flight model network work", async () => {
  const previousFetch = globalThis.fetch;
  let observedAbort = false;
  globalThis.fetch = async (_target, { signal } = {}) => new Promise((_resolve, reject) => {
    signal?.addEventListener("abort", () => {
      observedAbort = true;
      reject(new DOMException("aborted", "AbortError"));
    }, { once: true });
  });
  const ort = { InferenceSession: { async create() { throw new Error("must not create"); } } };
  try {
    const runtime = new NeuralInferenceRuntime(ort);
    const initialization = runtime.initialize("https://example.test/models/manifest.json");
    await Promise.resolve();
    await runtime.dispose();
    await assert.rejects(initialization, /aborted/i);
    assert.equal(observedAbort, true);
    assert.equal(runtime.status().ready, false);
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test("super batches reject duplicate request ids before allocating inference tensors", () => {
  const tokenizer = WordPieceTokenizer.fromVocabText(
    ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "كتب", "الطالب", "الدرس"].join("\n"),
    { maxLength: 16 },
  );
  assert.throws(() => buildCandidateSuperBatch(tokenizer, [request, request]), /duplicate request ids/);
});
