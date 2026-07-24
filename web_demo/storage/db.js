export const DB_NAME = "dhad-vmax";
export const DB_VERSION = 2;
export const OUTBOX_SYNC_TAG = "dhad-outbox-sync";

const STORE_NAMES = Object.freeze([
  "documents",
  "yjsUpdates",
  "outbox",
  "dictionaries",
  "settings",
  "analyticsHistory",
]);

function requestResult(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("IndexedDB request failed"));
  });
}

function isRequest(value) {
  return value && typeof value === "object" && "onsuccess" in value && "onerror" in value;
}

function cloneBytes(value) {
  if (value instanceof Uint8Array) return new Uint8Array(value);
  if (value instanceof ArrayBuffer) return new Uint8Array(value.slice(0));
  if (ArrayBuffer.isView(value)) {
    return new Uint8Array(value.buffer.slice(value.byteOffset, value.byteOffset + value.byteLength));
  }
  if (Array.isArray(value)) return Uint8Array.from(value);
  throw new TypeError("binary update must be an ArrayBuffer, TypedArray, or byte array");
}

function requireId(value, name = "id") {
  if (typeof value !== "string" || value.trim().length === 0 || value.length > 256) {
    throw new TypeError(`${name} must be a non-empty string of at most 256 characters`);
  }
  return value;
}

function createStore(database, name, options) {
  return database.objectStoreNames.contains(name)
    ? null
    : database.createObjectStore(name, options);
}

function installSchema(database) {
  const documents = createStore(database, "documents", { keyPath: "id" });
  documents?.createIndex("updatedAt", "updatedAt");
  const updates = createStore(database, "yjsUpdates", { keyPath: ["documentId", "sequence"] });
  updates?.createIndex("documentId", "documentId");
  const outbox = createStore(database, "outbox", { keyPath: "id" });
  outbox?.createIndex("nextAttemptAt", "nextAttemptAt");
  createStore(database, "dictionaries", { keyPath: "id" });
  createStore(database, "settings", { keyPath: "key" });
  const analytics = createStore(database, "analyticsHistory", { keyPath: "id" });
  analytics?.createIndex("documentId", "documentId");
  analytics?.createIndex("capturedAt", "capturedAt");
}

export async function withQuotaRecovery(operation, cleanup) {
  try {
    return await operation();
  } catch (error) {
    if (error?.name !== "QuotaExceededError") throw error;
    await cleanup();
    return operation();
  }
}


export class DhadStorage {
  constructor({ indexedDB = globalThis.indexedDB, navigator = globalThis.navigator } = {}) {
    if (!indexedDB || typeof indexedDB.open !== "function") {
      throw new Error("IndexedDB is unavailable in this runtime");
    }
    this.indexedDB = indexedDB;
    this.navigator = navigator;
    this.database = null;
    this.opening = null;
  }

  get version() {
    return this.database?.version ?? DB_VERSION;
  }

  async open() {
    if (this.database) return this.database;
    if (this.opening) return this.opening;
    this.opening = new Promise((resolve, reject) => {
      const request = this.indexedDB.open(DB_NAME, DB_VERSION);
      let settled = false;
      const fail = (error) => {
        if (settled) return;
        settled = true;
        reject(error);
      };
      request.onupgradeneeded = () => installSchema(request.result);
      request.onblocked = () => fail(new Error("IndexedDB upgrade is blocked by another tab"));
      request.onerror = () => fail(request.error ?? new Error("IndexedDB open failed"));
      request.onsuccess = () => {
        const database = request.result;
        if (settled) {
          database.close();
          return;
        }
        settled = true;
        database.onversionchange = () => {
          database.close();
          if (this.database === database) this.database = null;
        };
        database.onclose = () => {
          if (this.database === database) this.database = null;
        };
        this.database = database;
        resolve(database);
      };
    }).finally(() => {
      this.opening = null;
    });
    const database = await this.opening;
    void this.requestPersistentStorage();
    return database;
  }

  async requestPersistentStorage() {
    try {
      await this.navigator?.storage?.persist?.();
    } catch {
      return false;
    }
    return true;
  }

  async quota() {
    const estimate = await this.navigator?.storage?.estimate?.();
    return Object.freeze({ usage: estimate?.usage ?? null, quota: estimate?.quota ?? null });
  }

