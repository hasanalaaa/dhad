import assert from "node:assert/strict";
import test from "node:test";

import { NeuralInferenceClient } from "./neural-client.js";

const REQUEST = Object.freeze({
  requestId: "morph:0:0:0",
  sentence: "كتب الطالب الدرس",
  sentenceStart: 0,
  tokenIndex: 0,
  tokens: Object.freeze(["كتب", "الطالب", "الدرس"]),
  targetStart: 0,
  targetEnd: 3,
  candidates: Object.freeze([
    Object.freeze({ id: "كتب|verb|كتب", value: "كتب", lemma: "كتب", pos: "verb", root: "كتب" }),
    Object.freeze({ id: "كتاب|noun|كتب", value: "كتب", lemma: "كتاب", pos: "noun", root: "كتب" }),
  ]),
});

class FakeWorker {
  constructor() {
    this.sent = [];
    this.listeners = new Map();
    this.terminated = false;
  }

  postMessage(message) {
    this.sent.push(message);
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) ?? [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  removeEventListener(type, listener) {
    this.listeners.set(type, (this.listeners.get(type) ?? []).filter((value) => value !== listener));
  }

  emit(type, data) {
    for (const listener of this.listeners.get(type) ?? []) listener({ data, currentTarget: this });
  }

  fail(error) {
    for (const listener of this.listeners.get("error") ?? []) {
      listener({ error, currentTarget: this });
    }
  }

  terminate() {
    this.terminated = true;
  }
}

function createClient() {
  const worker = new FakeWorker();
  const client = new NeuralInferenceClient({
    workerFactory: () => worker,
    manifestUrl: new URL("https://example.test/student.json"),
    timeoutMs: 1_000,
  });
  return { client, worker };
}

test("initialization is delegated to the dedicated module worker", async () => {
  const { client, worker } = createClient();
  const ready = client.initialize();
  assert.equal(worker.sent.length, 1);
  assert.equal(worker.sent[0].type, "init");
  assert.equal(worker.sent[0].manifestUrl, "https://example.test/student.json");
  worker.emit("message", {
    type: "ready",
    operationId: worker.sent[0].operationId,
    status: { ready: true, provider: "webgpu-preferred", modelId: "student" },
  });
  assert.equal((await ready).provider, "webgpu-preferred");
  await client.dispose();
});

test("a valid decision resolves to the exact original Rust candidate object", async () => {
  const { client, worker } = createClient();
  const pending = client.rank(REQUEST);
  const init = worker.sent[0];
  worker.emit("message", {
    type: "ready",
    operationId: init.operationId,
    status: { ready: true, provider: "wasm-simd", modelId: "student" },
  });
  await new Promise((resolve) => setImmediate(resolve));
  const rank = worker.sent[1];
  assert.equal(rank.type, "rank");
  worker.emit("message", {
    type: "ranked",
    operationId: rank.operationId,
    result: {
      requestId: REQUEST.requestId,
      abstained: false,
      selectedIndex: 1,
      selectedCandidateId: REQUEST.candidates[1].id,
      confidence: 0.9995,
      margin: 0.9991,
      provider: "wasm-simd",
      elapsedMs: 3,
    },
  });
  const decision = await pending;
  assert.strictEqual(decision.selected, REQUEST.candidates[1]);
  assert.equal(decision.selectedIndex, 1);
  await client.dispose();
});

test("forged, out-of-range, or mismatched worker selections are rejected", async () => {
  for (const forged of [
    { selectedIndex: 7, selectedCandidateId: "دخيل" },
    { selectedIndex: 0, selectedCandidateId: REQUEST.candidates[1].id },
  ]) {
    const { client, worker } = createClient();
    const pending = client.rank(REQUEST);
    worker.emit("message", {
      type: "ready",
      operationId: worker.sent[0].operationId,
      status: { ready: true, provider: "wasm-simd", modelId: "student" },
    });
    await new Promise((resolve) => setImmediate(resolve));
    const rank = worker.sent[1];
    worker.emit("message", {
      type: "ranked",
      operationId: rank.operationId,
      result: {
        requestId: REQUEST.requestId,
        abstained: false,
        ...forged,
        confidence: 1,
        margin: 1,
        provider: "wasm-simd",
        elapsedMs: 1,
      },
    });
    await assert.rejects(pending, /violated the candidate-only contract/);
    await client.dispose();
  }
});

test("abstentions carry no candidate and preserve the strict confidence decision", async () => {
  const { client, worker } = createClient();
  const pending = client.rank(REQUEST);
  worker.emit("message", {
    type: "ready",
    operationId: worker.sent[0].operationId,
    status: { ready: true, provider: "wasm-simd", modelId: "student" },
  });
  await new Promise((resolve) => setImmediate(resolve));
  const rank = worker.sent[1];
  worker.emit("message", {
    type: "ranked",
    operationId: rank.operationId,
    result: {
      requestId: REQUEST.requestId,
      abstained: true,
      reason: "low_confidence",
      confidence: 0.8,
      margin: 0.2,
      provider: "wasm-simd",
      elapsedMs: 1,
    },
  });
  const decision = await pending;
  assert.equal(decision.abstained, true);
  assert.equal("selected" in decision, false);
  await client.dispose();
});

test("rankMany crosses the worker boundary once and validates every grouped decision", async () => {
  const { client, worker } = createClient();
  const second = Object.freeze({ ...REQUEST, requestId: "morph:0:1:4" });
  const pending = client.rankMany([REQUEST, second]);
  worker.emit("message", {
    type: "ready",
    operationId: worker.sent[0].operationId,
    status: { ready: true, provider: "wasm-simd", modelId: "student" },
  });
  await new Promise((resolve) => setImmediate(resolve));
  const operation = worker.sent[1];
  assert.equal(operation.type, "rank-many");
  assert.equal(operation.requests.length, 2);
  worker.emit("message", {
    type: "ranked-many",
    operationId: operation.operationId,
    results: [REQUEST, second].map((item) => ({
      requestId: item.requestId,
      abstained: true,
      reason: "low_confidence",
      confidence: 0.7,
      margin: 0.1,
      provider: "wasm-simd",
      elapsedMs: 4,
    })),
  });
  const decisions = await pending;
  assert.deepEqual(decisions.map((decision) => decision.requestId), [REQUEST.requestId, second.requestId]);
  await client.dispose();
});

test("dispose terminates the worker and rejects outstanding work", async () => {
  const { client, worker } = createClient();
  const pending = client.rank(REQUEST);
  await client.dispose();
  assert.equal(worker.terminated, true);
  await assert.rejects(pending, /disposed/);
  await assert.rejects(client.rank(REQUEST), /disposed/);
});



test("a crashed worker is discarded and the next initialization uses a fresh worker", async () => {
  const workers = [new FakeWorker(), new FakeWorker()];
  const client = new NeuralInferenceClient({
    workerFactory: () => workers.shift(),
    manifestUrl: new URL("https://example.test/student.json"),
    timeoutMs: 1_000,
  });

  const first = client.initialize();
  const crashed = client.worker;
  crashed.fail(new Error("GPU process crashed"));
  await assert.rejects(first, /GPU process crashed/);
  assert.equal(crashed.terminated, true);
  assert.equal(client.worker, null);

  const second = client.initialize();
  const replacement = client.worker;
  assert.notStrictEqual(replacement, crashed);
  replacement.emit("message", {
    type: "ready",
    operationId: replacement.sent[0].operationId,
    status: { ready: true, provider: "wasm-simd", modelId: "student" },
  });
  assert.equal((await second).ready, true);
  await client.dispose();
});

test("a synchronous postMessage failure cannot poison future retries", async () => {
  class BrokenWorker extends FakeWorker {
    postMessage() { throw new Error("structured clone failed"); }
  }
  const replacement = new FakeWorker();
  const workers = [new BrokenWorker(), replacement];
  const client = new NeuralInferenceClient({
    workerFactory: () => workers.shift(),
    manifestUrl: new URL("https://example.test/student.json"),
    timeoutMs: 1_000,
  });
  await assert.rejects(client.initialize(), /structured clone failed/);
  assert.equal(client.worker, null);
  const ready = client.initialize();
  replacement.emit("message", {
    type: "ready",
    operationId: replacement.sent[0].operationId,
    status: { ready: true, provider: "wasm-simd", modelId: "student" },
  });
  assert.equal((await ready).provider, "wasm-simd");
  await client.dispose();
});
