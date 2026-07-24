import { validateRankRequest } from "./neural-core.js";

const DEFAULT_TIMEOUT_MS = 120_000;

function errorFromWorker(payload) {
  const message = typeof payload?.message === "string" ? payload.message : "neural worker failed";
  const error = new Error(message);
  error.name = typeof payload?.name === "string" ? payload.name : "NeuralWorkerError";
  return error;
}

function requireFiniteUnit(value, name) {
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0 || number > 1) {
    throw new Error(`neural worker returned an invalid ${name}`);
  }
  return number;
}

function validateWorkerDecision(result, request, originalCandidates) {
  if (result === null || typeof result !== "object" || Array.isArray(result)) {
    throw new Error("neural worker returned an invalid decision");
  }
  if (result.requestId !== request.requestId) {
    throw new Error("neural worker returned a decision for another request");
  }
  const confidence = requireFiniteUnit(result.confidence, "confidence");
  const margin = requireFiniteUnit(result.margin, "margin");
  const provider = typeof result.provider === "string" ? result.provider : "unknown";
  const elapsedMs = Number(result.elapsedMs);
  if (!Number.isFinite(elapsedMs) || elapsedMs < 0) {
    throw new Error("neural worker returned an invalid latency");
  }
  if (result.abstained === true) {
    return Object.freeze({
      requestId: request.requestId,
      abstained: true,
      reason: typeof result.reason === "string" ? result.reason : "abstained",
      confidence,
      margin,
      provider,
      elapsedMs,
    });
  }
  const selectedIndex = Number(result.selectedIndex);
  const selected = originalCandidates[selectedIndex];
  if (
    result.abstained !== false ||
    !Number.isInteger(selectedIndex) ||
    selected === undefined ||
    result.selectedCandidateId !== request.candidates[selectedIndex]?.id ||
    result.selectedCandidateId !== selected.id
  ) {
    throw new Error("neural worker violated the candidate-only contract");
  }
  return Object.freeze({
    requestId: request.requestId,
    abstained: false,
    selectedIndex,
    selectedCandidateId: selected.id,
    selected,
    confidence,
    margin,
    provider,
    elapsedMs,
  });
}

export class NeuralInferenceClient {
  constructor({
    workerFactory = () =>
      new Worker(new URL("./neural-worker.js", import.meta.url), {
        type: "module",
        name: "dhad-neural-inference",
      }),
    manifestUrl = new URL("../models/student-manifest.json", import.meta.url),
    timeoutMs = DEFAULT_TIMEOUT_MS,
  } = {}) {
    if (typeof workerFactory !== "function") throw new TypeError("workerFactory must be a function");
    if (!Number.isFinite(timeoutMs) || timeoutMs < 100 || timeoutMs > 600_000) {
      throw new RangeError("timeoutMs must be between 100 and 600000 milliseconds");
    }
    this.workerFactory = workerFactory;
    this.manifestUrl = new URL(manifestUrl, globalThis.location?.href ?? "http://localhost/");
    this.timeoutMs = timeoutMs;
    this.worker = null;
    this.pending = new Map();
    this.operationSequence = 0;
    this.initializePromise = null;
    this.readyStatus = null;
    this.disposed = false;
    this.handleMessage = this.handleMessage.bind(this);
    this.handleWorkerFailure = this.handleWorkerFailure.bind(this);
  }

  ensureWorker() {
    if (this.disposed) throw new Error("neural client is disposed");
    if (this.worker !== null) return this.worker;
    const worker = this.workerFactory();
    if (worker === null || typeof worker.postMessage !== "function") {
      throw new TypeError("workerFactory did not return a Worker-compatible object");
    }
    worker.addEventListener("message", this.handleMessage);
    worker.addEventListener("error", this.handleWorkerFailure);
    worker.addEventListener("messageerror", this.handleWorkerFailure);
    this.worker = worker;
    return worker;
  }