  async transaction(storeNames, mode, callback) {
    const names = Array.isArray(storeNames) ? storeNames : [storeNames];
    if (!names.length || names.some((name) => !STORE_NAMES.includes(name))) {
      throw new RangeError("transaction contains an unknown store");
    }
    if (!new Set(["readonly", "readwrite"]).has(mode)) throw new RangeError("invalid transaction mode");
    if (typeof callback !== "function") throw new TypeError("transaction callback is required");
    const database = await this.open();
    return new Promise((resolve, reject) => {
      const tx = database.transaction(names, mode);
      const stores = Object.fromEntries(names.map((name) => [name, tx.objectStore(name)]));
      let callbackValue;
      let callbackError = null;
      let settled = false;
      const fail = (error) => {
        if (settled) return;
        settled = true;
        reject(error);
      };
      tx.oncomplete = () => {
        if (settled) return;
        settled = true;
        resolve(isRequest(callbackValue) ? callbackValue.result : callbackValue);
      };
      tx.onerror = () => fail(callbackError ?? tx.error ?? new Error("IndexedDB transaction failed"));
      tx.onabort = () => fail(callbackError ?? tx.error ?? new Error("IndexedDB transaction aborted"));
      try {
        callbackValue = callback(stores, tx);
        if (callbackValue && typeof callbackValue.then === "function") {
          throw new TypeError("IndexedDB transaction callbacks must enqueue requests synchronously");
        }
      } catch (error) {
        callbackError = error;
        try {
          tx.abort();
        } catch {
          fail(error);
        }
      }
    });
  }

  async get(storeName, key) {
    const value = await this.transaction(storeName, "readonly", (stores) => stores[storeName].get(key));
    return value ?? null;
  }

  async getAll(storeName) {
    return this.transaction(storeName, "readonly", (stores) => stores[storeName].getAll());
  }

  async putWithRecovery(storeName, record) {
    return withQuotaRecovery(
      () => this.transaction(storeName, "readwrite", (stores) => stores[storeName].put(record)),
      () => this.compactSafeRecords(),
    );
  }

  async putDocument(document) {
    const id = requireId(document?.id, "document.id");
    if (typeof document.content !== "string") throw new TypeError("document.content must be a string");
    const now = Date.now();
    const record = Object.freeze({
      ...document,
      id,
      title: typeof document.title === "string" ? document.title : "",
      createdAt: Number.isFinite(document.createdAt) ? document.createdAt : now,
      updatedAt: Number.isFinite(document.updatedAt) ? document.updatedAt : now,
    });
    await this.putWithRecovery("documents", record);
    return record;
  }

  getDocument(id) {
    return this.get("documents", requireId(id));
  }

  listDocuments() {
    return this.getAll("documents").then((records) => records.sort((a, b) => b.updatedAt - a.updatedAt));
  }

  async appendAnalyticsSnapshot(documentId, metrics, { capturedAt = Date.now() } = {}) {
    const id = requireId(documentId, "documentId");
    if (!metrics || typeof metrics !== "object" || Array.isArray(metrics)) {
      throw new TypeError("analytics metrics must be an object");
    }
    if (!Number.isFinite(capturedAt) || capturedAt < 0) throw new RangeError("capturedAt must be a non-negative timestamp");
    const record = Object.freeze({
      id: `${id}:${Math.trunc(capturedAt)}:${globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2)}`,
      documentId: id,
      capturedAt: Math.trunc(capturedAt),
      clarityScore: Number(metrics.clarityScore) || 0,
      engagementScore: Number(metrics.engagementScore) || 0,
      vocabularyRichness: Number(metrics.vocabularyRichness) || 0,
      complexityScore: Number(metrics.complexityScore) || 0,
      words: Number.isSafeInteger(metrics.words) ? metrics.words : 0,
    });
    await this.putWithRecovery("analyticsHistory", record);
    return record;
  }

  async listAnalyticsHistory(documentId, { limit = 60 } = {}) {
    const id = requireId(documentId, "documentId");
    if (!Number.isInteger(limit) || limit < 1 || limit > 500) throw new RangeError("analytics history limit must be between one and 500");
    const records = await this.transaction("analyticsHistory", "readonly", (stores) =>
      stores.analyticsHistory.index("documentId").getAll(id),
    );
    return records.sort((a, b) => a.capturedAt - b.capturedAt).slice(-limit);
  }

