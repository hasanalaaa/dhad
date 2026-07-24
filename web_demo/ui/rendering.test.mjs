import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { buildOverlaySegments, chunkOverlaySegments, computeVirtualWindow } from "./rendering.js";

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

test("overlay segments preserve the source while isolating diagnostics", () => {
  const text = "لغة عربية\nجميلة";
  const matches = [{ offset: 4, length: 5, severity: "warning", category: "style" }];
  const segments = buildOverlaySegments(text, matches);
  assert.equal(segments.map((segment) => segment.text).join(""), text);
  assert.deepEqual(
    segments.filter((segment) => segment.match).map((segment) => segment.text),
    ["عربية"],
  );
});

test("issue virtualization renders a bounded overscanned window", () => {
  assert.deepEqual(
    computeVirtualWindow({ count: 1_000, scrollTop: 12_000, viewportHeight: 600 }),
    { start: 98, end: 107, paddingStart: 11_760, paddingEnd: 107_160 },
  );
  const short = computeVirtualWindow({ count: 20, scrollTop: 0, viewportHeight: 600 });
  assert.deepEqual(short, { start: 0, end: 20, paddingStart: 0, paddingEnd: 0 });
});

test("overlay segmentation stays within the 50ms main-thread budget for 10k matches", () => {
  const text = "ا ".repeat(10_000);
  const matches = Array.from({ length: 10_000 }, (_, index) => ({
    offset: index * 2,
    length: 1,
    severity: "hint",
    category: "style",
  }));
  const started = performance.now();
  const segments = buildOverlaySegments(text, matches);
  const elapsed = performance.now() - started;
  assert.equal(segments.length, 20_000);
  assert.ok(elapsed < 50, `segmentation consumed ${elapsed.toFixed(2)}ms`);
});

test("large overlays are split into bounded animation-frame batches", () => {
  const segments = Array.from({ length: 2_501 }, (_, index) => ({ text: String(index) }));
  const chunks = chunkOverlaySegments(segments, 320);
  assert.equal(chunks.length, 8);
  assert.equal(chunks.flat().length, segments.length);
  assert.ok(chunks.every((chunk) => chunk.length <= 320));
});

test("the editor integrates composited overlay, worker checks, persistence, and sidebar virtualization", async () => {
  const [html, app, css] = await Promise.all([
    readFile(resolve(webRoot, "index.html"), "utf8"),
    readFile(resolve(webRoot, "app.js"), "utf8"),
    readFile(resolve(webRoot, "app.css"), "utf8"),
  ]);
  assert.match(html, /id="editorOverlay"/u);
  assert.match(app, /createAnalysisClient/u);
  assert.match(app, /new DhadStorage/u);
  assert.match(app, /computeVirtualWindow/u);
  assert.match(app, /requestAnimationFrame/u);
  assert.match(app, /chunkOverlaySegments/u);
  assert.match(app, /Math\.min\(issuesList\.clientHeight/u);
  assert.match(css, /\.editor-overlay/u);
  assert.match(css, /will-change:\s*transform/u);
  assert.match(css, /translate3d/u);
  assert.match(css, /\.issues\s*\{[\s\S]*?min-height:\s*0/u);
});

test("the Arabic editor exposes keyboard and assistive-technology state", async () => {
  const [html, app] = await Promise.all([
    readFile(resolve(webRoot, "index.html"), "utf8"),
    readFile(resolve(webRoot, "app.js"), "utf8"),
  ]);
  assert.match(html, /role="textbox" aria-multiline="true"/u);
  assert.match(html, /id="toast"[^>]*role="status"[^>]*aria-live="polite"/u);
  assert.match(html, /id="btnCopy"[^>]*aria-label=/u);
  assert.match(html, /id="filters"[^>]*role="group"/u);
  assert.match(app, /setAttribute\("aria-pressed"/u);
  assert.match(app, /إيقاف الإملاء الصوتي/u);
});