  dispatch(type, payload = {}) {
    const worker = this.ensureWorker();
    const operationId = `neural:${++this.operationSequence}`;
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        if (!this.pending.has(operationId)) return;
        this.invalidateWorker(new Error(`neural worker ${type} timed out`));
      }, this.timeoutMs);
      this.pending.set(operationId, { type, resolve, reject, timeout });
      try {
        worker.postMessage({ type, operationId, ...payload });
      } catch (error) {
        this.invalidateWorker(error instanceof Error ? error : new Error(String(error)));
      }
    });
  }

  initialize() {
    if (this.disposed) return Promise.reject(new Error("neural client is disposed"));
    if (this.readyStatus !== null) return Promise.resolve(this.readyStatus);
    if (this.initializePromise !== null) return this.initializePromise;
    this.initializePromise = this.dispatch("init", { manifestUrl: this.manifestUrl.href })
      .then((status) => {
        if (status === null || status.ready !== true || typeof status.provider !== "string") {
          throw new Error("neural worker returned an invalid ready status");
        }
        this.readyStatus = Object.freeze({ ...status });
        return this.readyStatus;
      })
      .catch((error) => {
        this.initializePromise = null;
        throw error;
      });
    return this.initializePromise;
  }

  async rank(unsafeRequest) {
    if (this.disposed) throw new Error("neural client is disposed");
    const originalCandidates = unsafeRequest?.candidates;
    const request = validateRankRequest(unsafeRequest);
    await this.initialize();
    if (this.disposed) throw new Error("neural client is disposed");
    const result = await this.dispatch("rank", { request });
    return validateWorkerDecision(result, request, originalCandidates);
  }

  async rankMany(unsafeRequests) {
    if (this.disposed) throw new Error("neural client is disposed");
    if (!Array.isArray(unsafeRequests) || unsafeRequests.length < 1 || unsafeRequests.length > 64) {
      throw new RangeError("rank batch must contain between 1 and 64 requests");
    }
    const requests = unsafeRequests.map((request) => validateRankRequest(request));
    if (new Set(requests.map((request) => request.requestId)).size !== requests.length) {
      throw new RangeError("rank batch contains duplicate request ids");
    }
    await this.initialize();
    if (this.disposed) throw new Error("neural client is disposed");
    const results = await this.dispatch("rank-many", { requests });
    if (!Array.isArray(results) || results.length !== requests.length) {
      throw new Error("neural worker returned an invalid decision batch");
    }
    return Object.freeze(
      results.map((result, index) =>
        validateWorkerDecision(result, requests[index], unsafeRequests[index].candidates),
      ),
    );
  }

  handleMessage(event) {
    const message = event?.data;
    if (message === null || typeof message !== "object") return;
    const pending = this.pending.get(message.operationId);
    if (pending === undefined) return;
    this.pending.delete(message.operationId);
    clearTimeout(pending.timeout);
    if (message.type === "error") {
      pending.reject(errorFromWorker(message.error));
      return;
    }
    const expected =
      pending.type === "init" ? "ready" : pending.type === "rank-many" ? "ranked-many" : "ranked";
    if (message.type !== expected) {
      pending.reject(new Error(`unexpected neural worker response: ${String(message.type)}`));
      return;
    }
    pending.resolve(
      pending.type === "init"
        ? message.status
        : pending.type === "rank-many"
          ? message.results
          : message.result,
    );
  }

  handleWorkerFailure(event) {
    if (event?.currentTarget && event.currentTarget !== this.worker) return;
    const reason = event?.error instanceof Error ? event.error : new Error("neural worker crashed");
    this.invalidateWorker(reason);
  }

  invalidateWorker(error, { notify = false } = {}) {
    const worker = this.worker;
    this.worker = null;
    if (worker !== null) {
      worker.removeEventListener?.("message", this.handleMessage);
      worker.removeEventListener?.("error", this.handleWorkerFailure);
      worker.removeEventListener?.("messageerror", this.handleWorkerFailure);
      if (notify) {
        try {
          worker.postMessage({ type: "dispose", operationId: `neural:${++this.operationSequence}` });
        } catch {
          // A failed or crashed worker may reject shutdown messages.
        }
      }
      worker.terminate?.();
    }
    this.rejectPending(error);
    this.readyStatus = null;
    this.initializePromise = null;
  }

  rejectPending(error) {
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timeout);
      pending.reject(error);
    }
    this.pending.clear();
  }

  async dispose() {
    if (this.disposed) return;
    this.disposed = true;
    const error = new Error("neural client is disposed");
    this.invalidateWorker(error, { notify: true });
  }
}