  async appendYjsUpdate(documentId, update, { sequence, compacted = false } = {}) {
    const id = requireId(documentId, "documentId");
    if (sequence !== undefined && (!Number.isSafeInteger(sequence) || sequence < 0)) {
      throw new RangeError("Yjs sequence must be a non-negative safe integer");
    }
    const updateBytes = cloneBytes(update);
    const counterKey = `yjs-sequence:${id}`;

    const write = async () => {
      let record = null;
      await this.transaction(["settings", "yjsUpdates"], "readwrite", (stores) => {
        const counter = stores.settings.get(counterKey);
        counter.onsuccess = () => {
          const previous = Number.isSafeInteger(counter.result?.value) ? counter.result.value : -1;
          const wallClockFloor = Date.now() * 1_000;
          const resolvedSequence = sequence ?? Math.max(previous + 1, wallClockFloor);
          if (!Number.isSafeInteger(resolvedSequence) || resolvedSequence < 0) {
            throw new RangeError("Yjs sequence exhausted the safe integer range");
          }
          record = Object.freeze({
            documentId: id,
            sequence: resolvedSequence,
            update: new Uint8Array(updateBytes),
            compacted: Boolean(compacted),
            createdAt: Date.now(),
          });
          stores.settings.put({ key: counterKey, value: Math.max(previous, resolvedSequence) });
          stores.yjsUpdates.put(record);
        };
      });
      if (record === null) throw new Error("IndexedDB did not allocate a Yjs sequence");
      return record;
    };

    return withQuotaRecovery(write, () => this.compactSafeRecords());
  }

  async listYjsUpdates(documentId) {
    const id = requireId(documentId, "documentId");
    const records = await this.transaction("yjsUpdates", "readonly", (stores) =>
      stores.yjsUpdates.index("documentId").getAll(id),
    );
    return records.sort((a, b) => a.sequence - b.sequence);
  }

  async enqueueOutbox(entry) {
    const id = requireId(entry?.id ?? globalThis.crypto?.randomUUID?.() ?? `outbox-${Date.now()}`);
    const record = Object.freeze({
      ...entry,
      id,
      kind: requireId(entry?.kind, "outbox.kind"),
      attempts: Number.isSafeInteger(entry.attempts) ? entry.attempts : 0,
      nextAttemptAt: Number.isFinite(entry.nextAttemptAt) ? entry.nextAttemptAt : 0,
      createdAt: Number.isFinite(entry.createdAt) ? entry.createdAt : Date.now(),
    });
    await this.putWithRecovery("outbox", record);
    await this.registerBackgroundSync();
    return record;
  }

  listOutbox() {
    return this.getAll("outbox").then((records) => records.sort((a, b) => a.createdAt - b.createdAt));
  }

