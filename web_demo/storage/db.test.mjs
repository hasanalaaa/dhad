import assert from "node:assert/strict";
import test from "node:test";

import { IDBFactory } from "fake-indexeddb";

import {
  DB_VERSION,
  DhadStorage,
  OutboxRecovery,
  withQuotaRecovery,
} from "./db.js";

function createStorage() {
  return new DhadStorage({
    indexedDB: new IDBFactory(),
    navigator: {
      storage: {
        estimate: async () => ({ usage: 1_024, quota: 1_048_576 }),
        persist: async () => true,
      },
      serviceWorker: { ready: Promise.resolve({ sync: { register: async () => undefined } }) },
    },
  });
}

test("versioned database persists every offline data class", async () => {
  const storage = createStorage();
  await storage.open();
  assert.equal(storage.version, DB_VERSION);

  await storage.putDocument({ id: "doc-1", title: "مسودة", content: "لغة عربية" });
  await storage.appendYjsUpdate("doc-1", new Uint8Array([1, 2, 3]), { sequence: 7 });
  await storage.enqueueOutbox({ id: "job-1", documentId: "doc-1", kind: "yjs", payload: [7] });
  await storage.putDictionary({ id: "personal", words: ["ضاد", "العراق"] });
  await storage.setSetting("theme", "obsidian");

  assert.equal((await storage.getDocument("doc-1")).content, "لغة عربية");
  assert.deepEqual(Array.from((await storage.listYjsUpdates("doc-1"))[0].update), [1, 2, 3]);
  assert.equal((await storage.listOutbox())[0].id, "job-1");
  assert.deepEqual((await storage.getDictionary("personal")).words, ["ضاد", "العراق"]);
  assert.equal(await storage.getSetting("theme"), "obsidian");
  storage.close();
});

test("multi-store transaction rolls back atomically when its callback fails", async () => {
  const storage = createStorage();
  await assert.rejects(
    storage.transaction(["documents", "settings"], "readwrite", (stores) => {
      stores.documents.put({ id: "rolled-back", content: "لا تحفظ" });
      stores.settings.put({ key: "rolled-back", value: true });
      throw new Error("abort batch");
    }),
    /abort batch/u,
  );
  assert.equal(await storage.getDocument("rolled-back"), null);
  assert.equal(await storage.getSetting("rolled-back"), null);
  storage.close();
});

test("quota recovery compacts safe records once and retries the write", async () => {
  let writes = 0;
  let cleanups = 0;
  const result = await withQuotaRecovery(
    async () => {
      writes += 1;
      if (writes === 1) throw new DOMException("full", "QuotaExceededError");
      return "stored";
    },
    async () => {
      cleanups += 1;
    },
  );
  assert.equal(result, "stored");
  assert.equal(writes, 2);
  assert.equal(cleanups, 1);
});

test("online recovery acknowledges successes and retains retry metadata for failures", async () => {
  const storage = createStorage();
  await storage.enqueueOutbox({ id: "ok", kind: "update", payload: [1] });
  await storage.enqueueOutbox({ id: "retry", kind: "update", payload: [2] });
  const onlineTarget = new EventTarget();
  const seen = [];
  const recovery = new OutboxRecovery(storage, async (entry) => {
    seen.push(entry.id);
    if (entry.id === "retry") throw new Error("offline again");
  }, { onlineTarget, now: () => 10_000, retryBaseMs: 100 });

  recovery.start();
  onlineTarget.dispatchEvent(new Event("online"));
  await recovery.whenIdle();
  recovery.stop();

  assert.deepEqual(seen.sort(), ["ok", "retry"]);
  const remaining = await storage.listOutbox();
  assert.equal(remaining.length, 1);
  assert.equal(remaining[0].id, "retry");
  assert.equal(remaining[0].attempts, 1);
  assert.equal(remaining[0].nextAttemptAt, 10_100);
  storage.close();
});

test("Yjs update reads are isolated by the documentId index", async () => {
  const storage = createStorage();
  await storage.appendYjsUpdate("doc-a", new Uint8Array([1]), { sequence: 1 });
  await storage.appendYjsUpdate("doc-b", new Uint8Array([2]), { sequence: 1 });
  const updates = await storage.listYjsUpdates("doc-a");
  assert.equal(updates.length, 1);
  assert.equal(updates[0].documentId, "doc-a");
  assert.deepEqual(Array.from(updates[0].update), [1]);
  storage.close();
});

test("online recovery heals a previously rejected infrastructure flush", async () => {
  const storage = createStorage();
  await storage.enqueueOutbox({ id: "eventual", kind: "update", payload: [1] });
  const originalListDueOutbox = storage.listDueOutbox.bind(storage);
  let reads = 0;
  storage.listDueOutbox = async (...args) => {
    reads += 1;
    if (reads === 1) throw new Error("temporary database failure");
    return originalListDueOutbox(...args);
  };
  const onlineTarget = new EventTarget();
  const sent = [];
  const reported = [];
  const recovery = new OutboxRecovery(storage, async (entry) => sent.push(entry.id), {
    onlineTarget,
    onError: (error) => reported.push(error),
  });
  recovery.start();
  onlineTarget.dispatchEvent(new Event("online"));
  await assert.rejects(recovery.whenIdle(), /temporary database failure/);
  assert.equal(reported.length, 1);
  onlineTarget.dispatchEvent(new Event("online"));
  await recovery.whenIdle();
  recovery.stop();
  assert.deepEqual(sent, ["eventual"]);
  assert.deepEqual(await storage.listOutbox(), []);
  storage.close();
});

test("automatic Yjs sequences are atomic across tabs sharing one database", async () => {
  const indexedDB = new IDBFactory();
  const navigator = { storage: { persist: async () => true } };
  const first = new DhadStorage({ indexedDB, navigator });
  const second = new DhadStorage({ indexedDB, navigator });
  const originalNow = Date.now;
  Date.now = () => 1_700_000_000_000;
  try {
    const records = await Promise.all([
      first.appendYjsUpdate("shared", new Uint8Array([1])),
      second.appendYjsUpdate("shared", new Uint8Array([2])),
      first.appendYjsUpdate("shared", new Uint8Array([3])),
    ]);
    const sequences = records.map((record) => record.sequence);
    assert.equal(new Set(sequences).size, 3);
    const persisted = await first.listYjsUpdates("shared");
    assert.deepEqual(persisted.map((record) => record.sequence), [...sequences].sort((a, b) => a - b));
    assert.deepEqual(persisted.map((record) => Array.from(record.update)).sort(), [[1], [2], [3]]);
  } finally {
    Date.now = originalNow;
    first.close();
    second.close();
  }
});

test("invalid explicit Yjs sequences fail before opening a transaction", async () => {
  const storage = createStorage();
  await assert.rejects(
    storage.appendYjsUpdate("doc", new Uint8Array([1]), { sequence: -1 }),
    /non-negative safe integer/,
  );
  await assert.rejects(
    storage.appendYjsUpdate("doc", new Uint8Array([1]), { sequence: Number.MAX_SAFE_INTEGER + 1 }),
    /non-negative safe integer/,
  );
  storage.close();
});

test("due outbox scanning uses the nextAttemptAt index and a hard batch limit", async () => {
  const storage = createStorage();
  for (let index = 0; index < 5; index += 1) {
    await storage.enqueueOutbox({
      id: `job-${index}`,
      kind: "update",
      createdAt: index,
      nextAttemptAt: index < 4 ? 10 : 1000,
    });
  }
  const due = await storage.listDueOutbox(10, 2);
  assert.deepEqual(due.map((entry) => entry.id), ["job-0", "job-1"]);
  storage.close();
});
