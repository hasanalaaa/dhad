#!/usr/bin/env node
/**
 * Build and verify the exact dependency-free frontendDist consumed by Tauri.
 *
 * The output is an allowlisted runtime closure, not a recursive copy. This
 * prevents Finder metadata, npm dependencies, tests, source maps, benchmarks,
 * or any newly added development file from entering a native bundle.
 */

import { createHash } from "node:crypto";
import { cp, lstat, mkdir, readFile, readdir, realpath, rm, stat } from "node:fs/promises";
import { dirname, extname, join, normalize, relative, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const sourceRoot = resolve(repositoryRoot, "web_demo");
const outputRoot = resolve(repositoryRoot, "web_dist");

const runtimeAssets = Object.freeze([
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
].sort());

const runtimeAssetSet = new Set(runtimeAssets);
const forbiddenPathParts = new Set([
  ".git",
  ".DS_Store",
  "__pycache__",
  "fixtures",
  "node_modules",
]);
const forbiddenSuffixes = [".map", ".test.js", ".test.mjs", ".test.ts"];
const allowedVendorBareImports = new Map([
  [
    "vendor/onnxruntime-web/ort-wasm-simd-threaded.asyncify.mjs",
    new Set(["module", "worker_threads"]),
  ],
]);

function portable(path) {
  return path.split(sep).join("/");
}

function assertSafeRelativePath(path) {
  const normalized = portable(normalize(path));
  if (
    normalized === "." ||
    normalized.startsWith("../") ||
    normalized.startsWith("/") ||
    normalized.includes("/../")
  ) {
    throw new Error(`unsafe frontend asset path: ${path}`);
  }
  const parts = normalized.split("/");
  if (parts.some((part) => forbiddenPathParts.has(part) || part.startsWith("._"))) {
    throw new Error(`forbidden frontend asset path: ${path}`);
  }
  if (forbiddenSuffixes.some((suffix) => normalized.endsWith(suffix))) {
    throw new Error(`development-only frontend asset path: ${path}`);
  }
}

async function assertRegularSource(relativePath) {
  assertSafeRelativePath(relativePath);
  const source = join(sourceRoot, relativePath);
  const sourceInfo = await lstat(source).catch(() => null);
  if (!sourceInfo?.isFile() || sourceInfo.isSymbolicLink()) {
    throw new Error(`required frontend source is not a regular file: ${relativePath}`);
  }
  const sourceReal = await realpath(source);
  const sourceRootReal = await realpath(sourceRoot);
  const containment = relative(sourceRootReal, sourceReal);
  if (containment.startsWith("..") || resolve(sourceReal) === resolve(sourceRootReal)) {
    throw new Error(`frontend source escapes web_demo: ${relativePath}`);
  }
  return source;
}

async function collectOutput(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries.sort((left, right) => (left.name < right.name ? -1 : left.name > right.name ? 1 : 0))) {
    const absolute = join(directory, entry.name);
    const rel = portable(relative(outputRoot, absolute));
    assertSafeRelativePath(rel);
    if (entry.isSymbolicLink()) throw new Error(`staged frontend contains a symlink: ${rel}`);
    if (entry.isDirectory()) files.push(...(await collectOutput(absolute)));
    else if (entry.isFile()) files.push(rel);
    else throw new Error(`unsupported staged frontend entry: ${rel}`);
  }
  return files;
}

