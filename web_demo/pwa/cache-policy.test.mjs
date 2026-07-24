import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import {
  APP_SHELL,
  CORE_IMMUTABLE_ASSETS,
  IMMUTABLE_ASSETS,
  OPTIONAL_NEURAL_ASSETS,
  PRECACHE_ASSETS,
  classifyRequest,
} from "./cache-policy.js";

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

test("cache policy separates immutable NLP assets from the revalidated app shell", () => {
  const origin = "https://dhad.example";
  assert.equal(classifyRequest(new Request(`${origin}/dhad_core.wasm`), origin), "immutable");
  assert.equal(classifyRequest(new Request(`${origin}/models/model_int8.onnx`), origin), "immutable");
  assert.equal(classifyRequest(new Request(`${origin}/rules.json`), origin), "immutable");
  assert.equal(classifyRequest(new Request(`${origin}/app.js`), origin), "shell");
  assert.equal(
    classifyRequest(new Request(`${origin}/document/42`, { headers: { accept: "text/html" } }), origin),
    "navigation",
  );
  assert.equal(classifyRequest(new Request("https://foreign.example/a.js"), origin), "passthrough");
});

test("the atomic precache is complete, unique, and entirely local", async () => {
  assert.equal(new Set(PRECACHE_ASSETS).size, PRECACHE_ASSETS.length);
  assert.ok(APP_SHELL.includes("./offline.html"));
  assert.ok(IMMUTABLE_ASSETS.includes("./models/model_int8.onnx"));
  assert.ok(OPTIONAL_NEURAL_ASSETS.includes("./models/model_int8.onnx"));
  assert.equal(PRECACHE_ASSETS.includes("./models/model_int8.onnx"), false);
  assert.ok(CORE_IMMUTABLE_ASSETS.every((asset) => PRECACHE_ASSETS.includes(asset)));
  for (const asset of PRECACHE_ASSETS) {
    assert.match(asset, /^\.\//u);
    await access(resolve(webRoot, asset.slice(2)));
  }
});

test("manifest is installable and points at local maskable icons", async () => {
  const manifest = JSON.parse(await readFile(resolve(webRoot, "manifest.json"), "utf8"));
  assert.equal(manifest.start_url, "./");
  assert.equal(manifest.scope, "./");
  assert.equal(manifest.display, "standalone");
  for (const size of ["192x192", "512x512"]) {
    const icon = manifest.icons.find((candidate) => candidate.sizes === size);
    assert.ok(icon, `missing ${size} icon`);
    assert.match(icon.purpose, /maskable/u);
    await access(resolve(webRoot, icon.src));
  }
  const student = JSON.parse(
    await readFile(resolve(webRoot, "models/student-manifest.json"), "utf8"),
  );
  assert.equal(student.model.url, "model_int8.onnx");
});

test("the HTML shell registers the module service worker and provides offline metadata", async () => {
  const html = await readFile(resolve(webRoot, "index.html"), "utf8");
  const app = await readFile(resolve(webRoot, "app.js"), "utf8");
  const worker = await readFile(resolve(webRoot, "service-worker.js"), "utf8");
  assert.match(html, /rel="manifest" href="manifest\.json"/u);
  assert.match(html, /name="theme-color"/u);
  assert.match(app, /serviceWorker\.register\("\.\/service-worker\.js", \{ type: "module" \}\)/u);
  assert.match(worker, /cache\.addAll\(PRECACHE_ASSETS\)/u);
  assert.match(worker, /warmOptionalNeuralAssets/u);
  assert.match(worker, /dhad:warm-neural-cache/u);
  assert.match(worker, /staleWhileRevalidate/u);
  assert.match(worker, /cacheFirst/u);
});

test("service-worker background refreshes are attached to the fetch lifecycle", async () => {
  const worker = await readFile(resolve(webRoot, "service-worker.js"), "utf8");
  assert.match(worker, /event\?\.waitUntil\?\.\(refreshed\)/u);
  assert.match(worker, /staleWhileRevalidate\(event\.request, \{ navigation: true, event \}\)/u);
  assert.match(worker, /event\.waitUntil\?\.\(self\.skipWaiting\(\)\)/u);
});

test("the production neural worker keeps benign ONNX provider diagnostics out of the error console", async () => {
  const source = await readFile(resolve(webRoot, "neural/neural-worker.js"), "utf8");
  assert.match(source, /ort\.env\.logLevel = "error"/u);
});
