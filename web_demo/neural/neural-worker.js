import * as ort from "../vendor/onnxruntime-web/ort.webgpu.min.mjs";

import { NeuralInferenceRuntime } from "./neural-runtime.js";

const runtimeDirectory = new URL("../vendor/onnxruntime-web/", import.meta.url).href;
ort.env.wasm.wasmPaths = runtimeDirectory;
ort.env.wasm.numThreads = globalThis.crossOriginIsolated
  ? Math.max(1, Math.min(4, Number(globalThis.navigator?.hardwareConcurrency ?? 1)))
  : 1;
ort.env.wasm.proxy = false;
ort.env.logLevel = "error";

const runtime = new NeuralInferenceRuntime(ort);
let initializedManifestUrl = null;
let queue = Promise.resolve();
let closing = false;

function post(type, operationId, payload = {}) {
  globalThis.postMessage({ type, operationId, ...payload });
}

function safeError(error) {
  return Object.freeze({
    name: error instanceof Error ? error.name : "Error",
    message: error instanceof Error ? error.message : String(error),
  });
}

async function initialize(manifestUrl) {
  const resolved = new URL(manifestUrl, globalThis.location.href).href;
  if (initializedManifestUrl !== null && initializedManifestUrl !== resolved) {
    throw new Error("neural worker cannot switch model manifests without disposal");
  }
  const status = await runtime.initialize(resolved);
  initializedManifestUrl = resolved;
  return status;
}

async function processMessage(message) {
  if (message === null || typeof message !== "object" || typeof message.operationId !== "string") {
    return;
  }
  const { operationId } = message;
  try {
    if (message.type === "init") {
      if (typeof message.manifestUrl !== "string") throw new TypeError("manifestUrl is required");
      post("ready", operationId, { status: await initialize(message.manifestUrl) });
      return;
    }
    if (message.type === "rank") {
      if (initializedManifestUrl === null) throw new Error("neural runtime is not initialized");
      post("ranked", operationId, { result: await runtime.rank(message.request) });
      return;
    }
    if (message.type === "rank-many") {
      if (initializedManifestUrl === null) throw new Error("neural runtime is not initialized");
      post("ranked-many", operationId, { results: await runtime.rankMany(message.requests) });
      return;
    }
    if (message.type === "dispose") {
      closing = true;
      await runtime.dispose();
      post("disposed", operationId);
      globalThis.close();
      return;
    }
    throw new Error(`unsupported neural worker message: ${String(message.type)}`);
  } catch (error) {
    post("error", operationId, { error: safeError(error) });
  }
}

globalThis.addEventListener("message", (event) => {
  if (closing) return;
  queue = queue.then(() => processMessage(event.data), () => processMessage(event.data));
});
