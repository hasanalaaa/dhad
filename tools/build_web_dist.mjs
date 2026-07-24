#!/usr/bin/env node
/** Build a deterministic, dependency-free frontendDist for Tauri. */

import { cp, mkdir, readdir, readFile, rm, stat } from "node:fs/promises";
import { dirname, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const sourceRoot = resolve(repositoryRoot, "web_demo");
const outputRoot = resolve(repositoryRoot, "web_dist");

const excludedDirectories = new Set([
  ".git",
  "__pycache__",
  "fixtures",
  "node_modules",
]);
const excludedNames = new Set([
  "README.md",
  "abi-benchmark.json",
  "abi_benchmark.mjs",
  "bench.mjs",
  "browser_proof.mjs",
  "package-lock.json",
  "package.json",
  "packed_bridge_test.mjs",
  "wasm-build-metrics.json",
]);
const excludedSuffixes = [".test.mjs", ".map"];
const requiredAssets = [
  "analysis/analysis-client.js",
  "analysis/analysis-worker.js",
  "analytics/writing-analytics.js",
  "app.css",
  "app.js",
  "collaboration/e2ee.js",
  "collaboration/secure-yjs-provider.js",
  "collaboration/sync-transport.js",
  "dhad-core.js",
  "dhad_core.fast.wasm",
  "dhad_core.small.wasm",
  "dhad_core.wasm",
  "documents/document-io.js",
  "icons/icon-192.png",
  "icons/icon-512.png",
  "index.html",
  "intelligence/writing-intelligence.js",
  "js/desktop-adapter.js",
  "js/native-file-dialogs.js",
  "manifest.json",
  "mini-assistant.css",
  "mini-assistant.html",
  "mini-assistant.js",
  "models/distiluse-vocab.txt",
  "models/model_int8.onnx",
  "models/student-manifest.json",
  "neural/neural-client.js",
  "neural/neural-core.js",
  "neural/neural-runtime.js",
  "neural/neural-worker.js",
  "offline.html",
  "pwa/cache-policy.js",
  "rewriting/offline-rewriter.js",
  "rules.json",
  "service-worker.js",
  "shared/capabilities.js",
  "storage/db.js",
  "templates/smart-templates.js",
  "themes/theme-controller.js",
  "ui/rendering.js",
  "vendor/onnxruntime-web/ort-wasm-simd-threaded.asyncify.mjs",
  "vendor/onnxruntime-web/ort-wasm-simd-threaded.asyncify.wasm",
  "vendor/onnxruntime-web/ort.webgpu.min.mjs",
  "vendor/onnxruntime-web/vendor-manifest.json",
];

function excluded(relativePath, directoryEntry) {
  const parts = relativePath.split(sep);
  if (parts.some((part) => excludedDirectories.has(part))) return true;
  if (directoryEntry.isDirectory()) return false;
  if (excludedNames.has(directoryEntry.name)) return true;
  return excludedSuffixes.some((suffix) => directoryEntry.name.endsWith(suffix));
}

async function collect(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name, "en"))) {
    const absolute = join(directory, entry.name);
    const rel = relative(sourceRoot, absolute);
    if (excluded(rel, entry)) continue;
    if (entry.isSymbolicLink()) throw new Error(`frontend source must not contain symlinks: ${rel}`);
    if (entry.isDirectory()) files.push(...(await collect(absolute)));
    else if (entry.isFile()) files.push(absolute);
  }
  return files;
}

async function assertOutput(files) {
  const relativeFiles = new Set(files.map((path) => relative(outputRoot, path).split(sep).join("/")));
  for (const required of requiredAssets) {
    if (!relativeFiles.has(required)) throw new Error(`staged frontend is missing required asset: ${required}`);
  }
  for (const path of files) {
    const rel = relative(outputRoot, path).split(sep).join("/");
    if (rel.includes("node_modules/") || rel.endsWith("/node_modules")) {
      throw new Error(`staged frontend contains node_modules: ${rel}`);
    }
    if (rel.endsWith(".test.mjs") || excludedNames.has(rel.split("/").at(-1))) {
      throw new Error(`staged frontend contains development-only file: ${rel}`);
    }
  }
  const index = await readFile(join(outputRoot, "index.html"), "utf8");
  if (!index.includes("app.js")) throw new Error("staged index.html does not reference app.js");
}

await rm(outputRoot, { recursive: true, force: true });
await mkdir(outputRoot, { recursive: true });
const sourceFiles = await collect(sourceRoot);
for (const source of sourceFiles) {
  const destination = join(outputRoot, relative(sourceRoot, source));
  await mkdir(dirname(destination), { recursive: true });
  await cp(source, destination, { preserveTimestamps: false });
}
const outputFiles = await collectOutput(outputRoot);
await assertOutput(outputFiles);
const totalBytes = (await Promise.all(outputFiles.map(async (path) => (await stat(path)).size))).reduce(
  (sum, size) => sum + size,
  0,
);
console.log(`Staged Tauri frontend: ${outputFiles.length} files, ${totalBytes} bytes -> web_dist`);

async function collectOutput(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name, "en"))) {
    const absolute = join(directory, entry.name);
    if (entry.isDirectory()) files.push(...(await collectOutput(absolute)));
    else if (entry.isFile()) files.push(absolute);
    else throw new Error(`unsupported staged frontend entry: ${relative(outputRoot, absolute)}`);
  }
  return files;
}
