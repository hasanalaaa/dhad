export const CACHE_VERSION = "gold-1.0.15-desktop-goldmaster";
export const PRECACHE_NAME = `dhad-precache-${CACHE_VERSION}`;
export const SHELL_CACHE_NAME = `dhad-shell-${CACHE_VERSION}`;

export const APP_SHELL = Object.freeze([
  "./",
  "./index.html",
  "./offline.html",
  "./manifest.json",
  "./app.css",
  "./app.js",
  "./dhad-core.js",
  "./analysis/analysis-client.js",
  "./analysis/analysis-worker.js",
  "./js/desktop-adapter.js",
  "./js/native-file-dialogs.js",
  "./mini-assistant.html",
  "./mini-assistant.css",
  "./mini-assistant.js",
  "./intelligence/writing-intelligence.js",
  "./storage/db.js",
  "./ui/rendering.js",
  "./rewriting/offline-rewriter.js",
  "./analytics/writing-analytics.js",
  "./templates/smart-templates.js",
  "./themes/theme-controller.js",
  "./documents/document-io.js",
  "./shared/capabilities.js",
  "./neural/neural-client.js",
  "./neural/neural-core.js",
  "./neural/neural-runtime.js",
  "./neural/neural-worker.js",
  "./collaboration/e2ee.js",
  "./collaboration/secure-yjs-provider.js",
  "./collaboration/sync-transport.js",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
]);

// Small deterministic assets remain part of the atomic install transaction.
export const CORE_IMMUTABLE_ASSETS = Object.freeze([
  "./dhad_core.wasm",
  "./dhad_core.fast.wasm",
  "./dhad_core.small.wasm",
  "./rules.json",
]);

// Neural assets exceed 150 MiB. They are cached on first use or by an explicit
// warm-up message so constrained devices can still install the offline shell.
export const OPTIONAL_NEURAL_ASSETS = Object.freeze([
  "./models/student-manifest.json",
  "./models/model_int8.onnx",
  "./models/distiluse-vocab.txt",
  "./vendor/onnxruntime-web/ort.webgpu.min.mjs",
  "./vendor/onnxruntime-web/ort-wasm-simd-threaded.asyncify.mjs",
  "./vendor/onnxruntime-web/ort-wasm-simd-threaded.asyncify.wasm",
]);

export const IMMUTABLE_ASSETS = Object.freeze([
  ...CORE_IMMUTABLE_ASSETS,
  ...OPTIONAL_NEURAL_ASSETS,
]);
export const PRECACHE_ASSETS = Object.freeze([
  ...new Set([...APP_SHELL, ...CORE_IMMUTABLE_ASSETS]),
]);

const immutableSuffixes = IMMUTABLE_ASSETS.map((asset) => asset.slice(1));
const shellSuffixes = APP_SHELL.filter((asset) => asset !== "./").map((asset) => asset.slice(1));

export function classifyRequest(request, origin = globalThis.location?.origin) {
  if (!(request instanceof Request) || request.method !== "GET") return "passthrough";
  const url = new URL(request.url);
  if (url.origin !== origin) return "passthrough";
  if (request.mode === "navigate" || request.headers.get("accept")?.includes("text/html")) {
    return "navigation";
  }
  if (immutableSuffixes.some((suffix) => url.pathname.endsWith(suffix))) return "immutable";
  if (shellSuffixes.some((suffix) => url.pathname.endsWith(suffix))) return "shell";
  return "passthrough";
}