function cleanSpecifier(specifier) {
  return specifier.split(/[?#]/u, 1)[0];
}

function resolveRuntimeReference(importer, specifier) {
  const clean = cleanSpecifier(specifier);
  if (clean === "" || clean.startsWith("#")) return null;
  if (/^[a-z][a-z0-9+.-]*:/iu.test(clean) || clean.startsWith("//")) return null;
  if (!clean.startsWith(".") && !clean.startsWith("/")) return { bare: clean };
  const importerDirectory = dirname(importer);
  const target = portable(normalize(join(importerDirectory, clean.replace(/^\//u, ""))));
  return { target };
}

function moduleSpecifiers(source) {
  const patterns = [
    /(?:import\s+(?:[^'";]+?\s+from\s+)?|export\s+[^'";]+?\s+from\s+|import\s*\()\s*['"]([^'"]+)['"]/gu,
    /new\s+URL\s*\(\s*['"]([^'"]+)['"]\s*,\s*import\.meta\.url\s*\)/gu,
    /new\s+Worker\s*\(\s*['"]([^'"]+)['"]/gu,
    /fetch\s*\(\s*['"]([^'"]+)['"]/gu,
    /serviceWorker\.register\s*\(\s*['"]([^'"]+)['"]/gu,
  ];
  return patterns.flatMap((pattern) => [...source.matchAll(pattern)].map((match) => match[1]));
}

function runtimeTargetExists(target) {
  if (runtimeAssetSet.has(target)) return true;
  const prefix = target.endsWith("/") ? target : `${target}/`;
  return runtimeAssets.some((asset) => asset.startsWith(prefix));
}

async function verifyModuleClosure() {
  for (const asset of runtimeAssets) {
    if (![".js", ".mjs"].includes(extname(asset))) continue;
    const source = await readFile(join(outputRoot, asset), "utf8");
    for (const specifier of moduleSpecifiers(source)) {
      const resolved = resolveRuntimeReference(asset, specifier);
      if (!resolved) continue;
      if (resolved.bare) {
        const adjacentAsset = portable(normalize(join(dirname(asset), resolved.bare)));
        if (runtimeAssetSet.has(adjacentAsset)) continue;
        const allowed = allowedVendorBareImports.get(asset);
        if (!allowed?.has(resolved.bare)) {
          throw new Error(`unresolved bare module import in ${asset}: ${resolved.bare}`);
        }
        continue;
      }
      if (!runtimeTargetExists(resolved.target)) {
        throw new Error(`unresolved frontend module reference in ${asset}: ${specifier}`);
      }
    }
  }
}

function localDocumentReferences(source, extension) {
  const patterns =
    extension === ".css"
      ? [/url\(\s*['"]?([^)'"\s]+)['"]?\s*\)/gu]
      : [/(?:src|href)\s*=\s*['"]([^'"]+)['"]/gu];
  return patterns.flatMap((pattern) => [...source.matchAll(pattern)].map((match) => match[1]));
}

async function verifyDocumentClosure() {
  for (const asset of runtimeAssets) {
    const extension = extname(asset);
    if (![".html", ".css"].includes(extension)) continue;
    const source = await readFile(join(outputRoot, asset), "utf8");
    for (const specifier of localDocumentReferences(source, extension)) {
      const resolved = resolveRuntimeReference(asset, specifier);
      if (!resolved || resolved.bare) continue;
      if (resolved.target.endsWith("/")) continue;
      if (!runtimeTargetExists(resolved.target)) {
        throw new Error(`unresolved frontend document reference in ${asset}: ${specifier}`);
      }
    }
  }
}

async function verifyPwaClosure() {
  const cachePolicyUrl = `${pathToFileURL(join(outputRoot, "pwa", "cache-policy.js")).href}?v=${Date.now()}`;
  const { OPTIONAL_NEURAL_ASSETS, PRECACHE_ASSETS } = await import(cachePolicyUrl);
  for (const specifier of [...PRECACHE_ASSETS, ...OPTIONAL_NEURAL_ASSETS]) {
    if (specifier === "./") continue;
    const normalized = portable(specifier.replace(/^\.\//u, ""));
    if (!runtimeAssetSet.has(normalized)) {
      throw new Error(`PWA cache policy references an unstaged asset: ${specifier}`);
    }
  }

  const manifest = JSON.parse(await readFile(join(outputRoot, "manifest.json"), "utf8"));
  if (manifest.start_url !== "./" || manifest.scope !== "./") {
    throw new Error("manifest start_url and scope must remain local to the packaged frontend");
  }
  for (const icon of manifest.icons ?? []) {
    const path = portable(String(icon.src ?? "").replace(/^\.\//u, ""));
    if (!runtimeAssetSet.has(path)) throw new Error(`manifest icon is not staged: ${icon.src}`);
  }
}

async function sha256(path) {
  const hash = createHash("sha256");
  hash.update(await readFile(path));
  return hash.digest("hex");
}

async function verifyPinnedAsset(path, contract) {
  const info = await stat(path);
  if (contract.bytes !== undefined && info.size !== contract.bytes) {
    throw new Error(`pinned asset size mismatch for ${portable(relative(outputRoot, path))}`);
  }
  if ((await sha256(path)) !== contract.sha256) {
    throw new Error(`pinned asset hash mismatch for ${portable(relative(outputRoot, path))}`);
  }
}

async function verifyIntegrityContracts() {
  const modelManifest = JSON.parse(
    await readFile(join(outputRoot, "models", "student-manifest.json"), "utf8"),
  );
  await verifyPinnedAsset(join(outputRoot, "models", modelManifest.model.url), {
    bytes: modelManifest.model.expectedBytes,
    sha256: modelManifest.model.sha256,
  });
  await verifyPinnedAsset(join(outputRoot, "models", modelManifest.tokenizer.url), {
    sha256: modelManifest.tokenizer.sha256,
  });

  const vendorRoot = join(outputRoot, "vendor", "onnxruntime-web");
  const vendorManifest = JSON.parse(await readFile(join(vendorRoot, "vendor-manifest.json"), "utf8"));
  for (const [name, contract] of Object.entries(vendorManifest.assets ?? {})) {
    const relativePath = `vendor/onnxruntime-web/${name}`;
    if (!runtimeAssetSet.has(relativePath)) {
      throw new Error(`vendor integrity manifest references an unstaged asset: ${name}`);
    }
    await verifyPinnedAsset(join(vendorRoot, name), contract);
  }
}

async function assertOutput() {
  const outputFiles = await collectOutput(outputRoot);
  const expected = [...runtimeAssets];
  if (outputFiles.length !== expected.length || outputFiles.some((file, index) => file !== expected[index])) {
    const actualSet = new Set(outputFiles);
    const missing = expected.filter((file) => !actualSet.has(file));
    const unexpected = outputFiles.filter((file) => !runtimeAssetSet.has(file));
    throw new Error(
      `staged frontend differs from its exact allowlist; missing=${JSON.stringify(missing)}, unexpected=${JSON.stringify(unexpected)}`,
    );
  }

  const index = await readFile(join(outputRoot, "index.html"), "utf8");
  if (!index.includes('src="app.js"') && !index.includes("src='app.js'")) {
    throw new Error("staged index.html does not load app.js");
  }

  await verifyModuleClosure();
  await verifyDocumentClosure();
  await verifyPwaClosure();
  await verifyIntegrityContracts();
  return outputFiles;
}

await rm(outputRoot, { recursive: true, force: true });
await mkdir(outputRoot, { recursive: true });
for (const relativePath of runtimeAssets) {
  const source = await assertRegularSource(relativePath);
  const destination = join(outputRoot, relativePath);
  await mkdir(dirname(destination), { recursive: true });
  await cp(source, destination, { preserveTimestamps: false });
}

const outputFiles = await assertOutput();
const sizes = await Promise.all(outputFiles.map((path) => stat(join(outputRoot, path))));
const totalBytes = sizes.reduce((sum, info) => sum + info.size, 0);
console.log(
  `Staged and verified Tauri frontend: ${outputFiles.length} allowlisted files, ${totalBytes} bytes -> web_dist`,
);
