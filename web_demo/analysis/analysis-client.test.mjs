import assert from "node:assert/strict";
import test from "node:test";

import { AnalysisWorkerClient } from "./analysis-client.js";

class FakeWorker extends EventTarget {
  sent = [];
  terminated = false;

  postMessage(message) {
    this.sent.push(message);
  }

  emit(data) {
    this.dispatchEvent(new MessageEvent("message", { data }));
  }

  terminate() {
    this.terminated = true;
  }
}

test("deterministic checks cross the worker boundary and preserve Arabic diagnostics", async () => {
  const worker = new FakeWorker();
  const client = new AnalysisWorkerClient({ workerFactory: () => worker, timeoutMs: 1_000 });
  const pending = client.check("انا اكتب", "all");
  assert.equal(worker.sent.length, 1);
  assert.deepEqual(
    { text: worker.sent[0].text, mode: worker.sent[0].mode },
    { text: "انا اكتب", mode: "all" },
  );
  worker.emit({
    type: "checked",
    operationId: worker.sent[0].operationId,
    result: { resolved: [{ rule_id: "HAMZA", offset: 0, length: 3 }], parsed: null, elapsedMs: 2 },
  });
  assert.equal((await pending).resolved[0].rule_id, "HAMZA");
  client.dispose();
  assert.equal(worker.terminated, true);
});

test("worker protocol rejects malformed responses", async () => {
  const worker = new FakeWorker();
  const client = new AnalysisWorkerClient({ workerFactory: () => worker, timeoutMs: 1_000 });
  const pending = client.check("نص", "style");
  worker.emit({ type: "checked", operationId: worker.sent[0].operationId, result: { resolved: null } });
  await assert.rejects(pending, /invalid analysis result/u);
  client.dispose();
});

test("synchronous worker dispatch failures reject cleanly without leaking pending work", async () => {
  const worker = new FakeWorker();
  worker.postMessage = () => {
    throw new DOMException("cannot clone payload", "DataCloneError");
  };
  const client = new AnalysisWorkerClient({ workerFactory: () => worker, timeoutMs: 1_000 });
  await assert.rejects(client.check("نص", "all"), /cannot clone payload/u);
  assert.equal(client.pending.size, 0);
  client.dispose();
});

test("analysis preferences cross the worker boundary with bounded copies", async () => {
  const worker = new FakeWorker();
  const client = new AnalysisWorkerClient({ workerFactory: () => worker, timeoutMs: 1_000 });
  const customWords = ["ضاد"];
  const disabledRules = ["RULE_X"];
  const pending = client.check("ضاد", "all", { customWords, disabledRules });
  customWords.push("متأخر");
  disabledRules.push("RULE_Y");
  assert.deepEqual(worker.sent[0].preferences, {
    customWords: ["ضاد"],
    disabledRules: ["RULE_X"],
  });
  worker.emit({
    type: "checked",
    operationId: worker.sent[0].operationId,
    result: {
      resolved: [],
      parsed: null,
      intelligence: { tone: { primary: "formal" } },
      elapsedMs: 1,
    },
  });
  assert.equal((await pending).intelligence.tone.primary, "formal");
  client.dispose();
});

test("analysis preferences reject unbounded payloads before worker dispatch", async () => {
  const worker = new FakeWorker();
  const client = new AnalysisWorkerClient({ workerFactory: () => worker, timeoutMs: 1_000 });
  await assert.rejects(
    client.check("نص", "all", { customWords: new Array(5_001).fill("كلمة") }),
    /safety bounds/u,
  );
  assert.equal(worker.sent.length, 0);
  client.dispose();
});
