import { createHash } from "node:crypto";
import { copyFile, mkdir, readFile, unlink, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const EXPECTED_VERSION = "1.27.0";
const FILES = Object.freeze([
  "ort.webgpu.min.mjs",
  "ort-wasm-simd-threaded.asyncify.mjs",
  "ort-wasm-simd-threaded.asyncify.wasm",
]);
const SUPERSEDED_FILES = Object.freeze([
  "ort-wasm-simd-threaded.jsep.mjs",
  "ort-wasm-simd-threaded.jsep.wasm",
  "ort-wasm-simd-threaded.mjs",
  "ort-wasm-simd-threaded.wasm",
  "ort-wasm-simd-threaded.jspi.mjs",
  "ort-wasm-simd-threaded.jspi.wasm",
]);

const toolsDirectory = dirname(fileURLToPath(import.meta.url));
const repository = resolve(toolsDirectory, "..");
const packageDirectory = join(repository, "web_demo", "node_modules", "onnxruntime-web");
const outputDirectory = join(repository, "web_demo", "vendor", "onnxruntime-web");
const metadata = JSON.parse(await readFile(join(packageDirectory, "package.json"), "utf8"));
if (metadata.version !== EXPECTED_VERSION) {
  throw new Error(`onnxruntime-web ${EXPECTED_VERSION} is required; found ${metadata.version}`);
}

await mkdir(outputDirectory, { recursive: true });
for (const filename of SUPERSEDED_FILES) {
  await unlink(join(outputDirectory, filename)).catch((error) => {
    if (error.code !== "ENOENT") throw error;
  });
}
const assets = {};
for (const filename of FILES) {
  const source = join(packageDirectory, "dist", filename);
  const destination = join(outputDirectory, filename);
  await copyFile(source, destination);
  const bytes = await readFile(destination);
  assets[filename] = Object.freeze({
    bytes: bytes.byteLength,
    sha256: createHash("sha256").update(bytes).digest("hex"),
  });
}
await writeFile(
  join(outputDirectory, "vendor-manifest.json"),
  `${JSON.stringify({ package: "onnxruntime-web", version: EXPECTED_VERSION, license: metadata.license, assets }, null, 2)}\n`,
  "utf8",
);

process.stdout.write(`Vendored onnxruntime-web ${EXPECTED_VERSION} (${FILES.length} runtime assets).\n`);