  async listDueOutbox(now = Date.now(), limit = 256) {
    if (!Number.isFinite(now)) throw new TypeError("outbox due time must be finite");
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > 10_000) {
      throw new RangeError("outbox due limit must be between 1 and 10000");
    }
    const records = [];
    await this.transaction("outbox", "readonly", (stores) => {
      const request = stores.outbox.index("nextAttemptAt").openCursor();
      request.onsuccess = () => {
        const cursor = request.result;
        if (cursor === null || records.length >= limit) return;
        if ((cursor.value.nextAttemptAt ?? 0) > now) return;
        records.push(cursor.value);
        cursor.continue();
      };
    });
    return records.sort((a, b) => a.createdAt - b.createdAt);
  }

  acknowledgeOutbox(id) {
    return this.transaction("outbox", "readwrite", (stores) => stores.outbox.delete(requireId(id)));
  }

  async markOutboxRetry(entry, nextAttemptAt) {
    return this.putWithRecovery("outbox", {
      ...entry,
      attempts: (entry.attempts ?? 0) + 1,
      nextAttemptAt,
      lastAttemptAt: Date.now(),
    });
  }

  async putDictionary(dictionary) {
    const id = requireId(dictionary?.id, "dictionary.id");
    if (!Array.isArray(dictionary.words) || dictionary.words.some((word) => typeof word !== "string")) {
      throw new TypeError("dictionary.words must be an array of strings");
    }
    const record = Object.freeze({ ...dictionary, id, words: [...new Set(dictionary.words)], updatedAt: Date.now() });
    await this.putWithRecovery("dictionaries", record);
    return record;
  }

  getDictionary(id) {
    return this.get("dictionaries", requireId(id));
  }

  async setSetting(key, value) {
    requireId(key, "setting key");
    await this.putWithRecovery("settings", { key, value, updatedAt: Date.now() });
    return value;
  }

  async getSetting(key) {
    const record = await this.get("settings", requireId(key, "setting key"));
    return record?.value ?? null;
  }

  async compactSafeRecords() {
    const [updates, outbox] = await Promise.all([this.getAll("yjsUpdates"), this.getAll("outbox")]);
    const compactedKeys = updates
      .filter((record) => record.compacted === true)
      .map((record) => [record.documentId, record.sequence]);
    const acknowledgedIds = outbox.filter((record) => record.acknowledged === true).map((record) => record.id);
    if (!compactedKeys.length && !acknowledgedIds.length) return 0;
    await this.transaction(["yjsUpdates", "outbox"], "readwrite", (stores) => {
      for (const key of compactedKeys) stores.yjsUpdates.delete(key);
      for (const id of acknowledgedIds) stores.outbox.delete(id);
    });
    return compactedKeys.length + acknowledgedIds.length;
  }

  async registerBackgroundSync() {
    try {
      const registration = await this.navigator?.serviceWorker?.ready;
      await registration?.sync?.register?.(OUTBOX_SYNC_TAG);
      return true;
    } catch {
      return false;
    }
  }

  close() {
    this.database?.close();
    this.database = null;
  }
}

export class OutboxRecovery {
  constructor(
    storage,
    sender,
    {
      onlineTarget = globalThis,
      now = () => Date.now(),
      retryBaseMs = 1_000,
      retryCapMs = 5 * 60_000,
      maxBatchEntries = 256,
      onError = () => {},
    } = {},
  ) {
    if (!(storage instanceof DhadStorage)) throw new TypeError("storage must be a DhadStorage instance");
    if (typeof sender !== "function") throw new TypeError("outbox sender must be a function");
    if (typeof onError !== "function") throw new TypeError("onError must be a function");
    this.storage = storage;
    this.sender = sender;
    this.onError = onError;
    this.onlineTarget = onlineTarget;
    this.now = now;
    if (!Number.isFinite(retryBaseMs) || retryBaseMs <= 0) {
      throw new RangeError("retryBaseMs must be positive");
    }
    if (!Number.isFinite(retryCapMs) || retryCapMs < retryBaseMs) {
      throw new RangeError("retryCapMs must be at least retryBaseMs");
    }
    if (!Number.isSafeInteger(maxBatchEntries) || maxBatchEntries < 1 || maxBatchEntries > 10_000) {
      throw new RangeError("maxBatchEntries must be between 1 and 10000");
    }
    this.retryBaseMs = retryBaseMs;
    this.retryCapMs = retryCapMs;
    this.maxBatchEntries = maxBatchEntries;
    this.idle = Promise.resolve();
    this.started = false;
    this.handleOnline = () => {
      this.idle = this.idle.catch(() => undefined).then(() => this.flush());
      void this.idle.catch((error) => {
        try {
          this.onError(error);
        } catch {
          // Error observers must never destabilize the recovery queue.
        }
      });
    };
  }

  start() {
    if (this.started) return;
    this.started = true;
    this.onlineTarget.addEventListener("online", this.handleOnline);
  }

  stop() {
    if (!this.started) return;
    this.started = false;
    this.onlineTarget.removeEventListener("online", this.handleOnline);
  }

  whenIdle() {
    return this.idle;
  }

  async flush() {
    const currentTime = this.now();
    const due = await this.storage.listDueOutbox(currentTime, this.maxBatchEntries);
    for (const entry of due) {
      try {
        await this.sender(entry);
        await this.storage.acknowledgeOutbox(entry.id);
      } catch {
        const exponent = Math.min(entry.attempts ?? 0, 16);
        const delay = Math.min(this.retryCapMs, this.retryBaseMs * 2 ** exponent);
        await this.storage.markOutboxRetry(entry, currentTime + delay);
      }
    }
    return due.length;
  }
}
