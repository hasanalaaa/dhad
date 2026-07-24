const DEFAULT_TIMEOUT_MS = 120_000;

function validateResult(result) {
  if (
    result === null ||
    typeof result !== "object" ||
    !Array.isArray(result.resolved) ||
    !Number.isFinite(result.elapsedMs) ||
    result.elapsedMs < 0
  ) {
    throw new Error("invalid analysis result from worker");
  }
  return Object.freeze({
    resolved: Object.freeze(result.resolved),
    parsed: result.parsed ?? null,
    intelligence: result.intelligence ?? null,
    elapsedMs: result.elapsedMs,
  });
}

export class AnalysisWorkerClient {
  constructor({
    workerFactory = () =>
      new Worker(new URL("./analysis-worker.js", import.meta.url), {
        type: "module",
        name: "dhad-deterministic-analysis",
      }),
    timeoutMs = DEFAULT_TIMEOUT_MS,
  } = {}) {
    if (typeof workerFactory !== "function") throw new TypeError("workerFactory must be a function");
    if (!Number.isFinite(timeoutMs) || timeoutMs < 100 || timeoutMs > 600_000) {
      throw new RangeError("timeoutMs must be between 100 and 600000 milliseconds");
    }
    this.worker = workerFactory();
    if (!this.worker || typeof this.worker.postMessage !== "function") {
      throw new TypeError("workerFactory did not return a Worker-compatible object");
    }
    this.timeoutMs = timeoutMs;
    this.sequence = 0;
    this.pending = new Map();
    this.disposed = false;
    this.onMessage = this.onMessage.bind(this);
    this.onError = this.onError.bind(this);
    this.worker.addEventListener("message", this.onMessage);
    this.worker.addEventListener("error", this.onError);
    this.worker.addEventListener("messageerror", this.onError);
  }

  check(text, mode = "all", { customWords = [], disabledRules = [] } = {}) {
    if (this.disposed) return Promise.reject(new Error("analysis client is disposed"));
    if (typeof text !== "string") return Promise.reject(new TypeError("text must be a string"));
    if (!new Set(["all", "style", "msa"]).has(mode)) {
      return Promise.reject(new RangeError("unsupported analysis mode"));
    }
    if (!Array.isArray(customWords) || !Array.isArray(disabledRules)) {
      return Promise.reject(new TypeError("analysis preferences must be arrays"));
    }
    if (customWords.length > 5_000 || disabledRules.length > 2_000) {
      return Promise.reject(new RangeError("analysis preferences exceed their safety bounds"));
    }
    const preferences = {
      customWords: [...customWords],
      disabledRules: [...disabledRules],
    };
    const operationId = `analysis:${++this.sequence}`;
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.pending.delete(operationId);
        reject(new Error("analysis worker timed out"));
      }, this.timeoutMs);
      this.pending.set(operationId, { resolve, reject, timeout });
      try {
        this.worker.postMessage({ type: "check", operationId, text, mode, preferences });
      } catch (error) {
        clearTimeout(timeout);
        this.pending.delete(operationId);
        reject(error);
      }
    });
  }

  onMessage(event) {
    const message = event?.data;
    const pending = this.pending.get(message?.operationId);
    if (!pending) return;
    this.pending.delete(message.operationId);
    clearTimeout(pending.timeout);
    if (message.type === "error") {
      pending.reject(new Error(message.error?.message ?? "analysis worker failed"));
      return;
    }
    if (message.type !== "checked") {
      pending.reject(new Error("unexpected analysis worker response"));
      return;
    }
    try {
      pending.resolve(validateResult(message.result));
    } catch (error) {
      pending.reject(error);
    }
  }

  onError(event) {
    const error = event?.error instanceof Error ? event.error : new Error("analysis worker crashed");
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timeout);
      pending.reject(error);
    }
    this.pending.clear();
  }

  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    this.onError({ error: new Error("analysis client is disposed") });
    this.worker.removeEventListener?.("message", this.onMessage);
    this.worker.removeEventListener?.("error", this.onError);
    this.worker.removeEventListener?.("messageerror", this.onError);
    this.worker.terminate();
  }
}
